"""Strict immutable models for the complete cloud architecture rules document."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_serializer,
    model_validator,
)

PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveFloat = Annotated[StrictFloat, Field(gt=0)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0)]


class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    @model_serializer(mode="wrap")
    def omit_absent_values(self, handler: object) -> object:
        serialized = handler(self)  # type: ignore[operator]
        return {key: value for key, value in serialized.items() if value is not None}


class Box4(RuleModel):
    top: NonNegativeInt
    right: NonNegativeInt
    bottom: NonNegativeInt
    left: NonNegativeInt


class Size2(RuleModel):
    width: PositiveInt
    height: PositiveInt


class Gap2(RuleModel):
    horizontal: NonNegativeInt
    vertical: NonNegativeInt


class RulesetMetadata(RuleModel):
    id: StrictStr
    version: StrictStr
    description: StrictStr
    deterministic: Literal[True]
    coordinate_unit: Literal["px"]
    grid_size: PositiveInt
    random_seed: NonNegativeInt


class CanvasRules(RuleModel):
    background: StrictStr
    adaptive_colors: StrictBool
    margin: Box4
    minimum_width: PositiveInt
    minimum_height: PositiveInt
    maximum_width: PositiveInt
    maximum_height: PositiveInt
    expand_only: StrictBool
    snap_all_geometry_to_grid: StrictBool

    @model_validator(mode="after")
    def dimensions_are_ordered(self) -> "CanvasRules":
        if self.minimum_width > self.maximum_width or self.minimum_height > self.maximum_height:
            raise ValueError("canvas minimum dimensions cannot exceed maximum dimensions")
        return self


class RankPolicy(RuleModel):
    external_source: NonNegativeInt
    entrypoint: NonNegativeInt
    gateway: NonNegativeInt
    frontend: NonNegativeInt
    service: NonNegativeInt
    worker: NonNegativeInt
    asynchronous_boundary: NonNegativeInt
    cache: NonNegativeInt
    datastore: NonNegativeInt
    analytics: NonNegativeInt
    external_sink: NonNegativeInt


class FlowRules(RuleModel):
    default_direction: Literal["left_to_right"]
    direction_locked: Literal[True]
    allowed_directions: tuple[Literal["left_to_right"], ...]
    reject_non_left_to_right: Literal[True]
    rank_policy: RankPolicy
    same_rank_roles: tuple[tuple[StrictStr, ...], ...]
    stable_tie_breakers: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def only_left_to_right(self) -> "FlowRules":
        if self.allowed_directions != ("left_to_right",):
            raise ValueError("allowed_directions must contain only 'left_to_right'")
        return self


class IconRules(RuleModel):
    width: PositiveInt
    height: PositiveInt
    preserve_aspect_ratio: StrictBool
    maximum_upscale_factor: PositiveFloat


class NodeBoxRules(RuleModel):
    minimum_width: PositiveInt
    minimum_height: PositiveInt
    maximum_width: PositiveInt
    internal_padding: Box4

    @model_validator(mode="after")
    def width_is_ordered(self) -> "NodeBoxRules":
        if self.minimum_width > self.maximum_width:
            raise ValueError("node minimum_width cannot exceed maximum_width")
        return self


class NodeLabelRules(RuleModel):
    position: Literal["below_icon"]
    maximum_lines: PositiveInt
    maximum_characters_per_line: PositiveInt
    line_height: PositiveInt
    icon_to_label_gap: NonNegativeInt
    horizontal_padding: NonNegativeInt
    overflow: Literal["grow_node_then_wrap"]


class BadgeRules(RuleModel):
    maximum_count: NonNegativeInt
    size: PositiveInt
    gap: NonNegativeInt
    node_clearance: NonNegativeInt


class NodeSpacingRules(RuleModel):
    minimum_horizontal: NonNegativeInt
    minimum_vertical: NonNegativeInt
    preferred_horizontal: NonNegativeInt
    preferred_vertical: NonNegativeInt
    same_service_replica_gap: NonNegativeInt
    unrelated_component_gap: NonNegativeInt


class AlignmentRules(RuleModel):
    snap_centers_to_grid: StrictBool
    align_peer_centers: StrictBool
    maximum_peer_drift: NonNegativeInt


class NodeRules(RuleModel):
    icon: IconRules
    box: NodeBoxRules
    label: NodeLabelRules
    badges: BadgeRules
    spacing: NodeSpacingRules
    alignment: AlignmentRules


class ContainerHeaderRules(RuleModel):
    height: PositiveInt
    label_left_padding: NonNegativeInt
    label_right_padding: NonNegativeInt
    child_clearance: NonNegativeInt
    edge_exclusion_zone: StrictBool


class BorderClearanceRules(RuleModel):
    node: NonNegativeInt
    edge_parallel: NonNegativeInt
    edge_crossing: NonNegativeInt


class ContainerBehaviorRules(RuleModel):
    child_must_be_inside_client_area: StrictBool
    prohibit_header_overlap: StrictBool
    prohibit_sibling_overlap: StrictBool
    grow_to_fit_children: StrictBool
    never_shrink_below_minimum: StrictBool
    preserve_semantic_nesting: StrictBool
    flatten_single_child_service_group: StrictBool
    flatten_provider_boundaries: StrictBool


class ContainerRules(RuleModel):
    hierarchy: tuple[StrictStr, ...]
    header: ContainerHeaderRules
    padding: Box4
    nested_padding: Box4
    sibling_gap: Gap2
    minimum_size: Size2
    border_clearance: BorderClearanceRules
    rules: ContainerBehaviorRules


class RankSpacingRules(RuleModel):
    minimum: PositiveInt
    preferred: PositiveInt
    with_edge_label: PositiveInt
    across_container_boundary: PositiveInt


class ComponentSpacingRules(RuleModel):
    minimum: PositiveInt
    preferred: PositiveInt


class CrossingPenalties(RuleModel):
    edge_crossing: NonNegativeInt
    node_overlap: NonNegativeInt
    container_title_intersection: NonNegativeInt
    reversed_primary_flow: NonNegativeInt
    additional_bend: NonNegativeInt
    route_length_per_grid_unit: NonNegativeInt


class CrossingMinimizationRules(RuleModel):
    enabled: StrictBool
    sweeps: PositiveInt
    stable_order: StrictBool
    penalties: CrossingPenalties


class CompactionRules(RuleModel):
    enabled: StrictBool
    maximum_iterations: NonNegativeInt
    preserve_minimum_spacing: StrictBool
    preserve_ranks: StrictBool
    preserve_container_hierarchy: StrictBool


class LayoutRules(RuleModel):
    primary_engine: Literal["graphviz"]
    optional_engine: Literal["elk"]
    strategy: Literal["layered"]
    phases: tuple[StrictStr, ...]
    rank_spacing: RankSpacingRules
    component_spacing: ComponentSpacingRules
    crossing_minimization: CrossingMinimizationRules
    compaction: CompactionRules


class PrimaryFlowPorts(RuleModel):
    source_side: Literal["east"]
    target_side: Literal["west"]
    prohibit_reverse_rank_progression: Literal[True]
    allow_reverse_only_for_classified_feedback: Literal[True]


class PreferredSide(RuleModel):
    preferred_side: Literal["north", "south", "east", "west"]


class FeedbackPorts(RuleModel):
    source_side: Literal["south"]
    target_side: Literal["south"]


class BidirectionalPorts(RuleModel):
    choose_shortest_opposed_sides: StrictBool


class SemanticPortOverrides(RuleModel):
    observability: PreferredSide
    management: PreferredSide
    feedback: FeedbackPorts
    bidirectional: BidirectionalPorts


class PortSharingRules(RuleModel):
    allow_same_port_for_parallel_edges: StrictBool
    allow_same_port_for_opposite_directions: StrictBool
    spread_fan_out_symmetrically: StrictBool
    spread_fan_in_symmetrically: StrictBool


class PortRules(RuleModel):
    assignment: Literal["deterministic_fixed_slots"]
    slots_per_side: PositiveInt
    corner_exclusion: NonNegativeInt
    minimum_port_gap: NonNegativeInt
    reserve_center_slot_for_primary_flow: StrictBool
    primary_flow: PrimaryFlowPorts
    semantic_overrides: SemanticPortOverrides
    allocation_order: tuple[StrictStr, ...]
    sharing: PortSharingRules


class RoutingClearanceRules(RuleModel):
    node: NonNegativeInt
    node_label: NonNegativeInt
    container_border: NonNegativeInt
    container_header: NonNegativeInt
    edge_label: NonNegativeInt
    arrowhead: NonNegativeInt


class SegmentRules(RuleModel):
    minimum_terminal_stub: NonNegativeInt
    minimum_middle_segment: NonNegativeInt
    preferred_middle_segment: NonNegativeInt
    snap_to_grid: StrictBool
    collapse_collinear_segments: StrictBool


class BendRules(RuleModel):
    maximum_normal_edge: Literal[5]
    maximum_feedback_edge: Literal[7]
    prohibit_bend_inside_label: StrictBool
    prohibit_consecutive_short_segments: StrictBool


class ParallelEdgeRules(RuleModel):
    minimum_gap: NonNegativeInt
    preferred_gap: NonNegativeInt
    use_distinct_lanes: StrictBool
    preserve_source_order: StrictBool


class ObstacleRules(RuleModel):
    avoid_nodes: StrictBool
    avoid_node_labels: StrictBool
    avoid_container_headers: StrictBool
    avoid_edge_labels: StrictBool
    avoid_unrelated_container_interiors: StrictBool
    allow_crossing_own_container_boundary: StrictBool


class CrossingRules(RuleModel):
    minimize: StrictBool
    prohibit_edge_node_crossing: StrictBool
    prohibit_edge_title_crossing: StrictBool
    residual_jump_style: Literal["arc"]
    residual_jump_size: NonNegativeInt
    report_every_crossing: StrictBool


class FeedbackEdgeRules(RuleModel):
    route: Literal["outer_perimeter"]
    perimeter_gap: NonNegativeInt
    stack_gap: NonNegativeInt
    preferred_side: Literal["south"]


class BoundaryEdgeRules(RuleModel):
    cross_border_perpendicularly: StrictBool
    minimum_perpendicular_run: NonNegativeInt
    consolidate_through_gateway: StrictBool
    gateway_threshold: PositiveInt


class FanoutRules(RuleModel):
    trunking_enabled: StrictBool
    minimum_edges_for_trunk: PositiveInt
    trunk_gap_from_source: NonNegativeInt
    branch_gap: NonNegativeInt
    require_same_semantic_kind: StrictBool


class SelfLoopRules(RuleModel):
    allowed: StrictBool
    preferred_side: Literal["south"]
    minimum_size: PositiveInt


class RoutingRules(RuleModel):
    type: Literal["orthogonal"]
    algorithm: Literal["obstacle_aware_manhattan"]
    rounded_corners: StrictBool
    corner_radius: NonNegativeInt
    clearance: RoutingClearanceRules
    segments: SegmentRules
    bends: BendRules
    parallel_edges: ParallelEdgeRules
    obstacles: ObstacleRules
    crossings: CrossingRules
    feedback_edges: FeedbackEdgeRules
    boundary_edges: BoundaryEdgeRules
    fanout: FanoutRules
    self_loops: SelfLoopRules


class EdgeLabelRules(RuleModel):
    maximum_characters: PositiveInt
    maximum_lines: PositiveInt
    padding_horizontal: NonNegativeInt
    padding_vertical: NonNegativeInt
    segment_offset: NonNegativeInt
    placement: Literal["longest_eligible_segment"]
    prefer_horizontal_segment: StrictBool
    minimum_segment_length: PositiveInt
    avoid_bends_by: NonNegativeInt
    avoid_arrowheads_by: NonNegativeInt
    background: StrictStr
    move_before_reroute: StrictBool


class ArrowheadRules(RuleModel):
    default: Literal["classic"]
    size: PositiveInt
    terminal_gap: NonNegativeInt


class EdgeStyle(RuleModel):
    description: StrictStr
    stroke_color: StrictStr
    stroke_width: PositiveInt
    dashed: StrictBool
    dash_pattern: StrictStr | None = None
    start_arrow: Literal["none", "classic", "open", "block"]
    start_fill: StrictBool | None = None
    end_arrow: Literal["none", "classic", "open", "block"]
    end_fill: StrictBool


class EdgeStyles(RuleModel):
    synchronous: EdgeStyle
    asynchronous: EdgeStyle
    data: EdgeStyle
    dependency: EdgeStyle
    bidirectional: EdgeStyle
    observability: EdgeStyle


class DirectionPolicy(RuleModel):
    require_arrow_for_directed_edge: StrictBool
    prohibit_arrow_for_association: StrictBool
    prohibit_implicit_bidirectionality: StrictBool
    split_bidirectional_when_labels_differ: StrictBool


class LabelingPolicy(RuleModel):
    omit_redundant_labels: StrictBool
    protocol_only_when_meaningful: StrictBool
    require_label_for_ambiguous_edge: StrictBool
    require_legend_when_multiple_nondefault_styles: StrictBool


class EdgeRules(RuleModel):
    default_kind: Literal["synchronous"]
    label: EdgeLabelRules
    arrowhead: ArrowheadRules
    styles: EdgeStyles
    drawio_base_style: StrictStr
    direction_policy: DirectionPolicy
    labeling_policy: LabelingPolicy


class ExternalComponentRules(RuleModel):
    place_outside_cloud_boundary: StrictBool
    minimum_boundary_gap: NonNegativeInt
    align_with_first_or_last_related_rank: StrictBool


class SharedServiceRules(RuleModel):
    prefer_single_shared_node: StrictBool
    duplicate_only_with_explicit_scope: StrictBool


class GatewayRules(RuleModel):
    insert_for_cross_boundary_fan_in: PositiveInt
    insert_for_cross_boundary_fan_out: PositiveInt
    place_on_traffic_side_of_boundary: StrictBool


class AvailabilityRules(RuleModel):
    distribute_replicas_across_zones: StrictBool
    align_equivalent_replicas: StrictBool
    minimum_zone_count_for_ha: PositiveInt


class DatastoreRules(RuleModel):
    place_after_writers: StrictBool
    keep_primary_and_replica_adjacent: StrictBool


class QueueRules(RuleModel):
    place_between_producers_and_consumers: StrictBool
    force_rank_boundary: StrictBool


class ObservabilityRules(RuleModel):
    place_below_primary_flow: StrictBool
    exclude_from_primary_rank_progression: StrictBool


class StructureRules(RuleModel):
    external_components: ExternalComponentRules
    shared_services: SharedServiceRules
    gateways: GatewayRules
    availability: AvailabilityRules
    datastores: DatastoreRules
    queues: QueueRules
    observability: ObservabilityRules


class AwsProfile(RuleModel):
    hierarchy: tuple[StrictStr, ...]
    public_private_subnet_separation: StrictBool


class AzureProfile(RuleModel):
    hierarchy: tuple[StrictStr, ...]
    resource_group_is_visual_container: StrictBool


class GcpProfile(RuleModel):
    hierarchy: tuple[StrictStr, ...]
    project_is_visual_container: StrictBool


class MixedCloudProfile(RuleModel):
    provider_boundaries_required: StrictBool
    intercloud_connections_use_gateway_nodes: StrictBool
    minimum_provider_boundary_gap: NonNegativeInt


class ProviderProfiles(RuleModel):
    aws: AwsProfile
    azure: AzureProfile
    gcp: GcpProfile
    mixed_cloud: MixedCloudProfile


class HardQualityGates(RuleModel):
    maximum_node_overlaps: Literal[0]
    maximum_node_title_intersections: Literal[0]
    maximum_edge_node_intersections_excluding_terminals: Literal[0]
    maximum_edge_title_intersections: Literal[0]
    maximum_label_overlaps: Literal[0]
    maximum_unresolved_icons: Literal[0]
    maximum_clipped_children: Literal[0]
    maximum_unsatisfied_minimum_spacing_rules: Literal[0]
    maximum_dangling_edges: Literal[0]
    maximum_geometry_drift_on_repeat_run: Literal[0]


class SoftQualityGates(RuleModel):
    maximum_crossings_per_10_edges: NonNegativeInt
    maximum_average_bends_per_edge: NonNegativeFloat
    maximum_average_route_stretch: NonNegativeFloat
    minimum_quality_score: NonNegativeInt


class ScoringPenalties(RuleModel):
    residual_crossing: NonNegativeInt
    bend_above_preferred: NonNegativeInt
    fallback_icon: NonNegativeInt
    long_edge_label: NonNegativeInt
    route_stretch_above_target: NonNegativeInt
    soft_spacing_violation: NonNegativeInt


class ScoringRules(RuleModel):
    start: NonNegativeInt
    penalties: ScoringPenalties


class QualityGateRules(RuleModel):
    hard: HardQualityGates
    soft: SoftQualityGates
    scoring: ScoringRules


class RepairRules(RuleModel):
    enabled: StrictBool
    maximum_iterations: NonNegativeInt
    deterministic: Literal[True]
    order: tuple[StrictStr, ...]
    prohibit_llm_geometry_repair: Literal[True]
    fail_if_hard_gate_remains: Literal[True]


class DiagnosticRules(RuleModel):
    include_effective_rules: StrictBool
    include_rule_trace: StrictBool
    include_icon_resolution: StrictBool
    include_node_geometry: StrictBool
    include_edge_ports: StrictBool
    include_edge_segments: StrictBool
    include_crossings: StrictBool
    include_repairs: StrictBool
    redact_secrets: Literal[True]


PrecedenceName = Literal[
    "global_defaults",
    "provider_profile",
    "template",
    "diagram_override",
    "explicit_user_constraint",
]
EXPECTED_PRECEDENCE: tuple[PrecedenceName, ...] = (
    "global_defaults",
    "provider_profile",
    "template",
    "diagram_override",
    "explicit_user_constraint",
)


class RuleSet(RuleModel):
    """The complete validated YAML document."""

    schema_version: Literal["1.0"]
    ruleset: RulesetMetadata
    precedence: tuple[PrecedenceName, ...]
    canvas: CanvasRules
    flow: FlowRules
    nodes: NodeRules
    containers: ContainerRules
    layout: LayoutRules
    ports: PortRules
    routing: RoutingRules
    edges: EdgeRules
    structure: StructureRules
    provider_profiles: ProviderProfiles
    quality_gates: QualityGateRules
    repair: RepairRules
    diagnostics: DiagnosticRules

    @model_validator(mode="after")
    def precedence_is_low_to_high(self) -> "RuleSet":
        if self.precedence != EXPECTED_PRECEDENCE:
            raise ValueError(f"precedence must be exactly low-to-high: {EXPECTED_PRECEDENCE!r}")
        return self


class MarginOverride(RuleModel):
    top: NonNegativeInt | None = None
    right: NonNegativeInt | None = None
    bottom: NonNegativeInt | None = None
    left: NonNegativeInt | None = None


class RuleOverrides(RuleModel):
    """Explicitly supported, unlocked tuning fields."""

    grid_size: PositiveInt | None = None
    canvas_margin: MarginOverride | None = None
    minimum_canvas_width: PositiveInt | None = None
    minimum_canvas_height: PositiveInt | None = None
    rank_spacing: PositiveInt | None = None
    component_spacing: PositiveInt | None = None
    crossing_sweeps: PositiveInt | None = None
    compaction_iterations: NonNegativeInt | None = None
    slots_per_side: PositiveInt | None = None
    routing_corner_radius: NonNegativeInt | None = None
    minimum_quality_score: NonNegativeInt | None = None
    repair_iterations: NonNegativeInt | None = None


__all__ = [
    "EXPECTED_PRECEDENCE",
    "MarginOverride",
    "PrecedenceName",
    "RuleModel",
    "RuleOverrides",
    "RuleSet",
]
