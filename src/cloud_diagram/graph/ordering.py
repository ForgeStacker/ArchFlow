"""Stable barycentric crossing reduction within deterministic ranks."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from cloud_diagram.domain import DiagramSpec
from cloud_diagram.rules import RuleSet

from .builder import DiagramGraph, GraphNode
from .ranking import RankAssignment


@dataclass(frozen=True, slots=True)
class NodeOrdering:
    ranks: tuple[tuple[int, tuple[str, ...]], ...]
    diagnostics: tuple[str, ...] = ()

    @property
    def by_rank(self) -> Mapping[int, tuple[str, ...]]:
        return MappingProxyType(dict(self.ranks))

    @property
    def position(self) -> Mapping[str, int]:
        return MappingProxyType(
            {
                node_id: position
                for _, nodes in self.ranks
                for position, node_id in enumerate(nodes)
            }
        )


def _stable_key(node: GraphNode) -> tuple[object, ...]:
    explicit = node.node.order
    return (
        explicit is None,
        explicit if explicit is not None else 0,
        node.node.role.value,
        node.parent_path,
        node.icon_key,
        node.id,
    )


def order_nodes(
    graph: DiagramGraph,
    ranks: RankAssignment,
    spec: DiagramSpec,
    rules: RuleSet,
) -> NodeOrdering:
    """Perform alternating stable barycenter sweeps without input-order dependence."""

    rank_of = ranks.index
    node_by_id = graph.node_index
    rank_nodes: dict[int, list[str]] = {}
    for node in graph.nodes:
        rank_nodes.setdefault(rank_of[node.id], []).append(node.id)
    for node_ids in rank_nodes.values():
        node_ids.sort(key=lambda node_id: _stable_key(node_by_id[node_id]))

    incoming: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    outgoing: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for edge in graph.nonfeedback_edges:
        if rank_of[edge.source] == rank_of[edge.target]:
            continue
        outgoing[edge.source].append(edge.target)
        incoming[edge.target].append(edge.source)
    for values in (*incoming.values(), *outgoing.values()):
        values.sort()

    sorted_ranks = sorted(rank_nodes)
    sweeps = rules.layout.crossing_minimization.sweeps if rules.layout.crossing_minimization.enabled else 0
    for sweep in range(sweeps):
        direction = sorted_ranks if sweep % 2 == 0 else list(reversed(sorted_ranks))
        positions = {
            node_id: position
            for rank in sorted_ranks
            for position, node_id in enumerate(rank_nodes[rank])
        }
        for rank in direction:
            adjacent = incoming if sweep % 2 == 0 else outgoing

            def sweep_key(node_id: str) -> tuple[object, ...]:
                neighbors = adjacent[node_id]
                if neighbors:
                    numerator = sum(positions[value] for value in neighbors)
                    denominator = len(neighbors)
                else:
                    numerator = positions[node_id]
                    denominator = 1
                return (
                    numerator / denominator,
                    _stable_key(node_by_id[node_id]),
                )

            rank_nodes[rank].sort(key=sweep_key)

    # Explicit order remains authoritative after heuristic sweeps.
    for node_ids in rank_nodes.values():
        prior_position = {node_id: index for index, node_id in enumerate(node_ids)}
        node_ids.sort(
            key=lambda node_id: (
                node_by_id[node_id].node.order is None,
                node_by_id[node_id].node.order if node_by_id[node_id].node.order is not None else 0,
                prior_position[node_id],
                _stable_key(node_by_id[node_id]),
            )
        )

    return NodeOrdering(
        ranks=tuple((rank, tuple(rank_nodes[rank])) for rank in sorted_ranks),
        diagnostics=(f"stable barycenter sweeps: {sweeps}",),
    )


__all__ = ["NodeOrdering", "order_nodes"]
