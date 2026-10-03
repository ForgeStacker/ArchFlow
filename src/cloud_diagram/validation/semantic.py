"""Pre-layout semantic and exact icon-resolution validation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from cloud_diagram.diagnostics import (
    Finding,
    HardGateCounts,
    IconResolutionRecord,
    Severity,
    hard_gate_counts,
    make_finding,
)
from cloud_diagram.domain import DiagramSpec, Provider
from cloud_diagram.icons import IconRegistry, Resolution
from cloud_diagram.rules import RuleSet


@dataclass(frozen=True, slots=True)
class SemanticValidationResult:
    resolutions: Mapping[str, Resolution]
    findings: tuple[Finding, ...]
    hard_counts: HardGateCounts
    icon_records: tuple[IconResolutionRecord, ...]

    @property
    def hard_pass(self) -> bool:
        return self.hard_counts.total == 0 and not any(
            finding.severity is Severity.ERROR for finding in self.findings
        )

    def raise_for_errors(self) -> None:
        errors = [finding for finding in self.findings if finding.severity is Severity.ERROR]
        if errors:
            raise SemanticValidationError(errors)


class SemanticValidationError(ValueError):
    def __init__(self, findings: list[Finding] | tuple[Finding, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("semantic validation failed:\n" + "\n".join(f"{f.code}: {f.message}" for f in self.findings))


def validate_semantics(
    spec: DiagramSpec,
    registry: IconRegistry,
    rules: RuleSet | None = None,
) -> SemanticValidationResult:
    """Resolve only canonical IDs or exact provider-scoped aliases and validate semantics."""

    findings: list[Finding] = []
    resolutions: dict[str, Resolution] = {}
    records: list[IconResolutionRecord] = []
    explicit_mixed = Provider.MIXED_CLOUD in spec.provider_scope

    for node in spec.nodes:
        requested = node.icon.service_id if node.icon.kind == "canonical" else node.icon.alias
        entry = None
        reason = None
        if node.icon.kind == "canonical":
            entry = registry.get(requested)
            reason = "exact-id" if entry is not None else None
            if entry is None:
                findings.append(make_finding(
                    Severity.ERROR,
                    "semantic.icon.unresolved",
                    f"node {node.id!r} references unknown canonical icon {requested!r}",
                    object_ids=(node.id,),
                    details={"requested": requested, "provider": node.provider.value},
                    hard_gate="maximum_unresolved_icons",
                ))
        else:
            provider_scope = None if node.provider in {Provider.MIXED_CLOUD, Provider.NEUTRAL} else node.provider.value
            candidates = registry.alias_candidates(requested, provider_scope)
            if len(candidates) == 1:
                entry = candidates[0]
                reason = "exact-provider-alias" if provider_scope else "exact-alias"
            elif not candidates:
                findings.append(make_finding(
                    Severity.ERROR,
                    "semantic.icon.unresolved",
                    f"node {node.id!r} has no exact alias match for {requested!r}",
                    object_ids=(node.id,),
                    details={"requested": requested, "provider": node.provider.value},
                    hard_gate="maximum_unresolved_icons",
                ))
            else:
                candidate_ids = tuple(candidate.id for candidate in candidates)
                findings.append(make_finding(
                    Severity.ERROR,
                    "semantic.icon.ambiguous",
                    f"node {node.id!r} alias {requested!r} is ambiguous",
                    object_ids=(node.id, *candidate_ids),
                    details={"candidates": candidate_ids, "provider": node.provider.value},
                    hard_gate="maximum_unresolved_icons",
                ))

        if entry is not None and reason is not None:
            resolution = Resolution(entry=entry, reason=reason)
            resolutions[node.id] = resolution
            provider_matches = entry.provider == node.provider.value
            mixed_node = explicit_mixed and node.provider in {Provider.MIXED_CLOUD, Provider.NEUTRAL}
            if not provider_matches and not mixed_node:
                findings.append(make_finding(
                    Severity.ERROR,
                    "semantic.icon.provider_mismatch",
                    f"resolved icon provider {entry.provider!r} does not match node provider {node.provider.value!r}",
                    object_ids=(node.id, entry.id),
                    details={"icon_provider": entry.provider, "node_provider": node.provider.value},
                ))
            if entry.deprecated:
                findings.append(make_finding(
                    Severity.WARNING,
                    "semantic.icon.deprecated",
                    f"node {node.id!r} uses deprecated icon {entry.id!r}",
                    object_ids=(node.id, entry.id),
                ))
        records.append(IconResolutionRecord(
            node_id=node.id,
            requested=requested,
            requested_kind=node.icon.kind,
            node_provider=node.provider.value,
            resolved_id=entry.id if entry is not None else None,
            resolved_provider=entry.provider if entry is not None else None,
            reason=reason,
            deprecated=bool(entry and entry.deprecated),
        ))

    node_ids = {node.id for node in spec.nodes}
    dangling = 0
    incident: dict[str, int] = {node_id: 0 for node_id in node_ids}
    for edge in spec.edges:
        missing = tuple(sorted({edge.source, edge.target} - node_ids))
        if missing:
            dangling += 1
            findings.append(make_finding(
                Severity.ERROR,
                "semantic.edge.dangling",
                f"edge {edge.id!r} references missing terminal(s)",
                object_ids=(edge.id, *missing),
                hard_gate="maximum_dangling_edges",
            ))
            continue
        incident[edge.source] += 1
        incident[edge.target] += 1

    for node in spec.nodes:
        if incident[node.id] != 0:
            continue
        is_critical = "critical" in {tag.casefold() for tag in node.tags}
        severity = Severity.ERROR if is_critical else Severity.WARNING
        findings.append(make_finding(
            severity,
            "semantic.node.isolated_critical" if is_critical else "semantic.node.isolated",
            f"{'critical ' if is_critical else ''}node {node.id!r} is isolated",
            object_ids=(node.id,),
        ))

    _validate_group_semantics(spec, rules, explicit_mixed, findings)
    ordered_findings = tuple(sorted(findings, key=lambda item: (item.severity.value, item.code, item.object_ids, item.message)))
    counts = hard_gate_counts(
        ordered_findings,
        maximum_unresolved_icons=sum(
            finding.hard_gate == "maximum_unresolved_icons" for finding in ordered_findings
        ),
        maximum_dangling_edges=dangling,
    )
    return SemanticValidationResult(
        resolutions=MappingProxyType(dict(sorted(resolutions.items()))),
        findings=ordered_findings,
        hard_counts=counts,
        icon_records=tuple(sorted(records, key=lambda item: item.node_id)),
    )


def _validate_group_semantics(
    spec: DiagramSpec,
    rules: RuleSet | None,
    explicit_mixed: bool,
    findings: list[Finding],
) -> None:
    groups = {group.id: group for group in spec.groups}
    direct_nodes: dict[str, list[object]] = {group_id: [] for group_id in groups}
    children: dict[str, list[str]] = {group_id: [] for group_id in groups}
    for node in spec.nodes:
        if node.group_id is not None:
            direct_nodes[node.group_id].append(node)
    for group in spec.groups:
        if group.parent_id is not None:
            children[group.parent_id].append(group.id)

    def descendant_providers(group_id: str) -> set[str]:
        providers = {node.provider.value for node in direct_nodes[group_id]}  # type: ignore[attr-defined]
        for child_id in children[group_id]:
            providers.update(descendant_providers(child_id))
        return providers

    for group in spec.groups:
        providers = descendant_providers(group.id)
        concrete = providers - {Provider.MIXED_CLOUD.value, Provider.NEUTRAL.value}
        if len(concrete) > 1 and not explicit_mixed:
            findings.append(make_finding(
                Severity.ERROR,
                "semantic.group.provider_mismatch",
                f"group {group.id!r} contains multiple providers without mixed-cloud semantics",
                object_ids=(group.id,),
                details={"providers": tuple(sorted(concrete))},
            ))
        hierarchy = rules.containers.hierarchy if rules is not None else ()
        provider: str | None = None
        if rules is not None and len(concrete) == 1:
            provider = next(iter(concrete))
            profile = getattr(rules.provider_profiles, provider, None)
            if profile is not None and hasattr(profile, "hierarchy"):
                hierarchy = profile.hierarchy
            neutral_types = {"provider", "network"}
            provider_extras = {
                Provider.AZURE.value: {"resource_group"},
                Provider.GCP.value: {"project"},
            }
            group_type = group.type.value
            if group_type not in hierarchy and group_type not in neutral_types | provider_extras.get(provider, set()):
                findings.append(make_finding(
                    Severity.ERROR,
                    "semantic.group.provider_hierarchy",
                    f"group {group.id!r} type {group_type!r} is incompatible with provider {provider!r}",
                    object_ids=(group.id,),
                    details={"provider": provider, "group_type": group_type},
                ))
        if group.parent_id is None or rules is None:
            continue
        parent = groups[group.parent_id]
        parent_type, child_type = parent.type.value, group.type.value
        if parent_type in hierarchy and child_type in hierarchy:
            if hierarchy.index(parent_type) >= hierarchy.index(child_type):
                findings.append(make_finding(
                    Severity.ERROR,
                    "semantic.group.hierarchy",
                    f"group {group.id!r} is not below parent {parent.id!r} in the active hierarchy",
                    object_ids=(parent.id, group.id),
                    details={"parent_type": parent_type, "child_type": child_type},
                ))


__all__ = [
    "SemanticValidationError",
    "SemanticValidationResult",
    "validate_semantics",
]
