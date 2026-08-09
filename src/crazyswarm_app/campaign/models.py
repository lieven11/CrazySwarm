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
        if self.environment is EnvironmentKind.REAL:
            if self.authorization is not AuthorizationStatus.NOT_AUTHORIZED:
                raise ValueError("WP26-34 Real mirrors must remain NOT_AUTHORIZED")
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
        return self

    @property
    def case_sha256(self) -> str:
        return canonical_sha256(self)


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

    @classmethod
    def from_case(cls, case: CampaignCase) -> LockedDevelopmentInputs:
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
    LifecycleState.DEFINED_NOT_RUN: frozenset(
        {LifecycleState.READY, LifecycleState.ACTIVE_DEVELOPMENT, LifecycleState.BLOCKED}
    ),
    LifecycleState.READY: frozenset({LifecycleState.ACTIVE_DEVELOPMENT, LifecycleState.BLOCKED}),
    LifecycleState.ACTIVE_DEVELOPMENT: frozenset(
        {LifecycleState.READY, LifecycleState.BASELINED, LifecycleState.BLOCKED}
    ),
    LifecycleState.BASELINED: frozenset(
        {LifecycleState.ACTIVE_DEVELOPMENT, LifecycleState.PROMOTED, LifecycleState.BLOCKED}
    ),
    LifecycleState.PROMOTED: frozenset({LifecycleState.ACTIVE_DEVELOPMENT}),
    LifecycleState.BLOCKED: frozenset(
        {LifecycleState.DEFINED_NOT_RUN, LifecycleState.READY, LifecycleState.ACTIVE_DEVELOPMENT}
    ),
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
    ) -> LifecycleRecord:
        if new_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid lifecycle transition {self.state} -> {new_state}")
        if new_state in {LifecycleState.BASELINED, LifecycleState.PROMOTED} and (
            evidence_sha256 is None or review_sha256 is None
        ):
            raise ValueError("baseline/promotion requires evidence and review hashes")
        if new_state is LifecycleState.PROMOTED and self.baseline_sha256 is None:
            raise ValueError("promotion requires a bound baseline")
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
                    if new_state is LifecycleState.BASELINED
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
