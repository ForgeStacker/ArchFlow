"""Independent, read-only validation of completed layout geometry."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from cloud_diagram.diagnostics import Finding, HardGateCounts, Severity, hard_gate_counts, make_finding
from cloud_diagram.domain import DiagramSpec, EdgeKind, PortSide
from cloud_diagram.layout import LayoutResult, Rect
from cloud_diagram.layout.geometry import terminal_segment_is_outward
from cloud_diagram.rules import RuleSet


@dataclass(frozen=True, slots=True)
class GeometryValidationResult:
    findings: tuple[Finding, ...]
    hard_counts: HardGateCounts

    @property
    def hard_pass(self) -> bool:
        return self.hard_counts.total == 0 and not any(
            finding.severity is Severity.ERROR for finding in self.findings
        )

    def raise_for_errors(self) -> None:
        errors = tuple(finding for finding in self.findings if finding.severity is Severity.ERROR)
        if errors:
            raise GeometryValidationError(errors)


class GeometryValidationError(ValueError):
    def __init__(self, findings: tuple[Finding, ...]) -> None:
        self.findings = findings
        super().__init__("geometry validation failed:\n" + "\n".join(f"{f.code}: {f.message}" for f in findings))


def validate_geometry(
    layout: LayoutResult,
    spec: DiagramSpec,
    rules: RuleSet,
    *,
    comparison: LayoutResult | None = None,
) -> GeometryValidationResult:
    """Inspect layout invariants and every configured hard gate without mutation."""

    findings: list[Finding] = []
    nodes = {node.node_id: node for node in layout.nodes}
    groups = {group.group_id: group for group in layout.groups}
    routes = {route.edge_id: route for route in layout.routes}
    edges = {edge.id: edge for edge in spec.edges}
    canvas = layout.canvas.rect
    grid = rules.ruleset.grid_size

    node_overlap_pairs: set[tuple[str, str]] = set()
    node_header_pairs: set[tuple[str, str]] = set()
    edge_node_hits: set[tuple[str, str, int]] = set()
    edge_header_hits: set[tuple[str, str, int]] = set()
    label_hits: set[tuple[str, ...]] = set()
    clipped: set[tuple[str, str]] = set()
    spacing: set[tuple[str, str, str]] = set()
    dangling: set[str] = set()

    for first, second in combinations(layout.nodes, 2):
        pair = tuple(sorted((first.node_id, second.node_id)))
        if first.rect.intersects(second.rect):
            node_overlap_pairs.add(pair)
            findings.append(_hard("geometry.node.overlap", f"nodes {pair[0]!r} and {pair[1]!r} overlap", pair, "maximum_node_overlaps"))
        horizontal, vertical = _axis_gaps(first.rect, second.rect)
        vertical_overlap = not (first.rect.bottom <= second.rect.top or second.rect.bottom <= first.rect.top)
        horizontal_overlap = not (first.rect.right <= second.rect.left or second.rect.right <= first.rect.left)
        if vertical_overlap and horizontal < rules.nodes.spacing.minimum_horizontal:
            _spacing_finding(findings, spacing, pair, "horizontal", horizontal, rules.nodes.spacing.minimum_horizontal)
        if horizontal_overlap and vertical < rules.nodes.spacing.minimum_vertical:
            _spacing_finding(findings, spacing, pair, "vertical", vertical, rules.nodes.spacing.minimum_vertical)

    for node in layout.nodes:
        _check_rect_grid(findings, "node", node.node_id, node.rect, grid)
        if not canvas.contains_rect(node.rect):
            findings.append(make_finding(Severity.ERROR, "geometry.canvas.node_clipped", f"node {node.node_id!r} is outside the canvas", object_ids=(node.node_id,)))
        for group in layout.groups:
            if node.rect.intersects(group.header_rect):
                key = (node.node_id, group.group_id)
                node_header_pairs.add(key)
                findings.append(_hard("geometry.node.header_intersection", f"node {node.node_id!r} intersects group header {group.group_id!r}", key, "maximum_node_title_intersections"))
        if node.group_id is not None:
            parent = groups.get(node.group_id)
            if parent is None or not parent.client_rect.contains_rect(node.rect):
                key = (node.node_id, node.group_id)
                clipped.add(key)
                findings.append(_hard("geometry.containment.clipped_node", f"node {node.node_id!r} is clipped by group {node.group_id!r}", key, "maximum_clipped_children"))
            elif node.rect.top - parent.client_rect.top < rules.containers.header.child_clearance:
                _spacing_finding(findings, spacing, (node.node_id, parent.group_id), "header_clearance", node.rect.top - parent.client_rect.top, rules.containers.header.child_clearance)

    for group in layout.groups:
        for part_name, part in (("rect", group.rect), ("header", group.header_rect), ("client", group.client_rect)):
            _check_rect_grid(findings, f"group_{part_name}", group.group_id, part, grid)
        if not canvas.contains_rect(group.rect):
            findings.append(make_finding(Severity.ERROR, "geometry.canvas.group_clipped", f"group {group.group_id!r} is outside the canvas", object_ids=(group.group_id,)))
        if group.parent_id is not None:
            parent = groups.get(group.parent_id)
            if parent is None or not parent.client_rect.contains_rect(group.rect):
                key = (group.group_id, group.parent_id)
                clipped.add(key)
                findings.append(_hard("geometry.containment.clipped_group", f"group {group.group_id!r} is clipped by parent {group.parent_id!r}", key, "maximum_clipped_children"))

    for first, second in combinations(layout.groups, 2):
        if first.parent_id != second.parent_id:
            continue
        pair = tuple(sorted((first.group_id, second.group_id)))
        if first.rect.intersects(second.rect):
            findings.append(make_finding(Severity.ERROR, "geometry.group.sibling_overlap", f"groups {pair[0]!r} and {pair[1]!r} overlap", object_ids=pair))
        horizontal, vertical = _axis_gaps(first.rect, second.rect)
        if horizontal < rules.containers.sibling_gap.horizontal and vertical < rules.containers.sibling_gap.vertical:
            _spacing_finding(findings, spacing, pair, "sibling", min(horizontal, vertical), min(rules.containers.sibling_gap.horizontal, rules.containers.sibling_gap.vertical))

    expected_edge_ids = set(edges)
    actual_route_ids = set(routes)
    for edge_id in sorted(expected_edge_ids ^ actual_route_ids):
        dangling.add(edge_id)
        findings.append(_hard("geometry.edge.dangling", f"edge/route {edge_id!r} is missing its counterpart", (edge_id,), "maximum_dangling_edges"))

    for route in layout.routes:
        edge = edges.get(route.edge_id)
        source = nodes.get(route.source_port.node_id)
        target = nodes.get(route.target_port.node_id)
        if edge is None or source is None or target is None:
            dangling.add(route.edge_id)
            continue
        if route.source_port.node_id != edge.source or route.target_port.node_id != edge.target:
            dangling.add(route.edge_id)
            findings.append(_hard("geometry.edge.terminal_mismatch", f"route {route.edge_id!r} terminals do not match DiagramSpec", (route.edge_id, edge.source, edge.target), "maximum_dangling_edges"))
        _validate_route_policy(findings, route, edge.kind, source, target, grid, rules)
        source_outward = terminal_segment_is_outward(route.segments[0], route.source_port, source.rect, source=True)
        target_outward = terminal_segment_is_outward(route.segments[-1], route.target_port, target.rect, source=False)
        if not source_outward:
            key = (route.edge_id, source.node_id, -1)
            edge_node_hits.add(key)
            findings.append(_hard("geometry.edge.illegal_source_terminal", f"route {route.edge_id!r} has illegal source boundary geometry", (route.edge_id, source.node_id), "maximum_edge_node_intersections_excluding_terminals"))
        if not target_outward:
            key = (route.edge_id, target.node_id, -2)
            edge_node_hits.add(key)
            findings.append(_hard("geometry.edge.illegal_target_terminal", f"route {route.edge_id!r} has illegal target boundary geometry", (route.edge_id, target.node_id), "maximum_edge_node_intersections_excluding_terminals"))
        for point in route.points:
            if not canvas.contains_point(point):
                findings.append(make_finding(Severity.ERROR, "geometry.canvas.route_clipped", f"route {route.edge_id!r} leaves the canvas", object_ids=(route.edge_id,), details={"point": (point.x, point.y)}))
        for index, segment in enumerate(route.segments):
            for node in layout.nodes:
                source_terminal_contact = node.node_id == route.source_port.node_id and index == 0
                target_terminal_contact = node.node_id == route.target_port.node_id and index == len(route.segments) - 1
                if source_terminal_contact or target_terminal_contact:
                    continue
                if segment.intersects_rect(node.rect):
                    key = (route.edge_id, node.node_id, index)
                    edge_node_hits.add(key)
                    findings.append(_hard("geometry.edge.node_intersection", f"route {route.edge_id!r} intersects node {node.node_id!r}", (route.edge_id, node.node_id), "maximum_edge_node_intersections_excluding_terminals", {"segment": index}))
            for group in layout.groups:
                if segment.intersects_rect(group.header_rect):
                    key = (route.edge_id, group.group_id, index)
                    edge_header_hits.add(key)
                    findings.append(_hard("geometry.edge.header_intersection", f"route {route.edge_id!r} intersects group header {group.group_id!r}", (route.edge_id, group.group_id), "maximum_edge_title_intersections", {"segment": index}))

    for first, second in combinations(layout.labels, 2):
        if first.rect.intersects(second.rect, touching=True):
            key = ("label", *sorted((first.edge_id, second.edge_id)))
            label_hits.add(key)
            findings.append(_hard("geometry.label.overlap", f"edge labels {first.edge_id!r} and {second.edge_id!r} overlap", key[1:], "maximum_label_overlaps"))
    for label in layout.labels:
        _check_rect_grid(findings, "edge_label", label.edge_id, label.rect, grid)
        if not canvas.contains_rect(label.rect):
            findings.append(make_finding(Severity.ERROR, "geometry.canvas.label_clipped", f"label {label.edge_id!r} is outside the canvas", object_ids=(label.edge_id,)))
        for node in layout.nodes:
            if label.rect.intersects(node.rect, touching=True):
                key = ("node", label.edge_id, node.node_id)
                label_hits.add(key)
                findings.append(_hard("geometry.label.node_overlap", f"label {label.edge_id!r} overlaps node {node.node_id!r}", (label.edge_id, node.node_id), "maximum_label_overlaps"))
        for group in layout.groups:
            if label.rect.intersects(group.header_rect, touching=True):
                key = ("header", label.edge_id, group.group_id)
                label_hits.add(key)
                findings.append(_hard("geometry.label.header_overlap", f"label {label.edge_id!r} overlaps group header {group.group_id!r}", (label.edge_id, group.group_id), "maximum_label_overlaps"))
        for route in layout.routes:
            for index, segment in enumerate(route.segments):
                if segment.intersects_rect(label.rect):
                    key = ("route", label.edge_id, route.edge_id, str(index))
                    label_hits.add(key)
                    findings.append(_hard("geometry.label.route_overlap", f"label {label.edge_id!r} overlaps route {route.edge_id!r}", (label.edge_id, route.edge_id), "maximum_label_overlaps", {"segment": index}))

    for constraint in spec.constraints.separations:
        first, second = nodes.get(constraint.first), nodes.get(constraint.second)
        if first is None or second is None:
            continue
        horizontal, vertical = _axis_gaps(first.rect, second.rect)
        actual = max(horizontal, vertical)
        required = constraint.minimum_grid_units * grid
        if actual < required:
            _spacing_finding(findings, spacing, (first.node_id, second.node_id), "explicit_separation", actual, required)

    drift_count = _geometry_drift_count(layout, comparison) if comparison is not None else 0
    if drift_count:
        findings.append(_hard("geometry.deterministic_drift", "layout differs from the comparison result", (layout.diagram_id,), "maximum_geometry_drift_on_repeat_run", {"changed_objects": drift_count}))

    ordered = tuple(sorted(findings, key=lambda item: (item.code, item.object_ids, item.message)))
    counts = hard_gate_counts(
        (),
        maximum_node_overlaps=len(node_overlap_pairs),
        maximum_node_title_intersections=len(node_header_pairs),
        maximum_edge_node_intersections_excluding_terminals=len(edge_node_hits),
        maximum_edge_title_intersections=len(edge_header_hits),
        maximum_label_overlaps=len(label_hits),
        maximum_unresolved_icons=0,
        maximum_clipped_children=len(clipped),
        maximum_unsatisfied_minimum_spacing_rules=len(spacing),
        maximum_dangling_edges=len(dangling),
        maximum_geometry_drift_on_repeat_run=drift_count,
    )
    return GeometryValidationResult(findings=ordered, hard_counts=counts)


def _validate_route_policy(findings: list[Finding], route: object, kind: EdgeKind, source: object, target: object, grid: int, rules: RuleSet) -> None:
    points = route.points  # type: ignore[attr-defined]
    for index, point in enumerate(points):
        if point.x % grid or point.y % grid:
            findings.append(make_finding(Severity.ERROR, "geometry.route.off_grid", f"route {route.edge_id!r} point is off grid", object_ids=(route.edge_id,), details={"point_index": index, "x": point.x, "y": point.y}))
    for index, (first, second) in enumerate(zip(points, points[1:])):
        if first == second or (first.x != second.x and first.y != second.y):
            findings.append(make_finding(Severity.ERROR, "geometry.route.non_orthogonal", f"route {route.edge_id!r} has a non-orthogonal segment", object_ids=(route.edge_id,), details={"segment": index}))
    maximum = rules.routing.bends.maximum_feedback_edge if route.feedback else rules.routing.bends.maximum_normal_edge
    if route.bends > maximum:
        findings.append(make_finding(Severity.ERROR, "geometry.route.bend_limit", f"route {route.edge_id!r} exceeds bend limit", object_ids=(route.edge_id,), details={"actual": route.bends, "maximum": maximum}))
    if not route.feedback and kind in {EdgeKind.SYNCHRONOUS, EdgeKind.ASYNCHRONOUS, EdgeKind.DATA}:
        if source.rank >= target.rank:
            findings.append(make_finding(Severity.ERROR, "geometry.flow.rank_progression", f"route {route.edge_id!r} does not advance to a later rank", object_ids=(route.edge_id, source.node_id, target.node_id), details={"source_rank": source.rank, "target_rank": target.rank}))
        if source.rect.center.x >= target.rect.center.x:
            findings.append(make_finding(Severity.ERROR, "geometry.flow.x_progression", f"route {route.edge_id!r} does not progress left-to-right", object_ids=(route.edge_id, source.node_id, target.node_id)))
        if route.source_port.side is not PortSide.EAST or route.target_port.side is not PortSide.WEST:
            findings.append(make_finding(Severity.ERROR, "geometry.flow.primary_ports", f"route {route.edge_id!r} does not use east/west primary ports", object_ids=(route.edge_id,), details={"source_side": route.source_port.side.value, "target_side": route.target_port.side.value}))


def _check_rect_grid(findings: list[Finding], kind: str, object_id: str, rect: Rect, grid: int) -> None:
    values = (rect.x, rect.y, rect.width, rect.height)
    if any(value % grid for value in values):
        findings.append(make_finding(Severity.ERROR, "geometry.grid_alignment", f"{kind} {object_id!r} is off grid", object_ids=(object_id,), details={"geometry": values, "grid": grid}))


def _spacing_finding(findings: list[Finding], seen: set[tuple[str, str, str]], pair: tuple[str, str], axis: str, actual: int, required: int) -> None:
    key = (*tuple(sorted(pair)), axis)
    if key in seen:
        return
    seen.add(key)
    findings.append(_hard("geometry.minimum_spacing", f"minimum {axis} spacing is unsatisfied", pair, "maximum_unsatisfied_minimum_spacing_rules", {"actual": actual, "required": required}))


def _hard(code: str, message: str, object_ids: tuple[str, ...], gate: str, details: dict[str, object] | None = None) -> Finding:
    return make_finding(Severity.ERROR, code, message, object_ids=object_ids, details=details, hard_gate=gate)  # type: ignore[arg-type]


def _axis_gaps(first: Rect, second: Rect) -> tuple[int, int]:
    return max(0, second.left - first.right, first.left - second.right), max(0, second.top - first.bottom, first.top - second.bottom)


def _geometry_drift_count(layout: LayoutResult, comparison: LayoutResult) -> int:
    if layout.diagram_id != comparison.diagram_id:
        return 1
    changed = int(layout.canvas != comparison.canvas)
    for attribute, key in (("groups", "group_id"), ("nodes", "node_id"), ("routes", "edge_id"), ("labels", "edge_id")):
        left = {getattr(item, key): item for item in getattr(layout, attribute)}
        right = {getattr(item, key): item for item in getattr(comparison, attribute)}
        changed += sum(left.get(item_id) != right.get(item_id) for item_id in set(left) | set(right))
    return changed


__all__ = ["GeometryValidationError", "GeometryValidationResult", "validate_geometry"]
