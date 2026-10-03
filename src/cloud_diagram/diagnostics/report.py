"""Immutable, deterministic compilation diagnostics."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from cloud_diagram.rules import RuleSet


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


NonEmpty = Annotated[StrictStr, Field(min_length=1)]
HardGateName = Literal[
    "maximum_node_overlaps",
    "maximum_node_title_intersections",
    "maximum_edge_node_intersections_excluding_terminals",
    "maximum_edge_title_intersections",
    "maximum_label_overlaps",
    "maximum_unresolved_icons",
    "maximum_clipped_children",
    "maximum_unsatisfied_minimum_spacing_rules",
    "maximum_dangling_edges",
    "maximum_geometry_drift_on_repeat_run",
]

_SECRET_KEY = re.compile(
    r"(?:^|[_\-.])(api[_-]?key|access[_-]?key|secret|token|password|passwd|credential|private[_-]?key|authorization|bearer)(?:$|[_\-.])",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"


class DiagnosticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class Detail(DiagnosticModel):
    key: NonEmpty
    value: StrictStr


class Finding(DiagnosticModel):
    severity: Severity
    code: NonEmpty
    message: NonEmpty
    object_ids: tuple[StrictStr, ...] = ()
    details: tuple[Detail, ...] = ()
    hard_gate: HardGateName | None = None

    @model_validator(mode="after")
    def canonicalize(self) -> "Finding":
        object.__setattr__(self, "object_ids", tuple(sorted(set(self.object_ids))))
        object.__setattr__(self, "details", tuple(sorted(self.details, key=lambda item: (item.key, item.value))))
        return self


class StageSummary(DiagnosticModel):
    stage: NonEmpty
    status: Literal["passed", "warning", "failed", "skipped"]
    error_count: StrictInt = Field(ge=0)
    warning_count: StrictInt = Field(ge=0)
    info_count: StrictInt = Field(ge=0)
    object_count: StrictInt = Field(default=0, ge=0)


class IconResolutionRecord(DiagnosticModel):
    node_id: NonEmpty
    requested: NonEmpty
    requested_kind: Literal["canonical", "alias"]
    node_provider: NonEmpty
    resolved_id: StrictStr | None = None
    resolved_provider: StrictStr | None = None
    reason: StrictStr | None = None
    deprecated: StrictBool = False


class DecisionRecord(DiagnosticModel):
    stage: NonEmpty
    kind: Literal["rule", "layout"]
    code: NonEmpty
    message: NonEmpty
    object_ids: tuple[StrictStr, ...] = ()
    details: tuple[Detail, ...] = ()

    @model_validator(mode="after")
    def canonicalize(self) -> "DecisionRecord":
        object.__setattr__(self, "object_ids", tuple(sorted(set(self.object_ids))))
        object.__setattr__(self, "details", tuple(sorted(self.details, key=lambda item: (item.key, item.value))))
        return self


class HardGateCounts(DiagnosticModel):
    """Observed counts for every hard-gate key in :class:`RuleSet`."""

    maximum_node_overlaps: StrictInt = Field(default=0, ge=0)
    maximum_node_title_intersections: StrictInt = Field(default=0, ge=0)
    maximum_edge_node_intersections_excluding_terminals: StrictInt = Field(default=0, ge=0)
    maximum_edge_title_intersections: StrictInt = Field(default=0, ge=0)
    maximum_label_overlaps: StrictInt = Field(default=0, ge=0)
    maximum_unresolved_icons: StrictInt = Field(default=0, ge=0)
    maximum_clipped_children: StrictInt = Field(default=0, ge=0)
    maximum_unsatisfied_minimum_spacing_rules: StrictInt = Field(default=0, ge=0)
    maximum_dangling_edges: StrictInt = Field(default=0, ge=0)
    maximum_geometry_drift_on_repeat_run: StrictInt = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return sum(self.model_dump().values())

    def passes(self, rules: RuleSet) -> bool:
        limits = rules.quality_gates.hard.model_dump()
        observed = self.model_dump()
        if tuple(sorted(limits)) != tuple(sorted(observed)):
            return False
        return all(observed[key] <= limits[key] for key in limits)


class DiagnosticReport(DiagnosticModel):
    schema_version: Literal["1.0"] = "1.0"
    diagram_id: NonEmpty
    ruleset_id: NonEmpty
    ruleset_version: NonEmpty
    stages: tuple[StageSummary, ...] = ()
    icon_resolutions: tuple[IconResolutionRecord, ...] = ()
    decisions: tuple[DecisionRecord, ...] = ()
    findings: tuple[Finding, ...] = ()
    hard_gates: HardGateCounts = Field(default_factory=HardGateCounts)
    quality_score: StrictInt = Field(ge=0, le=100)
    hard_pass: StrictBool

    @model_validator(mode="after")
    def sort_records(self) -> "DiagnosticReport":
        object.__setattr__(self, "stages", tuple(sorted(self.stages, key=lambda item: item.stage)))
        object.__setattr__(self, "icon_resolutions", tuple(sorted(self.icon_resolutions, key=lambda item: item.node_id)))
        object.__setattr__(self, "decisions", tuple(sorted(self.decisions, key=_model_sort_key)))
        object.__setattr__(self, "findings", tuple(sorted(self.findings, key=_model_sort_key)))
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    to_canonical_json = canonical_json


class ReportBuilder:
    """Mutable accumulator that emits an immutable, canonically sorted report."""

    def __init__(self, diagram_id: str, rules: RuleSet) -> None:
        self.diagram_id = diagram_id
        self.rules = rules
        self._findings: list[Finding] = []
        self._icons: list[IconResolutionRecord] = []
        self._decisions: list[DecisionRecord] = []
        self._stages: dict[str, StageSummary] = {}

    def add_finding(self, finding: Finding) -> "ReportBuilder":
        self._findings.append(redact_finding(finding))
        return self

    def add_findings(self, findings: Iterable[Finding]) -> "ReportBuilder":
        for finding in findings:
            self.add_finding(finding)
        return self

    def add_icon_resolution(self, record: IconResolutionRecord) -> "ReportBuilder":
        self._icons.append(record)
        return self

    def add_decision(self, record: DecisionRecord) -> "ReportBuilder":
        self._decisions.append(redact_decision(record))
        return self

    def summarize_stage(self, stage: str, *, object_count: int = 0) -> "ReportBuilder":
        relevant = [finding for finding in self._findings if finding.code.startswith(f"{stage}.")]
        errors = sum(finding.severity is Severity.ERROR for finding in relevant)
        warnings = sum(finding.severity is Severity.WARNING for finding in relevant)
        infos = sum(finding.severity is Severity.INFO for finding in relevant)
        status: Literal["passed", "warning", "failed", "skipped"] = (
            "failed" if errors else "warning" if warnings else "passed"
        )
        self._stages[stage] = StageSummary(
            stage=stage,
            status=status,
            error_count=errors,
            warning_count=warnings,
            info_count=infos,
            object_count=object_count,
        )
        return self

    def build(
        self,
        *,
        hard_gates: HardGateCounts | None = None,
        quality_score: int | None = None,
    ) -> DiagnosticReport:
        counts = hard_gates or hard_gate_counts(self._findings)
        score = quality_score if quality_score is not None else max(0, min(100, self.rules.quality_gates.scoring.start - counts.total * 10))
        return DiagnosticReport(
            diagram_id=self.diagram_id,
            ruleset_id=self.rules.ruleset.id,
            ruleset_version=self.rules.ruleset.version,
            stages=tuple(self._stages.values()),
            icon_resolutions=tuple(self._icons),
            decisions=tuple(self._decisions),
            findings=tuple(self._findings),
            hard_gates=counts,
            quality_score=score,
            hard_pass=counts.passes(self.rules) and not any(f.severity is Severity.ERROR for f in self._findings),
        )


def detail_records(details: Mapping[str, Any] | None = None) -> tuple[Detail, ...]:
    records: list[Detail] = []
    for key, value in sorted((details or {}).items(), key=lambda item: str(item[0])):
        normalized_key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key))
        text = _REDACTED if _SECRET_KEY.search(normalized_key) else _stable_value(value)
        records.append(Detail(key=str(key), value=text))
    return tuple(records)


def make_finding(
    severity: Severity | str,
    code: str,
    message: str,
    *,
    object_ids: Iterable[str] = (),
    details: Mapping[str, Any] | None = None,
    hard_gate: HardGateName | None = None,
) -> Finding:
    return Finding(
        severity=Severity(severity),
        code=code,
        message=message,
        object_ids=tuple(object_ids),
        details=detail_records(details),
        hard_gate=hard_gate,
    )


def hard_gate_counts(findings: Iterable[Finding], **overrides: int) -> HardGateCounts:
    values = {name: 0 for name in HardGateCounts.model_fields}
    for finding in findings:
        if finding.hard_gate is not None:
            values[finding.hard_gate] += 1
    for key, value in overrides.items():
        if key not in values:
            raise ValueError(f"unknown hard-gate key: {key}")
        values[key] = value
    return HardGateCounts(**values)


def calculate_quality_score(
    rules: RuleSet,
    *,
    hard_gates: HardGateCounts,
    residual_crossings: int = 0,
    extra_bends: int = 0,
    fallback_icons: int = 0,
    long_edge_labels: int = 0,
    route_stretch_violations: int = 0,
    soft_spacing_violations: int = 0,
) -> int:
    penalties = rules.quality_gates.scoring.penalties
    score = rules.quality_gates.scoring.start
    score -= hard_gates.total * 10
    score -= residual_crossings * penalties.residual_crossing
    score -= extra_bends * penalties.bend_above_preferred
    score -= fallback_icons * penalties.fallback_icon
    score -= long_edge_labels * penalties.long_edge_label
    score -= route_stretch_violations * penalties.route_stretch_above_target
    score -= soft_spacing_violations * penalties.soft_spacing_violation
    return max(0, min(100, score))


def redact_finding(finding: Finding) -> Finding:
    return finding.model_copy(update={"details": detail_records({item.key: item.value for item in finding.details})})


def redact_decision(decision: DecisionRecord) -> DecisionRecord:
    return decision.model_copy(update={"details": detail_records({item.key: item.value for item in decision.details})})


def _stable_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _model_sort_key(value: BaseModel) -> str:
    return json.dumps(value.model_dump(mode="json", exclude_none=True), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = [
    "DecisionRecord",
    "Detail",
    "DiagnosticReport",
    "Finding",
    "HardGateCounts",
    "HardGateName",
    "IconResolutionRecord",
    "ReportBuilder",
    "Severity",
    "StageSummary",
    "calculate_quality_score",
    "detail_records",
    "hard_gate_counts",
    "make_finding",
]
