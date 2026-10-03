"""Deterministic left-to-right semantic rank assignment."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import networkx as nx

from cloud_diagram.domain import DiagramSpec, EdgeKind, SemanticRole
from cloud_diagram.rules import RuleSet

from .builder import DiagramGraph, GraphEdge


class RankingError(ValueError):
    """Raised for contradictory primary-flow rank constraints."""


@dataclass(frozen=True, slots=True)
class RankAssignment:
    by_node: tuple[tuple[str, int], ...]
    diagnostics: tuple[str, ...] = ()

    @property
    def index(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self.by_node))

    @property
    def ranks(self) -> tuple[int, ...]:
        return tuple(sorted({rank for _, rank in self.by_node}))


def _role_rank(role: SemanticRole, rules: RuleSet) -> int:
    policy = rules.flow.rank_policy
    direct = {
        SemanticRole.EXTERNAL_SOURCE: policy.external_source,
        SemanticRole.ENTRYPOINT: policy.entrypoint,
        SemanticRole.GATEWAY: policy.gateway,
        SemanticRole.FRONTEND: policy.frontend,
        SemanticRole.SERVICE: policy.service,
        SemanticRole.WORKER: policy.worker,
        SemanticRole.ASYNCHRONOUS_BOUNDARY: policy.asynchronous_boundary,
        SemanticRole.QUEUE: policy.asynchronous_boundary,
        SemanticRole.CACHE: policy.cache,
        SemanticRole.DATASTORE: policy.datastore,
        SemanticRole.ANALYTICS: policy.analytics,
        SemanticRole.EXTERNAL_SINK: policy.external_sink,
        SemanticRole.COMPUTE: policy.service,
        SemanticRole.IDENTITY: policy.gateway,
        SemanticRole.OBSERVABILITY: policy.analytics,
        SemanticRole.EXTERNAL_SYSTEM: policy.external_source,
    }
    value = direct[role]
    for role_names in rules.flow.same_rank_roles:
        if role.value in role_names:
            known = [SemanticRole(name) for name in role_names]
            value = min(direct[item] for item in known)
            break
    return value


def _forces_progression(edge: GraphEdge, graph: DiagramGraph, rules: RuleSet) -> bool:
    if edge.feedback:
        return False
    kind = edge.edge.kind
    if kind in {EdgeKind.DEPENDENCY, EdgeKind.OBSERVABILITY, EdgeKind.BIDIRECTIONAL}:
        return False
    source_role = graph.node_index[edge.source].node.role
    target_role = graph.node_index[edge.target].node.role
    if SemanticRole.OBSERVABILITY in {source_role, target_role}:
        return False
    if kind is EdgeKind.ASYNCHRONOUS or {
        source_role,
        target_role,
    } & {SemanticRole.QUEUE, SemanticRole.ASYNCHRONOUS_BOUNDARY}:
        return rules.structure.queues.force_rank_boundary
    return True


def assign_ranks(graph: DiagramGraph, spec: DiagramSpec, rules: RuleSet) -> RankAssignment:
    """Combine semantic minima with a strict DAG of progression/order constraints."""

    if rules.flow.default_direction != "left_to_right" or not rules.flow.direction_locked:
        raise RankingError("compiler requires locked left-to-right flow")

    constraints = nx.DiGraph()
    constraints.add_nodes_from(graph.node_index)
    reasons: dict[tuple[str, str], list[str]] = {}

    def add_constraint(source: str, target: str, reason: str) -> None:
        constraints.add_edge(source, target)
        reasons.setdefault((source, target), []).append(reason)

    diagnostics: list[str] = []
    for graph_edge in graph.nonfeedback_edges:
        if _forces_progression(graph_edge, graph, rules):
            add_constraint(
                graph_edge.source,
                graph_edge.target,
                f"progression edge {graph_edge.id}",
            )
        else:
            diagnostics.append(
                f"edge {graph_edge.id} excluded from primary rank progression ({graph_edge.edge.kind.value})"
            )

    for constraint in spec.constraints.node_order:
        add_constraint(
            constraint.before,
            constraint.after,
            f"explicit node_order {constraint.before}->{constraint.after}",
        )

    if not nx.is_directed_acyclic_graph(constraints):
        cycle = nx.find_cycle(constraints, orientation="original")
        parts: list[str] = []
        for source, target, _ in cycle:
            parts.extend(reasons.get((source, target), [f"{source}->{target}"]))
        raise RankingError(
            "contradictory node-order/rank constraints form a cycle: " + "; ".join(parts)
        )

    raw = {node.id: _role_rank(node.node.role, rules) for node in graph.nodes}
    for node_id in nx.lexicographical_topological_sort(constraints, key=str):
        current = raw[node_id]
        predecessors = sorted(constraints.predecessors(node_id))
        if predecessors:
            required = max(raw[predecessor] + 1 for predecessor in predecessors)
            if required > current:
                raw[node_id] = required
                diagnostics.append(
                    f"node {node_id} advanced from semantic rank {current} to {required} by rank constraints"
                )

    if rules.structure.observability.exclude_from_primary_rank_progression:
        incident: dict[str, list[int]] = {}
        for edge in graph.edges:
            source_role = graph.node_index[edge.source].node.role
            target_role = graph.node_index[edge.target].node.role
            if edge.edge.kind is EdgeKind.OBSERVABILITY or SemanticRole.OBSERVABILITY in {
                source_role,
                target_role,
            }:
                incident.setdefault(edge.source, []).append(raw[edge.target])
                incident.setdefault(edge.target, []).append(raw[edge.source])
        for node in graph.nodes:
            if node.node.role is SemanticRole.OBSERVABILITY and incident.get(node.id):
                raw[node.id] = max(incident[node.id])
                diagnostics.append(
                    f"observability node {node.id} shares a related rank and is ordered below primary flow"
                )

    distinct = sorted(set(raw.values()))
    normalized = {value: index for index, value in enumerate(distinct)}
    by_node = tuple(sorted((node_id, normalized[value]) for node_id, value in raw.items()))
    for before_after in spec.constraints.node_order:
        if dict(by_node)[before_after.before] >= dict(by_node)[before_after.after]:
            raise RankingError(
                f"explicit node_order {before_after.before}->{before_after.after} was not satisfied"
            )
    return RankAssignment(by_node=by_node, diagnostics=tuple(sorted(set(diagnostics))))


__all__ = ["RankAssignment", "RankingError", "assign_ranks"]
