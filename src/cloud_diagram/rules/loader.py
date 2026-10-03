"""Actionable, duplicate-safe loading for architecture rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError

from .models import RuleSet


class RulesLoadError(ValueError):
    """A rules file could not be read, parsed, or strictly validated."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _format_validation_error(path: Path, error: ValidationError) -> str:
    details: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "<root>"
        details.append(f"{path}:{location}: {item['msg']}; value={item.get('input')!r}")
    return "rules validation failed:\n" + "\n".join(details)


def load_rules(path: str | Path) -> RuleSet:
    """Load and strictly validate a complete rules YAML file."""

    resolved = Path(path).expanduser().resolve()
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise RulesLoadError(f"cannot read rules file {resolved}: {exc}") from exc

    try:
        raw = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f":{mark.line + 1}:{mark.column + 1}" if mark is not None else ""
        raise RulesLoadError(f"invalid YAML in {resolved}{location}: {exc}") from exc

    if not isinstance(raw, dict):
        raise RulesLoadError(
            f"rules file {resolved}:<root>: expected a mapping, got {type(raw).__name__}"
        )
    try:
        return RuleSet.model_validate(raw)
    except ValidationError as exc:
        raise RulesLoadError(_format_validation_error(resolved, exc)) from exc


__all__ = ["RulesLoadError", "load_rules"]
