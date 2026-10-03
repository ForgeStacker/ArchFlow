"""Immutable integer geometry, result models, and hard geometry validation."""

from __future__ import annotations

import json
from itertools import combinations
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from cloud_diagram.domain import PortSide, StableId


class GeometryError(ValueError):
    """Raised when geometry is internally inconsistent."""


class GeometryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json", exclude_none=True), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    to_canonical_json = canonical_json


class Point(GeometryModel):
    x: StrictInt
    y: StrictInt


class Rect(GeometryModel):
    x: StrictInt
    y: StrictInt
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)

    @property
    def left(self) -> int: return self.x
    @property
    def top(self) -> int: return self.y
    @property
    def right(self) -> int: return self.x + self.width
    @property
    def bottom(self) -> int: return self.y + self.height
    @property
    def center(self) -> Point: return Point(x=self.x + self.width // 2, y=self.y + self.height // 2)

    def contains_point(self, point: Point, *, inclusive: bool = True) -> bool:
        if inclusive:
            return self.left <= point.x <= self.right and self.top <= point.y <= self.bottom
        return self.left < point.x < self.right and self.top < point.y < self.bottom

    def contains_rect(self, other: "Rect", *, inclusive: bool = True) -> bool:
        if inclusive:
            return self.left <= other.left and self.top <= other.top and self.right >= other.right and self.bottom >= other.bottom
        return self.left < other.left and self.top < other.top and self.right > other.right and self.bottom > other.bottom

    def intersects(self, other: "Rect", *, touching: bool = False) -> bool:
        if touching:
            return not (self.right < other.left or other.right < self.left or self.bottom < other.top or other.bottom < self.top)
        return not (self.right <= other.left or other.right <= self.left or self.bottom <= other.top or other.bottom <= self.top)

    def intersection(self, other: "Rect") -> "Rect | None":
        left, top = max(self.left, other.left), max(self.top, other.top)
        right, bottom = min(self.right, other.right), min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return None
        return Rect(x=left, y=top, width=right-left, height=bottom-top)

    def expanded(self, amount: int) -> "Rect":
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise GeometryError("rectangle expansion must be a non-negative integer")
        return Rect(x=self.x-amount, y=self.y-amount, width=self.width+2*amount, height=self.height+2*amount)

    def translated(self, dx: int, dy: int) -> "Rect":
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (dx, dy)):
            raise GeometryError("rectangle translation must use integers")
        return Rect(x=self.x+dx, y=self.y+dy, width=self.width, height=self.height)


class Port(GeometryModel):
    edge_id: StableId
    node_id: StableId
    terminal: Literal["source", "target"]
    side: PortSide
    slot: StrictInt = Field(ge=0)
    point: Point


class Segment(GeometryModel):
    start: Point
    end: Point

    @model_validator(mode="after")
    def is_nonzero_orthogonal(self) -> Self:
        if self.start == self.end: raise ValueError("segment cannot have zero length")
        if self.start.x != self.end.x and self.start.y != self.end.y: raise ValueError("segment must be orthogonal")
        return self

    @property
    def horizontal(self) -> bool: return self.start.y == self.end.y
    @property
    def vertical(self) -> bool: return self.start.x == self.end.x
    @property
    def length(self) -> int: return abs(self.end.x-self.start.x)+abs(self.end.y-self.start.y)

    def intersects_rect(self, rect: Rect, *, allow_boundary: bool = False) -> bool:
        if self.horizontal:
            low, high = sorted((self.start.x, self.end.x))
            if allow_boundary: return rect.top < self.start.y < rect.bottom and low < rect.right and high > rect.left
            return rect.top <= self.start.y <= rect.bottom and low <= rect.right and high >= rect.left
        low, high = sorted((self.start.y, self.end.y))
        if allow_boundary: return rect.left < self.start.x < rect.right and low < rect.bottom and high > rect.top
        return rect.left <= self.start.x <= rect.right and low <= rect.bottom and high >= rect.top


class EdgeRoute(GeometryModel):
    edge_id: StableId
    source_port: Port
    target_port: Port
    points: tuple[Point, ...] = Field(min_length=2)
    segments: tuple[Segment, ...] = ()
    feedback: StrictBool = False
    bends: StrictInt = Field(default=0, ge=0)
    total_length: StrictInt = Field(default=0, ge=0)

    @model_validator(mode="after")
    def derive_and_validate_segments(self) -> Self:
        if self.source_port.edge_id != self.edge_id or self.target_port.edge_id != self.edge_id: raise ValueError(f"route {self.edge_id!r} ports must reference the route edge")
        if self.source_port.terminal != "source" or self.target_port.terminal != "target": raise ValueError(f"route {self.edge_id!r} has reversed terminal port kinds")
        if self.points[0] != self.source_port.point or self.points[-1] != self.target_port.point: raise ValueError(f"route {self.edge_id!r} points must begin and end at assigned ports")
        derived = tuple(Segment(start=a, end=b) for a,b in zip(self.points, self.points[1:]))
        if self.segments and self.segments != derived: raise ValueError(f"route {self.edge_id!r} segments do not match points")
        object.__setattr__(self,"segments",derived); object.__setattr__(self,"bends",max(0,len(derived)-1)); object.__setattr__(self,"total_length",sum(s.length for s in derived))
        return self


class NodePlacement(GeometryModel):
    node_id: StableId
    group_id: StableId | None = None
    rank: StrictInt = Field(ge=0)
    order: StrictInt = Field(ge=0)
    rect: Rect
    label_lines: tuple[StrictStr, ...] = Field(min_length=1)


class GroupPlacement(GeometryModel):
    group_id: StableId
    parent_id: StableId | None = None
    label: StrictStr
    rect: Rect
    header_rect: Rect
    client_rect: Rect

    @model_validator(mode="after")
    def validate_parts(self) -> Self:
        if not self.rect.contains_rect(self.header_rect) or not self.rect.contains_rect(self.client_rect): raise ValueError(f"group {self.group_id!r} header/client must be inside its rectangle")
        if self.header_rect.intersects(self.client_rect): raise ValueError(f"group {self.group_id!r} header and client area overlap")
        return self


class EdgeLabelPlacement(GeometryModel):
    edge_id: StableId
    text: StrictStr
    lines: tuple[StrictStr, ...] = Field(min_length=1)
    rect: Rect
    segment_index: StrictInt = Field(ge=0)


class Canvas(GeometryModel):
    x: StrictInt = 0
    y: StrictInt = 0
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)
    @property
    def rect(self) -> Rect: return Rect(x=self.x,y=self.y,width=self.width,height=self.height)


class LayoutMetrics(GeometryModel):
    node_count: StrictInt = Field(ge=0)
    group_count: StrictInt = Field(ge=0)
    edge_count: StrictInt = Field(ge=0)
    feedback_edge_count: StrictInt = Field(ge=0)
    total_bends: StrictInt = Field(ge=0)
    maximum_bends: StrictInt = Field(ge=0)
    total_route_length: StrictInt = Field(ge=0)
    crossing_count: StrictInt = Field(default=0, ge=0)
    label_count: StrictInt = Field(default=0, ge=0)


class LayoutResult(GeometryModel):
    engine_id: Literal["internal-layered-v1"] = "internal-layered-v1"
    diagram_id: StableId
    canvas: Canvas
    groups: tuple[GroupPlacement, ...] = ()
    nodes: tuple[NodePlacement, ...] = ()
    routes: tuple[EdgeRoute, ...] = ()
    labels: tuple[EdgeLabelPlacement, ...] = ()
    metrics: LayoutMetrics
    decisions: tuple[StrictStr, ...] = ()
    warnings: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def canonicalize_and_validate_references(self) -> Self:
        groups=tuple(sorted(self.groups,key=lambda v:v.group_id)); nodes=tuple(sorted(self.nodes,key=lambda v:v.node_id)); routes=tuple(sorted(self.routes,key=lambda v:v.edge_id)); labels=tuple(sorted(self.labels,key=lambda v:v.edge_id))
        self._unique("group",[v.group_id for v in groups]); self._unique("node",[v.node_id for v in nodes]); self._unique("route",[v.edge_id for v in routes]); self._unique("label",[v.edge_id for v in labels])
        group_ids={v.group_id for v in groups}; node_ids={v.node_id for v in nodes}; route_ids={v.edge_id for v in routes}
        for group in groups:
            if group.parent_id is not None and group.parent_id not in group_ids: raise ValueError(f"group placement {group.group_id!r} has missing parent {group.parent_id!r}")
        for node in nodes:
            if node.group_id is not None and node.group_id not in group_ids: raise ValueError(f"node placement {node.node_id!r} has missing group {node.group_id!r}")
        for route in routes:
            if route.source_port.node_id not in node_ids or route.target_port.node_id not in node_ids: raise ValueError(f"route {route.edge_id!r} references an unknown node")
        for label in labels:
            if label.edge_id not in route_ids: raise ValueError(f"label {label.edge_id!r} has no route")
        if self.metrics.node_count!=len(nodes) or self.metrics.group_count!=len(groups): raise ValueError("layout metric object counts do not match placements")
        if self.metrics.edge_count!=len(routes) or self.metrics.label_count!=len(labels): raise ValueError("layout metric edge/label counts do not match output")
        object.__setattr__(self,"groups",groups); object.__setattr__(self,"nodes",nodes); object.__setattr__(self,"routes",routes); object.__setattr__(self,"labels",labels); object.__setattr__(self,"decisions",tuple(sorted(set(self.decisions)))); object.__setattr__(self,"warnings",tuple(sorted(set(self.warnings))))
        return self

    @staticmethod
    def _unique(kind: str, values: list[str]) -> None:
        duplicates=sorted({value for value in values if values.count(value)>1})
        if duplicates: raise ValueError(f"duplicate {kind} IDs: {duplicates!r}")


def rect_axis_gaps(first: Rect, second: Rect) -> tuple[int, int]:
    return max(0, second.left-first.right, first.left-second.right), max(0, second.top-first.bottom, first.top-second.bottom)


def validate_placement_geometry(nodes: tuple[NodePlacement,...], groups: tuple[GroupPlacement,...], *, grid: int, minimum_horizontal: int, minimum_vertical: int, child_clearance: int, sibling_horizontal: int, sibling_vertical: int) -> None:
    failures: list[str]=[]
    for node in nodes:
        values=(node.rect.x,node.rect.y,node.rect.width,node.rect.height,node.rect.center.x,node.rect.center.y)
        if any(value % grid for value in values): failures.append(f"node {node.node_id} is not grid-aligned: {values!r}")
    for group in groups:
        for part_name,rect in (("rect",group.rect),("header",group.header_rect),("client",group.client_rect)):
            values=(rect.x,rect.y,rect.width,rect.height)
            if any(value % grid for value in values): failures.append(f"group {group.group_id} {part_name} is not grid-aligned: {values!r}")
    for first,second in combinations(nodes,2):
        if first.rect.intersects(second.rect): failures.append(f"node overlap: {first.node_id}/{second.node_id}")
        horizontal,vertical=rect_axis_gaps(first.rect,second.rect)
        vertical_overlap=not(first.rect.bottom<=second.rect.top or second.rect.bottom<=first.rect.top)
        horizontal_overlap=not(first.rect.right<=second.rect.left or second.rect.right<=first.rect.left)
        if vertical_overlap and horizontal<minimum_horizontal: failures.append(f"minimum horizontal spacing: {first.node_id}/{second.node_id}={horizontal}<{minimum_horizontal}")
        if horizontal_overlap and vertical<minimum_vertical: failures.append(f"minimum vertical spacing: {first.node_id}/{second.node_id}={vertical}<{minimum_vertical}")
    group_by_id={g.group_id:g for g in groups}
    for node in nodes:
        if any(node.rect.intersects(g.header_rect) for g in groups): failures.append(f"node {node.node_id} intersects a group header")
        if node.group_id is not None:
            group=group_by_id[node.group_id]
            if not group.client_rect.contains_rect(node.rect): failures.append(f"node {node.node_id} is clipped by group {group.group_id}")
            if node.rect.top-group.client_rect.top<child_clearance: failures.append(f"node {node.node_id} lacks header child clearance in {group.group_id}")
    for group in groups:
        if group.parent_id is not None and not group_by_id[group.parent_id].client_rect.contains_rect(group.rect): failures.append(f"group {group.group_id} is clipped by parent {group.parent_id}")
    for first,second in combinations(groups,2):
        if first.parent_id!=second.parent_id: continue
        if first.rect.intersects(second.rect): failures.append(f"sibling group overlap: {first.group_id}/{second.group_id}")
        h,v=rect_axis_gaps(first.rect,second.rect)
        if not (h >= sibling_horizontal or v >= sibling_vertical):
            failures.append(
                f"sibling spacing: {first.group_id}/{second.group_id} horizontal={h}<{sibling_horizontal} "
                f"and vertical={v}<{sibling_vertical}"
            )
    if failures: raise GeometryError("hard placement geometry failure:\n"+"\n".join(sorted(set(failures))))


def terminal_segment_is_outward(
    segment: Segment, port: Port, rect: Rect, *, source: bool
) -> bool:
    """Validate a terminal segment as boundary contact followed by exterior travel."""

    point = segment.start if source else segment.end
    exterior = segment.end if source else segment.start
    if point != port.point:
        return False
    if port.side is PortSide.EAST:
        return point.x == rect.right and rect.top <= point.y <= rect.bottom and exterior.y == point.y and exterior.x > point.x
    if port.side is PortSide.WEST:
        return point.x == rect.left and rect.top <= point.y <= rect.bottom and exterior.y == point.y and exterior.x < point.x
    if port.side is PortSide.NORTH:
        return point.y == rect.top and rect.left <= point.x <= rect.right and exterior.x == point.x and exterior.y < point.y
    return point.y == rect.bottom and rect.left <= point.x <= rect.right and exterior.x == point.x and exterior.y > point.y


def validate_routed_geometry(nodes: tuple[NodePlacement,...], groups: tuple[GroupPlacement,...], routes: tuple[EdgeRoute,...], labels: tuple[EdgeLabelPlacement,...], *, grid: int) -> None:
    failures: list[str]=[]; node_by_id={n.node_id:n for n in nodes}
    for route in routes:
        if any(point.x%grid or point.y%grid for point in route.points): failures.append(f"route {route.edge_id} has off-grid points")
        if route.source_port.point.x%grid or route.source_port.point.y%grid or route.target_port.point.x%grid or route.target_port.point.y%grid: failures.append(f"route {route.edge_id} has off-grid ports")
        for index,segment in enumerate(route.segments):
            source_terminal = node_by_id[route.source_port.node_id]
            target_terminal = node_by_id[route.target_port.node_id]
            if index == 0 and not terminal_segment_is_outward(
                segment, route.source_port, source_terminal.rect, source=True
            ):
                failures.append(f"illegal source terminal segment: {route.edge_id}")
            if index == len(route.segments)-1 and not terminal_segment_is_outward(
                segment, route.target_port, target_terminal.rect, source=False
            ):
                failures.append(f"illegal target terminal segment: {route.edge_id}")
            for node in nodes:
                legal=(node.node_id==route.source_port.node_id and index==0) or (node.node_id==route.target_port.node_id and index==len(route.segments)-1)
                if not legal and segment.intersects_rect(node.rect): failures.append(f"edge-node intersection: {route.edge_id}/{node.node_id}/segment-{index}")
            for group in groups:
                if segment.intersects_rect(group.header_rect): failures.append(f"edge-header intersection: {route.edge_id}/{group.group_id}/segment-{index}")
    for first,second in combinations(labels,2):
        if first.rect.intersects(second.rect,touching=True): failures.append(f"label overlap: {first.edge_id}/{second.edge_id}")
    for label in labels:
        if any(label.rect.intersects(node.rect,touching=True) for node in nodes): failures.append(f"label-node overlap: {label.edge_id}")
        if any(label.rect.intersects(group.header_rect,touching=True) for group in groups): failures.append(f"label-header overlap: {label.edge_id}")
        for route in routes:
            if any(segment.intersects_rect(label.rect) for segment in route.segments): failures.append(f"label-route overlap: {label.edge_id}/{route.edge_id}")
    if failures: raise GeometryError("hard routed geometry failure:\n"+"\n".join(sorted(set(failures))))


__all__=["Canvas","EdgeLabelPlacement","EdgeRoute","GeometryError","GeometryModel","GroupPlacement","LayoutMetrics","LayoutResult","NodePlacement","Point","Port","Rect","Segment","rect_axis_gaps","terminal_segment_is_outward","validate_placement_geometry","validate_routed_geometry"]
