"""Deterministic internal layered layout public API."""

from __future__ import annotations

from itertools import combinations

from cloud_diagram.domain import DiagramSpec
from cloud_diagram.graph import assign_ranks, build_graph, order_nodes
from cloud_diagram.rules import RuleEngine, RuleOverrideError, RuleSet

from .base import LayoutEngine, LayoutError, PlacementResult
from .geometry import (
    Canvas,
    EdgeLabelPlacement,
    EdgeRoute,
    GeometryError,
    GeometryModel,
    GroupPlacement,
    LayoutMetrics,
    LayoutResult,
    NodePlacement,
    Point,
    Port,
    Rect,
    Segment,
    validate_placement_geometry,
    validate_routed_geometry,
)
from .graphviz import DeterministicLayeredLayout, LayeredPlacement


def _segments_cross(first: Segment, second: Segment) -> bool:
    """Return true only for an actual perpendicular interior crossing."""

    if {first.start, first.end} & {second.start, second.end}:
        return False
    if first.horizontal and second.vertical:
        low_x, high_x = sorted((first.start.x, first.end.x))
        low_y, high_y = sorted((second.start.y, second.end.y))
        return low_x < second.start.x < high_x and low_y < first.start.y < high_y
    if first.vertical and second.horizontal:
        return _segments_cross(second, first)
    return False


def _crossing_count(routes: tuple[EdgeRoute, ...]) -> int:
    """Count every intersecting segment pair, not merely each route pair."""

    return sum(
        1
        for first, second in combinations(routes, 2)
        for first_segment in first.segments
        for second_segment in second.segments
        if _segments_cross(first_segment, second_segment)
    )


def _final_canvas(
    placement: LayeredPlacement,
    routes: tuple[EdgeRoute, ...],
    labels: tuple[EdgeLabelPlacement, ...],
    rules: RuleSet,
) -> Canvas:
    grid = rules.ruleset.grid_size
    rects = [value.rect for value in placement.nodes] + [value.rect for value in placement.groups]
    xs = [rect.x for rect in rects]
    ys = [rect.y for rect in rects]
    rights = [rect.right for rect in rects]
    bottoms = [rect.bottom for rect in rects]
    for route in routes:
        xs.extend(point.x for point in route.points); ys.extend(point.y for point in route.points)
        rights.extend(point.x for point in route.points); bottoms.extend(point.y for point in route.points)
    for label in labels:
        xs.append(label.rect.left); ys.append(label.rect.top); rights.append(label.rect.right); bottoms.append(label.rect.bottom)
    minimum_x = min(xs, default=0) - rules.canvas.margin.left
    minimum_y = min(ys, default=0) - rules.canvas.margin.top
    maximum_x = max(rights, default=0) + rules.canvas.margin.right
    maximum_y = max(bottoms, default=0) + rules.canvas.margin.bottom
    x = (minimum_x // grid) * grid; y = (minimum_y // grid) * grid
    width = max(rules.canvas.minimum_width, ((maximum_x - x + grid - 1) // grid) * grid)
    height = max(rules.canvas.minimum_height, ((maximum_y - y + grid - 1) // grid) * grid)
    if width > rules.canvas.maximum_width or height > rules.canvas.maximum_height:
        raise LayoutError(
            f"routed layout requires {width}x{height}px, exceeding maximum "
            f"{rules.canvas.maximum_width}x{rules.canvas.maximum_height}px"
        )
    return Canvas(x=x, y=y, width=width, height=height)


def layout_diagram(spec: DiagramSpec, rules: RuleSet) -> LayoutResult:
    """Build, rank, place, route, validate, and return a byte-stable result."""

    from cloud_diagram.routing import RoutingError, assign_ports, place_edge_labels, route_edges

    if spec.overrides.template is not None:
        raise LayoutError(
            f"unsupported layout template {spec.overrides.template!r}: no template registry exists"
        )
    diagram_override = spec.overrides.model_dump(
        exclude={"template"}, exclude_none=True, mode="python"
    )
    try:
        resolution = RuleEngine().resolve(
            rules,
            diagram_override=diagram_override or None,
        )
    except RuleOverrideError as exc:
        raise LayoutError(f"invalid DiagramSpec override: {exc}") from exc
    effective_rules = resolution.effective_rules
    override_decisions = tuple(
        f"rule override [{record.precedence}] {record.field_path}: "
        f"{record.previous_value}->{record.override_value}"
        for record in resolution.trace
    )

    graph = build_graph(spec)
    ranks = assign_ranks(graph, spec, effective_rules)
    ordering = order_nodes(graph, ranks, spec, effective_rules)
    engine = DeterministicLayeredLayout()
    placement = engine.place(graph, ranks, ordering, spec, effective_rules)
    ports = assign_ports(graph, placement.nodes, effective_rules)
    routing = route_edges(graph, placement.nodes, placement.groups, placement.canvas, ports, effective_rules)
    label_placement = place_edge_labels(graph, routing.routes, placement.nodes, placement.groups, effective_rules)
    try:
        validate_placement_geometry(
            placement.nodes,
            placement.groups,
            grid=effective_rules.ruleset.grid_size,
            minimum_horizontal=effective_rules.nodes.spacing.minimum_horizontal,
            minimum_vertical=effective_rules.nodes.spacing.minimum_vertical,
            child_clearance=effective_rules.containers.header.child_clearance,
            sibling_horizontal=effective_rules.containers.sibling_gap.horizontal,
            sibling_vertical=effective_rules.containers.sibling_gap.vertical,
        )
        validate_routed_geometry(
            placement.nodes,
            placement.groups,
            routing.routes,
            label_placement.labels,
            grid=effective_rules.ruleset.grid_size,
        )
    except GeometryError as exc:
        raise RoutingError(str(exc)) from exc
    canvas = _final_canvas(placement, routing.routes, label_placement.labels, effective_rules)
    crossings = _crossing_count(routing.routes)
    total_bends = sum(route.bends for route in routing.routes)
    maximum_bends = max((route.bends for route in routing.routes), default=0)
    metrics = LayoutMetrics(
        node_count=len(placement.nodes), group_count=len(placement.groups), edge_count=len(routing.routes),
        feedback_edge_count=sum(route.feedback for route in routing.routes), total_bends=total_bends,
        maximum_bends=maximum_bends, total_route_length=sum(route.total_length for route in routing.routes),
        crossing_count=crossings, label_count=len(label_placement.labels),
    )
    warnings = list(placement.warnings); edge_count = len(routing.routes)
    if edge_count and total_bends > effective_rules.quality_gates.soft.maximum_average_bends_per_edge * edge_count:
        warnings.append(f"average bend target exceeded: {total_bends}/{edge_count} edges")
    if crossings * 10 > effective_rules.quality_gates.soft.maximum_crossings_per_10_edges * max(1, edge_count):
        warnings.append(f"crossing target exceeded: {crossings} individual residual crossings")
    decisions = tuple(sorted(set(
        (
            f"requested layout engine={rules.layout.primary_engine}; actual layout engine={engine.engine_id}; explicit deterministic fallback",
            "Graphviz was not invoked",
        )
        + override_decisions + graph.diagnostics + ranks.diagnostics + ordering.diagnostics
        + placement.decisions + ports.diagnostics + routing.diagnostics + label_placement.diagnostics
    )))
    return LayoutResult(
        engine_id=engine.engine_id,
        diagram_id=spec.diagram_id,
        canvas=canvas,
        groups=placement.groups,
        nodes=placement.nodes,
        routes=routing.routes,
        labels=label_placement.labels,
        metrics=metrics,
        decisions=decisions,
        warnings=tuple(warnings),
    )


__all__ = [
    "Canvas", "DeterministicLayeredLayout", "EdgeLabelPlacement", "EdgeRoute", "GeometryError",
    "GeometryModel", "GroupPlacement", "LayeredPlacement", "LayoutEngine", "LayoutError",
    "LayoutMetrics", "LayoutResult", "NodePlacement", "PlacementResult", "Point", "Port", "Rect",
    "Segment", "layout_diagram", "validate_placement_geometry", "validate_routed_geometry",
]
