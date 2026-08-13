from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, CoordinateFrame, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class FieldClass(StrEnum):
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    OPTIMIZATION_PREFERENCE = "OPTIMIZATION_PREFERENCE"
    EXECUTION_SETTING = "EXECUTION_SETTING"


class EnvironmentKind(StrEnum):
    SIMULATION = "SIMULATION"
    REAL = "REAL"


class AuthorizationStatus(StrEnum):
    SOFTWARE_SIMULATION_ONLY = "SOFTWARE_SIMULATION_ONLY"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


class ExecutionEligibility(StrEnum):
    STATIC_VALIDATE_ONLY = "STATIC_VALIDATE_ONLY"
    AUTOMATED_ACCELERATED = "AUTOMATED_ACCELERATED"
    OPERATOR_OBSERVED_REALTIME = "OPERATOR_OBSERVED_REALTIME"
    BOTH = "BOTH"


class LifecycleState(StrEnum):
    DEFINED_NOT_RUN = "DEFINED_NOT_RUN"
    READY = "READY"
    ACTIVE_DEVELOPMENT = "ACTIVE_DEVELOPMENT"
    BASELINED = "BASELINED"
    PROMOTED = "PROMOTED"
    BLOCKED = "BLOCKED"


class ImplementationStatus(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    PLANNED_NOT_EXECUTABLE = "PLANNED_NOT_EXECUTABLE"


class MissionCluster(StrEnum):
    BASIC_FLIGHT_AND_ROUTE_FOLLOWING = "BASIC_FLIGHT_AND_ROUTE_FOLLOWING"
    GEOMETRIC_CONFLICT_RESOLUTION = "GEOMETRIC_CONFLICT_RESOLUTION"
    CONSTRAINTS_AND_OPTIMIZATION = "CONSTRAINTS_AND_OPTIMIZATION"
    COORDINATION_AND_ALLOCATION = "COORDINATION_AND_ALLOCATION"
    FAILURE_RECOVERY_AND_REPLANNING = "FAILURE_RECOVERY_AND_REPLANNING"


class PlannerStrategy(StrEnum):
    DIRECT = "DIRECT"
    GROUND_DELAY = "GROUND_DELAY"
    AIRBORNE_STAGING = "AIRBORNE_STAGING"
    SPEED_RETIMING = "SPEED_RETIMING"
    HORIZONTAL_DETOUR = "HORIZONTAL_DETOUR"
    VERTICAL_LAYER = "VERTICAL_LAYER"
    COMBINED_TIMING_GEOMETRY = "COMBINED_TIMING_GEOMETRY"


class ObjectiveMetric(StrEnum):
    PRIORITY_INVERSION = "PRIORITY_INVERSION"
    STARVATION = "STARVATION"
    MISSION_COMPLETION_TIME_S = "MISSION_COMPLETION_TIME_S"
    MAXIMUM_WAIT_S = "MAXIMUM_WAIT_S"
    TOTAL_ENERGY_PERCENT = "TOTAL_ENERGY_PERCENT"
    AIRBORNE_HOVER_TIME_S = "AIRBORNE_HOVER_TIME_S"
    PATH_LENGTH_M = "PATH_LENGTH_M"
    ACCELERATION_M_S2 = "ACCELERATION_M_S2"
    JERK_M_S3 = "JERK_M_S3"
    SEPARATION_ROBUSTNESS_M = "SEPARATION_ROBUSTNESS_M"
    BOUNDARY_ROBUSTNESS_M = "BOUNDARY_ROBUSTNESS_M"
    PATH_FIDELITY_M = "PATH_FIDELITY_M"
    REGION_CAPTURE_ERROR_M = "REGION_CAPTURE_ERROR_M"
    INTEGRATED_SQUARED_ACCELERATION_M2_S3 = "INTEGRATED_SQUARED_ACCELERATION_M2_S3"
    INTEGRATED_SQUARED_JERK_M2_S5 = "INTEGRATED_SQUARED_JERK_M2_S5"
    ENERGY_RESERVE_PERCENT = "ENERGY_RESERVE_PERCENT"
    AFFECTED_ROLE_COUNT = "AFFECTED_ROLE_COUNT"
    CUTOVER_LATENCY_S = "CUTOVER_LATENCY_S"


class MetricComparator(StrEnum):
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    EQUAL = "EQUAL"


class ClockMode(StrEnum):
    ACCELERATED = "ACCELERATED"
    REALTIME = "REALTIME"


class ReplanningAuthority(StrEnum):
    OPERATOR_APPROVAL_REQUIRED = "OPERATOR_APPROVAL_REQUIRED"
    AUTO_WITHIN_FROZEN_LIMITS = "AUTO_WITHIN_FROZEN_LIMITS"
    ABORT_ONLY = "ABORT_ONLY"


class RouteNodeMode(StrEnum):
    """The behavior required at an authored route node."""

    FLY_THROUGH = "FLY_THROUGH"
    CAPTURE = "CAPTURE"
    CAPTURE_AND_HOLD = "CAPTURE_AND_HOLD"
    REVERSAL = "REVERSAL"


class ScenarioEventKind(StrEnum):
    GOAL_UPDATE = "GOAL_UPDATE"
    OBSTACLE_ADDED = "OBSTACLE_ADDED"
    OBSTACLE_MOVED = "OBSTACLE_MOVED"
    OBSTACLE_REMOVED = "OBSTACLE_REMOVED"
    PASSAGE_CLOSED = "PASSAGE_CLOSED"
    PASSAGE_OPENED = "PASSAGE_OPENED"
    PEER_TRAJECTORY_UPDATED = "PEER_TRAJECTORY_UPDATED"
    VEHICLE_DEGRADED = "VEHICLE_DEGRADED"
    BATTERY_DROP = "BATTERY_DROP"
    TELEMETRY_LOSS = "TELEMETRY_LOSS"
    VEHICLE_LOSS = "VEHICLE_LOSS"
    ASSIGNMENT_CONFLICT = "ASSIGNMENT_CONFLICT"
    ACKNOWLEDGEMENT_LOSS = "ACKNOWLEDGEMENT_LOSS"
    ABORT_REQUEST = "ABORT_REQUEST"


class ScenarioExpectedDisposition(StrEnum):
    ACCEPTED_UPDATE = "ACCEPTED_UPDATE"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_AUTHORITY = "REJECTED_AUTHORITY"
    BLOCKED_BUDGET = "BLOCKED_BUDGET"
    BLOCKED_INFEASIBLE = "BLOCKED_INFEASIBLE"
    SAFE_ROLE_RECOVERY = "SAFE_ROLE_RECOVERY"
    REJECTED_ASSIGNMENT_CONFLICT = "REJECTED_ASSIGNMENT_CONFLICT"
    ZERO_PARTIAL_COMMIT = "ZERO_PARTIAL_COMMIT"
    RESERVE_HANDOVER = "RESERVE_HANDOVER"
    COORDINATED_ABORT = "COORDINATED_ABORT"


class BehaviorOracleKind(StrEnum):
    ROUTE_NODES_CAPTURED = "ROUTE_NODES_CAPTURED"
    HOLD_DURATION = "HOLD_DURATION"
    NO_UNDECLARED_STOP = "NO_UNDECLARED_STOP"
    ALTITUDE_TRANSITION = "ALTITUDE_TRANSITION"
    CURVED_PATH = "CURVED_PATH"
    CLOSED_SHAPE = "CLOSED_SHAPE"
    DISTINCT_START_AND_LANDING = "DISTINCT_START_AND_LANDING"
    SYNCHRONIZED_ROUTE_START = "SYNCHRONIZED_ROUTE_START"
    MINIMUM_FLIGHT_OVERLAP = "MINIMUM_FLIGHT_OVERLAP"
    FORMATION_ERROR = "FORMATION_ERROR"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"
    BOUNDARY_MARGIN = "BOUNDARY_MARGIN"
    KEEP_OUT_AVOIDED = "KEEP_OUT_AVOIDED"
    NO_AIRBORNE_HOLD = "NO_AIRBORNE_HOLD"
    PRIORITY_PRECEDENCE = "PRIORITY_PRECEDENCE"
    CONSTRAINT_ENFORCED = "CONSTRAINT_ENFORCED"
    UNAFFECTED_ROLE_NONINTERFERENCE = "UNAFFECTED_ROLE_NONINTERFERENCE"
    EVENT_HANDLED = "EVENT_HANDLED"
    ACCEPTED_EVENT_GOALS_CAPTURED = "ACCEPTED_EVENT_GOALS_CAPTURED"


class OracleEvidenceSource(StrEnum):
    AUTHORED_ROUTE = "AUTHORED_ROUTE"
    PLANNER_PREDICTION = "PLANNER_PREDICTION"
    EXECUTION_TELEMETRY = "EXECUTION_TELEMETRY"
    EVENT_TRACE = "EVENT_TRACE"


class SpatialPoint(ContractModel):
    value_m: Vector3
    frame: CoordinateFrame


class Region3D(ContractModel):
    region_id: Identifier
    frame: Literal[CoordinateFrame.WORLD] = CoordinateFrame.WORLD
    minimum_m: Vector3
    maximum_m: Vector3

    @model_validator(mode="after")
    def ordered(self) -> Region3D:
        if not (
            self.minimum_m.x <= self.maximum_m.x
            and self.minimum_m.y <= self.maximum_m.y
            and self.minimum_m.z <= self.maximum_m.z
        ):
            raise ValueError("region minimum_m must not exceed maximum_m")
        return self

    @property
    def center_m(self) -> Vector3:
        return Vector3(
            x=(self.minimum_m.x + self.maximum_m.x) / 2.0,
            y=(self.minimum_m.y + self.maximum_m.y) / 2.0,
            z=(self.minimum_m.z + self.maximum_m.z) / 2.0,
        )

    def contains(self, point: Vector3, *, margin_m: float = 0.0) -> bool:
        return (
            self.minimum_m.x + margin_m <= point.x <= self.maximum_m.x - margin_m
            and self.minimum_m.y + margin_m <= point.y <= self.maximum_m.y - margin_m
            and self.minimum_m.z + margin_m <= point.z <= self.maximum_m.z - margin_m
        )


class RouteNodeIntent(ContractModel):
    region_id: Identifier
    mode: RouteNodeMode
    dwell_s: float = Field(default=0.0, ge=0.0, le=60.0)
    capture_tolerance_m: float = Field(default=0.08, gt=0.0, le=0.50)

    @model_validator(mode="after")
    def hold_contract(self) -> RouteNodeIntent:
        if self.mode is RouteNodeMode.CAPTURE_AND_HOLD and self.dwell_s <= 0.0:
            raise ValueError("CAPTURE_AND_HOLD route nodes require positive dwell_s")
        if self.mode is not RouteNodeMode.CAPTURE_AND_HOLD and self.dwell_s != 0.0:
            raise ValueError("dwell_s is only valid for CAPTURE_AND_HOLD route nodes")
        return self


class EnvironmentConstraints(ContractModel):
    keep_out_regions: tuple[Region3D, ...] = ()
    required_corridors: tuple[Region3D, ...] = ()


class CoordinationConstraints(ContractModel):
    synchronized_route_start_required: bool = False
    maximum_route_start_skew_s: float = Field(default=0.20, ge=0.0, le=10.0)
    minimum_simultaneous_flight_s: float = Field(default=0.0, ge=0.0, le=120.0)
    maximum_formation_error_m: float | None = Field(default=None, gt=0.0, le=2.0)
    formation_offsets_m: dict[Identifier, Vector3] = Field(default_factory=dict)
    formation_offsets_by_node_m: dict[Identifier, tuple[Vector3, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def formation_contract(self) -> CoordinationConstraints:
        if self.maximum_formation_error_m is None and (
            self.formation_offsets_m or self.formation_offsets_by_node_m
        ):
            raise ValueError("formation offsets require maximum_formation_error_m")
        if self.formation_offsets_m and self.formation_offsets_by_node_m:
            raise ValueError("use either fixed or per-node formation offsets, not both")
        active_offsets = self.formation_offsets_m or self.formation_offsets_by_node_m
        if self.maximum_formation_error_m is not None and len(active_offsets) < 2:
            raise ValueError("formation error requires offsets for at least two roles")
        node_lengths = {len(values) for values in self.formation_offsets_by_node_m.values()}
        if len(node_lengths) > 1 or 0 in node_lengths:
            raise ValueError("per-node formation offsets must have one shared positive length")
        return self


class ScenarioEvent(ContractModel):
    event_id: Identifier
    kind: ScenarioEventKind
    trigger_time_s: float = Field(gt=0.0, le=120.0)
    role_id: Identifier | None = None
    replacement_goal: Region3D | None = None
    battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    duration_s: float | None = Field(default=None, gt=0.0, le=60.0)
    source_id: Identifier = "campaign-scenario"
    sequence: int = Field(default=1, ge=1)
    generation: int = Field(default=1, ge=1)
    authenticated: bool = True
    acknowledgement_required: bool = False
    acknowledgement_received: bool = True
    update_identity: Identifier | None = None
    expected_disposition: ScenarioExpectedDisposition

    @model_validator(mode="after")
    def event_payload(self) -> ScenarioEvent:
        region_kinds = {
            ScenarioEventKind.GOAL_UPDATE,
            ScenarioEventKind.OBSTACLE_ADDED,
            ScenarioEventKind.OBSTACLE_MOVED,
            ScenarioEventKind.PASSAGE_CLOSED,
            ScenarioEventKind.PASSAGE_OPENED,
        }
        if self.kind in region_kinds and self.replacement_goal is None:
            raise ValueError(f"{self.kind.value} requires a region payload")
        if self.kind not in region_kinds and self.replacement_goal is not None:
            raise ValueError("replacement_goal/region is not valid for this event kind")
        if self.kind is ScenarioEventKind.OBSTACLE_REMOVED and self.update_identity is None:
            raise ValueError("OBSTACLE_REMOVED requires update_identity as the solid ID")
        environment_change_kinds = {
            ScenarioEventKind.OBSTACLE_ADDED,
            ScenarioEventKind.OBSTACLE_MOVED,
            ScenarioEventKind.OBSTACLE_REMOVED,
            ScenarioEventKind.PASSAGE_CLOSED,
            ScenarioEventKind.PASSAGE_OPENED,
        }
        if self.kind in environment_change_kinds and self.duration_s is None:
            raise ValueError(f"{self.kind.value} requires duration_s as source-time lead to effect")
        if self.kind is ScenarioEventKind.BATTERY_DROP and self.battery_percent is None:
            raise ValueError("BATTERY_DROP requires battery_percent")
        return self

    @property
    def environment_region(self) -> Region3D | None:
        """Typed alias for the v1 wire field retained for hash compatibility."""

        return self.replacement_goal


class BehaviorOracle(ContractModel):
    oracle_id: Identifier
    kind: BehaviorOracleKind
    evidence_source: OracleEvidenceSource
    role_ids: tuple[Identifier, ...] = ()
    threshold: float | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    required: bool = True

    @model_validator(mode="after")
    def threshold_unit_pair(self) -> BehaviorOracle:
        if (self.threshold is None) != (self.unit is None):
            raise ValueError("oracle threshold and unit must be provided together")
        return self


class CaseSemantics(ContractModel):
    """Executable mission meaning, independent of display labels and prose."""

    contract_version: Literal[1] = 1
    curriculum_level: int = Field(ge=1, le=5)
    learning_objective: str = Field(min_length=1, max_length=1000)
    difficulty_rationale: str = Field(min_length=1, max_length=1000)
    route_intent_by_role: dict[Identifier, tuple[RouteNodeIntent, ...]]
    environment_constraints: EnvironmentConstraints = EnvironmentConstraints()
    coordination_constraints: CoordinationConstraints = CoordinationConstraints()
    scenario_events: tuple[ScenarioEvent, ...] = ()
    behavior_oracles: tuple[BehaviorOracle, ...] = Field(min_length=1)
    semantic_baseline_case_id: Identifier | None = None
    intended_delta: str | None = Field(default=None, min_length=1, max_length=1000)


class MetricGate(ContractModel):
    metric_id: Identifier
    comparator: MetricComparator
    threshold: float
    unit: str = Field(min_length=1, max_length=40)


class DroneCase(ContractModel):
    role_id: Identifier
    start_region: Region3D
    goal_sequence: tuple[Region3D, ...] = Field(min_length=1)
    landing_region: Region3D
    initial_battery_percent: float = Field(default=100.0, ge=0.0, le=100.0)
    minimum_reserve_battery_percent: float = Field(default=20.0, ge=0.0, le=100.0)
    health: Literal["HEALTHY", "DEGRADED"] = "HEALTHY"
    priority: int = Field(default=100, ge=0, le=1000)
    roles: tuple[Identifier, ...] = ()
    required_capabilities: tuple[Identifier, ...] = ()
    available_capabilities: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def capabilities_and_reserve(self) -> DroneCase:
        if self.minimum_reserve_battery_percent > self.initial_battery_percent:
            raise ValueError("minimum battery reserve exceeds initial battery")
        missing = set(self.required_capabilities).difference(self.available_capabilities)
        if missing:
            raise ValueError(f"required capabilities unavailable: {sorted(missing)}")
        return self


class DynamicsLimits(ContractModel):
    maximum_horizontal_speed_m_s: float = Field(default=0.6, gt=0.0)
    maximum_vertical_speed_m_s: float = Field(default=0.4, gt=0.0)
    maximum_acceleration_m_s2: float = Field(default=1.0, gt=0.0)
    maximum_jerk_m_s3: float = Field(default=8.0, gt=0.0)
    stop_speed_threshold_m_s: float = Field(default=0.02, ge=0.0)
    unintended_stop_persistence_s: float = Field(default=0.20, gt=0.0)


class ModeComparisonTolerances(ContractModel):
    schema_version: Literal[1] = 1
    maximum_source_clock_target_error_difference_s: float = Field(default=0.10, ge=0.0)
    maximum_truth_path_length_difference_m: float = Field(default=0.10, ge=0.0)
    maximum_tracking_rms_difference_m: float = Field(default=0.02, ge=0.0)
    maximum_minimum_separation_difference_m: float = Field(default=0.10, ge=0.0)


class HardConstraints(ContractModel):
    flight_volume: Region3D
    warning_separation_m: float = Field(default=0.75, gt=0.0)
    critical_separation_m: float = Field(default=0.50, gt=0.0)
    position_uncertainty_m: float = Field(default=0.05, ge=0.0)
    dynamics: DynamicsLimits = DynamicsLimits()
    deadline_s: float = Field(default=120.0, gt=0.0)
    hover_allowed: bool = True
    maximum_hover_s: float = Field(default=60.0, ge=0.0)
    vertical_layers_allowed: bool = True
    synchronized_launch_required: bool = False
    maximum_unrequired_airborne_wait_s: float = Field(default=2.0, ge=0.0)
    maximum_equal_route_battery_spread_percent: float = Field(default=1.0, ge=0.0)
    minimum_realtime_factor: float = Field(default=0.80, gt=0.0, le=10.0)
    watchdog_guard_s: float = Field(default=2.0, ge=0.0)
    observation_freshness_limit_s: float = Field(default=0.25, gt=0.0)
    minimum_goal_update_interval_s: float = Field(default=0.50, gt=0.0)
    planning_budget_s: float = Field(default=2.0, gt=0.0, le=10.0)
    mode_comparison: ModeComparisonTolerances = ModeComparisonTolerances()

    @model_validator(mode="after")
    def separation_order(self) -> HardConstraints:
        if self.critical_separation_m >= self.warning_separation_m:
            raise ValueError("critical separation must be below warning separation")
        if not self.hover_allowed and self.maximum_hover_s != 0.0:
            raise ValueError("maximum_hover_s must be zero when hover is forbidden")
        return self


class SearchSettings(ContractModel):
    implementation_id: Identifier = "bounded-joint-candidate-planner"
    implementation_version: str = "1.0.0"
    prediction_step_s: float = Field(default=0.02, gt=0.0, le=0.02)
    maximum_candidate_count: int = Field(default=256, ge=1, le=4096)
    planning_budget_s: float = Field(default=5.0, gt=0.0, le=60.0)
    lateral_offsets_m: tuple[float, ...] = (0.20, -0.20, 0.35, -0.35)
    arc_radii_m: tuple[float, ...] = (0.20, 0.35)
    vertical_offsets_m: tuple[float, ...] = (0.20, -0.20)
    speed_factors: tuple[float, ...] = (0.80, 1.20)
    delay_grid_s: tuple[float, ...] = (2.0, 4.0, 8.0, 12.0, 24.0, 40.0)

    @model_validator(mode="after")
    def bounded_grids(self) -> SearchSettings:
        grids = (
            self.lateral_offsets_m,
            self.arc_radii_m,
            self.vertical_offsets_m,
            self.speed_factors,
            self.delay_grid_s,
        )
        if any(not grid or len(grid) > 16 for grid in grids):
            raise ValueError("candidate parameter grids must contain 1..16 values")
        if any(value <= 0.0 for value in self.arc_radii_m + self.speed_factors):
            raise ValueError("arc radii and speed factors must be positive")
        if any(value < 0.0 for value in self.delay_grid_s):
            raise ValueError("delay grid must be non-negative")
        return self


class ExecutionSettings(ContractModel):
    seed: int = Field(default=42, ge=0)
    repetitions: int = Field(default=1, ge=1, le=100)
    clock_modes: tuple[ClockMode, ...] = (ClockMode.ACCELERATED, ClockMode.REALTIME)
    backend_profile_id: Identifier = "fast-sim-v1"
    noise_latency_profile_id: Identifier = "nominal-v1"
    evidence_profile_id: Identifier = "complete-evidence-v1"
    configuration_sha256: SHA256 = "0" * 64
    playback_buffer_s: float = Field(default=0.25, ge=0.0, le=5.0)
    maximum_interpolation_gap_s: float = Field(default=0.20, gt=0.0, le=5.0)
    maximum_extrapolation_s: float = Field(default=0.10, ge=0.0, le=1.0)


class CampaignCase(ContractModel):
    schema_version: Literal[2] = 2
    case_id: Identifier
    template_id: Identifier
    cluster: MissionCluster
    family: Identifier
    variation_name: Identifier
    parent_case_sha256: SHA256 | None = None
    baseline_sha256: SHA256 | None = None
    purpose: str = Field(min_length=1, max_length=1000)
    behavior_under_test: str = Field(min_length=1, max_length=1000)
    expected_outcome: str = Field(min_length=1, max_length=1000)
    environment: EnvironmentKind
    authorization: AuthorizationStatus
    implementation_status: ImplementationStatus = ImplementationStatus.EXECUTABLE
    implementation_milestone: Identifier | None = None
    drone_count: int = Field(ge=1, le=3)
    drones: tuple[DroneCase, ...] = Field(min_length=1, max_length=3)
    hard_constraints: HardConstraints
    allowed_strategies: tuple[PlannerStrategy, ...] = Field(min_length=1)
    objective_order: tuple[ObjectiveMetric, ...] = Field(min_length=1)
    expected_decisions: tuple[Identifier, ...] = Field(min_length=1)
    pass_fail_metrics: tuple[MetricGate, ...] = Field(min_length=1)
    execution_eligibility: ExecutionEligibility
    operator_observation_questions: tuple[str, ...] = Field(min_length=1)
    difficulty: int = Field(ge=1, le=10)
    prerequisites: tuple[Identifier, ...] = ()
    claim_boundary: str = Field(min_length=1, max_length=1000)
    named_variations: tuple[Identifier, ...] = Field(min_length=1)
    search: SearchSettings = SearchSettings()
    execution: ExecutionSettings = ExecutionSettings()
    replanning_authority: ReplanningAuthority = ReplanningAuthority.ABORT_ONLY
    semantics: CaseSemantics | None = None
    field_classification: dict[str, FieldClass] = Field(
        default_factory=lambda: {
            "hard_constraints": FieldClass.HARD_CONSTRAINT,
            "allowed_strategies": FieldClass.HARD_CONSTRAINT,
            "objective_order": FieldClass.OPTIMIZATION_PREFERENCE,
            "search": FieldClass.EXECUTION_SETTING,
            "execution": FieldClass.EXECUTION_SETTING,
        }
    )

    @model_validator(mode="after")
    def complete_and_safe(self) -> CampaignCase:
        if len(self.drones) != self.drone_count:
            raise ValueError("drone_count does not match drones")
        role_ids = tuple(drone.role_id for drone in self.drones)
        if len(set(role_ids)) != len(role_ids):
            raise ValueError("drone role IDs must be unique")
        if len(set(self.allowed_strategies)) != len(self.allowed_strategies):
            raise ValueError("allowed strategies must be unique")
        if (
            PlannerStrategy.VERTICAL_LAYER in self.allowed_strategies
            or PlannerStrategy.COMBINED_TIMING_GEOMETRY in self.allowed_strategies
        ) and not self.hard_constraints.vertical_layers_allowed:
            raise ValueError("vertical strategy is unsupported when vertical layers are forbidden")
        if (
            self.implementation_status is ImplementationStatus.PLANNED_NOT_EXECUTABLE
            and self.execution_eligibility is not ExecutionEligibility.STATIC_VALIDATE_ONLY
        ):
            raise ValueError("planned campaign cases are static-validation only")
        if self.environment is EnvironmentKind.REAL:
            if self.authorization is not AuthorizationStatus.NOT_AUTHORIZED:
                raise ValueError("Real campaign mirrors must remain NOT_AUTHORIZED")
            if self.execution_eligibility is not ExecutionEligibility.STATIC_VALIDATE_ONLY:
                raise ValueError("unauthorized Real mirrors are static-validation only")
        required_classes = {
            "hard_constraints": FieldClass.HARD_CONSTRAINT,
            "allowed_strategies": FieldClass.HARD_CONSTRAINT,
            "objective_order": FieldClass.OPTIMIZATION_PREFERENCE,
            "search": FieldClass.EXECUTION_SETTING,
            "execution": FieldClass.EXECUTION_SETTING,
        }
        if any(
            self.field_classification.get(key) is not value
            for key, value in required_classes.items()
        ):
            raise ValueError("field classification cannot weaken a hard constraint")
        for drone in self.drones:
            points = (
                drone.start_region.center_m,
                *(goal.center_m for goal in drone.goal_sequence),
                drone.landing_region.center_m,
            )
            if any(not self.hard_constraints.flight_volume.contains(point) for point in points):
                raise ValueError(f"role {drone.role_id} geometry leaves the flight volume")
        if self.semantics is not None:
            semantic_roles = set(self.semantics.route_intent_by_role)
            if semantic_roles != set(role_ids):
                raise ValueError("route intent must cover every drone role exactly once")
            drone_by_role = {drone.role_id: drone for drone in self.drones}
            for role_id, nodes in self.semantics.route_intent_by_role.items():
                expected_regions = tuple(
                    region.region_id for region in drone_by_role[role_id].goal_sequence
                )
                actual_regions = tuple(node.region_id for node in nodes)
                if actual_regions != expected_regions:
                    raise ValueError(
                        f"route intent for {role_id} must match its ordered goal_sequence"
                    )
            referenced_roles = {
                role_id
                for event in self.semantics.scenario_events
                for role_id in (() if event.role_id is None else (event.role_id,))
            }
            referenced_roles.update(self.semantics.coordination_constraints.formation_offsets_m)
            referenced_roles.update(
                self.semantics.coordination_constraints.formation_offsets_by_node_m
            )
            referenced_roles.update(
                role_id for oracle in self.semantics.behavior_oracles for role_id in oracle.role_ids
            )
            unknown_roles = referenced_roles.difference(role_ids)
            if unknown_roles:
                raise ValueError(
                    f"semantic contract references unknown roles: {sorted(unknown_roles)}"
                )
            coordination = self.semantics.coordination_constraints
            formation_roles = set(
                coordination.formation_offsets_m or coordination.formation_offsets_by_node_m
            )
            if coordination.maximum_formation_error_m is not None and formation_roles != set(
                role_ids
            ):
                raise ValueError("formation offsets must cover every drone role exactly once")
            events = self.semantics.scenario_events
            if len({event.event_id for event in events}) != len(events):
                raise ValueError("scenario event IDs must be unique")
            if tuple(event.trigger_time_s for event in events) != tuple(
                sorted(event.trigger_time_s for event in events)
            ):
                raise ValueError("scenario events must be ordered by trigger_time_s")
            semantic_regions = (
                *self.semantics.environment_constraints.keep_out_regions,
                *self.semantics.environment_constraints.required_corridors,
                *(
                    event.replacement_goal
                    for event in self.semantics.scenario_events
                    if event.replacement_goal is not None
                ),
            )
            for region in semantic_regions:
                if not (
                    self.hard_constraints.flight_volume.contains(region.minimum_m)
                    and self.hard_constraints.flight_volume.contains(region.maximum_m)
                ):
                    raise ValueError(f"semantic region {region.region_id} leaves the flight volume")
            environment_change_kinds = {
                ScenarioEventKind.OBSTACLE_ADDED,
                ScenarioEventKind.OBSTACLE_MOVED,
                ScenarioEventKind.OBSTACLE_REMOVED,
                ScenarioEventKind.PASSAGE_CLOSED,
                ScenarioEventKind.PASSAGE_OPENED,
            }
            for event in events:
                if (
                    event.kind in environment_change_kinds
                    and event.expected_disposition is ScenarioExpectedDisposition.ACCEPTED_UPDATE
                    and (
                        event.duration_s is None
                        or event.duration_s < self.hard_constraints.planning_budget_s + 0.10
                    )
                ):
                    raise ValueError("accepted environment change lacks planning plus cutover lead")
        return self

    @property
    def case_sha256(self) -> str:
        if self.semantics is None:
            # Preserve the identity of schema-v2 evidence produced before the semantic
            # contract was introduced. New cases include semantics in their identity.
            return canonical_sha256(self.model_dump(mode="python", exclude={"semantics"}))
        return canonical_sha256(self)

    @property
    def execution_semantics_sha256(self) -> str:
        """Hash only fields that can change the authored mission behavior."""

        return canonical_sha256(
            {
                "drone_count": self.drone_count,
                "drones": self.drones,
                "environment": self.environment,
                "authorization": self.authorization,
                "execution_eligibility": self.execution_eligibility,
                "hard_constraints": self.hard_constraints,
                "allowed_strategies": self.allowed_strategies,
                "search": self.search,
                "execution": self.execution,
                "replanning_authority": self.replanning_authority,
                "semantics": self.semantics,
            }
        )

    def route_nodes_for(self, role_id: str) -> tuple[RouteNodeIntent, ...]:
        drone = next((item for item in self.drones if item.role_id == role_id), None)
        if drone is None:
            raise KeyError(f"unknown campaign role: {role_id}")
        if self.semantics is not None:
            return self.semantics.route_intent_by_role[role_id]
        return tuple(
            RouteNodeIntent(region_id=region.region_id, mode=RouteNodeMode.CAPTURE)
            for region in drone.goal_sequence
        )


class LockedDevelopmentInputs(ContractModel):
    case_id: Identifier
    case_sha256: SHA256
    seed: int = Field(ge=0)
    backend_profile_id: Identifier
    configuration_sha256: SHA256
    planner_implementation_id: Identifier
    planner_implementation_version: str
    planner_settings_sha256: SHA256
    comparison_baseline_sha256: SHA256 | None = None
    submission_id: Identifier | None = None
    submission_sha256: SHA256 | None = None
    planning_submission_id: Identifier | None = None
    planning_submission_sha256: SHA256 | None = None
    resolved_planning_package_sha256: SHA256 | None = None

    @model_validator(mode="after")
    def submission_hash_pairs(self) -> LockedDevelopmentInputs:
        if (self.submission_id is None) != (self.submission_sha256 is None):
            raise ValueError("execution submission ID/hash must be locked together")
        if (self.planning_submission_id is None) != (self.planning_submission_sha256 is None):
            raise ValueError("planning submission ID/hash must be locked together")
        if (
            self.resolved_planning_package_sha256 is not None
            and self.planning_submission_sha256 is None
        ):
            raise ValueError("resolved planning package requires a planning submission lock")
        return self

    @classmethod
    def from_case(
        cls,
        case: CampaignCase,
        *,
        submission_id: str | None = None,
        submission_sha256: str | None = None,
        planning_submission_id: str | None = None,
        planning_submission_sha256: str | None = None,
        resolved_planning_package_sha256: str | None = None,
    ) -> LockedDevelopmentInputs:
        return cls(
            case_id=case.case_id,
            case_sha256=case.case_sha256,
            seed=case.execution.seed,
            backend_profile_id=case.execution.backend_profile_id,
            configuration_sha256=case.execution.configuration_sha256,
            planner_implementation_id=case.search.implementation_id,
            planner_implementation_version=case.search.implementation_version,
            planner_settings_sha256=canonical_sha256(case.search),
            comparison_baseline_sha256=case.baseline_sha256,
            submission_id=submission_id,
            submission_sha256=submission_sha256,
            planning_submission_id=planning_submission_id,
            planning_submission_sha256=planning_submission_sha256,
            resolved_planning_package_sha256=resolved_planning_package_sha256,
        )

    @property
    def lock_sha256(self) -> str:
        return canonical_sha256(self)


class LifecycleTransition(ContractModel):
    transition_id: Identifier
    case_id: Identifier
    case_sha256: SHA256
    previous_state: LifecycleState | None
    new_state: LifecycleState
    actor_id: Identifier
    occurred_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str = Field(min_length=1, max_length=1000)
    evidence_sha256: SHA256 | None = None
    review_sha256: SHA256 | None = None

    @property
    def transition_sha256(self) -> str:
        return canonical_sha256(self)


_ALLOWED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    current: frozenset(candidate for candidate in LifecycleState if candidate is not current)
    for current in LifecycleState
}


class LifecycleRecord(ContractModel):
    case_id: Identifier
    case_sha256: SHA256
    state: LifecycleState = LifecycleState.DEFINED_NOT_RUN
    transitions: tuple[LifecycleTransition, ...] = ()
    run_ids: tuple[Identifier, ...] = ()
    baseline_sha256: SHA256 | None = None

    def transition(
        self,
        new_state: LifecycleState,
        *,
        actor_id: str,
        reason: str,
        evidence_sha256: str | None = None,
        review_sha256: str | None = None,
        occurred_at_utc: datetime | None = None,
        require_qualification_evidence: bool = True,
    ) -> LifecycleRecord:
        if new_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid lifecycle transition {self.state} -> {new_state}")
        if (
            require_qualification_evidence
            and new_state in {LifecycleState.BASELINED, LifecycleState.PROMOTED}
            and (evidence_sha256 is None or review_sha256 is None)
        ):
            raise ValueError("baseline/promotion requires evidence and review hashes")
        timestamp = occurred_at_utc or datetime.now(UTC)
        payload = [
            self.case_id,
            self.case_sha256,
            self.state,
            new_state,
            actor_id,
            timestamp,
            reason,
        ]
        transition = LifecycleTransition(
            transition_id=f"transition-{canonical_sha256(payload)[:20]}",
            case_id=self.case_id,
            case_sha256=self.case_sha256,
            previous_state=self.state,
            new_state=new_state,
            actor_id=actor_id,
            occurred_at_utc=timestamp,
            reason=reason,
            evidence_sha256=evidence_sha256,
            review_sha256=review_sha256,
        )
        return self.model_copy(
            update={
                "state": new_state,
                "transitions": (*self.transitions, transition),
                "baseline_sha256": (
                    evidence_sha256
                    if new_state in {LifecycleState.BASELINED, LifecycleState.PROMOTED}
                    and evidence_sha256 is not None
                    else self.baseline_sha256
                ),
            }
        )


class MigrationReceipt(ContractModel):
    source_schema_version: int = Field(ge=1)
    target_schema_version: int = Field(ge=1)
    source_bytes_sha256: SHA256
    source_case_sha256: SHA256
    migrated_case_sha256: SHA256
    migration_implementation_id: Identifier
    migration_implementation_version: str
    migrated_case: CampaignCase


Percent = Annotated[float, Field(ge=0.0, le=100.0)]
