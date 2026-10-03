"""Semantic planning protocol."""

from __future__ import annotations

from typing import Protocol

from cloud_diagram.domain import DiagramSpec, Provider


class PlannerError(RuntimeError):
    """A planner request or strict DiagramSpec validation failed."""


class Planner(Protocol):
    """A semantic-only planner; geometry and rendering remain compiler-owned."""

    async def plan(self, prompt: str, provider: Provider | str) -> DiagramSpec:
        """Return a strict DiagramSpec for the untrusted natural-language request."""
        ...


__all__ = ["Planner", "PlannerError"]
