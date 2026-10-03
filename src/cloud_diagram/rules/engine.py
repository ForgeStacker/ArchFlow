"""Typed, immutable low-to-high rule precedence evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .models import EXPECTED_PRECEDENCE, RuleOverrides, RuleSet


ExcludeGlobalPrecedence = Literal[
    "provider_profile",
    "template",
    "diagram_override",
    "explicit_user_constraint",
]


class RuleOverrideError(ValueError):
    """An override is unknown, invalid, or attempts to change a locked rule."""


class RuleTraceRecord(BaseModel):
    """One explicit override applied by the precedence engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    precedence: ExcludeGlobalPrecedence
    field_path: str
    previous_value: int
    override_value: int


class RuleResolution(BaseModel):
    """Effective rules and an immutable trace of every explicit override."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    effective_rules: RuleSet
    trace: tuple[RuleTraceRecord, ...]


_PATHS: dict[str, tuple[str, ...]] = {
    "grid_size": ("ruleset", "grid_size"),
    "minimum_canvas_width": ("canvas", "minimum_width"),
    "minimum_canvas_height": ("canvas", "minimum_height"),
    "rank_spacing": ("layout", "rank_spacing", "preferred"),
    "component_spacing": ("layout", "component_spacing", "preferred"),
    "crossing_sweeps": ("layout", "crossing_minimization", "sweeps"),
    "compaction_iterations": ("layout", "compaction", "maximum_iterations"),
    "slots_per_side": ("ports", "slots_per_side"),
    "routing_corner_radius": ("routing", "corner_radius"),
    "minimum_quality_score": ("quality_gates", "soft", "minimum_quality_score"),
    "repair_iterations": ("repair", "maximum_iterations"),
}
_LOCKED_NAMES = frozenset(
    {
        "direction",
        "flow_direction",
        "default_direction",
        "direction_locked",
        "source_side",
        "target_side",
        "routing_type",
        "deterministic",
        "maximum_normal_edge",
        "maximum_feedback_edge",
        "hard_gates",
        "quality_gates_hard",
    }
)


def _validated_override(
    layer: ExcludeGlobalPrecedence,
    value: RuleOverrides | Mapping[str, object] | None,
) -> RuleOverrides | None:
    if value is None or isinstance(value, RuleOverrides):
        return value
    locked = sorted(set(value) & _LOCKED_NAMES)
    if locked:
        raise RuleOverrideError(f"{layer}: locked override fields are not allowed: {locked!r}")
    try:
        return RuleOverrides.model_validate(value)
    except ValidationError as exc:
        details = []
        for item in exc.errors(include_url=False):
            path = ".".join(str(part) for part in item["loc"]) or "<root>"
            details.append(f"{layer}.{path}: {item['msg']}; value={item.get('input')!r}")
        raise RuleOverrideError("invalid rule override:\n" + "\n".join(details)) from exc


def _lookup(document: dict[str, object], path: tuple[str, ...]) -> int:
    current: object = document
    for part in path:
        current = current[part]  # type: ignore[index]
    if not isinstance(current, int):
        raise TypeError(f"override target {'.'.join(path)} is not an integer")
    return current


def _assign(document: dict[str, object], path: tuple[str, ...], value: int) -> None:
    current: dict[str, object] = document
    for part in path[:-1]:
        current = current[part]  # type: ignore[assignment]
    current[path[-1]] = value


def _iter_override_values(override: RuleOverrides) -> tuple[tuple[tuple[str, ...], int], ...]:
    values: list[tuple[tuple[str, ...], int]] = []
    dumped = override.model_dump(exclude_none=True)
    margin = dumped.pop("canvas_margin", None)
    for field_name, value in dumped.items():
        values.append((_PATHS[field_name], value))
    if margin is not None:
        for side, value in margin.items():
            values.append((("canvas", "margin", side), value))
    return tuple(sorted(values, key=lambda item: item[0]))


class RuleEngine:
    """Apply supported override layers in the YAML-declared low-to-high order."""

    def resolve(
        self,
        base: RuleSet,
        *,
        provider_profile: RuleOverrides | Mapping[str, object] | None = None,
        template: RuleOverrides | Mapping[str, object] | None = None,
        diagram_override: RuleOverrides | Mapping[str, object] | None = None,
        explicit_user_constraint: RuleOverrides | Mapping[str, object] | None = None,
    ) -> RuleResolution:
        if base.precedence != EXPECTED_PRECEDENCE:
            raise RuleOverrideError(
                f"rules precedence must be exactly low-to-high: {EXPECTED_PRECEDENCE!r}"
            )
        supplied = {
            "provider_profile": provider_profile,
            "template": template,
            "diagram_override": diagram_override,
            "explicit_user_constraint": explicit_user_constraint,
        }
        document = deepcopy(base.model_dump(mode="python"))
        trace: list[RuleTraceRecord] = []
        for raw_layer in base.precedence[1:]:
            layer: ExcludeGlobalPrecedence = raw_layer  # type: ignore[assignment]
            override = _validated_override(layer, supplied[layer])
            if override is None:
                continue
            for path, value in _iter_override_values(override):
                previous = _lookup(document, path)
                _assign(document, path, value)
                trace.append(
                    RuleTraceRecord(
                        precedence=layer,
                        field_path=".".join(path),
                        previous_value=previous,
                        override_value=value,
                    )
                )
        return RuleResolution(
            effective_rules=RuleSet.model_validate(document),
            trace=tuple(trace),
        )


def resolve_rules(base: RuleSet, **overrides: object) -> RuleResolution:
    """Functional convenience API for ``RuleEngine.resolve``."""

    return RuleEngine().resolve(base, **overrides)  # type: ignore[arg-type]


__all__ = [
    "RuleEngine",
    "RuleOverrideError",
    "RuleResolution",
    "RuleTraceRecord",
    "resolve_rules",
]
