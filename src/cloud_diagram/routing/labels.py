"""Deterministic edge-label wrapping and route-aware placement."""

from __future__ import annotations

from dataclasses import dataclass

from cloud_diagram.graph import DiagramGraph
from cloud_diagram.layout.geometry import EdgeLabelPlacement, EdgeRoute, GroupPlacement, NodePlacement, Rect
from cloud_diagram.rules import RuleSet


class LabelPlacementError(ValueError):
    """Raised when a required edge label has no legal candidate."""


@dataclass(frozen=True, slots=True)
class LabelPlacementResult:
    labels: tuple[EdgeLabelPlacement, ...]
    diagnostics: tuple[str, ...] = ()


def _ceil_grid(value: int, grid: int) -> int:
    return ((value + grid - 1) // grid) * grid


def _snap(value: int, grid: int) -> int:
    return ((value + grid // 2) // grid) * grid


def _wrap(text: str, maximum: int, maximum_lines: int) -> tuple[str, ...]:
    words = [piece for word in text.split() for piece in (word[index:index+maximum] for index in range(0,len(word),maximum))]
    if not words: words=[text[:maximum] or " "]
    lines: list[str]=[]; current=""
    for word in words:
        candidate=word if not current else f"{current} {word}"
        if len(candidate)<=maximum: current=candidate
        else: lines.append(current); current=word
    if current: lines.append(current)
    if len(lines)>maximum_lines:
        lines=lines[:maximum_lines]; last=lines[-1]; lines[-1]=(last[:maximum-1]+"…") if len(last)>=maximum else last+"…"
    return tuple(lines)


def _ordered_centers(low: int, high: int, preferred: int, grid: int) -> tuple[int,...]:
    first=_ceil_grid(low,grid); values=range(first,high+1,grid)
    return tuple(sorted(values,key=lambda value:(abs(value-preferred),value)))


def place_edge_labels(
    graph: DiagramGraph,
    routes: tuple[EdgeRoute,...],
    nodes: tuple[NodePlacement,...],
    groups: tuple[GroupPlacement,...],
    rules: RuleSet,
) -> LabelPlacementResult:
    """Search deterministic positions along every eligible segment."""

    route_by_edge={route.edge_id:route for route in routes}
    static_rects=[(f"node:{node.node_id}",node.rect.expanded(rules.routing.clearance.node_label)) for node in nodes]
    static_rects.extend((f"header:{group.group_id}",group.header_rect.expanded(rules.routing.clearance.container_header)) for group in groups)
    labels: list[EdgeLabelPlacement]=[]; diagnostics: list[str]=[]; grid=rules.ruleset.grid_size; label_rules=rules.edges.label

    for graph_edge in graph.edges:
        text=graph_edge.edge.label
        if text is None: continue
        route=route_by_edge[graph_edge.id]
        lines=_wrap(text,label_rules.maximum_characters,label_rules.maximum_lines)
        width=_ceil_grid(max(len(line) for line in lines)*7+2*label_rules.padding_horizontal,grid)
        height=_ceil_grid(len(lines)*16+2*label_rules.padding_vertical,grid)
        indexed=list(enumerate(route.segments)); indexed.sort(key=lambda item:(0 if label_rules.prefer_horizontal_segment and item[1].horizontal else 1,-item[1].length,item[0]))
        placed: EdgeLabelPlacement|None=None; attempts=0
        occupied=static_rects+[(f"label:{label.edge_id}",label.rect.expanded(rules.routing.clearance.edge_label)) for label in labels]
        for segment_index,segment in indexed:
            axis_size=width if segment.horizontal else height
            bend_margin=_ceil_grid(label_rules.avoid_bends_by,grid)
            arrow_margin=_ceil_grid(label_rules.avoid_arrowheads_by if segment_index==len(route.segments)-1 else label_rules.avoid_bends_by,grid)
            low_axis=(min(segment.start.x,segment.end.x) if segment.horizontal else min(segment.start.y,segment.end.y))+bend_margin+axis_size//2
            high_axis=(max(segment.start.x,segment.end.x) if segment.horizontal else max(segment.start.y,segment.end.y))-arrow_margin-axis_size//2
            if segment.length<max(label_rules.minimum_segment_length,axis_size+bend_margin+arrow_margin) or low_axis>high_axis: continue
            preferred=(low_axis+high_axis)//2
            for center in _ordered_centers(low_axis,high_axis,preferred,grid):
                for direction in (-1,1):
                    for step in range(10):
                        attempts+=1; distance=_ceil_grid(label_rules.segment_offset+step*grid,grid)
                        if segment.horizontal:
                            x=_snap(center-width//2,grid); y=_snap(segment.start.y+direction*distance-(height if direction<0 else 0),grid)
                        else:
                            x=_snap(segment.start.x+direction*distance-(width if direction<0 else 0),grid); y=_snap(center-height//2,grid)
                        candidate=Rect(x=x,y=y,width=width,height=height)
                        if any(candidate.intersects(rect,touching=True) for _,rect in occupied): continue
                        if any(other_segment.intersects_rect(candidate) for other_route in routes for other_segment in other_route.segments): continue
                        placed=EdgeLabelPlacement(edge_id=graph_edge.id,text=text,lines=lines,rect=candidate,segment_index=segment_index)
                        break
                    if placed is not None: break
                if placed is not None: break
            if placed is not None: break
        if placed is None:
            raise LabelPlacementError(
                f"edge {graph_edge.id!r} label {text!r} is impossible to place without node/header/label/route overlap "
                f"after {attempts} candidates; segment_lengths={[segment.length for segment in route.segments]!r}"
            )
        labels.append(placed); diagnostics.append(f"edge {graph_edge.id}: label placed on segment {placed.segment_index} after {attempts} candidates")
    return LabelPlacementResult(labels=tuple(sorted(labels,key=lambda value:value.edge_id)),diagnostics=tuple(sorted(diagnostics)))


__all__=["LabelPlacementError","LabelPlacementResult","place_edge_labels"]
