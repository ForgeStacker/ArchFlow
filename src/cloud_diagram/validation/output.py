"""Secure structural and semantic validation of generated draw.io XML."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from lxml import etree

from cloud_diagram.diagnostics import Finding, Severity, make_finding
from cloud_diagram.domain import DiagramSpec, PortSide
from cloud_diagram.icons import IconRegistry, Resolution, SvgSafetyError
from cloud_diagram.icons.registry import validate_svg_bytes
from cloud_diagram.layout import LayoutResult, Point, Rect
from cloud_diagram.renderers.styles import semantic_edge_style
from cloud_diagram.rules import RuleSet

_IMAGE_DATA = re.compile(r"image=(data:image/svg\+xml;base64,([A-Za-z0-9+/=]+))(?=;|$)")
_FORBIDDEN_URL = re.compile(r"(?:https?|ftp|file):|(?<![A-Za-z0-9+.-])//", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OutputValidationResult:
    findings: tuple[Finding, ...]

    @property
    def hard_pass(self) -> bool:
        return not any(finding.severity is Severity.ERROR for finding in self.findings)

    def raise_for_errors(self) -> None:
        if not self.hard_pass:
            raise OutputValidationError(self.findings)


class OutputValidationError(ValueError):
    def __init__(self, findings: tuple[Finding, ...]) -> None:
        self.findings = findings
        super().__init__("draw.io output validation failed:\n" + "\n".join(f"{f.code}: {f.message}" for f in findings if f.severity is Severity.ERROR))


def validate_drawio_output(
    data: bytes | str,
    spec: DiagramSpec,
    layout: LayoutResult,
    resolutions: Mapping[str, Resolution],
    registry: IconRegistry,
    rules: RuleSet,
) -> OutputValidationResult:
    """Parse securely and verify generated XML against semantic and layout inputs."""

    findings: list[Finding] = []
    raw = data.encode("utf-8") if isinstance(data, str) else data
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        findings.append(make_finding(Severity.ERROR, "output.xml.forbidden_declaration", "DOCTYPE and ENTITY declarations are forbidden"))
        return _result(findings)
    try:
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False, huge_tree=False, remove_comments=False)
        document = etree.fromstring(raw, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        findings.append(make_finding(Severity.ERROR, "output.xml.malformed", "generated output is not well-formed XML", details={"error": str(exc)}))
        return _result(findings)

    if document.tag != "mxfile":
        findings.append(make_finding(Severity.ERROR, "output.structure.mxfile", "root element must be mxfile"))
        return _result(findings)
    diagrams = document.findall("diagram")
    if len(diagrams) != 1:
        findings.append(make_finding(Severity.ERROR, "output.structure.diagram_count", "mxfile must contain exactly one diagram", details={"actual": len(diagrams)}))
        return _result(findings)
    models = diagrams[0].findall("mxGraphModel")
    if len(models) != 1:
        findings.append(make_finding(Severity.ERROR, "output.structure.model_count", "diagram must contain exactly one mxGraphModel", details={"actual": len(models)}))
        return _result(findings)
    model = models[0]
    roots = model.findall("root")
    if len(roots) != 1:
        findings.append(make_finding(Severity.ERROR, "output.structure.root_count", "mxGraphModel must contain exactly one root", details={"actual": len(roots)}))
        return _result(findings)
    root = roots[0]

    for element in document.iter():
        if not isinstance(element.tag, str):
            if isinstance(element, etree._ProcessingInstruction):
                findings.append(make_finding(Severity.ERROR, "output.xml.processing_instruction", "processing instructions are forbidden"))
            continue
        local = etree.QName(element).localname.casefold()
        if local in {"script", "foreignobject"}:
            findings.append(make_finding(Severity.ERROR, "output.xml.active_content", f"forbidden element {local!r}"))
        for attribute, value in element.attrib.items():
            searchable = _IMAGE_DATA.sub("image=[embedded-svg]", value)
            if _FORBIDDEN_URL.search(searchable):
                findings.append(make_finding(Severity.ERROR, "output.resource.external_url", "remote/file URL is forbidden", details={"attribute": attribute}))
        for location, value in (("text", element.text), ("tail", element.tail)):
            if value and _FORBIDDEN_URL.search(value):
                findings.append(make_finding(Severity.ERROR, "output.resource.external_url", "remote/file URL is forbidden", details={"location": location}))

    identity_elements = [*root.iter("mxCell"), *root.iter("object")]
    ids = [element.get("id") for element in identity_elements if element.get("id") is not None]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    for duplicate in duplicates:
        findings.append(make_finding(Severity.ERROR, "output.id.duplicate", f"duplicate cell/object ID {duplicate!r}", object_ids=(duplicate,)))
    valid_ids = set(ids)
    if "0" not in valid_ids or "1" not in valid_ids:
        findings.append(make_finding(Severity.ERROR, "output.structure.layers", "root/default layer IDs 0 and 1 are required"))

    cells = list(root.iterfind(".//mxCell"))
    effective_cells: dict[str, etree._Element] = {}
    for cell in cells:
        identity = _cell_identity(cell)
        if identity is not None:
            effective_cells[identity] = cell
        parent = cell.get("parent")
        if parent is not None and parent not in valid_ids:
            findings.append(make_finding(Severity.ERROR, "output.reference.parent", f"cell has invalid parent {parent!r}", object_ids=(identity or "anonymous", parent)))

    spec_nodes = {node.id: node for node in spec.nodes}
    placements = {node.node_id: node for node in layout.nodes}
    group_placements = {group.group_id: group for group in layout.groups}
    spec_edges = {edge.id: edge for edge in spec.edges}
    routes = {route.edge_id: route for route in layout.routes}

    for group in layout.groups:
        cell_id = _id("group", group.group_id)
        cell = effective_cells.get(cell_id)
        if cell is None:
            findings.append(make_finding(Severity.ERROR, "output.group.missing", f"group cell {group.group_id!r} is missing", object_ids=(group.group_id,)))
            continue
        reconstructed = _absolute_rect(cell_id, effective_cells, findings)
        if reconstructed != group.rect:
            findings.append(make_finding(Severity.ERROR, "output.geometry.group_relative", f"group {group.group_id!r} relative geometry does not reconstruct its layout rectangle", object_ids=(group.group_id,), details={"actual": _rect_tuple(reconstructed), "expected": _rect_tuple(group.rect)}))
        expected_parent = _id("group", group.parent_id) if group.parent_id is not None else "1"
        if cell.get("parent") != expected_parent:
            findings.append(make_finding(Severity.ERROR, "output.group.parent", f"group {group.group_id!r} has incorrect parent", object_ids=(group.group_id, expected_parent)))

    decoded_by_checksum: dict[str, bytes] = {}
    validated_images: set[int] = set()
    for node in spec.nodes:
        node_id = _id("node", node.id)
        wrapper = effective_cells.get(node_id)
        if wrapper is None:
            findings.append(make_finding(Severity.ERROR, "output.node.missing", f"node wrapper {node.id!r} is missing", object_ids=(node.id,)))
            continue
        reconstructed = _absolute_rect(node_id, effective_cells, findings)
        if reconstructed != placements[node.id].rect:
            findings.append(make_finding(Severity.ERROR, "output.geometry.node_relative", f"node {node.id!r} relative geometry does not reconstruct its layout rectangle", object_ids=(node.id,), details={"actual": _rect_tuple(reconstructed), "expected": _rect_tuple(placements[node.id].rect)}))
        effective_group_id = placements[node.id].group_id
        expected_parent = _id("group", effective_group_id) if effective_group_id is not None else "layer__nodes"
        if wrapper.get("parent") != expected_parent:
            findings.append(make_finding(Severity.ERROR, "output.node.parent", f"node {node.id!r} has incorrect direct parent", object_ids=(node.id, expected_parent)))
        children = [cell for cell in cells if cell.get("parent") == node_id]
        image_children = [cell for cell in children if _style_map(cell.get("style", "")).get("shape") == "image"]
        label_children = [cell for cell in children if _style_map(cell.get("style", "")).get("text") == "1"]
        expected_image_id, expected_label_id = _id("image", node.id), _id("node_label", node.id)
        recognized = {id(cell) for cell in (*image_children, *label_children)}
        unexpected = [cell.get("id", "anonymous") for cell in children if id(cell) not in recognized]
        if len(image_children) != 1 or len(label_children) != 1 or unexpected:
            findings.append(make_finding(Severity.ERROR, "output.node.children", f"node {node.id!r} must have exactly one image and one label child and no extras", object_ids=(node.id,), details={"images": len(image_children), "labels": len(label_children), "unexpected": tuple(unexpected)}))
            continue
        if image_children[0].get("id") != expected_image_id or label_children[0].get("id") != expected_label_id:
            findings.append(make_finding(Severity.ERROR, "output.node.child_ids", f"node {node.id!r} child IDs are not canonical", object_ids=(node.id,)))
        resolution = resolutions.get(node.id)
        if resolution is None:
            findings.append(make_finding(Severity.ERROR, "output.node.resolution", f"node {node.id!r} has no supplied resolution", object_ids=(node.id,)))
            continue
        registered = registry.get(resolution.entry.id)
        if registered is None or registered != resolution.entry:
            findings.append(make_finding(Severity.ERROR, "output.node.registry", f"node {node.id!r} resolution is not the selected registry entry", object_ids=(node.id, resolution.entry.id)))
        owner = wrapper.getparent()
        if owner is None or owner.tag != "object" or owner.get("iconId") != resolution.entry.id or owner.get("iconChecksum") != resolution.entry.checksum:
            findings.append(make_finding(Severity.ERROR, "output.node.metadata", f"node {node.id!r} icon metadata does not match its resolution", object_ids=(node.id, resolution.entry.id)))
        validated_images.add(id(image_children[0]))
        _validate_image(image_children[0], node.id, resolution, decoded_by_checksum, findings)

    for cell in cells:
        if _style_map(cell.get("style", "")).get("shape") == "image" and id(cell) not in validated_images:
            findings.append(make_finding(Severity.ERROR, "output.image.unexpected", "image cell is not the canonical child of a rendered node", object_ids=(cell.get("id", "anonymous"),)))

    edge_cells = [cell for cell in cells if cell.get("edge") == "1"]
    edge_ids = {_strip_id("edge", cell.get("id", "")) for cell in edge_cells}
    for missing in sorted(set(spec_edges) - edge_ids):
        findings.append(make_finding(Severity.ERROR, "output.edge.missing", f"edge {missing!r} is missing", object_ids=(missing,)))
    for cell in edge_cells:
        edge_id = _strip_id("edge", cell.get("id", ""))
        edge = spec_edges.get(edge_id)
        route = routes.get(edge_id)
        if edge is None or route is None:
            findings.append(make_finding(Severity.ERROR, "output.edge.unknown", f"unknown rendered edge {edge_id!r}", object_ids=(edge_id,)))
            continue
        expected_source, expected_target = _id("node", edge.source), _id("node", edge.target)
        if cell.get("source") != expected_source or cell.get("target") != expected_target:
            findings.append(make_finding(Severity.ERROR, "output.edge.dangling", f"edge {edge_id!r} has invalid terminals", object_ids=(edge_id, cell.get("source", ""), cell.get("target", ""))))
        for terminal_name in ("source", "target"):
            terminal = cell.get(terminal_name)
            if terminal not in valid_ids:
                findings.append(make_finding(Severity.ERROR, "output.reference.terminal", f"edge {edge_id!r} has missing {terminal_name} terminal", object_ids=(edge_id, terminal or "missing")))
        geometries = cell.findall("mxGeometry")
        if len(geometries) != 1 or geometries[0].get("relative") != "1":
            findings.append(make_finding(Severity.ERROR, "output.edge.geometry", f"edge {edge_id!r} requires one expanded relative geometry", object_ids=(edge_id,)))
            continue
        arrays = geometries[0].findall("Array[@as='points']")
        if len(arrays) != 1:
            findings.append(make_finding(Severity.ERROR, "output.edge.waypoints", f"edge {edge_id!r} requires an ordered waypoint array", object_ids=(edge_id,)))
        else:
            try:
                actual_points = tuple((int(point.get("x", "")), int(point.get("y", ""))) for point in arrays[0].findall("mxPoint"))
            except (TypeError, ValueError):
                findings.append(make_finding(Severity.ERROR, "output.edge.waypoints", f"edge {edge_id!r} has non-integer waypoint coordinates", object_ids=(edge_id,)))
            else:
                expected_points = tuple((point.x, point.y) for point in route.points[1:-1])
                if actual_points != expected_points:
                    findings.append(make_finding(Severity.ERROR, "output.edge.waypoints", f"edge {edge_id!r} waypoints do not match LayoutResult", object_ids=(edge_id,), details={"actual": actual_points, "expected": expected_points}))
        _validate_edge_style(cell, edge, route, placements, rules, findings)

    expected_labels = {label.edge_id: label for label in layout.labels}
    for edge_id, placement in expected_labels.items():
        cell = effective_cells.get(_id("edge_label", edge_id))
        if cell is None or _geometry_rect(cell) != placement.rect:
            findings.append(make_finding(Severity.ERROR, "output.label.geometry", f"edge label {edge_id!r} is missing or misplaced", object_ids=(edge_id,)))

    return _result(findings)


def require_valid_drawio_output(
    data: bytes | str,
    spec: DiagramSpec,
    layout: LayoutResult,
    resolutions: Mapping[str, Resolution],
    registry: IconRegistry,
    rules: RuleSet,
) -> OutputValidationResult:
    result = validate_drawio_output(data, spec, layout, resolutions, registry, rules)
    result.raise_for_errors()
    return result


def _validate_image(cell: etree._Element, node_id: str, resolution: Resolution, cache: dict[str, bytes], findings: list[Finding]) -> None:
    style = cell.get("style", "")
    match = _IMAGE_DATA.search(style)
    if match is None:
        findings.append(make_finding(Severity.ERROR, "output.image.embedded", f"node {node_id!r} image is not an embedded base64 SVG", object_ids=(node_id,)))
        return
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        findings.append(make_finding(Severity.ERROR, "output.image.base64", f"node {node_id!r} image has invalid base64", object_ids=(node_id,), details={"error": str(exc)}))
        return
    actual_checksum = sha256(decoded).hexdigest()
    if actual_checksum != resolution.entry.checksum:
        findings.append(make_finding(Severity.ERROR, "output.image.checksum", f"node {node_id!r} image checksum does not match selected icon", object_ids=(node_id, resolution.entry.id), details={"actual": actual_checksum, "expected": resolution.entry.checksum}))
        return
    prior = cache.setdefault(actual_checksum, decoded)
    if prior != decoded:
        findings.append(make_finding(Severity.ERROR, "output.image.deduplication", "identical checksums contain different SVG bytes", object_ids=(node_id,)))
    try:
        validate_svg_bytes(decoded, source=f"embedded:{node_id}")
    except SvgSafetyError as exc:
        findings.append(make_finding(Severity.ERROR, "output.image.unsafe_svg", f"node {node_id!r} SVG is unsafe", object_ids=(node_id,), details={"error": str(exc)}))


def _validate_edge_style(cell: etree._Element, edge: object, route: object, placements: Mapping[str, object], rules: RuleSet, findings: list[Finding]) -> None:
    actual = _style_map(cell.get("style", ""))
    expected = _style_map(semantic_edge_style(edge.kind, rules))  # type: ignore[attr-defined]
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            findings.append(make_finding(Severity.ERROR, "output.edge.style", f"edge {edge.id!r} style property {key!r} is incorrect", object_ids=(edge.id,), details={"actual": actual.get(key), "expected": expected_value}))  # type: ignore[attr-defined]
    semantic = getattr(rules.edges.styles, edge.kind.value)  # type: ignore[attr-defined]
    arrow_expected = {
        "startArrow": semantic.start_arrow,
        "endArrow": semantic.end_arrow,
        "endFill": "1" if semantic.end_fill else "0",
    }
    if semantic.start_fill is not None:
        arrow_expected["startFill"] = "1" if semantic.start_fill else "0"
    for key, expected_value in arrow_expected.items():
        if actual.get(key) != expected_value:
            findings.append(make_finding(Severity.ERROR, "output.edge.arrow", f"edge {edge.id!r} arrow property {key!r} does not match its semantic rule", object_ids=(edge.id,), details={"actual": actual.get(key), "expected": expected_value}))  # type: ignore[attr-defined]
    source_rect = placements[edge.source].rect  # type: ignore[attr-defined,index]
    target_rect = placements[edge.target].rect  # type: ignore[attr-defined,index]
    exit_x, exit_y = _normalized_port(route.source_port.side, route.source_port.point, source_rect)  # type: ignore[attr-defined]
    entry_x, entry_y = _normalized_port(route.target_port.side, route.target_port.point, target_rect)  # type: ignore[attr-defined]
    port_expected = {"exitX": exit_x, "exitY": exit_y, "entryX": entry_x, "entryY": entry_y, "exitPerimeter": "1", "entryPerimeter": "1"}
    for key, value in port_expected.items():
        if actual.get(key) != value:
            findings.append(make_finding(Severity.ERROR, "output.edge.port", f"edge {edge.id!r} port property {key!r} is incorrect", object_ids=(edge.id,), details={"actual": actual.get(key), "expected": value}))  # type: ignore[attr-defined]


def _absolute_rect(cell_id: str, cells: Mapping[str, etree._Element], findings: list[Finding], trail: tuple[str, ...] = ()) -> Rect | None:
    if cell_id in trail:
        findings.append(make_finding(Severity.ERROR, "output.reference.parent_cycle", "cell parent cycle detected", object_ids=(*trail, cell_id)))
        return None
    cell = cells.get(cell_id)
    if cell is None:
        return None
    local = _geometry_rect(cell)
    if local is None:
        return None
    parent_id = cell.get("parent")
    if parent_id is None or parent_id not in cells:
        return local
    parent_cell = cells[parent_id]
    if parent_cell.get("vertex") != "1":
        return local
    parent_rect = _absolute_rect(parent_id, cells, findings, (*trail, cell_id))
    if parent_rect is None:
        return None
    return local.translated(parent_rect.x, parent_rect.y)


def _geometry_rect(cell: etree._Element) -> Rect | None:
    geometry = cell.find("mxGeometry")
    if geometry is None or geometry.get("relative") == "1":
        return None
    try:
        return Rect(x=int(geometry.get("x", "0")), y=int(geometry.get("y", "0")), width=int(geometry.get("width", "0")), height=int(geometry.get("height", "0")))
    except (TypeError, ValueError):
        return None


def _cell_identity(cell: etree._Element) -> str | None:
    direct = cell.get("id")
    if direct is not None:
        return direct
    parent = cell.getparent()
    if parent is not None and parent.tag == "object":
        return parent.get("id")
    return None


def _style_map(style: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in style.split(";"):
        key, separator, value = token.partition("=")
        if separator:
            result[key] = value
    return result


def _normalized_port(side: PortSide, point: Point, rect: Rect) -> tuple[str, str]:
    if side is PortSide.EAST:
        values = 1.0, _clamp((point.y - rect.y) / rect.height)
    elif side is PortSide.WEST:
        values = 0.0, _clamp((point.y - rect.y) / rect.height)
    elif side is PortSide.NORTH:
        values = _clamp((point.x - rect.x) / rect.width), 0.0
    else:
        values = _clamp((point.x - rect.x) / rect.width), 1.0
    return _number(values[0]), _number(values[1])


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".12g")


def _id(kind: str, raw: str | None) -> str:
    return f"cd_{kind}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', raw or '')}"


def _strip_id(kind: str, value: str) -> str:
    prefix = f"cd_{kind}_"
    return value[len(prefix):] if value.startswith(prefix) else value


def _rect_tuple(rect: Rect | None) -> tuple[int, int, int, int] | None:
    return None if rect is None else (rect.x, rect.y, rect.width, rect.height)


def _result(findings: list[Finding]) -> OutputValidationResult:
    return OutputValidationResult(findings=tuple(sorted(findings, key=lambda item: (item.code, item.object_ids, item.message))))


__all__ = [
    "OutputValidationError",
    "OutputValidationResult",
    "require_valid_drawio_output",
    "validate_drawio_output",
]
