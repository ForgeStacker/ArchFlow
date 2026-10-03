"""Compatibility module for the deterministic internal layered layout engine.

The filename is retained for imports only.  No Graphviz executable or library is
invoked here; engine metadata always names ``internal-layered-v1``.
"""

from __future__ import annotations

from dataclasses import dataclass

from cloud_diagram.domain import AlignmentAxis, DiagramSpec, SemanticRole
from cloud_diagram.graph import DiagramGraph, NodeOrdering, RankAssignment
from cloud_diagram.rules import RuleSet

from .base import LayoutError
from .geometry import (
    Canvas,
    GeometryError,
    GroupPlacement,
    NodePlacement,
    Rect,
    rect_axis_gaps,
    validate_placement_geometry,
)


_EXTERNAL_ROLES = {
    SemanticRole.EXTERNAL_SOURCE,
    SemanticRole.EXTERNAL_SYSTEM,
    SemanticRole.EXTERNAL_SINK,
}


def _ceil_grid(value: int, grid: int) -> int:
    return ((value + grid - 1) // grid) * grid


def _floor_grid(value: int, grid: int) -> int:
    return (value // grid) * grid


def _even_grid(value: int, grid: int) -> int:
    return _ceil_grid(value, 2 * grid)


def _wrap(text: str, maximum: int, lines: int) -> tuple[str, ...]:
    words: list[str] = []
    for word in text.split():
        words.extend(
            [word] if len(word) <= maximum else
            [word[index:index + maximum] for index in range(0, len(word), maximum)]
        )
    if not words:
        words = [text[:maximum] or " "]
    output: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= maximum:
            current = candidate
        else:
            output.append(current)
            current = word
    if current:
        output.append(current)
    if len(output) > lines:
        output = output[:lines]
        last = output[-1]
        output[-1] = (last[:maximum - 1] + "…") if len(last) >= maximum else (last + "…")
    return tuple(output)


@dataclass(frozen=True, slots=True)
class LayeredPlacement:
    canvas: Canvas
    groups: tuple[GroupPlacement, ...]
    nodes: tuple[NodePlacement, ...]
    decisions: tuple[str, ...]
    warnings: tuple[str, ...] = ()


class DeterministicLayeredLayout:
    """Integer, grid-snapped, left-to-right internal layered placement."""

    engine_id = "internal-layered-v1"

    def place(
        self,
        graph: DiagramGraph,
        ranks: RankAssignment,
        ordering: NodeOrdering,
        spec: DiagramSpec,
        rules: RuleSet,
    ) -> LayeredPlacement:
        adjacency = sorted(
            group.id
            for group in graph.groups
            if group.group.placement is not None
            and group.group.placement.adjacent_to is not None
        )
        if adjacency:
            raise LayoutError(
                "unsupported group placement constraint adjacent_to for groups "
                f"{adjacency!r}; adjacency is rejected before geometry output"
            )

        grid = rules.ruleset.grid_size
        explicit_separation = max(
            (constraint.minimum_grid_units * grid for constraint in spec.constraints.separations),
            default=0,
        )
        rank_gap_base = _ceil_grid(
            max(rules.layout.rank_spacing.preferred, rules.layout.rank_spacing.minimum, explicit_separation),
            grid,
        )
        vertical_gap = _ceil_grid(
            max(
                rules.layout.component_spacing.preferred,
                rules.layout.component_spacing.minimum,
                rules.nodes.spacing.minimum_vertical,
                explicit_separation,
            ),
            grid,
        )
        rank_of = ranks.index
        position = ordering.position
        node_by_id = graph.node_index
        group_by_id = graph.group_index
        required_membership_ids = {
            constraint.node_id for constraint in spec.constraints.required_memberships
        }

        label_lines = {
            node.id: _wrap(
                node.node.label,
                rules.nodes.label.maximum_characters_per_line,
                rules.nodes.label.maximum_lines,
            )
            for node in graph.nodes
        }
        node_sizes: dict[str, tuple[int, int]] = {}
        for node in graph.nodes:
            lines = label_lines[node.id]
            text_width = max(len(line) for line in lines) * 8 + 2 * rules.nodes.label.horizontal_padding
            width = max(
                rules.nodes.box.minimum_width,
                max(rules.nodes.icon.width, text_width)
                + rules.nodes.box.internal_padding.left
                + rules.nodes.box.internal_padding.right,
            )
            width = min(width, rules.nodes.box.maximum_width)
            height = max(
                rules.nodes.box.minimum_height,
                rules.nodes.box.internal_padding.top
                + rules.nodes.icon.height
                + rules.nodes.label.icon_to_label_gap
                + len(lines) * rules.nodes.label.line_height
                + rules.nodes.box.internal_padding.bottom,
            )
            node_sizes[node.id] = (_even_grid(width, grid), _even_grid(height, grid))

        rank_ids = sorted({rank_of[node.id] for node in graph.nodes})
        rank_width = {
            rank: max(
                (node_sizes[node.id][0] for node in graph.nodes if rank_of[node.id] == rank),
                default=_even_grid(rules.nodes.box.minimum_width, grid),
            )
            for rank in rank_ids
        }
        x_by_rank: dict[int, int] = {}
        x_cursor = _ceil_grid(rules.canvas.margin.left, grid)
        previous_rank: int | None = None
        for rank in rank_ids:
            if previous_rank is not None:
                gap = rank_gap_base
                crossing_edges = [
                    edge for edge in graph.nonfeedback_edges
                    if rank_of[edge.source] <= previous_rank and rank_of[edge.target] >= rank
                ]
                if any(edge.edge.label for edge in crossing_edges):
                    gap = max(gap, _ceil_grid(rules.layout.rank_spacing.with_edge_label, grid))
                if any(
                    node_by_id[edge.source].parent_path != node_by_id[edge.target].parent_path
                    for edge in crossing_edges
                ):
                    gap = max(gap, _ceil_grid(rules.layout.rank_spacing.across_container_boundary, grid))
                x_cursor += rank_width[previous_rank] + gap
            x_by_rank[rank] = x_cursor
            previous_rank = rank

        children: dict[str | None, list[str]] = {None: []}
        for group in graph.groups:
            children.setdefault(group.group.parent_id, []).append(group.id)
            children.setdefault(group.id, [])
        for values in children.values():
            values.sort(
                key=lambda group_id: (
                    group_by_id[group_id].group.placement is None,
                    group_by_id[group_id].group.placement.order
                    if group_by_id[group_id].group.placement is not None
                    and group_by_id[group_id].group.placement.order is not None else 0,
                    group_by_id[group_id].parent_path,
                    group_id,
                )
            )

        effective_group: dict[str, str | None] = {}
        externalized: list[str] = []
        for node in graph.nodes:
            if node.node.role in _EXTERNAL_ROLES and node.id not in required_membership_ids:
                effective_group[node.id] = None
                if node.group_id is not None:
                    externalized.append(node.id)
            else:
                effective_group[node.id] = node.group_id

        direct_nodes: dict[str | None, list[str]] = {group.id: [] for group in graph.groups}
        direct_nodes[None] = []
        for node in graph.nodes:
            direct_nodes.setdefault(effective_group[node.id], []).append(node.id)
        for values in direct_nodes.values():
            values.sort(
                key=lambda node_id: (
                    rank_of[node_id],
                    node_by_id[node_id].node.role is SemanticRole.OBSERVABILITY,
                    position[node_id],
                    node_id,
                )
            )

        header = _ceil_grid(rules.containers.header.height, grid)
        nested_top = _ceil_grid(
            max(rules.containers.nested_padding.top, rules.containers.header.child_clearance), grid
        )
        nested_bottom = _ceil_grid(rules.containers.nested_padding.bottom, grid)
        sibling_gap = _ceil_grid(rules.containers.sibling_gap.vertical, grid)
        min_group_height = _ceil_grid(rules.containers.minimum_size.height, grid)
        max_node_height = max((height for _, height in node_sizes.values()), default=0)

        subtree_height: dict[str, int] = {}

        def measure(group_id: str) -> int:
            counts: dict[int, int] = {}
            for node_id in direct_nodes[group_id]:
                counts[rank_of[node_id]] = counts.get(rank_of[node_id], 0) + 1
            rows = max(counts.values(), default=0)
            direct_height = rows * max_node_height + max(0, rows - 1) * vertical_gap
            child_heights = [measure(child_id) for child_id in children[group_id]]
            child_total = sum(child_heights) + max(0, len(child_heights) - 1) * sibling_gap
            between = sibling_gap if direct_height and child_total else 0
            subtree_height[group_id] = max(
                min_group_height,
                header + nested_top + direct_height + between + child_total + nested_bottom,
            )
            return subtree_height[group_id]

        for root_id in children[None]:
            measure(root_id)

        ungrouped = direct_nodes[None]
        ungrouped_counts: dict[int, int] = {}
        for node_id in ungrouped:
            ungrouped_counts[rank_of[node_id]] = ungrouped_counts.get(rank_of[node_id], 0) + 1
        ungrouped_rows = max(ungrouped_counts.values(), default=0)
        ungrouped_height = ungrouped_rows * max_node_height + max(0, ungrouped_rows - 1) * vertical_gap
        root_top = _ceil_grid(rules.canvas.margin.top, grid)
        if ungrouped_height:
            root_top += ungrouped_height + _ceil_grid(
                max(sibling_gap, rules.structure.external_components.minimum_boundary_gap), grid
            )

        group_y: dict[str, tuple[int, int]] = {}
        node_y: dict[str, int] = {}

        def place_direct(node_ids: list[str], top: int) -> int:
            rank_counts: dict[int, int] = {}
            for node_id in node_ids:
                row = rank_counts.get(rank_of[node_id], 0)
                node_y[node_id] = top + row * (max_node_height + vertical_gap)
                rank_counts[rank_of[node_id]] = row + 1
            rows = max(rank_counts.values(), default=0)
            return rows * max_node_height + max(0, rows - 1) * vertical_gap

        place_direct(ungrouped, _ceil_grid(rules.canvas.margin.top, grid))

        def assign_group(group_id: str, top: int) -> None:
            group_y[group_id] = (top, subtree_height[group_id])
            cursor = top + header + nested_top
            used = place_direct(direct_nodes[group_id], cursor)
            if used:
                cursor += used
                if children[group_id]:
                    cursor += sibling_gap
            for child_id in children[group_id]:
                assign_group(child_id, cursor)
                cursor += subtree_height[child_id] + sibling_gap

        cursor = root_top
        for root_id in children[None]:
            assign_group(root_id, cursor)
            cursor += subtree_height[root_id] + sibling_gap

        for alignment in spec.constraints.alignments:
            ids = alignment.node_ids
            groups = {effective_group[node_id] for node_id in ids}
            if alignment.axis is AlignmentAxis.VERTICAL:
                rank_values = {rank_of[node_id] for node_id in ids}
                if len(rank_values) != 1:
                    raise LayoutError(
                        f"unsupported vertical alignment {ids!r}: nodes occupy different ranks {sorted(rank_values)!r}"
                    )
            else:
                if len(groups) != 1:
                    raise LayoutError(
                        f"unsupported horizontal alignment {ids!r}: nodes have different direct containers {sorted(str(v) for v in groups)!r}"
                    )
                if len({rank_of[node_id] for node_id in ids}) != len(ids):
                    raise LayoutError(
                        f"unsupported horizontal alignment {ids!r}: two aligned nodes share a rank and would overlap"
                    )
                target_center = max(node_y[node_id] + node_sizes[node_id][1] // 2 for node_id in ids)
                for node_id in ids:
                    node_y[node_id] = target_center - node_sizes[node_id][1] // 2

        rank_local_order = {
            node_id: index
            for _, node_ids in ordering.ranks
            for index, node_id in enumerate(node_ids)
        }
        provisional_nodes: dict[str, NodePlacement] = {}
        for node in graph.nodes:
            width, height = node_sizes[node.id]
            rank_left = x_by_rank[rank_of[node.id]]
            x = rank_left + _floor_grid((rank_width[rank_of[node.id]] - width) // 2, grid)
            provisional_nodes[node.id] = NodePlacement(
                node_id=node.id,
                group_id=effective_group[node.id],
                rank=rank_of[node.id],
                order=rank_local_order[node.id],
                rect=Rect(x=x, y=node_y[node.id], width=width, height=height),
                label_lines=label_lines[node.id],
            )

        pad_left = _ceil_grid(max(rules.containers.nested_padding.left, rules.containers.border_clearance.node), grid)
        pad_right = _ceil_grid(max(rules.containers.nested_padding.right, rules.containers.border_clearance.node), grid)
        min_group_width = _ceil_grid(rules.containers.minimum_size.width, grid)
        provisional_groups: dict[str, GroupPlacement] = {}

        def build_group(group_id: str) -> GroupPlacement:
            child_groups = [build_group(child_id) for child_id in children[group_id]]
            contents = [provisional_nodes[node_id].rect for node_id in direct_nodes[group_id]]
            contents.extend(group.rect for group in child_groups)
            top, height = group_y[group_id]
            label_width = _ceil_grid(
                len(group_by_id[group_id].group.label) * 8
                + rules.containers.header.label_left_padding
                + rules.containers.header.label_right_padding,
                grid,
            )
            required_width = max(min_group_width, label_width)
            if contents:
                left = _floor_grid(min(rect.left for rect in contents) - pad_left, grid)
                right = _ceil_grid(max(rect.right for rect in contents) + pad_right, grid)
            else:
                left = x_by_rank[rank_ids[0]] if rank_ids else _ceil_grid(rules.canvas.margin.left, grid)
                right = left + required_width
            width = max(required_width, right - left)
            if width > right - left:
                left = _floor_grid(left - (width - (right - left)) // 2, grid)
            width = _ceil_grid(width, grid)
            rect = Rect(x=left, y=top, width=width, height=height)
            placement = GroupPlacement(
                group_id=group_id,
                parent_id=group_by_id[group_id].group.parent_id,
                label=group_by_id[group_id].group.label,
                rect=rect,
                header_rect=Rect(x=left, y=top, width=width, height=header),
                client_rect=Rect(x=left, y=top + header, width=width, height=height - header),
            )
            provisional_groups[group_id] = placement
            return placement

        for root_id in children[None]:
            build_group(root_id)

        all_rects = [placement.rect for placement in provisional_nodes.values()]
        all_rects.extend(placement.rect for placement in provisional_groups.values())
        min_left = min((rect.left for rect in all_rects), default=0)
        min_top = min((rect.top for rect in all_rects), default=0)
        dx = max(0, _ceil_grid(rules.canvas.margin.left - min_left, grid))
        dy = max(0, _ceil_grid(rules.canvas.margin.top - min_top, grid))

        nodes = tuple(
            value.model_copy(update={"rect": value.rect.translated(dx, dy)})
            for value in sorted(provisional_nodes.values(), key=lambda item: item.node_id)
        )
        groups = tuple(
            value.model_copy(update={
                "rect": value.rect.translated(dx, dy),
                "header_rect": value.header_rect.translated(dx, dy),
                "client_rect": value.client_rect.translated(dx, dy),
            })
            for value in sorted(provisional_groups.values(), key=lambda item: item.group_id)
        )

        try:
            validate_placement_geometry(
                nodes,
                groups,
                grid=grid,
                minimum_horizontal=rules.nodes.spacing.minimum_horizontal,
                minimum_vertical=rules.nodes.spacing.minimum_vertical,
                child_clearance=rules.containers.header.child_clearance,
                sibling_horizontal=rules.containers.sibling_gap.horizontal,
                sibling_vertical=rules.containers.sibling_gap.vertical,
            )
        except GeometryError as exc:
            raise LayoutError(str(exc)) from exc

        placed_node = {node.node_id: node for node in nodes}
        for constraint in spec.constraints.separations:
            first, second = placed_node[constraint.first], placed_node[constraint.second]
            horizontal, vertical = rect_axis_gaps(first.rect, second.rect)
            required = constraint.minimum_grid_units * grid
            if max(horizontal, vertical) < required:
                raise LayoutError(
                    f"separation constraint {constraint.first}/{constraint.second} requires {required}px "
                    f"but placement provides horizontal={horizontal}px vertical={vertical}px"
                )
        for alignment in spec.constraints.alignments:
            centers = [placed_node[node_id].rect.center for node_id in alignment.node_ids]
            values = [point.y if alignment.axis is AlignmentAxis.HORIZONTAL else point.x for point in centers]
            if len(set(values)) != 1:
                raise LayoutError(f"{alignment.axis.value} alignment {alignment.node_ids!r} was not satisfied: {values!r}")

        final_rects = [value.rect for value in nodes] + [value.rect for value in groups]
        right = max((rect.right for rect in final_rects), default=0) + rules.canvas.margin.right
        bottom = max((rect.bottom for rect in final_rects), default=0) + rules.canvas.margin.bottom
        canvas_width = max(rules.canvas.minimum_width, _ceil_grid(right, grid))
        canvas_height = max(rules.canvas.minimum_height, _ceil_grid(bottom, grid))
        if canvas_width > rules.canvas.maximum_width or canvas_height > rules.canvas.maximum_height:
            raise LayoutError(
                f"layout requires {canvas_width}x{canvas_height}px, exceeding maximum "
                f"{rules.canvas.maximum_width}x{rules.canvas.maximum_height}px"
            )

        decisions = [
            f"actual layout engine={self.engine_id}",
            f"grid={grid}px; node dimensions use even grid multiples and ranks increase x",
            "nested groups measured top-down and bounded bottom-up",
            f"explicit constraints applied: alignments={len(spec.constraints.alignments)}, separations={len(spec.constraints.separations)}",
        ]
        if externalized:
            decisions.append(f"external-role policy moved nodes outside groups: {externalized!r}")
        if required_membership_ids:
            decisions.append(f"required membership overrides external-role policy for {sorted(required_membership_ids)!r}")
        return LayeredPlacement(
            canvas=Canvas(width=canvas_width, height=canvas_height),
            groups=groups,
            nodes=nodes,
            decisions=tuple(decisions),
        )


__all__ = ["DeterministicLayeredLayout", "LayeredPlacement"]
