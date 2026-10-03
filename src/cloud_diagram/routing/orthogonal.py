"""Deterministic obstacle-aware Manhattan routing with hard postconditions."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from cloud_diagram.domain import PortSide
from cloud_diagram.graph import DiagramGraph
from cloud_diagram.layout.geometry import (
    Canvas,
    EdgeRoute,
    GeometryError,
    GroupPlacement,
    NodePlacement,
    Point,
    Port,
    Rect,
    Segment,
    terminal_segment_is_outward,
    validate_routed_geometry,
)
from cloud_diagram.rules import RuleSet

from .ports import EdgePorts, PortAssignments


class RoutingError(ValueError):
    """Raised when no legal bounded orthogonal candidate exists."""


@dataclass(frozen=True, slots=True)
class RoutingResult:
    routes: tuple[EdgeRoute, ...]
    diagnostics: tuple[str, ...] = ()


def _snap(value: int, grid: int) -> int:
    return ((value + grid // 2) // grid) * grid


def _ceil_grid(value: int, grid: int) -> int:
    return ((value + grid - 1) // grid) * grid


def _stub(point: Point, side: PortSide, length: int) -> Point:
    if side is PortSide.EAST: return Point(x=point.x + length, y=point.y)
    if side is PortSide.WEST: return Point(x=point.x - length, y=point.y)
    if side is PortSide.NORTH: return Point(x=point.x, y=point.y - length)
    return Point(x=point.x, y=point.y + length)


def _collapse(points: list[Point]) -> tuple[Point, ...]:
    compact: list[Point] = []
    for point in points:
        if compact and point == compact[-1]: continue
        compact.append(point)
        while len(compact) >= 3:
            first, middle, last = compact[-3:]
            if first.x == middle.x == last.x or first.y == middle.y == last.y:
                compact.pop(-2)
            else:
                break
    return tuple(compact)


def _segments_cross(first: Segment, second: Segment) -> bool:
    if first.horizontal and second.vertical:
        lo_x, hi_x = sorted((first.start.x, first.end.x)); lo_y, hi_y = sorted((second.start.y, second.end.y))
        return lo_x < second.start.x < hi_x and lo_y < first.start.y < hi_y
    if first.vertical and second.horizontal: return _segments_cross(second, first)
    if first.horizontal and second.horizontal and first.start.y == second.start.y:
        a,b=sorted((first.start.x,first.end.x)); c,d=sorted((second.start.x,second.end.x)); return max(a,c)<min(b,d)
    if first.vertical and second.vertical and first.start.x == second.start.x:
        a,b=sorted((first.start.y,first.end.y)); c,d=sorted((second.start.y,second.end.y)); return max(a,c)<min(b,d)
    return False


def _candidate_segments(points: tuple[Point, ...]) -> tuple[Segment, ...] | None:
    try:
        return tuple(Segment(start=a, end=b) for a,b in zip(points, points[1:]))
    except ValueError:
        return None


def _candidate_is_legal(
    points: tuple[Point, ...],
    obstacles: tuple[tuple[str, Rect], ...],
    source_id: str,
    target_id: str,
    source_rect: Rect,
    target_rect: Rect,
    source_port: Port,
    target_port: Port,
    maximum_bends: int,
    rules: RuleSet,
) -> bool:
    if len(points) < 2 or len(points)-2 > maximum_bends:
        return False
    if any(point.x % rules.ruleset.grid_size or point.y % rules.ruleset.grid_size for point in points):
        return False
    segments = _candidate_segments(points)
    if segments is None:
        return False
    if not terminal_segment_is_outward(segments[0], source_port, source_rect, source=True):
        return False
    if not terminal_segment_is_outward(segments[-1], target_port, target_rect, source=False):
        return False
    terminal_min = _ceil_grid(rules.routing.segments.minimum_terminal_stub, rules.ruleset.grid_size)
    middle_min = _ceil_grid(rules.routing.segments.minimum_middle_segment, rules.ruleset.grid_size)
    if len(segments) > 1 and (segments[0].length < terminal_min or segments[-1].length < terminal_min):
        return False
    if len(segments) > 2 and any(segment.length < middle_min for segment in segments[1:-1]):
        return False
    for index, segment in enumerate(segments):
        for obstacle_id, rect in obstacles:
            legal_terminal = (obstacle_id == source_id and index == 0) or (
                obstacle_id == target_id and index == len(segments)-1
            )
            if legal_terminal:
                continue
            if segment.intersects_rect(rect):
                return False
    return True


def _ordered(values: set[int], preferred: int, limit: int = 96) -> tuple[int, ...]:
    return tuple(sorted(values, key=lambda value: (abs(value-preferred), value))[:limit])


def _normal_candidates(
    ports: EdgePorts,
    obstacles: tuple[tuple[str, Rect], ...],
    canvas: Canvas,
    prior: tuple[EdgeRoute, ...],
    rules: RuleSet,
    boundary_x: tuple[int, ...] = (),
    boundary_y: tuple[int, ...] = (),
) -> tuple[tuple[Point, ...], ...]:
    grid=rules.ruleset.grid_size
    stub_length=_ceil_grid(max(rules.routing.segments.minimum_terminal_stub, rules.routing.clearance.node)+grid,grid)
    source,target=ports.source.point,ports.target.point
    source_stub=_stub(source,ports.source.side,stub_length); target_stub=_stub(target,ports.target.side,stub_length)
    result=[
        _collapse([source,source_stub,Point(x=target_stub.x,y=source_stub.y),target_stub,target]),
        _collapse([source,source_stub,Point(x=source_stub.x,y=target_stub.y),target_stub,target]),
    ]
    preferred_x=_snap((source_stub.x+target_stub.x)//2,grid); preferred_y=_snap((source_stub.y+target_stub.y)//2,grid)
    x_values={preferred_x,source_stub.x,target_stub.x,canvas.x+rules.canvas.margin.left,canvas.x+canvas.width-rules.canvas.margin.right,*boundary_x}
    y_values={preferred_y,source_stub.y,target_stub.y,canvas.y+rules.canvas.margin.top,canvas.y+canvas.height-rules.canvas.margin.bottom,*boundary_y}
    # `obstacles` rectangles are already expanded by clearance at the call
    # site, so only a single grid step of margin is added here to keep lane
    # values strictly outside each obstacle rather than exactly on its edge.
    margin=grid
    for _,rect in obstacles:
        x_values.update({_snap(rect.left-margin,grid),_snap(rect.right+margin,grid)})
        y_values.update({_snap(rect.top-margin,grid),_snap(rect.bottom+margin,grid)})
    lane_gap=_ceil_grid(rules.routing.parallel_edges.minimum_gap,grid)
    for route in prior:
        for point in route.points:
            x_values.update((point.x-lane_gap,point.x+lane_gap)); y_values.update((point.y-lane_gap,point.y+lane_gap))
    for lane_x in _ordered(x_values,preferred_x):
        result.append(_collapse([source,source_stub,Point(x=lane_x,y=source_stub.y),Point(x=lane_x,y=target_stub.y),target_stub,target]))
    for lane_y in _ordered(y_values,preferred_y):
        result.append(_collapse([source,source_stub,Point(x=source_stub.x,y=lane_y),Point(x=target_stub.x,y=lane_y),target_stub,target]))
    for lane_x in _ordered(set(boundary_x), preferred_x, limit=24):
        for lane_y in _ordered(set(boundary_y), preferred_y, limit=24):
            result.append(
                _collapse([
                    source,
                    source_stub,
                    Point(x=lane_x, y=source_stub.y),
                    Point(x=lane_x, y=lane_y),
                    Point(x=target_stub.x, y=lane_y),
                    target_stub,
                    target,
                ])
            )
    result.extend(
        _boundary_descent_candidates(
            source, source_stub, target, target_stub, ports, boundary_x, boundary_y, obstacles
        )
    )
    return tuple(dict.fromkeys(result))


def _boundary_descent_candidates(
    source: Point,
    source_stub: Point,
    target: Point,
    target_stub: Point,
    ports: EdgePorts,
    boundary_x: tuple[int, ...],
    boundary_y: tuple[int, ...],
    obstacles: tuple[tuple[str, Rect], ...],
) -> list[tuple[Point, ...]]:
    """Thread one contiguous trunk segment through every nested ancestor boundary.

    When an endpoint is nested several containers deep and the other endpoint
    shares none of those ancestors, ``_boundary_route_is_legal`` requires one
    perpendicular crossing per ancestor group. A single long trunk segment run
    along one axis crosses every concentric border exactly once with ample run
    length; only the final short jog handles the innermost container, so
    terminal stubs never re-cross an already-entered boundary. Descent planes
    that would run the trunk back through either terminal's own expanded
    obstacle rectangle are skipped, since that is never a legal middle segment.
    """

    candidates: list[tuple[Point, ...]] = []
    vertical = source_stub.x == target_stub.x
    horizontal = source_stub.y == target_stub.y
    if not vertical:
        candidates.append(
            _collapse([source, source_stub, Point(x=source_stub.x, y=target_stub.y), target_stub, target])
        )
    if not horizontal:
        candidates.append(
            _collapse([source, source_stub, Point(x=target_stub.x, y=source_stub.y), target_stub, target])
        )
    excluded = {ports.source.node_id, ports.target.node_id}

    def _clear(trunk: Segment) -> bool:
        return not any(trunk.intersects_rect(rect) for name, rect in obstacles if name not in excluded)

    def _safe_segment(start: Point, end: Point) -> Segment | None:
        if start == end:
            return None
        return Segment(start=start, end=end)

    # Nested containers have a header band only at their top, so a route must
    # cross each ancestor's left/right border (never its top/bottom) to avoid
    # every header. Build an L-shaped path that first moves, while still
    # fully outside every relevant ancestor, to a y aligned with the target
    # row (or an x aligned with the target column), then travels the
    # remaining axis as one long trunk that crosses every ancestor exactly
    # once through its side at a row/column already clear of every header.
    departs_east = ports.source.side is PortSide.EAST
    departs_west = ports.source.side is PortSide.WEST
    arrives_east = ports.target.side is PortSide.EAST
    arrives_west = ports.target.side is PortSide.WEST

    def _x_after_source(value: int) -> bool:
        if departs_east:
            return value >= source_stub.x
        if departs_west:
            return value <= source_stub.x
        return True

    def _x_before_target(value: int) -> bool:
        if arrives_east:
            return value >= target_stub.x
        if arrives_west:
            return value <= target_stub.x
        return True

    for approach_x in sorted({*boundary_x, source_stub.x}):
        if not _x_after_source(approach_x):
            continue
        elbow = Point(x=approach_x, y=source_stub.y)
        lead = _safe_segment(source_stub, elbow)
        if lead is not None and not _clear(lead):
            continue
        trunk_end = Point(x=approach_x, y=target_stub.y)
        trunk = _safe_segment(elbow, trunk_end)
        if trunk is not None and not _clear(trunk):
            continue
        candidates.append(
            _collapse(
                [
                    source,
                    source_stub,
                    elbow,
                    trunk_end,
                    target_stub,
                    target,
                ]
            )
        )
    for approach_y in sorted({*boundary_y, target_stub.y}):
        elbow = Point(x=source_stub.x, y=approach_y)
        lead = _safe_segment(source_stub, elbow)
        if lead is not None and not _clear(lead):
            continue
        if not _x_before_target(source_stub.x):
            continue
        trunk_end = Point(x=target_stub.x, y=approach_y)
        trunk = _safe_segment(elbow, trunk_end)
        if trunk is not None and not _clear(trunk):
            continue
        candidates.append(
            _collapse(
                [
                    source,
                    source_stub,
                    elbow,
                    Point(x=target_stub.x, y=approach_y),
                    target_stub,
                    target,
                ]
            )
        )

    # When many stacked ancestor headers make a compact elbow illegal, swing
    # around the entire obstacle field: travel outside its extent along one
    # axis, sweep past it along the other axis at a row/column clear of every
    # header and every sibling node, then approach the target from whichever
    # side its own port actually faces.
    relevant_rects = tuple(rect for _, rect in obstacles)
    if relevant_rects:
        clear_left = min(rect.left for rect in relevant_rects) - 8
        clear_right = max(rect.right for rect in relevant_rects) + 8
        clear_top = min(rect.top for rect in relevant_rects) - 8
        clear_bottom = max(rect.bottom for rect in relevant_rects) + 8
        for wide_x in sorted({clear_left, clear_right}):
            if arrives_west and wide_x >= target_stub.x:
                continue
            if arrives_east and wide_x <= target_stub.x:
                continue
            entry = Point(x=wide_x, y=source_stub.y)
            lead = _safe_segment(source_stub, entry)
            if lead is not None and not _clear(lead):
                continue
            trunk_end = Point(x=wide_x, y=target_stub.y)
            trunk = _safe_segment(entry, trunk_end)
            if trunk is not None and not _clear(trunk):
                continue
            candidates.append(
                _collapse(
                    [
                        source,
                        source_stub,
                        entry,
                        trunk_end,
                        target_stub,
                        target,
                    ]
                )
            )
        for wide_y in sorted({clear_top, clear_bottom}):
            entry = Point(x=source_stub.x, y=wide_y)
            lead = _safe_segment(source_stub, entry)
            if lead is not None and not _clear(lead):
                continue
            for wide_x in sorted({clear_left, clear_right}):
                if arrives_west and wide_x >= target_stub.x:
                    continue
                if arrives_east and wide_x <= target_stub.x:
                    continue
                corner = Point(x=wide_x, y=wide_y)
                across = _safe_segment(entry, corner)
                if across is not None and not _clear(across):
                    continue
                trunk_end = Point(x=wide_x, y=target_stub.y)
                down = _safe_segment(corner, trunk_end)
                if down is not None and not _clear(down):
                    continue
                candidates.append(
                    _collapse(
                        [
                            source,
                            source_stub,
                            entry,
                            corner,
                            trunk_end,
                            target_stub,
                            target,
                        ]
                    )
                )
    return candidates


def _feedback_candidates(
    ports: EdgePorts,
    lane_y: int,
    rules: RuleSet,
    *,
    self_loop: bool,
    loop_index: int = 0,
) -> tuple[tuple[Point,...],...]:
    grid=rules.ruleset.grid_size
    terminal=_ceil_grid(max(rules.routing.segments.minimum_terminal_stub,rules.routing.clearance.node)+grid,grid)
    source,target=ports.source.point,ports.target.point
    if self_loop:
        size=_ceil_grid(rules.routing.self_loops.minimum_size,grid)
        lane_gap=_ceil_grid(
            max(rules.routing.feedback_edges.stack_gap, rules.routing.parallel_edges.minimum_gap),
            grid,
        )
        local_y=_snap(max(lane_y, max(source.y,target.y)+max(size,terminal))+loop_index*lane_gap,grid)
        return (_collapse([source,Point(x=source.x,y=local_y),Point(x=target.x,y=local_y),target]),)
    source_stub=_stub(source,PortSide.SOUTH,terminal); target_stub=_stub(target,PortSide.SOUTH,terminal)
    lane_y=max(lane_y,source_stub.y+_ceil_grid(rules.routing.segments.minimum_middle_segment,grid),target_stub.y+_ceil_grid(rules.routing.segments.minimum_middle_segment,grid))
    lane_y=_snap(lane_y,grid)
    return (
        _collapse([source,source_stub,Point(x=source_stub.x,y=lane_y),Point(x=target_stub.x,y=lane_y),target_stub,target]),
    )


def _score(points: tuple[Point,...], prior: tuple[EdgeRoute,...]) -> tuple[object,...]:
    segments=_candidate_segments(points) or ()
    crossings=0; overlaps=0
    for segment in segments:
        for route in prior:
            for other in route.segments:
                if _segments_cross(segment,other):
                    if (segment.horizontal==other.horizontal) or (segment.vertical==other.vertical): overlaps+=1
                    else: crossings+=1
    return (overlaps,crossings,max(0,len(segments)-1),sum(segment.length for segment in segments),tuple((p.x,p.y) for p in points))


def _boundary_crossings(
    segments: tuple[Segment, ...], rect: Rect
) -> tuple[tuple[bool, int], ...] | None:
    """Return (perpendicular, shortest run) for every rectangle-border crossing."""

    crossings: list[tuple[bool, int]] = []
    for segment in segments:
        if segment.horizontal:
            low, high = sorted((segment.start.x, segment.end.x))
            if segment.start.y in {rect.top, rect.bottom} and high > rect.left and low < rect.right:
                return None
            if rect.top < segment.start.y < rect.bottom:
                for border in (rect.left, rect.right):
                    if low <= border <= high:
                        crossings.append((True, min(abs(segment.start.x-border), abs(segment.end.x-border))))
        else:
            low, high = sorted((segment.start.y, segment.end.y))
            if segment.start.x in {rect.left, rect.right} and high > rect.top and low < rect.bottom:
                return None
            if rect.left < segment.start.x < rect.right:
                for border in (rect.top, rect.bottom):
                    if low <= border <= high:
                        crossings.append((True, min(abs(segment.start.y-border), abs(segment.end.y-border))))
    return tuple(crossings)


def _boundary_route_is_legal(
    points: tuple[Point, ...],
    source_path: tuple[str, ...],
    target_path: tuple[str, ...],
    groups: tuple[GroupPlacement, ...],
    minimum_run: int,
    *,
    feedback: bool,
) -> bool:
    segments = _candidate_segments(points)
    if segments is None:
        return False
    source_groups, target_groups = set(source_path), set(target_path)
    for group in groups:
        crossings = _boundary_crossings(segments, group.rect)
        if crossings is None or any(not perpendicular or run < minimum_run for perpendicular, run in crossings):
            return False
        source_inside = group.group_id in source_groups
        target_inside = group.group_id in target_groups
        if source_inside != target_inside and len(crossings) != 1:
            return False
        if source_inside and target_inside:
            allowed = {0, 2} if feedback else {0}
            if len(crossings) not in allowed:
                return False
        if not source_inside and not target_inside and crossings:
            return False
    return True


def route_edges(
    graph: DiagramGraph,
    nodes: tuple[NodePlacement,...],
    groups: tuple[GroupPlacement,...],
    canvas: Canvas,
    ports: PortAssignments,
    rules: RuleSet,
) -> RoutingResult:
    """Route stable candidates, considering existing routes, or fail explicitly."""

    if any(edge.self_loop for edge in graph.edges) and not rules.routing.self_loops.allowed:
        loops=sorted(edge.id for edge in graph.edges if edge.self_loop)
        raise RoutingError(f"self loops are disabled by rules; rejected edges={loops!r}")
    node_by_id={node.node_id:node for node in nodes}; group_by_id={group.group_id:group for group in groups}; port_by_edge=ports.by_edge
    group_parent = {group.group_id: group.parent_id for group in groups}
    actual_paths: dict[str, tuple[str, ...]] = {}
    for node in nodes:
        path: list[str] = []
        current = node.group_id
        while current is not None:
            path.append(current)
            current = group_parent[current]
        actual_paths[node.node_id] = tuple(reversed(path))
    node_clearance=_ceil_grid(rules.routing.clearance.node,rules.ruleset.grid_size); header_clearance=_ceil_grid(rules.routing.clearance.container_header,rules.ruleset.grid_size)
    base=[(node.node_id,node.rect.expanded(node_clearance)) for node in nodes]
    base.extend((f"header:{group.group_id}",group.header_rect.expanded(header_clearance)) for group in groups)
    geometry_bottom=max([node.rect.bottom for node in nodes]+[group.rect.bottom for group in groups]+[0])
    feedback_order={edge.id:index for index,edge in enumerate(sorted((edge for edge in graph.feedback_edges if not edge.self_loop),key=lambda value:value.id))}
    self_loop_order: dict[str, int] = {}
    self_loop_count: dict[str, int] = {}
    for loop in sorted((edge for edge in graph.feedback_edges if edge.self_loop), key=lambda value: value.id):
        self_loop_order[loop.id] = self_loop_count.get(loop.source, 0)
        self_loop_count[loop.source] = self_loop_order[loop.id] + 1
    routes: list[EdgeRoute]=[]; diagnostics: list[str]=[]

    for edge in graph.edges:
        edge_ports=port_by_edge[edge.id]
        obstacles=list(base)
        source_path=actual_paths[edge.source]; target_path=actual_paths[edge.target]
        if rules.routing.obstacles.avoid_unrelated_container_interiors:
            for group in groups:
                if group.group_id not in source_path and group.group_id not in target_path:
                    obstacles.append((f"group:{group.group_id}",group.rect.expanded(rules.routing.clearance.container_border)))
        hint=edge.edge.routing_hint
        if hint is not None:
            for group_id in hint.avoid_group_ids:
                if group_id in source_path or group_id in target_path:
                    raise RoutingError(f"edge {edge.id!r} cannot avoid endpoint ancestor group {group_id!r}")
                obstacles.append((f"avoid:{group_id}",group_by_id[group_id].rect.expanded(rules.routing.clearance.container_border)))
        obstacle_tuple=tuple(sorted(set(obstacles),key=lambda item:(item[0],item[1].x,item[1].y)))
        if edge.feedback:
            lane_y=geometry_bottom+_ceil_grid(rules.routing.feedback_edges.perimeter_gap+feedback_order.get(edge.id,0)*rules.routing.feedback_edges.stack_gap,rules.ruleset.grid_size)
            candidates=_feedback_candidates(
                edge_ports,
                lane_y,
                rules,
                self_loop=edge.self_loop,
                loop_index=self_loop_order.get(edge.id, 0),
            )
            maximum_bends=rules.routing.bends.maximum_feedback_edge
        else:
            boundary_gap = _ceil_grid(
                max(
                    rules.routing.boundary_edges.minimum_perpendicular_run,
                    rules.routing.clearance.container_header,
                    rules.routing.clearance.container_border,
                ) + max(
                    rules.ruleset.grid_size,
                    rules.routing.segments.minimum_middle_segment,
                ) + rules.ruleset.grid_size,
                rules.ruleset.grid_size,
            )
            endpoint_boundaries = [
                group.rect for group in groups
                if group.group_id in (set(source_path) | set(target_path))
            ]
            boundary_x = tuple(
                sorted({value for rect in endpoint_boundaries for value in (rect.left-boundary_gap, rect.right+boundary_gap)})
            )
            boundary_y = tuple(
                sorted(
                    {value for rect in endpoint_boundaries for value in (rect.top-boundary_gap, rect.bottom+boundary_gap)}
                    | {
                        group.header_rect.top
                        - _ceil_grid(rules.routing.clearance.container_header, rules.ruleset.grid_size)
                        - rules.ruleset.grid_size
                        for group in groups
                        if group.group_id in (set(source_path) | set(target_path))
                    }
                )
            )
            nested_only = [
                group.rect for group in groups
                if (group.group_id in source_path) != (group.group_id in target_path)
            ]
            if nested_only:
                shared_x = tuple(
                    sorted(
                        {
                            value
                            for value in boundary_x
                            if all(rect.left < value < rect.right for rect in nested_only)
                        }
                    )
                )
                shared_y = tuple(
                    sorted(
                        {
                            value
                            for value in boundary_y
                            if all(rect.top < value < rect.bottom for rect in nested_only)
                        }
                    )
                )
                boundary_x = shared_x or boundary_x
                boundary_y = shared_y or boundary_y
            candidates=_normal_candidates(
                edge_ports,
                obstacle_tuple,
                canvas,
                tuple(routes),
                rules,
                boundary_x,
                boundary_y,
            )
            maximum_bends=rules.routing.bends.maximum_normal_edge
        legal=[candidate for candidate in candidates if _candidate_is_legal(
            candidate,
            obstacle_tuple,
            edge.source,
            edge.target,
            node_by_id[edge.source].rect,
            node_by_id[edge.target].rect,
            edge_ports.source,
            edge_ports.target,
            maximum_bends,
            rules,
        ) and _boundary_route_is_legal(
            candidate,
            source_path,
            target_path,
            groups,
            _ceil_grid(rules.routing.boundary_edges.minimum_perpendicular_run, rules.ruleset.grid_size),
            feedback=edge.feedback,
        )]
        if not legal:
            raise RoutingError(
                f"edge {edge.id!r} ({edge.source}->{edge.target}, feedback={edge.feedback}) has no legal orthogonal route "
                f"after {len(candidates)} bounded candidates; endpoint rectangles were ignored only on terminal segments"
            )
        selected=min(legal,key=lambda candidate:_score(candidate,tuple(routes)))
        route=EdgeRoute(edge_id=edge.id,source_port=edge_ports.source,target_port=edge_ports.target,points=selected,feedback=edge.feedback)
        routes.append(route)
        diagnostics.append(f"edge {edge.id}: bends={route.bends}, length={route.total_length}, ports={route.source_port.side.value}/{route.target_port.side.value}")

    result=tuple(sorted(routes,key=lambda value:value.edge_id))
    try:
        validate_routed_geometry(nodes,groups,result,(),grid=rules.ruleset.grid_size)
    except GeometryError as exc:
        raise RoutingError(str(exc)) from exc
    return RoutingResult(routes=result,diagnostics=tuple(sorted(diagnostics)))


__all__=["RoutingError","RoutingResult","route_edges"]
