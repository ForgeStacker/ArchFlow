"""Deterministic draw.io style factories."""

from __future__ import annotations

from collections.abc import Mapping

from cloud_diagram.domain import EdgeKind, Provider
from cloud_diagram.rules import RuleSet

_PROVIDER_GROUP_COLORS: Mapping[str, tuple[str, str]] = {
    Provider.AWS.value: ("#FFF4E5", "#C78A35"),
    Provider.AZURE.value: ("#EAF4FF", "#5B8DB8"),
    Provider.GCP.value: ("#EEF7EC", "#6F9A68"),
    Provider.MIXED_CLOUD.value: ("#F2EEFA", "#8974A8"),
    Provider.NEUTRAL.value: ("#F5F5F5", "#8A8A8A"),
}


def _style(properties: list[tuple[str, object]]) -> str:
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, value in properties:
        if key in seen:
            continue
        seen.add(key)
        if isinstance(value, bool):
            rendered = "1" if value else "0"
        else:
            rendered = str(value)
        ordered.append((key, rendered))
    if "html" not in seen:
        ordered.append(("html", "1"))
    return ";".join(f"{key}={value}" for key, value in ordered) + ";"


def group_style(provider: Provider | str | None, rules: RuleSet) -> str:
    provider_value = provider.value if isinstance(provider, Provider) else provider or Provider.NEUTRAL.value
    fill, stroke = _PROVIDER_GROUP_COLORS.get(provider_value, _PROVIDER_GROUP_COLORS[Provider.NEUTRAL.value])
    return _style([
        ("swimlane", 1),
        ("horizontal", 1),
        ("startSize", rules.containers.header.height),
        ("container", 1),
        ("collapsible", 0),
        ("recursiveResize", 0),
        ("rounded", 1),
        ("arcSize", 6),
        ("whiteSpace", "wrap"),
        ("fillColor", fill),
        ("swimlaneFillColor", "#FFFFFF"),
        ("strokeColor", stroke),
        ("fontColor", "#333333"),
        ("fontStyle", 1),
        ("align", "left"),
        ("spacingLeft", rules.containers.header.label_left_padding),
        ("html", 1),
    ])


def node_wrapper_style() -> str:
    return _style([
        ("shape", "rectangle"),
        ("rounded", 0),
        ("fillColor", "none"),
        ("strokeColor", "none"),
        ("container", 1),
        ("connectable", 1),
        ("pointerEvents", 1),
        ("whiteSpace", "wrap"),
        ("html", 1),
    ])


def image_style(data_uri: str) -> str:
    return _style([
        ("shape", "image"),
        ("imageAspect", 0),
        ("aspect", "fixed"),
        ("verticalLabelPosition", "bottom"),
        ("verticalAlign", "top"),
        ("connectable", 0),
        ("movable", 0),
        ("resizable", 0),
        ("image", data_uri),
        ("html", 1),
    ])


def text_label_style(*, line_height: int = 18) -> str:
    return _style([
        ("text", 1),
        ("strokeColor", "none"),
        ("fillColor", "none"),
        ("align", "center"),
        ("verticalAlign", "middle"),
        ("whiteSpace", "wrap"),
        ("overflow", "hidden"),
        ("spacing", 0),
        ("fontColor", "#333333"),
        ("fontSize", 12),
        ("lineHeight", f"{line_height}px"),
        ("connectable", 0),
        ("html", 1),
    ])


def semantic_edge_style(kind: EdgeKind | str, rules: RuleSet) -> str:
    kind_value = kind.value if isinstance(kind, EdgeKind) else kind
    semantic = getattr(rules.edges.styles, kind_value)
    base: list[tuple[str, object]] = []
    for token in rules.edges.drawio_base_style.split(";"):
        if not token:
            continue
        key, separator, value = token.partition("=")
        if separator:
            base.append((key, value))
    base_keys = {key for key, _ in base}
    properties = base + [
        ("strokeColor", semantic.stroke_color),
        ("strokeWidth", semantic.stroke_width),
        ("dashed", semantic.dashed),
    ]
    if semantic.dash_pattern is not None:
        properties.append(("dashPattern", semantic.dash_pattern))
    properties.append(("startArrow", semantic.start_arrow))
    if semantic.start_fill is not None:
        properties.append(("startFill", semantic.start_fill))
    properties.extend([
        ("endArrow", semantic.end_arrow),
        ("endFill", semantic.end_fill),
        ("startSize", rules.edges.arrowhead.size),
        ("endSize", rules.edges.arrowhead.size),
        ("jumpStyle", rules.routing.crossings.residual_jump_style),
        ("jumpSize", rules.routing.crossings.residual_jump_size),
    ])
    # Preserve base ordering while allowing semantic values to replace base keys.
    overrides = {key: value for key, value in properties[len(base):]}
    merged = [(key, overrides.pop(key, value)) for key, value in base]
    merged.extend((key, value) for key, value in properties[len(base):] if key not in base_keys)
    return _style(merged)


def edge_label_style(rules: RuleSet) -> str:
    return _style([
        ("text", 1),
        ("strokeColor", "none"),
        ("fillColor", rules.edges.label.background),
        ("align", "center"),
        ("verticalAlign", "middle"),
        ("whiteSpace", "wrap"),
        ("overflow", "hidden"),
        ("spacing", 0),
        ("fontColor", "#333333"),
        ("fontSize", 11),
        ("connectable", 0),
        ("html", 1),
    ])


__all__ = [
    "edge_label_style",
    "group_style",
    "image_style",
    "node_wrapper_style",
    "semantic_edge_style",
    "text_label_style",
]
