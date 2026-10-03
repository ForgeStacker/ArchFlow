"""Layout engine protocol and orchestration errors."""

from __future__ import annotations

from typing import Protocol

from cloud_diagram.domain import DiagramSpec
from cloud_diagram.graph import DiagramGraph, NodeOrdering, RankAssignment
from cloud_diagram.rules import RuleSet

from .geometry import Canvas, GroupPlacement, NodePlacement


class LayoutError(ValueError):
    """Raised when deterministic placement cannot satisfy hard geometry bounds."""


class PlacementResult(Protocol):
    canvas: Canvas
    groups: tuple[GroupPlacement, ...]
    nodes: tuple[NodePlacement, ...]
    decisions: tuple[str, ...]
    warnings: tuple[str, ...]


class LayoutEngine(Protocol):
    engine_id: str

    def place(
        self,
        graph: DiagramGraph,
        ranks: RankAssignment,
        ordering: NodeOrdering,
        spec: DiagramSpec,
        rules: RuleSet,
    ) -> PlacementResult: ...


__all__ = ["LayoutEngine", "LayoutError", "PlacementResult"]
