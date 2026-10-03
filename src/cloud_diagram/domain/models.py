"""Strict, immutable domain contracts for deterministic cloud diagrams."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from .enums import (
    AlignmentAxis,
    Criticality,
    EdgeKind,
    GroupType,
    PortSide,
    Provider,
    SemanticRole,
)

StableId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$",
    ),
]
CanonicalServiceId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=256,
        pattern=r"^(?:aws|azure|gcp):(service|resource|group|category):[a-z0-9]+(?:-[a-z0-9]+)*:[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
NonEmptyText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512)]
Tag = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64)]


class StrictModel(BaseModel):
    """Common closed and immutable Pydantic configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class CanonicalIconReference(StrictModel):
    """A registry canonical service identifier."""

    kind: Literal["canonical"] = "canonical"
    service_id: CanonicalServiceId


class AliasIconReference(StrictModel):
    """An exact, provider-scoped registry alias."""

    kind: Literal["alias"] = "alias"
    alias: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]


IconReference = Annotated[
    CanonicalIconReference | AliasIconReference,
    Field(discriminator="kind"),
]


class GroupPlacementHint(StrictModel):
    """Non-geometric semantic hints consumed by the deterministic compiler."""

    order: StrictInt | None = Field(default=None, ge=0)
    adjacent_to: StableId | None = None


class DiagramGroup(StrictModel):
    id: StableId
    type: GroupType
    parent_id: StableId | None = None
    label: NonEmptyText
    placement: GroupPlacementHint | None = None


class AvailabilityMetadata(StrictModel):
    """Availability facts; these are semantic metadata, not coordinates."""

    region: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)] | None = None
    zone: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)] | None = None
    replica: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)] | None = None
    highly_available: StrictBool = False
    tags: tuple[Tag, ...] = ()

    @model_validator(mode="after")
    def normalize_tags(self) -> "AvailabilityMetadata":
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("availability tags must be unique")
        object.__setattr__(self, "tags", tuple(sorted(self.tags)))
        return self


class DiagramNode(StrictModel):
    id: StableId
    icon: IconReference
    provider: Provider
    role: SemanticRole
    group_id: StableId | None = None
    label: NonEmptyText
    order: StrictInt | None = Field(default=None, ge=0)
    availability: AvailabilityMetadata | None = None
    tags: tuple[Tag, ...] = ()

    @model_validator(mode="after")
    def normalize_tags(self) -> "DiagramNode":
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("node tags must be unique")
        object.__setattr__(self, "tags", tuple(sorted(self.tags)))
        return self


class RoutingHint(StrictModel):
    """Optional semantic routing preferences; feedback is compiler-classified later."""

    source_side: PortSide | None = None
    target_side: PortSide | None = None
    avoid_group_ids: tuple[StableId, ...] = ()

    @model_validator(mode="after")
    def normalize_groups(self) -> "RoutingHint":
        if len(set(self.avoid_group_ids)) != len(self.avoid_group_ids):
            raise ValueError("routing avoid_group_ids must be unique")
        object.__setattr__(self, "avoid_group_ids", tuple(sorted(self.avoid_group_ids)))
        return self


class DiagramEdge(StrictModel):
    id: StableId
    source: StableId
    target: StableId
    kind: EdgeKind = EdgeKind.SYNCHRONOUS
    label: NonEmptyText | None = None
    protocol: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)] | None = None
    criticality: Criticality = Criticality.NORMAL
    routing_hint: RoutingHint | None = None


class NodeOrderConstraint(StrictModel):
    before: StableId
    after: StableId

    @model_validator(mode="after")
    def distinct_nodes(self) -> "NodeOrderConstraint":
        if self.before == self.after:
            raise ValueError("order constraint must reference two distinct nodes")
        return self


class AlignmentConstraint(StrictModel):
    node_ids: tuple[StableId, ...] = Field(min_length=2)
    axis: AlignmentAxis

    @model_validator(mode="after")
    def normalize_nodes(self) -> "AlignmentConstraint":
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("alignment node_ids must be unique")
        object.__setattr__(self, "node_ids", tuple(sorted(self.node_ids)))
        return self


class SeparationConstraint(StrictModel):
    first: StableId
    second: StableId
    minimum_grid_units: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def normalize_pair(self) -> "SeparationConstraint":
        if self.first == self.second:
            raise ValueError("separation constraint must reference two distinct nodes")
        if self.second < self.first:
            first, second = self.first, self.second
            object.__setattr__(self, "first", second)
            object.__setattr__(self, "second", first)
        return self


class RequiredMembershipConstraint(StrictModel):
    node_id: StableId
    group_id: StableId


class DiagramConstraints(StrictModel):
    """Bounded, explicitly typed user constraints."""

    node_order: tuple[NodeOrderConstraint, ...] = ()
    alignments: tuple[AlignmentConstraint, ...] = ()
    separations: tuple[SeparationConstraint, ...] = ()
    required_memberships: tuple[RequiredMembershipConstraint, ...] = ()

    @model_validator(mode="after")
    def normalize_constraints(self) -> "DiagramConstraints":
        object.__setattr__(self, "node_order", tuple(sorted(self.node_order, key=lambda value: (value.before, value.after))))
        object.__setattr__(self, "alignments", tuple(sorted(self.alignments, key=lambda value: (value.axis.value, value.node_ids))))
        object.__setattr__(self, "separations", tuple(sorted(self.separations, key=lambda value: (value.first, value.second))))
        object.__setattr__(self, "required_memberships", tuple(sorted(self.required_memberships, key=lambda value: (value.node_id, value.group_id))))
        return self


class DiagramOverrides(StrictModel):
    """Allowed per-diagram tuning. Flow direction is deliberately absent."""

    template: StableId | None = None
    grid_size: StrictInt | None = Field(default=None, gt=0)
    rank_spacing: StrictInt | None = Field(default=None, gt=0)
    component_spacing: StrictInt | None = Field(default=None, gt=0)


class DiagramSpec(StrictModel):
    """Validated semantic input to the left-to-right diagram compiler."""

    schema_version: Literal["1.0"] = "1.0"
    diagram_id: StableId
    title: NonEmptyText
    provider_scope: tuple[Provider, ...] = Field(min_length=1)
    groups: tuple[DiagramGroup, ...] = ()
    nodes: tuple[DiagramNode, ...] = ()
    edges: tuple[DiagramEdge, ...] = ()
    constraints: DiagramConstraints = Field(default_factory=DiagramConstraints)
    overrides: DiagramOverrides = Field(default_factory=DiagramOverrides)

    @model_validator(mode="after")
    def validate_and_canonicalize(self) -> "DiagramSpec":
        if len(set(self.provider_scope)) != len(self.provider_scope):
            raise ValueError("provider_scope entries must be unique")

        group_ids = [group.id for group in self.groups]
        node_ids = [node.id for node in self.nodes]
        edge_ids = [edge.id for edge in self.edges]
        self._reject_duplicates("group", group_ids)
        self._reject_duplicates("node", node_ids)
        self._reject_duplicates("edge", edge_ids)
        all_ids = group_ids + node_ids + edge_ids
        self._reject_duplicates("object", all_ids)

        group_id_set = set(group_ids)
        node_id_set = set(node_ids)
        for group in self.groups:
            if group.parent_id is not None and group.parent_id not in group_id_set:
                raise ValueError(f"group {group.id!r} has unresolved parent_id {group.parent_id!r}")
            if group.placement is not None and group.placement.adjacent_to is not None:
                adjacent_to = group.placement.adjacent_to
                if adjacent_to not in group_id_set:
                    raise ValueError(f"group {group.id!r} has unresolved adjacent_to {adjacent_to!r}")
                if adjacent_to == group.id:
                    raise ValueError(f"group {group.id!r} cannot be adjacent to itself")
        for node in self.nodes:
            if node.group_id is not None and node.group_id not in group_id_set:
                raise ValueError(f"node {node.id!r} has unresolved group_id {node.group_id!r}")
            if node.provider not in self.provider_scope and Provider.MIXED_CLOUD not in self.provider_scope:
                raise ValueError(f"node {node.id!r} provider {node.provider.value!r} is outside provider_scope")
        for edge in self.edges:
            if edge.source not in node_id_set:
                raise ValueError(f"edge {edge.id!r} has unresolved source {edge.source!r}")
            if edge.target not in node_id_set:
                raise ValueError(f"edge {edge.id!r} has unresolved target {edge.target!r}")
            if edge.routing_hint is not None:
                unknown = set(edge.routing_hint.avoid_group_ids) - group_id_set
                if unknown:
                    raise ValueError(f"edge {edge.id!r} routing hint has unresolved groups {sorted(unknown)!r}")

        self._reject_containment_cycles()
        self._validate_constraint_references(node_id_set, group_id_set)

        object.__setattr__(self, "provider_scope", tuple(sorted(self.provider_scope, key=str)))
        object.__setattr__(self, "groups", tuple(sorted(self.groups, key=lambda value: value.id)))
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda value: value.id)))
        object.__setattr__(self, "edges", tuple(sorted(self.edges, key=lambda value: value.id)))
        return self

    @staticmethod
    def _reject_duplicates(kind: str, values: list[str]) -> None:
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise ValueError(f"duplicate {kind} IDs: {duplicates!r}")

    def _reject_containment_cycles(self) -> None:
        parents = {group.id: group.parent_id for group in self.groups}
        for start in parents:
            seen: set[str] = set()
            current: str | None = start
            while current is not None:
                if current in seen:
                    raise ValueError(f"containment cycle detected at group {current!r}")
                seen.add(current)
                current = parents[current]

    def _validate_constraint_references(self, node_ids: set[str], group_ids: set[str]) -> None:
        for constraint in self.constraints.node_order:
            self._require_nodes("node_order", (constraint.before, constraint.after), node_ids)
        for constraint in self.constraints.alignments:
            self._require_nodes("alignment", constraint.node_ids, node_ids)
        for constraint in self.constraints.separations:
            self._require_nodes("separation", (constraint.first, constraint.second), node_ids)
        for constraint in self.constraints.required_memberships:
            self._require_nodes("required_membership", (constraint.node_id,), node_ids)
            if constraint.group_id not in group_ids:
                raise ValueError(f"required_membership has unresolved group {constraint.group_id!r}")

    @staticmethod
    def _require_nodes(kind: str, references: tuple[str, ...], node_ids: set[str]) -> None:
        unknown = sorted(set(references) - node_ids)
        if unknown:
            raise ValueError(f"{kind} constraint has unresolved nodes {unknown!r}")

    def canonical_json(self) -> str:
        """Return byte-stable JSON independent of accepted collection order."""

        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    to_canonical_json = canonical_json


__all__ = [
    "AliasIconReference",
    "AlignmentConstraint",
    "AvailabilityMetadata",
    "CanonicalIconReference",
    "DiagramConstraints",
    "DiagramEdge",
    "DiagramGroup",
    "DiagramNode",
    "DiagramOverrides",
    "DiagramSpec",
    "GroupPlacementHint",
    "IconReference",
    "NodeOrderConstraint",
    "RequiredMembershipConstraint",
    "RoutingHint",
    "SeparationConstraint",
    "StableId",
]
