"""Deterministic grid-aligned seven-slot semantic port allocation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from cloud_diagram.domain import EdgeKind, PortSide, SemanticRole
from cloud_diagram.graph import DiagramGraph, GraphEdge
from cloud_diagram.layout.geometry import NodePlacement, Point, Port
from cloud_diagram.rules import RuleSet


class PortAssignmentError(ValueError):
    """Raised when fixed port slots or routing hints are illegal."""


@dataclass(frozen=True, slots=True)
class EdgePorts:
    edge_id: str
    source: Port
    target: Port


@dataclass(frozen=True, slots=True)
class PortAssignments:
    edges: tuple[EdgePorts, ...]
    diagnostics: tuple[str, ...] = ()

    @property
    def by_edge(self) -> Mapping[str, EdgePorts]:
        return MappingProxyType({value.edge_id: value for value in self.edges})


def _semantic_class(edge: GraphEdge, graph: DiagramGraph) -> str:
    if edge.feedback:
        return "feedback"
    roles = {graph.node_index[edge.source].node.role, graph.node_index[edge.target].node.role}
    # An edge is observability-adjacent if it is tagged as such OR if either
    # endpoint has the observability role, matching the ranking module's
    # progression-exclusion rule (graph/ranking.py::_forces_progression). The
    # two must agree, or ranking can exclude an edge from primary progression
    # while ports/routing still treat it as ordinary east/west primary flow,
    # producing a route that violates the very exclusion ranking decided on.
    if edge.edge.kind is EdgeKind.OBSERVABILITY or SemanticRole.OBSERVABILITY in roles:
        return "observability"
    if SemanticRole.IDENTITY in roles or edge.edge.kind is EdgeKind.DEPENDENCY:
        return "control"
    if edge.edge.kind is EdgeKind.DATA:
        return "data"
    if edge.edge.kind is EdgeKind.ASYNCHRONOUS:
        return "asynchronous"
    if edge.edge.kind is EdgeKind.BIDIRECTIONAL:
        return "bidirectional"
    return "primary_flow"


def _opposed_sides(source: NodePlacement, target: NodePlacement) -> tuple[PortSide, PortSide]:
    dx = target.rect.center.x - source.rect.center.x
    dy = target.rect.center.y - source.rect.center.y
    if abs(dx) >= abs(dy):
        return (PortSide.EAST, PortSide.WEST) if dx >= 0 else (PortSide.WEST, PortSide.EAST)
    return (PortSide.SOUTH, PortSide.NORTH) if dy >= 0 else (PortSide.NORTH, PortSide.SOUTH)


def _validate_hint(edge: GraphEdge, source: PortSide, target: PortSide) -> None:
    hint = edge.edge.routing_hint
    if hint is None:
        return
    illegal: list[str] = []
    if hint.source_side is not None and hint.source_side is not source:
        illegal.append(f"source_side={hint.source_side.value}, required={source.value}")
    if hint.target_side is not None and hint.target_side is not target:
        illegal.append(f"target_side={hint.target_side.value}, required={target.value}")
    if illegal:
        raise PortAssignmentError(
            f"edge {edge.id!r} has illegal routing hint for its classified semantics: "
            + ", ".join(illegal)
        )


def _sides(
    edge: GraphEdge,
    graph: DiagramGraph,
    placements: Mapping[str, NodePlacement],
) -> tuple[PortSide, PortSide]:
    semantic = _semantic_class(edge, graph)
    if semantic == "feedback":
        result = (PortSide.SOUTH, PortSide.SOUTH)
    elif semantic == "observability":
        # Observability nodes are placed below the primary flow, so an edge
        # leaves the primary node's south side and arrives at the
        # observability node's north side, matching the rules'
        # ``preferred_side: south`` placement for observability.
        source_role = graph.node_index[edge.source].node.role
        target_role = graph.node_index[edge.target].node.role
        if source_role is SemanticRole.OBSERVABILITY:
            result = (PortSide.NORTH, PortSide.SOUTH)
        else:
            result = (PortSide.SOUTH, PortSide.NORTH)
    elif semantic == "control":
        result = (PortSide.NORTH, PortSide.NORTH)
    elif semantic == "bidirectional":
        result = _opposed_sides(placements[edge.source], placements[edge.target])
    else:
        result = (PortSide.EAST, PortSide.WEST)
    _validate_hint(edge, *result)
    if result == (PortSide.SOUTH, PortSide.SOUTH) and not edge.feedback:
        raise PortAssignmentError(f"edge {edge.id!r} illegally selected south/south without feedback classification")
    return result


def _slot_order(*, include_center: bool) -> tuple[int, ...]:
    center = 3
    result = [center] if include_center else []
    for distance in range(1, 4):
        result.extend((center - distance, center + distance))
    return tuple(result)


def _port_point(
    placement: NodePlacement,
    side: PortSide,
    slot: int,
    *,
    gap: int,
) -> Point:
    rect = placement.rect
    offset = (slot - 3) * gap
    if side is PortSide.EAST:
        return Point(x=rect.right, y=rect.center.y + offset)
    if side is PortSide.WEST:
        return Point(x=rect.left, y=rect.center.y + offset)
    if side is PortSide.NORTH:
        return Point(x=rect.center.x + offset, y=rect.top)
    return Point(x=rect.center.x + offset, y=rect.bottom)


def assign_ports(
    graph: DiagramGraph,
    nodes: tuple[NodePlacement, ...],
    rules: RuleSet,
) -> PortAssignments:
    """Allocate distinct symmetric slots with corner and center reservations."""

    if rules.ports.slots_per_side != 7:
        raise PortAssignmentError(
            f"internal-layered-v1 supports exactly seven ports per side, got {rules.ports.slots_per_side}"
        )
    grid = rules.ruleset.grid_size
    gap = ((max(grid, rules.ports.minimum_port_gap) + grid - 1) // grid) * grid
    node_placements = {node.node_id: node for node in nodes}
    allocation_priority = {name: index for index, name in enumerate(rules.ports.allocation_order)}
    allocation_priority.setdefault("bidirectional", len(allocation_priority))
    requested: list[tuple[GraphEdge, PortSide, PortSide]] = []
    for edge in graph.edges:
        source_side, target_side = _sides(edge, graph, node_placements)
        requested.append((edge, source_side, target_side))
    requested.sort(
        key=lambda value: (
            allocation_priority.get(_semantic_class(value[0], graph), len(allocation_priority)),
            value[0].source,
            value[0].target,
            value[0].edge.kind.value,
            value[0].id,
        )
    )

    used_slots: dict[tuple[str, PortSide], set[int]] = {}

    def allocate(edge: GraphEdge, node_id: str, terminal: str, side: PortSide) -> Port:
        semantic = _semantic_class(edge, graph)
        include_center = not rules.ports.reserve_center_slot_for_primary_flow or semantic == "primary_flow"
        order = _slot_order(include_center=include_center)
        key = (node_id, side)
        used = used_slots.setdefault(key, set())
        available = next((slot for slot in order if slot not in used), None)
        if available is None:
            reservation = " (center reserved for primary flow)" if not include_center else ""
            raise PortAssignmentError(
                f"node {node_id!r} has no distinct {side.value} slot for edge {edge.id!r}{reservation}"
            )
        point = _port_point(node_placements[node_id], side, available, gap=gap)
        rect = node_placements[node_id].rect
        exclusion = rules.ports.corner_exclusion
        if side in {PortSide.EAST, PortSide.WEST}:
            legal = rect.top + exclusion <= point.y <= rect.bottom - exclusion
        else:
            legal = rect.left + exclusion <= point.x <= rect.right - exclusion
        if not legal:
            raise PortAssignmentError(
                f"node {node_id!r} is too small for seven grid-aligned {side.value} slots: "
                f"point={point.model_dump()} corner_exclusion={exclusion}px gap={gap}px"
            )
        if point.x % grid or point.y % grid:
            raise PortAssignmentError(f"edge {edge.id!r} produced off-grid port {point.model_dump()}")
        used.add(available)
        return Port(
            edge_id=edge.id,
            node_id=node_id,
            terminal=terminal,
            side=side,
            slot=available,
            point=point,
        )

    assignments = [
        EdgePorts(
            edge_id=edge.id,
            source=allocate(edge, edge.source, "source", source_side),
            target=allocate(edge, edge.target, "target", target_side),
        )
        for edge, source_side, target_side in requested
    ]
    return PortAssignments(
        edges=tuple(sorted(assignments, key=lambda value: value.edge_id)),
        diagnostics=(
            f"seven-slot allocation enforced; grid-aligned slot gap={gap}px; corner exclusion={rules.ports.corner_exclusion}px",
            "identity and dependency edges classified as control",
            "bidirectional edges use deterministic shortest opposed sides",
        ),
    )


__all__ = ["EdgePorts", "PortAssignmentError", "PortAssignments", "assign_ports"]
