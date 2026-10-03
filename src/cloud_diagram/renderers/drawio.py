"""Canonical uncompressed draw.io rendering with embedded verified SVGs."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

from lxml import etree

from cloud_diagram.domain import DiagramSpec, PortSide, Provider
from cloud_diagram.icons import IconEntry, IconRegistry, Resolution, SvgEmbedder
from cloud_diagram.layout import LayoutResult, Point, Rect
from cloud_diagram.rules import RuleSet

from .styles import (
    edge_label_style,
    group_style,
    image_style,
    node_wrapper_style,
    semantic_edge_style,
    text_label_style,
)

_LAYER_CONTAINERS = "1"
_LAYER_CONNECTIONS = "layer__connections"
_LAYER_NODES = "layer__nodes"
_LAYER_LABELS = "layer__labels"
_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")


class DrawioRenderError(ValueError):
    """Raised when renderer inputs are incomplete or inconsistent."""


def render_drawio(
    spec: DiagramSpec,
    layout: LayoutResult,
    resolutions: Mapping[str, Resolution],
    registry: IconRegistry,
    rules: RuleSet,
) -> bytes:
    """Render a byte-stable, editable and fully offline uncompressed mxfile."""

    _validate_inputs(spec, layout, resolutions)
    spec_nodes = {node.id: node for node in spec.nodes}
    spec_edges = {edge.id: edge for edge in spec.edges}
    placements = {node.node_id: node for node in layout.nodes}
    group_placements = {group.group_id: group for group in layout.groups}
    embedder = SvgEmbedder(registry)

    mxfile = etree.Element("mxfile")
    diagram = etree.SubElement(mxfile, "diagram", id=_safe("diagram", spec.diagram_id), name=spec.title)
    model = etree.SubElement(
        diagram,
        "mxGraphModel",
        adaptiveColors="auto",
        background=rules.canvas.background,
        canvasX=str(layout.canvas.x),
        canvasY=str(layout.canvas.y),
        dx="0",
        dy="0",
        grid="1",
        gridSize=str(rules.ruleset.grid_size),
        guides="1",
        page="1",
        pageScale="1",
        pageWidth=str(layout.canvas.width),
        pageHeight=str(layout.canvas.height),
        math="0",
        shadow="0",
    )
    root = etree.SubElement(model, "root")
    etree.SubElement(root, "mxCell", id="0")
    _layer(root, _LAYER_CONTAINERS, "Containers")
    _layer(root, _LAYER_CONNECTIONS, "Connections")
    _layer(root, _LAYER_NODES, "Nodes")
    _layer(root, _LAYER_LABELS, "Labels")

    provider_by_group = _group_providers(spec, resolutions)
    for group in sorted(layout.groups, key=lambda value: (_group_depth(value.group_id, group_placements), value.group_id)):
        parent_id = _safe("group", group.parent_id) if group.parent_id is not None else _LAYER_CONTAINERS
        parent_rect = group_placements[group.parent_id].rect if group.parent_id is not None else None
        local = _relative_rect(group.rect, parent_rect)
        object_element = etree.SubElement(
            root,
            "object",
            id=_safe("group", group.group_id),
            label=group.label,
            tags="container " + provider_by_group[group.group_id],
            groupId=group.group_id,
            groupType=next(item.type.value for item in spec.groups if item.id == group.group_id),
            provider=provider_by_group[group.group_id],
        )
        cell = etree.SubElement(
            object_element,
            "mxCell",
            style=group_style(provider_by_group[group.group_id], rules),
            vertex="1",
            parent=parent_id,
        )
        _geometry(cell, local)

    for placement in layout.nodes:
        node = spec_nodes[placement.node_id]
        resolution = resolutions[placement.node_id]
        parent_id = _safe("group", placement.group_id) if placement.group_id is not None else _LAYER_NODES
        parent_rect = group_placements[placement.group_id].rect if placement.group_id is not None else None
        local = _relative_rect(placement.rect, parent_rect)
        tags = " ".join(_safe_tag(tag) for tag in ("node", node.provider.value, node.role.value, *node.tags))
        object_element = etree.SubElement(
            root,
            "object",
            id=_safe("node", node.id),
            label=node.label,
            tags=tags,
            nodeId=node.id,
            provider=node.provider.value,
            role=node.role.value,
            iconId=resolution.entry.id,
            iconChecksum=resolution.entry.checksum,
            resolutionReason=resolution.reason,
        )
        wrapper = etree.SubElement(
            object_element,
            "mxCell",
            style=node_wrapper_style(),
            vertex="1",
            parent=parent_id,
        )
        _geometry(wrapper, local)
        data_uri = embedder.embed_entry(resolution.entry)
        icon_rect = _icon_rect(placement.rect, resolution.entry, rules)
        image = etree.SubElement(
            root,
            "mxCell",
            id=_safe("image", node.id),
            value="",
            style=image_style(data_uri),
            vertex="1",
            parent=_safe("node", node.id),
        )
        _geometry(image, icon_rect)
        label_rect = _node_label_rect(placement.rect, len(placement.label_lines), rules)
        label = etree.SubElement(
            root,
            "mxCell",
            id=_safe("node_label", node.id),
            value="<br>".join(placement.label_lines),
            style=text_label_style(line_height=rules.nodes.label.line_height),
            vertex="1",
            parent=_safe("node", node.id),
        )
        _geometry(label, label_rect)

    for route in layout.routes:
        edge = spec_edges[route.edge_id]
        source_rect = placements[edge.source].rect
        target_rect = placements[edge.target].rect
        exit_x, exit_y = _normalized_port(route.source_port.side, route.source_port.point, source_rect)
        entry_x, entry_y = _normalized_port(route.target_port.side, route.target_port.point, target_rect)
        style = semantic_edge_style(edge.kind, rules) + (
            f"exitX={_number(exit_x)};exitY={_number(exit_y)};exitPerimeter=1;"
            f"entryX={_number(entry_x)};entryY={_number(entry_y)};entryPerimeter=1;"
        )
        cell = etree.SubElement(
            root,
            "mxCell",
            id=_safe("edge", route.edge_id),
            value="",
            style=style,
            edge="1",
            parent=_LAYER_CONNECTIONS,
            source=_safe("node", edge.source),
            target=_safe("node", edge.target),
        )
        geometry = etree.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        points = etree.SubElement(geometry, "Array", **{"as": "points"})
        for point in route.points[1:-1]:
            etree.SubElement(points, "mxPoint", x=str(point.x), y=str(point.y))

    labels = {label.edge_id: label for label in layout.labels}
    for edge_id in sorted(labels):
        placement = labels[edge_id]
        cell = etree.SubElement(
            root,
            "mxCell",
            id=_safe("edge_label", edge_id),
            value="<br>".join(placement.lines),
            style=edge_label_style(rules),
            vertex="1",
            parent=_LAYER_LABELS,
        )
        _geometry(cell, placement.rect)

    rendered = etree.tostring(mxfile, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    return rendered + b"\n"


def render_drawio_text(
    spec: DiagramSpec,
    layout: LayoutResult,
    resolutions: Mapping[str, Resolution],
    registry: IconRegistry,
    rules: RuleSet,
) -> str:
    return render_drawio(spec, layout, resolutions, registry, rules).decode("utf-8")


def write_drawio_atomic(
    path: str | os.PathLike[str],
    spec: DiagramSpec,
    layout: LayoutResult,
    resolutions: Mapping[str, Resolution],
    registry: IconRegistry,
    rules: RuleSet,
) -> bytes:
    """Validate rendered bytes, then atomically promote a same-directory temporary file."""

    data = render_drawio(spec, layout, resolutions, registry, rules)
    from cloud_diagram.validation.output import require_valid_drawio_output

    require_valid_drawio_output(data, spec, layout, resolutions, registry, rules)
    destination = Path(path)
    if not destination.parent.exists():
        raise DrawioRenderError(f"output directory does not exist: {destination.parent}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return data


def _validate_inputs(spec: DiagramSpec, layout: LayoutResult, resolutions: Mapping[str, Resolution]) -> None:
    if layout.diagram_id != spec.diagram_id:
        raise DrawioRenderError("layout diagram_id does not match DiagramSpec")
    spec_node_ids = {node.id for node in spec.nodes}
    layout_node_ids = {node.node_id for node in layout.nodes}
    if spec_node_ids != layout_node_ids:
        raise DrawioRenderError("layout node IDs do not match DiagramSpec")
    if set(resolutions) != spec_node_ids:
        raise DrawioRenderError("resolutions must contain exactly one entry for every node")
    if {edge.id for edge in spec.edges} != {route.edge_id for route in layout.routes}:
        raise DrawioRenderError("layout routes do not match DiagramSpec edges")


def _layer(root: etree._Element, layer_id: str, name: str) -> None:
    etree.SubElement(root, "mxCell", id=layer_id, value=name, parent="0")


def _geometry(cell: etree._Element, rect: Rect) -> etree._Element:
    return etree.SubElement(
        cell,
        "mxGeometry",
        x=_number(rect.x),
        y=_number(rect.y),
        width=_number(rect.width),
        height=_number(rect.height),
        **{"as": "geometry"},
    )


def _relative_rect(rect: Rect, parent: Rect | None) -> Rect:
    if parent is None:
        return rect
    return Rect(x=rect.x - parent.x, y=rect.y - parent.y, width=rect.width, height=rect.height)


def _icon_rect(node_rect: Rect, entry: IconEntry, rules: RuleSet) -> Rect:
    target_width = rules.nodes.icon.width
    target_height = rules.nodes.icon.height
    if rules.nodes.icon.preserve_aspect_ratio:
        # SVG dimensions define the artwork aspect ratio, not a raster resolution.
        # Fit vectors to the configured icon area without distorting provider art.
        scale = min(target_width / entry.width, target_height / entry.height)
        width = max(1, round(entry.width * scale))
        height = max(1, round(entry.height * scale))
    else:
        width, height = target_width, target_height
    icon_area_x = (node_rect.width - target_width) // 2
    x = icon_area_x + (target_width - width) // 2
    y = rules.nodes.box.internal_padding.top + (target_height - height) // 2
    return Rect(x=x, y=y, width=width, height=height)


def _node_label_rect(node_rect: Rect, line_count: int, rules: RuleSet) -> Rect:
    y = rules.nodes.box.internal_padding.top + rules.nodes.icon.height + rules.nodes.label.icon_to_label_gap
    height = line_count * rules.nodes.label.line_height
    return Rect(x=0, y=y, width=node_rect.width, height=height)


def _normalized_port(side: PortSide, point: Point, rect: Rect) -> tuple[float, float]:
    if side is PortSide.EAST:
        return 1.0, _clamp((point.y - rect.y) / rect.height)
    if side is PortSide.WEST:
        return 0.0, _clamp((point.y - rect.y) / rect.height)
    if side is PortSide.NORTH:
        return _clamp((point.x - rect.x) / rect.width), 0.0
    return _clamp((point.x - rect.x) / rect.width), 1.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _group_depth(group_id: str, groups: Mapping[str, object]) -> int:
    depth = 0
    current = groups[group_id]
    while current.parent_id is not None:  # type: ignore[attr-defined]
        depth += 1
        current = groups[current.parent_id]  # type: ignore[attr-defined]
    return depth


def _group_providers(spec: DiagramSpec, resolutions: Mapping[str, Resolution]) -> dict[str, str]:
    groups = {group.id: group for group in spec.groups}
    result: dict[str, str] = {}
    for group_id in groups:
        providers: set[str] = set()
        for node in spec.nodes:
            current = node.group_id
            while current is not None:
                if current == group_id:
                    providers.add(resolutions[node.id].entry.provider)
                    break
                current = groups[current].parent_id
        result[group_id] = next(iter(providers)) if len(providers) == 1 else Provider.MIXED_CLOUD.value if providers else Provider.NEUTRAL.value
    return result


def _safe(kind: str, raw: str | None) -> str:
    if raw is None:
        raise DrawioRenderError(f"cannot create {kind} ID from None")
    return f"cd_{kind}_{_SAFE_ID.sub('_', raw)}"


def _safe_tag(value: str) -> str:
    return _SAFE_ID.sub("_", value).strip("_") or "tag"


def _number(value: int | float) -> str:
    if isinstance(value, int) or value.is_integer():
        return str(int(value))
    return format(value, ".12g")


__all__ = [
    "DrawioRenderError",
    "render_drawio",
    "render_drawio_text",
    "write_drawio_atomic",
]
