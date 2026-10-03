"""Shared deterministic cloud-diagram compilation service."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cloud_diagram.diagnostics import (
    DecisionRecord,
    DiagnosticReport,
    HardGateCounts,
    ReportBuilder,
    Severity,
    StageSummary,
    calculate_quality_score,
    detail_records,
    make_finding,
)
from cloud_diagram.domain import DiagramOverrides, DiagramSpec
from cloud_diagram.icons import IconRegistry
from cloud_diagram.layout import LayoutResult, layout_diagram
from cloud_diagram.renderers import render_drawio
from cloud_diagram.rules import RuleEngine, RuleSet, load_rules
from cloud_diagram.settings import Settings
from cloud_diagram.validation import validate_drawio_output, validate_geometry, validate_semantics


class SpecLoadError(ValueError):
    """A DiagramSpec source is malformed, ambiguous, or schema-invalid."""


class CompilationError(ValueError):
    """Compilation reached diagnostics but did not pass every required gate."""

    def __init__(self, report: DiagnosticReport) -> None:
        self.report = report
        errors = [finding for finding in report.findings if finding.severity is Severity.ERROR]
        message = "; ".join(f"{item.code}: {item.message}" for item in errors[:5])
        super().__init__(f"diagram compilation failed: {message or 'a hard gate remains'}")


class ResolvedIconMetadata(BaseModel):
    """Safe, serializable icon resolution metadata (never SVG bytes or file paths)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    requested: str
    icon_id: str
    provider: str
    kind: str
    category: str
    display_name: str
    checksum: str
    deprecated: bool
    reason: str


class CompilationResult(BaseModel):
    """Immutable successful compilation result.

    ``drawio`` is deliberately excluded from ordinary model serialization. Callers
    must explicitly request ``drawio_text()`` when they intend to return XML.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    spec: DiagramSpec
    layout: LayoutResult
    drawio: bytes = Field(exclude=True, repr=False)
    diagnostics: DiagnosticReport
    semantic_summary: StageSummary
    geometry_summary: StageSummary
    output_summary: StageSummary
    resolved_icons: tuple[ResolvedIconMetadata, ...]

    def drawio_text(self) -> str:
        return self.drawio.decode("utf-8")

    def summary_dict(self) -> dict[str, Any]:
        return {
            "diagram_id": self.spec.diagram_id,
            "diagnostics": self.diagnostics.model_dump(mode="json", exclude_none=True),
            "layout": {
                "canvas": self.layout.canvas.model_dump(mode="json"),
                "engine_id": self.layout.engine_id,
                "metrics": self.layout.metrics.model_dump(mode="json"),
            },
            "resolved_icons": [item.model_dump(mode="json") for item in self.resolved_icons],
        }


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            mark = key_node.start_mark
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _reject_json_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SpecLoadError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _validation_message(error: ValidationError, *, source: str) -> str:
    details: list[str] = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"]) or "<root>"
        details.append(f"{source}:{location}: {item['msg']}")
    return "invalid DiagramSpec:\n" + "\n".join(details)


def parse_diagram_spec(
    data: str | bytes,
    *,
    format: Literal["json", "yaml"],
    source: str = "<memory>",
) -> DiagramSpec:
    """Parse JSON/YAML with duplicate-key rejection, then validate the closed schema."""

    text = data.decode("utf-8") if isinstance(data, bytes) else data
    try:
        if format == "json":
            document = json.loads(text, object_pairs_hook=_reject_json_duplicates)
        else:
            document = yaml.load(text, Loader=_UniqueKeyLoader)
    except SpecLoadError:
        raise
    except json.JSONDecodeError as exc:
        raise SpecLoadError(f"{source}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}") from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f":{mark.line + 1}:{mark.column + 1}" if mark is not None else ""
        problem = getattr(exc, "problem", None) or str(exc)
        raise SpecLoadError(f"{source}{location}: invalid YAML: {problem}") from exc
    if not isinstance(document, Mapping):
        raise SpecLoadError(f"{source}: DiagramSpec document must be an object")
    try:
        return DiagramSpec.model_validate(document)
    except ValidationError as exc:
        raise SpecLoadError(_validation_message(exc, source=source)) from exc


def load_diagram_spec(path: str | os.PathLike[str]) -> DiagramSpec:
    """Load a strict DiagramSpec from a ``.json``, ``.yaml``, or ``.yml`` file."""

    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix not in {".json", ".yaml", ".yml"}:
        raise SpecLoadError(f"unsupported DiagramSpec format {suffix!r}; expected .json, .yaml, or .yml")
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise SpecLoadError(f"unable to read DiagramSpec {source}: {exc}") from exc
    return parse_diagram_spec(data, format="json" if suffix == ".json" else "yaml", source=str(source))


def validate_diagram_spec(value: DiagramSpec | Mapping[str, Any]) -> DiagramSpec:
    """Strictly validate a direct model or mapping without invoking a planner."""

    try:
        document = value.model_dump(mode="python") if isinstance(value, DiagramSpec) else value
        return DiagramSpec.model_validate(document)
    except ValidationError as exc:
        raise SpecLoadError(_validation_message(exc, source="<mapping>")) from exc


def write_bytes_atomic(path: str | os.PathLike[str], data: bytes) -> None:
    """Atomically write bytes without creating the explicit parent directory."""

    destination = Path(path)
    if not destination.parent.is_dir():
        raise ValueError(f"output directory does not exist: {destination.parent}")
    if destination.exists() and destination.is_dir():
        raise ValueError(f"output path is a directory: {destination}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_text_atomic(path: str | os.PathLike[str], text: str) -> None:
    """Atomically write UTF-8 text without creating the explicit parent directory."""

    write_bytes_atomic(path, text.encode("utf-8"))


def write_diagram_spec(path: str | os.PathLike[str], spec: DiagramSpec) -> None:
    write_text_atomic(path, spec.canonical_json() + "\n")


def write_diagnostics(path: str | os.PathLike[str], report: DiagnosticReport) -> None:
    write_text_atomic(path, report.canonical_json() + "\n")


def _merge_hard_counts(*counts: HardGateCounts) -> HardGateCounts:
    values = {
        name: sum(getattr(item, name) for item in counts)
        for name in HardGateCounts.model_fields
    }
    return HardGateCounts.model_validate(values)


def _route_stretch_violations(layout: LayoutResult, rules: RuleSet) -> int:
    limit = rules.quality_gates.soft.maximum_average_route_stretch
    violations = 0
    for route in layout.routes:
        direct = abs(route.points[-1].x - route.points[0].x) + abs(route.points[-1].y - route.points[0].y)
        if direct and route.total_length / direct > limit:
            violations += 1
    return violations


def _build_diagnostics(
    spec: DiagramSpec,
    rules: RuleSet,
    rule_trace: tuple[Any, ...],
    semantic: Any,
    *,
    layout: LayoutResult | None = None,
    geometry: Any | None = None,
    output_findings: tuple[Any, ...] = (),
    output_ran: bool = False,
    additional_findings: tuple[Any, ...] = (),
) -> DiagnosticReport:
    """Build a canonical full or partial report, marking unrun stages skipped."""

    builder = ReportBuilder(spec.diagram_id, rules)
    builder.add_findings(semantic.findings)
    if geometry is not None:
        builder.add_findings(geometry.findings)
    builder.add_findings(output_findings)
    builder.add_findings(additional_findings)
    if layout is not None:
        for warning in layout.warnings:
            builder.add_finding(make_finding(Severity.WARNING, "layout.warning", warning))
    for record in semantic.icon_records:
        builder.add_icon_resolution(record)
    for index, record in enumerate(rule_trace):
        builder.add_decision(DecisionRecord(
            stage="rules",
            kind="rule",
            code=f"rules.override.{index:03d}",
            message=f"applied {record.precedence} override to {record.field_path}",
            details=detail_records({
                "field_path": record.field_path,
                "precedence": record.precedence,
                "previous_value": record.previous_value,
                "override_value": record.override_value,
            }),
        ))
    if layout is not None:
        for index, message in enumerate(layout.decisions):
            builder.add_decision(DecisionRecord(
                stage="layout",
                kind="layout",
                code=f"layout.decision.{index:03d}",
                message=message,
            ))

    semantic_objects = len(spec.nodes) + len(spec.edges) + len(spec.groups)
    builder.summarize_stage("semantic", object_count=semantic_objects)
    builder.summarize_stage("rules", object_count=len(rule_trace))
    if layout is not None:
        layout_objects = len(layout.nodes) + len(layout.routes) + len(layout.groups)
        builder.summarize_stage("layout", object_count=layout_objects)
    elif any(finding.code.startswith("layout.") for finding in additional_findings):
        builder.summarize_stage("layout", object_count=0)
    if geometry is not None and layout is not None:
        builder.summarize_stage("geometry", object_count=layout_objects)
    if output_ran:
        builder.summarize_stage("output", object_count=1)

    geometry_counts = geometry.hard_counts if geometry is not None else HardGateCounts()
    hard_counts = _merge_hard_counts(semantic.hard_counts, geometry_counts)
    if layout is None:
        score = calculate_quality_score(rules, hard_gates=hard_counts)
    else:
        edge_count = layout.metrics.edge_count
        preferred_total_bends = int(
            rules.quality_gates.soft.maximum_average_bends_per_edge * edge_count
        )
        long_labels = sum(
            bool(edge.label) and len(edge.label or "") > rules.edges.label.maximum_characters
            for edge in spec.edges
        )
        score = calculate_quality_score(
            rules,
            hard_gates=hard_counts,
            residual_crossings=layout.metrics.crossing_count,
            extra_bends=max(0, layout.metrics.total_bends - preferred_total_bends),
            fallback_icons=0,
            long_edge_labels=long_labels,
            route_stretch_violations=_route_stretch_violations(layout, rules),
            soft_spacing_violations=0,
        )
    report = builder.build(hard_gates=hard_counts, quality_score=score)
    present = {stage.stage for stage in report.stages}
    skipped = tuple(
        StageSummary(
            stage=stage,
            status="skipped",
            error_count=0,
            warning_count=0,
            info_count=0,
            object_count=0,
        )
        for stage in ("semantic", "rules", "layout", "geometry", "output")
        if stage not in present
    )
    if skipped:
        report = report.model_copy(
            update={"stages": tuple(sorted((*report.stages, *skipped), key=lambda item: item.stage))}
        )
    return report


class CloudDiagramCompiler:
    """Long-lived shared compiler with rules and verified icon registry loaded once."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment(validate_files=True)
        self.settings.require_files()
        assert self.settings.rules_path is not None
        assert self.settings.registry_path is not None
        self.rules = load_rules(self.settings.rules_path)
        self.registry = IconRegistry.load(self.settings.registry_path)
        self.registry_verification = self.registry.verify(strict=True)

    def _effective_inputs(self, spec: DiagramSpec) -> tuple[DiagramSpec, RuleSet, tuple[Any, ...]]:
        if spec.overrides.template is not None:
            raise SpecLoadError(
                f"unsupported layout template {spec.overrides.template!r}: no template registry exists"
            )
        override = spec.overrides.model_dump(exclude={"template"}, exclude_none=True, mode="python")
        resolution = RuleEngine().resolve(self.rules, diagram_override=override or None)
        execution_spec = spec.model_copy(update={"overrides": DiagramOverrides()})
        return execution_spec, resolution.effective_rules, resolution.trace

    def compile(self, value: DiagramSpec | Mapping[str, Any]) -> CompilationResult:
        return self._run(value)

    def validate(
        self,
        value: DiagramSpec | Mapping[str, Any],
        *,
        drawio: bytes | str | None = None,
    ) -> CompilationResult:
        """Compile in memory; optionally validate caller-supplied XML against fresh inputs."""

        supplied = drawio.encode("utf-8") if isinstance(drawio, str) else drawio
        return self._run(value, supplied_drawio=supplied)

    def _run(
        self,
        value: DiagramSpec | Mapping[str, Any],
        *,
        supplied_drawio: bytes | None = None,
    ) -> CompilationResult:
        spec = validate_diagram_spec(value)
        execution_spec, effective_rules, rule_trace = self._effective_inputs(spec)

        semantic = validate_semantics(execution_spec, self.registry, effective_rules)
        if not semantic.hard_pass:
            raise CompilationError(_build_diagnostics(
                spec,
                effective_rules,
                rule_trace,
                semantic,
            ))

        try:
            layout = layout_diagram(execution_spec, effective_rules)
            repeated_layout = layout_diagram(execution_spec, effective_rules)
        except (ValueError, RuntimeError) as exc:
            finding = make_finding(
                Severity.ERROR,
                "layout.error",
                "deterministic layout failed",
                details={"error": str(exc)},
            )
            raise CompilationError(_build_diagnostics(
                spec,
                effective_rules,
                rule_trace,
                semantic,
                additional_findings=(finding,),
            )) from exc
        geometry = validate_geometry(
            layout,
            execution_spec,
            effective_rules,
            comparison=repeated_layout,
        )
        if not geometry.hard_pass:
            raise CompilationError(_build_diagnostics(
                spec,
                effective_rules,
                rule_trace,
                semantic,
                layout=layout,
                geometry=geometry,
            ))

        try:
            generated = render_drawio(
                execution_spec,
                layout,
                semantic.resolutions,
                self.registry,
                effective_rules,
            )
        except ValueError as exc:
            finding = make_finding(
                Severity.ERROR,
                "output.render_error",
                "draw.io rendering failed",
                details={"error": str(exc)},
            )
            raise CompilationError(_build_diagnostics(
                spec,
                effective_rules,
                rule_trace,
                semantic,
                layout=layout,
                geometry=geometry,
                output_ran=True,
                additional_findings=(finding,),
            )) from exc
        output_data = generated if supplied_drawio is None else supplied_drawio
        output = validate_drawio_output(
            output_data,
            execution_spec,
            layout,
            semantic.resolutions,
            self.registry,
            effective_rules,
        )
        report = _build_diagnostics(
            spec,
            effective_rules,
            rule_trace,
            semantic,
            layout=layout,
            geometry=geometry,
            output_findings=output.findings,
            output_ran=True,
        )
        if not report.hard_pass or not output.hard_pass:
            raise CompilationError(report)

        requested_by_node = {
            record.node_id: record.requested for record in semantic.icon_records
        }
        resolved_icons = tuple(
            ResolvedIconMetadata(
                node_id=node_id,
                requested=requested_by_node[node_id],
                icon_id=resolution.entry.id,
                provider=resolution.entry.provider,
                kind=resolution.entry.kind,
                category=resolution.entry.category,
                display_name=resolution.entry.display_name,
                checksum=resolution.entry.checksum,
                deprecated=resolution.entry.deprecated,
                reason=resolution.reason,
            )
            for node_id, resolution in sorted(semantic.resolutions.items())
        )
        stages = {stage.stage: stage for stage in report.stages}
        return CompilationResult(
            spec=spec,
            layout=layout,
            drawio=output_data,
            diagnostics=report,
            semantic_summary=stages["semantic"],
            geometry_summary=stages["geometry"],
            output_summary=stages["output"],
            resolved_icons=resolved_icons,
        )

    def write(
        self,
        value: DiagramSpec | Mapping[str, Any],
        path: str | os.PathLike[str],
    ) -> CompilationResult:
        """Compile, then use the renderer's validated same-directory atomic writer."""

        result = self.compile(value)
        write_bytes_atomic(path, result.drawio)
        return result

    def search_icons(
        self,
        query: str,
        *,
        provider: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> tuple[dict[str, Any], ...]:
        entries = self.registry.search(query, provider=provider, kind=kind, limit=limit)
        return tuple({
            "aliases": list(entry.aliases),
            "category": entry.category,
            "deprecated": entry.deprecated,
            "display_name": entry.display_name,
            "id": entry.id,
            "kind": entry.kind,
            "provider": entry.provider,
        } for entry in entries)


__all__ = [
    "CloudDiagramCompiler",
    "CompilationError",
    "CompilationResult",
    "ResolvedIconMetadata",
    "SpecLoadError",
    "load_diagram_spec",
    "parse_diagram_spec",
    "validate_diagram_spec",
    "write_bytes_atomic",
    "write_diagnostics",
    "write_diagram_spec",
    "write_text_atomic",
]
