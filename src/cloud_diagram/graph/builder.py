"""Deterministic immutable graph construction from :class:`DiagramSpec`."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import networkx as nx

from cloud_diagram.domain import DiagramEdge, DiagramGroup, DiagramNode, DiagramSpec


class GraphBuildError(ValueError):
    """Raised when semantic constraints cannot form a valid compiler graph."""


@dataclass(frozen=True, slots=True)
class GraphGroup:
    group: DiagramGroup
    parent_path: tuple[str, ...]

    @property
    def id(self) -> str:
        return self.group.id


@dataclass(frozen=True, slots=True)
class GraphNode:
    node: DiagramNode
    group_id: str | None
    parent_path: tuple[str, ...]
    icon_key: str

    @property
    def id(self) -> str:
        return self.node.id


@dataclass(frozen=True, slots=True)
class GraphEdge:
    edge: DiagramEdge
    feedback: bool
    self_loop: bool
    cyclic: bool

    @property
    def id(self) -> str:
        return self.edge.id

    @property
    def source(self) -> str:
        return self.edge.source

    @property
    def target(self) -> str:
        return self.edge.target


@dataclass(frozen=True, slots=True)
class DiagramGraph:
    nodes: tuple[GraphNode, ...]
    groups: tuple[GraphGroup, ...]
    edges: tuple[GraphEdge, ...]
    diagnostics: tuple[str, ...] = ()

    @property
    def node_index(self) -> Mapping[str, GraphNode]:
        return MappingProxyType({node.id: node for node in self.nodes})

    @property
    def group_index(self) -> Mapping[str, GraphGroup]:
        return MappingProxyType({group.id: group for group in self.groups})

    @property
    def edge_index(self) -> Mapping[str, GraphEdge]:
        return MappingProxyType({edge.id: edge for edge in self.edges})

    @property
    def nonfeedback_edges(self) -> tuple[GraphEdge, ...]:
        return tuple(edge for edge in self.edges if not edge.feedback)

    @property
    def feedback_edges(self) -> tuple[GraphEdge, ...]:
        return tuple(edge for edge in self.edges if edge.feedback)


def _icon_key(node: DiagramNode) -> str:
    if node.icon.kind == "canonical":
        return node.icon.service_id
    return f"alias:{node.provider.value}:{node.icon.alias.casefold()}"


def _group_path(group_id: str | None, parents: Mapping[str, str | None]) -> tuple[str, ...]:
    if group_id is None:
        return ()
    path: list[str] = []
    current: str | None = group_id
    while current is not None:
        path.append(current)
        current = parents[current]
    return tuple(reversed(path))


def _dfs_feedback_edges(
    node_ids: tuple[str, ...], edges: tuple[DiagramEdge, ...]
) -> frozenset[str]:
    """Return the stable DFS back-edge subset, including every self-loop.

    Removing exactly DFS back edges makes a directed graph acyclic while retaining
    tree, forward, cross, and parallel edges.  This is the deliberately minimal
    DFS cycle-breaking subset, rather than all edges in each SCC.
    """

    outgoing: dict[str, list[DiagramEdge]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        outgoing[edge.source].append(edge)
    for values in outgoing.values():
        values.sort(key=lambda edge: (edge.target, edge.id))

    white, gray, black = 0, 1, 2
    color = {node_id: white for node_id in node_ids}
    feedback: set[str] = set()

    def visit(node_id: str) -> None:
        color[node_id] = gray
        for edge in outgoing[node_id]:
            if edge.source == edge.target:
                feedback.add(edge.id)
                continue
            target_color = color[edge.target]
            if target_color == white:
                visit(edge.target)
            elif target_color == gray:
                feedback.add(edge.id)
        color[node_id] = black

    for node_id in node_ids:
        if color[node_id] == white:
            visit(node_id)
    return frozenset(feedback)


def build_graph(spec: DiagramSpec) -> DiagramGraph:
    """Build stable graph records and classify only deterministic DFS back edges."""

    group_by_id = {group.id: group for group in spec.groups}
    parents = {group.id: group.parent_id for group in spec.groups}
    required: dict[str, str] = {}
    diagnostics: list[str] = ["synthetic hubs disabled: graph preserves only declared objects"]
    for constraint in spec.constraints.required_memberships:
        previous = required.get(constraint.node_id)
        if previous is not None and previous != constraint.group_id:
            raise GraphBuildError(
                f"node {constraint.node_id!r} has contradictory required memberships "
                f"{previous!r} and {constraint.group_id!r}"
            )
        required[constraint.node_id] = constraint.group_id

    graph_groups = tuple(
        GraphGroup(group=group, parent_path=_group_path(group.id, parents))
        for group in sorted(spec.groups, key=lambda value: value.id)
    )
    graph_nodes: list[GraphNode] = []
    for node in sorted(spec.nodes, key=lambda value: value.id):
        effective_group = required.get(node.id, node.group_id)
        if effective_group != node.group_id:
            diagnostics.append(
                f"explicit required membership moved node {node.id} from "
                f"{node.group_id or '<root>'} to {effective_group}"
            )
        elif node.id in required:
            diagnostics.append(
                f"explicit required membership retained node {node.id} in {effective_group}"
            )
        if effective_group is not None and effective_group not in group_by_id:
            raise GraphBuildError(f"node {node.id!r} has unknown effective group {effective_group!r}")
        graph_nodes.append(
            GraphNode(
                node=node,
                group_id=effective_group,
                parent_path=_group_path(effective_group, parents),
                icon_key=_icon_key(node),
            )
        )

    sorted_edges = tuple(sorted(spec.edges, key=lambda value: value.id))
    directed = nx.DiGraph()
    directed.add_nodes_from(node.id for node in graph_nodes)
    directed.add_edges_from((edge.source, edge.target) for edge in sorted_edges)
    components = tuple(
        frozenset(component) for component in nx.strongly_connected_components(directed)
    )
    component_by_node = {
        node_id: component for component in components for node_id in component
    }
    cyclic_components = {component for component in components if len(component) > 1}

    feedback_ids = _dfs_feedback_edges(
        tuple(node.id for node in graph_nodes), sorted_edges
    )
    graph_edges: list[GraphEdge] = []
    for edge in sorted_edges:
        self_loop = edge.source == edge.target
        component = component_by_node[edge.source]
        cyclic = self_loop or (
            component in cyclic_components
            and component_by_node[edge.target] == component
        )
        feedback = edge.id in feedback_ids
        if feedback:
            reason = "self-loop" if self_loop else "deterministic DFS back edge"
            diagnostics.append(f"edge {edge.id} classified as feedback: {reason}")
        elif cyclic:
            diagnostics.append(f"edge {edge.id} retained as forward SCC edge")
        graph_edges.append(
            GraphEdge(edge=edge, feedback=feedback, self_loop=self_loop, cyclic=cyclic)
        )

    retained = nx.DiGraph()
    retained.add_nodes_from(node.id for node in graph_nodes)
    retained.add_edges_from(
        (edge.source, edge.target) for edge in graph_edges if not edge.feedback
    )
    if not nx.is_directed_acyclic_graph(retained):
        raise GraphBuildError("internal error: DFS feedback removal did not produce a DAG")

    return DiagramGraph(
        nodes=tuple(graph_nodes),
        groups=graph_groups,
        edges=tuple(graph_edges),
        diagnostics=tuple(sorted(diagnostics)),
    )


__all__ = [
    "DiagramGraph",
    "GraphBuildError",
    "GraphEdge",
    "GraphGroup",
    "GraphNode",
    "build_graph",
]
