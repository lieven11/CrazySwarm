from __future__ import annotations

# The admission records intentionally keep each operator-facing sentence intact.
# ruff: noqa: E501
import math
from enum import StrEnum
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import (
    CampaignCase,
    EnvironmentKind,
    ImplementationStatus,
    MotionQualityContract,
    MotionQualityMetric,
    MotionSpeedLaw,
    ObjectiveMetric,
    PlannerStrategy,
    RouteNodeMode,
    motion_contract_for,
)
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256

BASELINE_SUBMISSION_ID = "planner_retained_baseline"
BASELINE_PLANNING_SUBMISSION_ID = "case_planning_authority"
CONSTANT_PATH_SPEED_CAPABILITY_ID = "core.constant_path_speed"
ROUTE_FIDELITY_CAPABILITY_ID = "core.route_fidelity"
CORNER_TRANSITION_CAPABILITY_ID = "core.corner_transition"
ENERGY_AWARE_RETIMING_CAPABILITY_ID = "core.energy_aware_retiming"
SUBMISSION_REGISTRY_PATH = Path("missions/campaigns/sim/submissions/case-submissions-v1.yaml")
CAPABILITY_REGISTRY_PATH = Path("missions/campaigns/sim/submissions/capabilities-v1.yaml")
ADMISSION_RECORDS_PATH = Path("missions/campaigns/sim/submissions/admission-records-v1.yaml")
SEMANTIC_POLYLINE_RULE_VERSION = "semantic-polyline-v1"
OVERLAP_CAPACITY_CONTEXT_ID = "overlap-capacity-v1"
OVERLAP_CAPACITY_CONTEXT = {"minimum_simultaneous_flight_s": 2.0}
OVERLAP_CAPACITY_CONTEXT_SHA256 = "5254a2e98af7599c2d81bdf4457d94f7b44768d267a4a51d374752651b445f63"
QUALIFICATION_METRIC_IDS = frozenset(
    [
        "DS_ACKNOWLEDGED_ROLES",
        "DS_AFFECTED_ROLES",
        "DS_ALL_ROLE_COMPLETION",
        "DS_ASSIGNMENT",
        "DS_COMMAND_OWNERSHIP",
        "DS_DIRECTION_CHANGE_COUNT",
        "DS_DISPOSITION",
        "DS_FALLBACK",
        "DS_FLEET_EPOCH",
        "DS_GENERATION",
        "DS_LEASE_GENERATION",
        "DS_LOBE_ORDER",
        "DS_MANEUVER",
        "DS_OCCUPANCY_INTERVALS",
        "DS_PARTIAL_COMMIT_COUNT",
        "DS_PREPARED_ROLES",
        "DS_PRIORITY_INVERSION_COUNT",
        "DS_QUEUE_ORDER",
        "DS_REVERSAL_COUNT",
        "DS_ROLE_ORDER",
        "DS_ROUTE_IDENTITY",
        "DS_SCHEDULE",
        "DS_STALE_COMMAND_COUNT",
        "DS_TERMINAL_STATE",
        "DS_TOPOLOGY",
        "DS_UNINTENDED_STOP_COUNT",
        "DY_ACCELERATION",
        "DY_CURVATURE",
        "DY_JERK",
        "DY_SPEED_MIN",
        "DY_SPEED_TRACKING",
        "DY_VERTICAL_TRACKING",
        "EN_ACTUATOR_HEADROOM_N",
        "EN_ENERGY_WH",
        "EN_RESERVE_PP",
        "EN_SPREAD_PP",
        "SP_BOUNDARY",
        "SP_CAPTURE",
        "SP_CLEARANCE",
        "SP_CLOSURE",
        "SP_CORNER_CUT",
        "SP_FORMATION",
        "SP_OFFSET",
        "SP_RADIAL",
        "SP_REFERENCE",
        "SP_SPACING",
        "SP_SPLICE_POSITION",
        "SP_UNAFFECTED_PATH",
        "TM_COVERAGE_GAP",
        "TM_CUTOVER",
        "TM_DURATION",
        "TM_DWELL",
        "TM_FINISH_SKEW",
        "TM_HOLD",
        "TM_HORIZON",
        "TM_OVERLAP",
        "TM_PHASE_ERROR",
        "TM_RELEASE",
        "TM_SETTLE",
        "TM_STARVATION",
        "TM_TRANSITION_START",
        "TM_WAIT",
    ]
)


class CapabilityFeasibilityDisposition(StrEnum):
    CERTIFIED = "CERTIFIED"
    PROVEN_INFEASIBLE = "PROVEN_INFEASIBLE"


class NormalizedPolyline(ContractModel):
    schema_version: Literal[1] = 1
    rule_version: Literal["semantic-polyline-v1"] = SEMANTIC_POLYLINE_RULE_VERSION
    role_id: Identifier
    raw_node_ids: tuple[str, ...] = Field(min_length=2)
    raw_node_modes: tuple[RouteNodeMode, ...] = Field(min_length=2)
    raw_points_m: tuple[Vector3, ...] = Field(min_length=2)
    retained_raw_indices: tuple[int, ...] = Field(min_length=2)
    normalized_points_m: tuple[Vector3, ...] = Field(min_length=2)
    raw_capture_sha256: SHA256
    normalized_geometry_sha256: SHA256

    @model_validator(mode="after")
    def identities_match_payload(self) -> NormalizedPolyline:
        if not (len(self.raw_node_ids) == len(self.raw_node_modes) == len(self.raw_points_m)):
            raise ValueError("normalized polyline raw node fields must have equal length")
        if (
            self.retained_raw_indices[0] != 0
            or self.retained_raw_indices[-1] != len(self.raw_points_m) - 1
        ):
            raise ValueError("normalized polyline must retain both endpoints")
        if tuple(sorted(set(self.retained_raw_indices))) != self.retained_raw_indices:
            raise ValueError("normalized polyline indices must be unique and increasing")
        if self.normalized_points_m != tuple(
            self.raw_points_m[index] for index in self.retained_raw_indices
        ):
            raise ValueError("normalized polyline points do not match retained indices")
        raw_payload = {
            "role_id": self.role_id,
            "node_ids": self.raw_node_ids,
            "node_modes": self.raw_node_modes,
            "points_m": self.raw_points_m,
        }
        if self.raw_capture_sha256 != canonical_sha256(raw_payload):
            raise ValueError("normalized polyline raw capture hash mismatch")
        normalized_payload = {
            "rule_version": self.rule_version,
            "role_id": self.role_id,
            "points_m": self.normalized_points_m,
            "semantic_markers": tuple(
                {
                    "normalized_index": normalized_index,
                    "node_id": self.raw_node_ids[raw_index],
                    "mode": self.raw_node_modes[raw_index],
                }
                for normalized_index, raw_index in enumerate(self.retained_raw_indices)
                if self.raw_node_modes[raw_index] is not RouteNodeMode.FLY_THROUGH
            ),
        }
        if self.normalized_geometry_sha256 != canonical_sha256(normalized_payload):
            raise ValueError("normalized polyline geometry hash mismatch")
        return self


class CapabilityFeasibilityRecord(ContractModel):
    schema_version: Literal[1] = 1
    oracle_id: Literal["independent-dense-capability-feasibility-v1"] = (
        "independent-dense-capability-feasibility-v1"
    )
    disposition: CapabilityFeasibilityDisposition
    complete_bounded_compiler: bool
    sample_step_s: Literal[0.01] = 0.01
    maximum_route_duration_s: float = Field(gt=0.0)
    execution_overhead_s: float = Field(default=8.0, ge=0.0)
    deadline_s: float = Field(gt=0.0)
    maximum_acceleration_m_s2: float = Field(ge=0.0)
    maximum_jerk_m_s3: float = Field(ge=0.0)
    maximum_path_deviation_m: float | None = Field(default=None, ge=0.0)
    minimum_protected_free_space_m: float | None = None
    violated_constraints: tuple[str, ...]
    evidence_sha256: SHA256

    @model_validator(mode="after")
    def disposition_matches_constraints(self) -> CapabilityFeasibilityRecord:
        if not self.complete_bounded_compiler:
            raise ValueError("capability feasibility record requires a complete compiler")
        if (self.disposition is CapabilityFeasibilityDisposition.PROVEN_INFEASIBLE) != bool(
            self.violated_constraints
        ):
            raise ValueError("capability feasibility disposition/violations mismatch")
        payload = self.model_dump(mode="python", exclude={"evidence_sha256"})
        if self.evidence_sha256 != canonical_sha256(payload):
            raise ValueError("capability feasibility evidence hash mismatch")
        return self


class EnergyCandidateDisposition(StrEnum):
    FEASIBLE = "FEASIBLE"
    REJECTED = "REJECTED"


class EnergyRetimingCandidate(ContractModel):
    duration_factor: float
    disposition: EnergyCandidateDisposition
    predicted_energy_wh: float = Field(ge=0.0)
    peak_current_a: float = Field(ge=0.0)
    duration_s: float = Field(gt=0.0)
    maximum_horizontal_speed_m_s: float = Field(ge=0.0)
    maximum_vertical_speed_m_s: float = Field(ge=0.0)
    maximum_acceleration_m_s2: float = Field(ge=0.0)
    maximum_jerk_m_s3: float = Field(ge=0.0)
    predicted_minimum_reserve_percent: float
    rejection_reasons: tuple[str, ...]
    trajectory_set_sha256: SHA256

    @model_validator(mode="after")
    def disposition_matches_reasons(self) -> EnergyRetimingCandidate:
        if self.duration_factor not in ENERGY_RETIMING_FACTORS:
            raise ValueError("energy candidate uses an unfrozen duration factor")
        if (self.disposition is EnergyCandidateDisposition.REJECTED) != bool(
            self.rejection_reasons
        ):
            raise ValueError("energy candidate disposition/reasons mismatch")
        return self


ENERGY_RETIMING_FACTORS = (0.80, 0.90, 1.00, 1.15, 1.30)


class EnergyRetimingResolution(ContractModel):
    oracle_id: Literal["bounded-energy-retiming-v1"] = "bounded-energy-retiming-v1"
    physics_model_id: Literal["crazyflie-6dof"] = "crazyflie-6dof"
    physics_model_version: Literal["2.0.0"] = "2.0.0"
    powertrain_model: Literal["BATTERY_COUPLED_V2"] = "BATTERY_COUPLED_V2"
    physics_configuration_sha256: SHA256
    sample_step_s: Literal[0.01] = 0.01
    candidates: tuple[EnergyRetimingCandidate, ...] = Field(min_length=5, max_length=5)
    selected_factor: float
    limiting_constraint: str = Field(min_length=1, max_length=240)
    evidence_sha256: SHA256

    @model_validator(mode="after")
    def selection_is_reproducible(self) -> EnergyRetimingResolution:
        if tuple(item.duration_factor for item in self.candidates) != ENERGY_RETIMING_FACTORS:
            raise ValueError("energy resolution must retain all five frozen candidates in order")
        feasible = tuple(
            item
            for item in self.candidates
            if item.disposition is EnergyCandidateDisposition.FEASIBLE
        )
        if not feasible:
            raise ValueError("energy resolution has no feasible candidate")
        minimum_energy = min(item.predicted_energy_wh for item in feasible)
        energy_ties = tuple(
            item for item in feasible if item.predicted_energy_wh <= minimum_energy + 1e-5
        )
        expected = min(
            energy_ties,
            key=lambda item: (item.peak_current_a, item.duration_s, item.duration_factor),
        )
        if self.selected_factor != expected.duration_factor:
            raise ValueError("energy resolution selected factor violates the frozen ranking")
        payload = self.model_dump(mode="python", exclude={"evidence_sha256"})
        if self.evidence_sha256 != canonical_sha256(payload):
            raise ValueError("energy resolution evidence hash mismatch")
        return self


class ExecutionProfileKind(StrEnum):
    PLANNER_RETIMED_BASELINE = "PLANNER_RETIMED_BASELINE"
    CONSTANT_PATH_SPEED = "CONSTANT_PATH_SPEED"
    RAMPED_SEGMENT_SPEED = "RAMPED_SEGMENT_SPEED"
    BOUNDED_VERTICAL_RATE = "BOUNDED_VERTICAL_RATE"
    DURATION_SCALE = "DURATION_SCALE"
    CORNER_TRANSITION = "CORNER_TRANSITION"
    CONSTANT_ROTOR_SPEED = "CONSTANT_ROTOR_SPEED"


class ExecutionProfileOwner(StrEnum):
    PLANNER = "PLANNER"
    TIME_PARAMETERIZER = "TIME_PARAMETERIZER"
    TRAJECTORY_TRACKER = "TRAJECTORY_TRACKER"
    LOW_LEVEL_ACTUATOR = "LOW_LEVEL_ACTUATOR"


class SubmissionStatus(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    PLANNED_NOT_EXECUTABLE = "PLANNED_NOT_EXECUTABLE"


class ManeuverDimension(StrEnum):
    TIMING = "TIMING"
    SPEED = "SPEED"
    LATERAL = "LATERAL"
    VERTICAL = "VERTICAL"


class SubmissionLayer(StrEnum):
    PLANNING = "P"
    EXECUTION_PROFILE = "E"
    CORE_CAPABILITY = "C"
    REPLANNING_POLICY = "R"
    BASELINE_ONLY = "BASELINE_ONLY"


class ExperimentAxis(StrEnum):
    OBJECTIVE_ORDER = "OBJECTIVE_ORDER"
    MANEUVER_DIMENSION = "MANEUVER_DIMENSION"
    FALLBACK_POLICY = "FALLBACK_POLICY"
    SCALAR_PARAMETER = "SCALAR_PARAMETER"
    CAPABILITY_BINDING = "CAPABILITY_BINDING"
    PATH_ADHERENCE_MODE = "PATH_ADHERENCE_MODE"


class PlanningSelectionOracle(StrEnum):
    OBJECTIVE_ORDER = "OBJECTIVE_ORDER"
    ARGMIN_BOUNDED_RELEASE = "ARGMIN_BOUNDED_RELEASE"
    ARGMAX_BOUNDED_CLEARANCE = "ARGMAX_BOUNDED_CLEARANCE"


class FallbackPolicy(StrEnum):
    SAFE_PREFIX = "SAFE_PREFIX"
    BOUNDED_HOLD = "BOUNDED_HOLD"
    CONTROLLED_LAND = "CONTROLLED_LAND"
    SAFE_OLD_EPOCH = "SAFE_OLD_EPOCH"
    COORDINATED_LAND = "COORDINATED_LAND"
    PROMOTE_SUCCESSOR = "PROMOTE_SUCCESSOR"


class PathAdherenceMode(StrEnum):
    EXACT_ROUTE = "EXACT_ROUTE"
    HARD_TUBE = "HARD_TUBE"
    REQUIRED_REGIONS = "REQUIRED_REGIONS"
    SOFT_REFERENCE = "SOFT_REFERENCE"
    # Historical values remain parseable so retained hashes and evidence do not change.
    GOAL_SEQUENCE_ONLY = "GOAL_SEQUENCE_ONLY"
    ROUTE_CORRIDOR = "ROUTE_CORRIDOR"
    AUTHORED_CENTERLINE = "AUTHORED_CENTERLINE"


class ObjectiveComposition(StrEnum):
    LEXICOGRAPHIC = "LEXICOGRAPHIC"
    WEIGHTED_SUM = "WEIGHTED_SUM"


class PlanningObjectiveTerm(ContractModel):
    metric: ObjectiveMetric
    weight: float | None = Field(default=None, gt=0.0)


class PlanningObjective(ContractModel):
    composition: ObjectiveComposition = ObjectiveComposition.LEXICOGRAPHIC
    terms: tuple[PlanningObjectiveTerm, ...] = Field(min_length=1)
    deterministic_tie_breaker: Literal["CANDIDATE_SHA256"] = "CANDIDATE_SHA256"

    @model_validator(mode="after")
    def complete_semantics(self) -> PlanningObjective:
        metrics = tuple(term.metric for term in self.terms)
        if len(set(metrics)) != len(metrics):
            raise ValueError("planning objective metrics must be unique")
        weights = tuple(term.weight for term in self.terms)
        if self.composition is ObjectiveComposition.LEXICOGRAPHIC and any(
            weight is not None for weight in weights
        ):
            raise ValueError("lexicographic objectives do not accept weights")
        if self.composition is ObjectiveComposition.WEIGHTED_SUM and any(
            weight is None for weight in weights
        ):
            raise ValueError("weighted objectives require every weight")
        return self


class PathAdherencePolicy(ContractModel):
    mode: PathAdherenceMode = PathAdherenceMode.GOAL_SEQUENCE_ONLY
    maximum_centerline_deviation_m: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def deviation_matches_mode(self) -> PathAdherencePolicy:
        modes_without_deviation = {
            PathAdherenceMode.GOAL_SEQUENCE_ONLY,
            PathAdherenceMode.REQUIRED_REGIONS,
            PathAdherenceMode.SOFT_REFERENCE,
        }
        if self.mode in modes_without_deviation and self.maximum_centerline_deviation_m is not None:
            raise ValueError(f"{self.mode.value} path adherence has no hard deviation limit")
        if self.mode not in modes_without_deviation and self.maximum_centerline_deviation_m is None:
            raise ValueError(
                "exact, tube, corridor, and centerline modes require a deviation limit"
            )
        if (
            self.mode is PathAdherenceMode.EXACT_ROUTE
            and self.maximum_centerline_deviation_m is not None
            and self.maximum_centerline_deviation_m > 0.03
        ):
            raise ValueError("exact-route tolerance must not exceed 0.03 m")
        return self


class ClearancePolicy(ContractModel):
    nominal_vehicle_radius_m: float = Field(default=0.055, gt=0.0, le=0.50)
    nominal_vehicle_half_height_m: float = Field(default=0.025, gt=0.0, le=0.50)
    required_pairwise_center_separation_m: float = Field(gt=0.0)
    required_solid_clearance_m: float = Field(default=0.05, ge=0.0)
    uncertainty_allowance_m: float = Field(default=0.05, ge=0.0)
    contact_allowed_role_ids: tuple[Identifier, ...] = ()
    contact_target_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def contact_pairing_is_explicit(self) -> ClearancePolicy:
        if bool(self.contact_allowed_role_ids) != bool(self.contact_target_ids):
            raise ValueError("contact authority requires both roles and named targets")
        return self


class CoordinationPolicy(ContractModel):
    synchronized_launch_required: bool
    synchronized_route_start_required: bool
    maximum_route_start_skew_s: float = Field(default=0.0, ge=0.0)
    minimum_simultaneous_flight_s: float = Field(ge=0.0)
    precedence_role_ids: tuple[Identifier, ...] = ()
    maximum_release_delay_s: float = Field(default=60.0, ge=0.0)


class CapabilityResolution(ContractModel):
    capability_id: Identifier
    capability_request_sha256: SHA256
    normalization_rule_version: Literal["semantic-polyline-v1"] | None = None
    normalized_geometry_sha256: SHA256 | None = None
    raw_capture_sha256s: tuple[SHA256, ...] = ()
    authored_lookahead_time_s: float | None = Field(default=None, gt=0.0, le=2.0)
    authored_target_path_speed_m_s: float | None = Field(default=None, gt=0.0, le=0.5)
    certified_entry_speed_m_s: float | None = Field(default=None, gt=0.0, le=0.5)
    derived_lookahead_distance_m: float | None = Field(default=None, gt=0.0, le=0.30)
    derived_turn_blend_radius_m: float | None = Field(default=None, gt=0.0, le=0.25)
    adjacent_segment_cap_m: float | None = Field(default=None, gt=0.0)
    protected_free_space_cap_m: float | None = Field(default=None, gt=0.0)
    path_deviation_cap_m: float | None = Field(default=None, gt=0.0)
    dynamics_speed_cap_m_s: float | None = Field(default=None, gt=0.0, le=0.5)
    safety_retiming_factor: float | None = Field(default=None, ge=1.0)
    limiting_constraint: str | None = Field(default=None, min_length=1, max_length=240)
    feasibility: CapabilityFeasibilityRecord | None = None
    exact_route_tolerance_m: float | None = Field(default=None, gt=0.0)
    energy_retiming: EnergyRetimingResolution | None = None

    @model_validator(mode="after")
    def derived_values_are_consistent(self) -> CapabilityResolution:
        if self.capability_id == ROUTE_FIDELITY_CAPABILITY_ID:
            if self.exact_route_tolerance_m != 1e-6:
                raise ValueError("route-fidelity resolution requires the frozen 1e-6 m bound")
        elif self.exact_route_tolerance_m is not None:
            raise ValueError("only route fidelity may carry an exact-route tolerance")
        if self.capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID:
            if self.energy_retiming is None:
                raise ValueError("energy-aware capability requires its bounded compiler record")
        elif self.energy_retiming is not None:
            raise ValueError("only energy-aware retiming may carry an energy compiler record")
        values = (
            self.authored_lookahead_time_s,
            self.authored_target_path_speed_m_s,
            self.certified_entry_speed_m_s,
            self.derived_lookahead_distance_m,
            self.derived_turn_blend_radius_m,
            self.adjacent_segment_cap_m,
            self.protected_free_space_cap_m,
            self.path_deviation_cap_m,
            self.dynamics_speed_cap_m_s,
            self.safety_retiming_factor,
            self.limiting_constraint,
        )
        if any(value is not None for value in values) and any(value is None for value in values):
            raise ValueError("corner-transition resolution requires every derived value")
        if self.authored_lookahead_time_s is not None:
            if (
                self.normalization_rule_version is None
                or self.normalized_geometry_sha256 is None
                or not self.raw_capture_sha256s
                or self.feasibility is None
            ):
                raise ValueError(
                    "corner-transition resolution requires normalized geometry and feasibility"
                )
            assert self.certified_entry_speed_m_s is not None
            assert self.derived_lookahead_distance_m is not None
            assert self.derived_turn_blend_radius_m is not None
            assert self.adjacent_segment_cap_m is not None
            assert self.protected_free_space_cap_m is not None
            assert self.path_deviation_cap_m is not None
            assert self.authored_target_path_speed_m_s is not None
            assert self.dynamics_speed_cap_m_s is not None
            assert self.safety_retiming_factor is not None
            expected_speed = (
                min(
                    self.authored_target_path_speed_m_s,
                    self.dynamics_speed_cap_m_s,
                )
                / self.safety_retiming_factor
            )
            if not math.isclose(
                expected_speed,
                self.certified_entry_speed_m_s,
                rel_tol=1e-8,
                abs_tol=1e-9,
            ):
                raise ValueError("certified entry speed does not match bounded retiming")
            preliminary_distance = min(
                0.30,
                self.authored_lookahead_time_s * self.certified_entry_speed_m_s,
                self.adjacent_segment_cap_m,
            )
            radius_candidate = min(0.25, max(0.08, preliminary_distance * 0.75))
            expected_radius = min(
                radius_candidate,
                self.adjacent_segment_cap_m,
                2.0 * self.protected_free_space_cap_m,
                2.0 * self.path_deviation_cap_m,
            )
            expected_distance = min(preliminary_distance, 2.0 * expected_radius)
            if not math.isclose(
                expected_distance,
                self.derived_lookahead_distance_m,
                abs_tol=1e-9,
            ):
                raise ValueError("lookahead distance does not match time/speed derivation")
            if not math.isclose(
                expected_radius,
                self.derived_turn_blend_radius_m,
                abs_tol=1e-9,
            ):
                raise ValueError("turn blend radius does not match bounded derivation")
        elif (
            any(
                value is not None
                for value in (
                    self.normalization_rule_version,
                    self.normalized_geometry_sha256,
                    self.feasibility,
                )
            )
            or self.raw_capture_sha256s
        ):
            raise ValueError("non-corner capability cannot carry corner geometry evidence")
        return self


class VariationAdmissionRecord(ContractModel):
    causal_question: str = Field(min_length=1, max_length=1000)
    baseline_limitation: str = Field(min_length=1, max_length=1000)
    principal_variable: Identifier
    fixed_inputs: tuple[Identifier, ...] = Field(min_length=1)
    behavior_difference: str = Field(min_length=1, max_length=1000)
    distinguishing_oracle: str = Field(min_length=1, max_length=1000)
    reused_evidence: tuple[Identifier, ...]
    new_integration_gate: str = Field(min_length=1, max_length=1000)
    backend_semantics: str = Field(min_length=1, max_length=1000)
    safety_bounds: str = Field(min_length=1, max_length=1000)
    operator_comparison: str = Field(min_length=1, max_length=1000)
    learning_value: str = Field(min_length=1, max_length=1000)


class PlanningSubmission(ContractModel):
    """Operator-authored planning authority, separate from immutable world truth."""

    schema_version: Literal[1] = 1
    planning_submission_id: Identifier
    submission_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    display_name: str = Field(min_length=1, max_length=160)
    case_id: Identifier
    case_sha256: SHA256
    world_definition_sha256: SHA256
    vehicle_model_sha256: SHA256
    status: SubmissionStatus
    rationale: str = Field(min_length=1, max_length=1000)
    strategy_authority: tuple[PlannerStrategy, ...] = Field(min_length=1)
    maneuver_dimensions: tuple[ManeuverDimension, ...] = Field(min_length=1)
    path_adherence: PathAdherencePolicy
    clearance: ClearancePolicy
    coordination: CoordinationPolicy
    objective: PlanningObjective
    selection_oracle: PlanningSelectionOracle = PlanningSelectionOracle.OBJECTIVE_ORDER
    feasibility_oracle_ids: tuple[Identifier, ...] = Field(min_length=1)
    experiment_id: Identifier = "baseline_case_authority"
    experiment_axis: ExperimentAxis = ExperimentAxis.OBJECTIVE_ORDER
    axis_value: Identifier = "case_default"
    layer: SubmissionLayer = SubmissionLayer.PLANNING
    fallback_policy: FallbackPolicy | None = None
    capability_id: Identifier | None = None
    comparison_context_id: Identifier | None = None
    comparison_context_sha256: SHA256 | None = None
    support_reason: str = Field(
        default="Executable through the bounded Fast-Sim planning path.",
        min_length=1,
        max_length=1000,
    )
    admission: VariationAdmissionRecord
    execution_profile_submission_id: Identifier = BASELINE_SUBMISSION_ID
    execution_profile_sha256: SHA256
    supported_backend_profile_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def bounded_authority(self) -> PlanningSubmission:
        if len(set(self.strategy_authority)) != len(self.strategy_authority):
            raise ValueError("planning strategy authority must be unique")
        if len(set(self.maneuver_dimensions)) != len(self.maneuver_dimensions):
            raise ValueError("planning maneuver dimensions must be unique")
        if self.status is SubmissionStatus.EXECUTABLE and not self.supported_backend_profile_ids:
            raise ValueError("executable planning submission requires a backend mapping")
        if self.layer is SubmissionLayer.REPLANNING_POLICY and self.fallback_policy is None:
            raise ValueError("replanning-policy submission requires a fallback policy")
        if self.layer is not SubmissionLayer.REPLANNING_POLICY and self.fallback_policy is not None:
            raise ValueError("fallback policy is only valid for replanning submissions")
        if (self.comparison_context_id is None) != (self.comparison_context_sha256 is None):
            raise ValueError("planning comparison context identity must be complete")
        if self.comparison_context_id is not None and (
            self.comparison_context_id != OVERLAP_CAPACITY_CONTEXT_ID
            or self.comparison_context_sha256 != OVERLAP_CAPACITY_CONTEXT_SHA256
        ):
            raise ValueError("planning submission uses an unknown comparison context")
        return self

    @property
    def planning_submission_sha256(self) -> str:
        return canonical_sha256(self)

    @property
    def semantic_fingerprint_sha256(self) -> str:
        return canonical_sha256(
            {
                "case_sha256": self.case_sha256,
                "strategy_authority": self.strategy_authority,
                "maneuver_dimensions": self.maneuver_dimensions,
                "path_adherence": self.path_adherence,
                "clearance": self.clearance,
                "coordination": self.coordination,
                "objective": self.objective,
                "selection_oracle": self.selection_oracle,
                "fallback_policy": self.fallback_policy,
                "capability_id": self.capability_id,
                "comparison_context_id": self.comparison_context_id,
                "comparison_context_sha256": self.comparison_context_sha256,
                "execution_profile_sha256": self.execution_profile_sha256,
            }
        )


class CoordinationPreparationRequest(ContractModel):
    """Optional exact two-drone launch-gap experiment, separate from motion physics."""

    schema_version: Literal[1] = 1
    launch_gap_s: float = Field(ge=0.0, le=60.0)


class ResolvedPlanningPackage(ContractModel):
    """The exact single-file-equivalent package accepted for a run."""

    schema_version: Literal[1] = 1
    case: CampaignCase
    planning_submission: PlanningSubmission
    execution_profile: ExecutionProfileSubmission
    world_definition: dict[str, object]
    vehicle_model: dict[str, object]
    backend_configuration_sha256: SHA256
    capability_resolution: CapabilityResolution | None = None
    motion_preparation: MotionPreparationResolution | None = None
    coordination_preparation: CoordinationPreparationRequest | None = None
    resolved_package_sha256: SHA256

    @model_validator(mode="after")
    def hashes_match_snapshots(self) -> ResolvedPlanningPackage:
        if self.case.case_id != self.planning_submission.case_id:
            raise ValueError("planning package case ID mismatch")
        if self.case.case_sha256 != self.planning_submission.case_sha256:
            raise ValueError("planning package case hash mismatch")
        if (
            self.execution_profile.case_id != self.case.case_id
            or self.execution_profile.case_sha256 != self.case.case_sha256
        ):
            raise ValueError("planning package execution-profile case mismatch")
        if (
            canonical_sha256(self.world_definition)
            != self.planning_submission.world_definition_sha256
        ):
            raise ValueError("planning package world hash mismatch")
        if canonical_sha256(self.vehicle_model) != self.planning_submission.vehicle_model_sha256:
            raise ValueError("planning package vehicle-model hash mismatch")
        if (
            self.execution_profile.profile_sha256
            != self.planning_submission.execution_profile_sha256
        ):
            raise ValueError("planning package execution-profile hash mismatch")
        if (
            self.execution_profile.submission_id
            != self.planning_submission.execution_profile_submission_id
        ):
            raise ValueError("planning package execution-profile ID mismatch")
        if self.backend_configuration_sha256 != self.case.execution.configuration_sha256:
            raise ValueError("planning package backend-configuration hash mismatch")
        expected_resolution = resolve_package_capability_resolution(
            self.case,
            self.planning_submission,
            self.execution_profile,
        )
        if self.capability_resolution != expected_resolution:
            raise ValueError("planning package capability resolution mismatch")
        if self.motion_preparation is not None and (
            self.motion_preparation.motion_quality_contract
            != motion_contract_for_execution_profile(self.case, self.execution_profile)
            or self.motion_preparation.motion_quality_contract_sha256
            != canonical_sha256(self.motion_preparation.motion_quality_contract)
            or self.planning_submission.planning_submission_id
            != self.motion_preparation.planning_submission_id
            or self.execution_profile.submission_id
            != self.motion_preparation.execution_profile_submission_id
        ):
            raise ValueError("planning package motion preparation mismatch")
        if self.resolved_package_sha256 != canonical_sha256(self.canonical_payload()):
            raise ValueError("planning package resolved hash mismatch")
        return self

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"resolved_package_sha256"})


class ExecutionProfileParameters(ContractModel):
    target_path_speed_m_s: float | None = Field(default=None, gt=0.0, le=0.5)
    certified_path_speed_m_s: float | None = Field(default=None, gt=0.0, le=0.5)
    segment_target_speeds_m_s: tuple[float, ...] = ()
    target_vertical_rate_m_s: float | None = Field(default=None, gt=0.0, le=0.3)
    duration_scale: float | None = Field(default=None, ge=0.75, le=1.50)
    lookahead_time_s: float | None = Field(default=None, gt=0.0, le=2.0)
    maximum_path_tube_error_m: float | None = Field(default=None, gt=0.0, le=100.0)
    smoothness_percent: int | None = Field(default=None, ge=0, le=100, strict=True)
    entry_exit_ramp_s: float = Field(default=1.25, gt=0.0, le=5.0)
    steady_window_tolerance_fraction: float = Field(default=0.20, gt=0.0, le=0.50)

    @model_validator(mode="after")
    def bounded_segment_speeds(self) -> ExecutionProfileParameters:
        if len(self.segment_target_speeds_m_s) > 32:
            raise ValueError("submission segment-speed schedule is unbounded")
        if any(value <= 0.0 or value > 0.5 for value in self.segment_target_speeds_m_s):
            raise ValueError("submission segment speeds must be inside 0..0.5 m/s")
        if (
            self.certified_path_speed_m_s is not None
            and self.target_path_speed_m_s is not None
            and self.certified_path_speed_m_s > self.target_path_speed_m_s + 1e-12
        ):
            raise ValueError("certified path speed cannot exceed the authored target")
        return self


class MotionPreparationRequest(ContractModel):
    """Plain operator motion controls retained before safety resolution."""

    schema_version: Literal[1] = 1
    balance: int = Field(default=50, ge=0, le=100, strict=True)
    speed_m_s: float | None = Field(default=None, gt=0.0, le=2.0)
    accuracy_m: float | None = Field(default=None, gt=0.0, le=100.0)
    smoothness: int | None = Field(default=None, ge=0, le=100, strict=True)


class MotionPreparationLimits(ContractModel):
    """Mission-authored bounds for plain operator motion controls."""

    accuracy_min_m: float = Field(gt=0.0)
    accuracy_max_m: float = Field(gt=0.0, le=100.0)
    accuracy_binding: str = Field(min_length=1, max_length=120)


def motion_preparation_limits_for_case(case: CampaignCase) -> MotionPreparationLimits:
    """Resolve the meaningful accuracy range from goal and world geometry."""

    volume = case.hard_constraints.flight_volume
    volume_spans = (
        volume.maximum_m.x - volume.minimum_m.x,
        volume.maximum_m.y - volume.minimum_m.y,
        volume.maximum_m.z - volume.minimum_m.z,
    )
    positive_volume_spans = tuple(span for span in volume_spans if span > 0.0)
    volume_route_span = math.sqrt(sum(span * span for span in positive_volume_spans))
    candidates: list[tuple[float, str]] = [
        (
            volume_route_span if positive_volume_spans else 100.0,
            "flight-volume route span",
        )
    ]
    route_nodes = tuple(
        node
        for nodes in (case.semantics.route_intent_by_role.values() if case.semantics else ())
        for node in nodes
    )
    capture_tolerances = tuple(node.capture_tolerance_m for node in route_nodes)
    if capture_tolerances and (
        case.drone_count != 1
        or any(node.mode is not RouteNodeMode.FLY_THROUGH for node in route_nodes)
    ):
        candidates.append((min(capture_tolerances), "mission goal tolerance"))
    elif not route_nodes:
        goal_half_spans = tuple(
            min(positive_spans) / 2.0
            for drone in case.drones
            for goal in drone.goal_sequence
            if (
                positive_spans := tuple(
                    span
                    for span in (
                        goal.maximum_m.x - goal.minimum_m.x,
                        goal.maximum_m.y - goal.minimum_m.y,
                        goal.maximum_m.z - goal.minimum_m.z,
                    )
                    if span > 0.0
                )
            )
        )
        if goal_half_spans:
            candidates.append((min(goal_half_spans), "mission goal dimensions"))
    accuracy_max_m, accuracy_binding = min(candidates, key=lambda item: item[0])
    return MotionPreparationLimits(
        accuracy_min_m=min(0.01, accuracy_max_m),
        accuracy_max_m=accuracy_max_m,
        accuracy_binding=accuracy_binding,
    )


class ResolvedMotionControl(ContractModel):
    label: Literal["Speed", "Accuracy", "Smoothness"]
    unit: Literal["m/s", "m", "%"]
    requested_value: float
    resolved_value: float
    binding_safety_cap: str | None = Field(default=None, min_length=1, max_length=240)


class MotionPreparationResolution(ContractModel):
    schema_version: Literal[1] = 1
    request: MotionPreparationRequest
    controls: tuple[ResolvedMotionControl, ResolvedMotionControl, ResolvedMotionControl]
    planning_submission_id: Identifier
    execution_profile_submission_id: Identifier
    motion_quality_contract: MotionQualityContract
    motion_quality_contract_sha256: SHA256
    resolution_sha256: SHA256

    @model_validator(mode="after")
    def exact_resolution_is_hash_bound(self) -> MotionPreparationResolution:
        if tuple(item.label for item in self.controls) != (
            "Speed",
            "Accuracy",
            "Smoothness",
        ):
            raise ValueError("motion controls must retain the plain ordered control set")
        if canonical_sha256(self.motion_quality_contract) != self.motion_quality_contract_sha256:
            raise ValueError("resolved motion contract hash mismatch")
        if (
            canonical_sha256(self.model_dump(mode="python", exclude={"resolution_sha256"}))
            != self.resolution_sha256
        ):
            raise ValueError("motion preparation resolution hash mismatch")
        return self


class ExecutionCapabilityRequest(ContractModel):
    """Planner request for a reusable execution capability, not a catalog experiment."""

    schema_version: Literal[1] = 1
    capability_id: Literal[
        "core.constant_path_speed",
        "core.route_fidelity",
        "core.corner_transition",
        "core.energy_aware_retiming",
    ]
    parameters: ExecutionProfileParameters

    @model_validator(mode="after")
    def parameters_match_capability(self) -> ExecutionCapabilityRequest:
        parameters = self.parameters
        if self.capability_id == CONSTANT_PATH_SPEED_CAPABILITY_ID:
            if parameters.target_path_speed_m_s is None:
                raise ValueError("constant-path-speed capability requires a target speed")
            if (
                parameters.segment_target_speeds_m_s
                or parameters.target_vertical_rate_m_s
                or parameters.duration_scale
                or parameters.lookahead_time_s
                or parameters.maximum_path_tube_error_m
                or parameters.smoothness_percent is not None
            ):
                raise ValueError("constant-path-speed capability has unrelated parameters")
        elif self.capability_id == CORNER_TRANSITION_CAPABILITY_ID:
            if parameters.lookahead_time_s is None or parameters.target_path_speed_m_s is None:
                raise ValueError("corner-transition capability requires lookahead and path speed")
            if (
                parameters.segment_target_speeds_m_s
                or parameters.target_vertical_rate_m_s
                or parameters.duration_scale
            ):
                raise ValueError("corner-transition capability has unrelated parameters")
        elif self.capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID:
            if parameters.segment_target_speeds_m_s or any(
                value is not None
                for value in (
                    parameters.target_path_speed_m_s,
                    parameters.target_vertical_rate_m_s,
                    parameters.duration_scale,
                    parameters.lookahead_time_s,
                    parameters.maximum_path_tube_error_m,
                    parameters.smoothness_percent,
                )
            ):
                raise ValueError("energy-aware retiming has no caller-selected scalar parameter")
        elif self.capability_id == ROUTE_FIDELITY_CAPABILITY_ID:
            if parameters.segment_target_speeds_m_s or any(
                value is not None
                for value in (
                    parameters.target_path_speed_m_s,
                    parameters.target_vertical_rate_m_s,
                    parameters.duration_scale,
                    parameters.lookahead_time_s,
                    parameters.maximum_path_tube_error_m,
                    parameters.smoothness_percent,
                )
            ):
                raise ValueError("route-fidelity capability is planning-owned")
        return self


class PlanningCapabilityRequest(ContractModel):
    """Planner-owned reusable capability request, separate from trajectory time laws."""

    schema_version: Literal[1] = 1
    capability_id: Literal["core.route_fidelity"]


class ProfileFeasibilityRecord(ContractModel):
    method: Literal["PIECEWISE_LINEAR_TANGENT_BOUNDS_AND_BOUNDED_ALLOCATION"] = (
        "PIECEWISE_LINEAR_TANGENT_BOUNDS_AND_BOUNDED_ALLOCATION"
    )
    minimum_path_speed_m_s: float = Field(gt=0.0)
    maximum_path_speed_m_s: float = Field(gt=0.0)
    limiting_segment_index: int = Field(ge=0)
    maximum_horizontal_tangent_fraction: float = Field(ge=0.0, le=1.0)
    maximum_vertical_tangent_fraction: float = Field(ge=0.0, le=1.0)
    maximum_steady_window_curvature_m_inverse: float = Field(ge=0.0)
    route_segment_lengths_m: tuple[float, ...] = Field(min_length=1)
    climb_descent_segment_indices: tuple[int, ...]
    declared_windows: tuple[Literal["ROUTE_SEGMENT_INTERIOR"], ...] = ("ROUTE_SEGMENT_INTERIOR",)
    excluded_phases: tuple[str, ...] = (
        "TAKEOFF",
        "ENTRY_RAMP",
        "KNOT_TRANSITION_RAMP",
        "EXIT_RAMP",
        "LANDING",
    )
    residual_gates: tuple[str, ...] = (
        "BOUNDED_ACCELERATION",
        "BOUNDED_JERK",
        "ENERGY_RESERVE",
        "TERMINAL_CAPTURE",
    )


class ExecutionProfileSubmission(ContractModel):
    """Versioned case/profile binding; never a replacement campaign case."""

    schema_version: Literal[2] = 2
    submission_id: Identifier
    submission_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    display_name: str = Field(min_length=1, max_length=160)
    case_id: Identifier
    case_sha256: SHA256
    baseline_submission_id: Identifier | None = None
    baseline_submission_sha256: SHA256 | None = None
    kind: ExecutionProfileKind
    owner: ExecutionProfileOwner
    status: SubmissionStatus
    rationale: str = Field(min_length=1, max_length=1000)
    parameters: ExecutionProfileParameters = ExecutionProfileParameters()
    feasibility: ProfileFeasibilityRecord | None = None
    supported_backend_profile_ids: tuple[Identifier, ...]
    prerequisite_submission_ids: tuple[Identifier, ...] = ()
    metric_ids: tuple[Identifier, ...] = Field(min_length=1)
    admission: VariationAdmissionRecord
    semantic_equivalence_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def semantics_match_kind(self) -> ExecutionProfileSubmission:
        parameters = self.parameters
        if (self.baseline_submission_id is None) != (self.baseline_submission_sha256 is None):
            raise ValueError("baseline submission ID and hash must be provided together")
        if self.kind is ExecutionProfileKind.CONSTANT_PATH_SPEED:
            if parameters.target_path_speed_m_s is None:
                raise ValueError("constant-path-speed submission requires a target speed")
            if (
                parameters.segment_target_speeds_m_s
                or parameters.target_vertical_rate_m_s
                or parameters.duration_scale
                or parameters.lookahead_time_s
            ):
                raise ValueError("constant-path-speed submission has unrelated parameters")
        elif self.kind is ExecutionProfileKind.RAMPED_SEGMENT_SPEED:
            if not parameters.segment_target_speeds_m_s:
                raise ValueError("segment-speed submission requires a bounded schedule")
            if (
                parameters.target_path_speed_m_s
                or parameters.target_vertical_rate_m_s
                or parameters.duration_scale
                or parameters.lookahead_time_s
                or parameters.maximum_path_tube_error_m
                or parameters.smoothness_percent is not None
            ):
                raise ValueError("segment-speed submission has unrelated parameters")
        elif self.kind is ExecutionProfileKind.BOUNDED_VERTICAL_RATE:
            if parameters.target_vertical_rate_m_s is None:
                raise ValueError("vertical-rate submission requires a target rate")
            if (
                parameters.target_path_speed_m_s
                or parameters.segment_target_speeds_m_s
                or parameters.duration_scale
                or parameters.lookahead_time_s
                or parameters.maximum_path_tube_error_m
                or parameters.smoothness_percent is not None
            ):
                raise ValueError("vertical-rate submission has unrelated parameters")
        elif self.kind is ExecutionProfileKind.DURATION_SCALE:
            if parameters.duration_scale is None:
                raise ValueError("duration-scale submission requires a scale")
            if (
                parameters.target_path_speed_m_s
                or parameters.segment_target_speeds_m_s
                or parameters.target_vertical_rate_m_s
                or parameters.lookahead_time_s
            ):
                raise ValueError("duration-scale submission has unrelated parameters")
        elif self.kind is ExecutionProfileKind.CORNER_TRANSITION:
            if parameters.lookahead_time_s is None or parameters.target_path_speed_m_s is None:
                raise ValueError("corner-transition submission requires lookahead and path speed")
            if (
                parameters.segment_target_speeds_m_s
                or parameters.target_vertical_rate_m_s
                or parameters.duration_scale
            ):
                raise ValueError("corner-transition submission has unrelated parameters")
        elif self.kind in {
            ExecutionProfileKind.PLANNER_RETIMED_BASELINE,
            ExecutionProfileKind.CONSTANT_ROTOR_SPEED,
        } and (
            parameters.target_path_speed_m_s
            or parameters.segment_target_speeds_m_s
            or parameters.target_vertical_rate_m_s
            or parameters.duration_scale
            or parameters.lookahead_time_s
            or parameters.maximum_path_tube_error_m
            or parameters.smoothness_percent is not None
        ):
            raise ValueError("submission kind has unsupported time-law parameters")
        if self.status is SubmissionStatus.EXECUTABLE and not self.supported_backend_profile_ids:
            raise ValueError("executable submission requires an explicit backend mapping")
        if (
            self.kind is ExecutionProfileKind.CONSTANT_ROTOR_SPEED
            and self.status is not SubmissionStatus.PLANNED_NOT_EXECUTABLE
        ):
            raise ValueError("constant rotor speed is not an executable trajectory profile")
        return self

    @property
    def profile_sha256(self) -> str:
        return canonical_sha256(self)

    @property
    def semantic_fingerprint_sha256(self) -> str:
        """Hash behavior-driving inputs while deliberately excluding labels and prose."""

        return canonical_sha256(
            {
                "case_sha256": self.case_sha256,
                "baseline_submission_id": self.baseline_submission_id,
                "baseline_submission_sha256": self.baseline_submission_sha256,
                "kind": self.kind,
                "owner": self.owner,
                "status": self.status,
                "parameters": self.parameters,
                "feasibility": self.feasibility,
                "supported_backend_profile_ids": self.supported_backend_profile_ids,
                "prerequisite_submission_ids": self.prerequisite_submission_ids,
                "principal_variable": self.admission.principal_variable,
                "fixed_inputs": self.admission.fixed_inputs,
            }
        )


def motion_contract_for_execution_profile(
    case: CampaignCase,
    profile: ExecutionProfileSubmission,
) -> MotionQualityContract:
    """Bind the flown time law to the immutable motion-quality guard vector.

    Execution profiles may reorder objectives and declare the requested speed law,
    but they do not silently loosen any of the case's quantitative safety or motion
    guards.  The returned contract is therefore suitable for hashing into the plan,
    trajectory set, execution request, and retained analysis.
    """

    contract = motion_contract_for(case)
    kind = profile.kind
    if kind in {
        ExecutionProfileKind.CONSTANT_PATH_SPEED,
        ExecutionProfileKind.CORNER_TRANSITION,
    }:
        target_speed = (
            profile.parameters.certified_path_speed_m_s or profile.parameters.target_path_speed_m_s
        )
        if target_speed is None:  # Model validation already prevents this.
            raise ValueError(f"{kind.value} profile has no target path speed")
        objectives = (
            (
                MotionQualityMetric.JERK,
                MotionQualityMetric.ANGULAR_ACTIVITY,
                MotionQualityMetric.MOTOR_SPREAD,
                MotionQualityMetric.SPEED_RIPPLE,
                MotionQualityMetric.PATH_ADHERENCE,
                MotionQualityMetric.DURATION,
            )
            if kind is ExecutionProfileKind.CORNER_TRANSITION
            and (
                (profile.parameters.smoothness_percent or 0) >= 50
                or (
                    profile.parameters.smoothness_percent is None
                    and "smoothness" in profile.submission_id
                )
            )
            else (
                MotionQualityMetric.JERK,
                MotionQualityMetric.MOTOR_SPREAD,
                MotionQualityMetric.SPEED_COMPLIANCE,
                MotionQualityMetric.PATH_ADHERENCE,
                MotionQualityMetric.DURATION,
            )
            if kind is ExecutionProfileKind.CONSTANT_PATH_SPEED
            and (profile.parameters.smoothness_percent or 0) >= 50
            else (
                MotionQualityMetric.DURATION,
                MotionQualityMetric.SPEED_RIPPLE,
                MotionQualityMetric.PATH_ADHERENCE,
                MotionQualityMetric.JERK,
            )
            if kind is ExecutionProfileKind.CORNER_TRANSITION
            else (
                MotionQualityMetric.SPEED_COMPLIANCE,
                MotionQualityMetric.SPEED_RIPPLE,
                MotionQualityMetric.PATH_ADHERENCE,
                MotionQualityMetric.JERK,
            )
        )
        return contract.model_copy(
            update={
                "speed_law": MotionSpeedLaw.CONSTANT,
                "target_speed_m_s": target_speed,
                "objective_order": objectives,
                "maximum_path_tube_error_m": (
                    profile.parameters.maximum_path_tube_error_m
                    or contract.maximum_path_tube_error_m
                ),
            }
        )
    if kind is ExecutionProfileKind.RAMPED_SEGMENT_SPEED:
        return contract.model_copy(
            update={
                "speed_law": MotionSpeedLaw.RAMPED,
                "target_speed_m_s": None,
                "objective_order": (
                    MotionQualityMetric.SPEED_COMPLIANCE,
                    MotionQualityMetric.JERK,
                    MotionQualityMetric.PATH_ADHERENCE,
                    MotionQualityMetric.DURATION,
                ),
            }
        )
    if kind is ExecutionProfileKind.DURATION_SCALE:
        return contract.model_copy(
            update={
                "speed_law": MotionSpeedLaw.PRECISION_FIRST,
                "target_speed_m_s": None,
                "objective_order": (
                    (
                        MotionQualityMetric.JERK,
                        MotionQualityMetric.MOTOR_SPREAD,
                        MotionQualityMetric.PATH_ADHERENCE,
                        MotionQualityMetric.DURATION,
                    )
                    if (profile.parameters.smoothness_percent or 0) >= 50
                    else (
                        MotionQualityMetric.DURATION,
                        MotionQualityMetric.PATH_ADHERENCE,
                        MotionQualityMetric.JERK,
                        MotionQualityMetric.ENERGY,
                    )
                ),
                "maximum_path_tube_error_m": (
                    profile.parameters.maximum_path_tube_error_m
                    or contract.maximum_path_tube_error_m
                ),
            }
        )
    return contract


class CapabilityRegistrySpec(ContractModel):
    capability_id: Identifier
    owner: ExecutionProfileOwner
    status: SubmissionStatus
    qualified_backend_profile_ids: tuple[Identifier, ...]
    anchor_case_ids: tuple[Identifier, ...]
    rationale: str = Field(min_length=1, max_length=1000)


class CapabilityRegistry(ContractModel):
    schema_version: Literal[1] = 1
    capabilities: tuple[CapabilityRegistrySpec, ...]

    @model_validator(mode="after")
    def unique_capabilities(self) -> CapabilityRegistry:
        ids = tuple(item.capability_id for item in self.capabilities)
        if len(set(ids)) != len(ids):
            raise ValueError("capability registry IDs must be unique")
        for capability in self.capabilities:
            has_qualification = bool(capability.qualified_backend_profile_ids) and bool(
                capability.anchor_case_ids
            )
            if (capability.status is SubmissionStatus.EXECUTABLE) != has_qualification:
                raise ValueError(
                    f"capability {capability.capability_id} status does not match retained qualification"
                )
        return self


class AdmissionLifecycle(StrEnum):
    SUBMISSIONS = "SUBMISSIONS"
    BASELINE_ONLY = "BASELINE_ONLY"
    RETAIN_EXISTING_ONLY = "RETAIN_EXISTING_ONLY"


class ProposalOracleRecord(ContractModel):
    submission_id: Identifier
    experiment_id: Identifier
    axis: ExperimentAxis
    axis_value: Identifier
    qualifying_relation: str = Field(min_length=1, max_length=1000)
    comparator_id: str | None = Field(default=None, min_length=1, max_length=240)
    comparison_context_id: Identifier | None = None

    @model_validator(mode="after")
    def context_matches_comparator(self) -> ProposalOracleRecord:
        if self.comparison_context_id is None:
            if self.comparator_id is not None and "overlap-capacity-v1" in self.comparator_id:
                raise ValueError("proposal oracle comparator/context mismatch")
        elif (
            self.comparison_context_id != OVERLAP_CAPACITY_CONTEXT_ID
            or self.comparator_id is None
            or OVERLAP_CAPACITY_CONTEXT_ID not in self.comparator_id
        ):
            raise ValueError("proposal oracle comparator/context mismatch")
        if self.comparison_context_id not in {None, OVERLAP_CAPACITY_CONTEXT_ID}:
            raise ValueError("proposal oracle uses an unknown comparison context")
        if self.comparator_id is None and not self.qualifying_relation.startswith(
            ("ARGMAX_BOUNDED(", "OPEN(")
        ):
            raise ValueError("only an absolute or open oracle may omit its comparator")
        return self


class CaseAdmissionRecord(ContractModel):
    case_id: Identifier
    expected_case_sha256: SHA256
    lifecycle: AdmissionLifecycle
    proposed_additions_or_disposition: str = Field(min_length=1, max_length=3000)
    causal_question: str = Field(min_length=1, max_length=3000)
    baseline_limitation: str = Field(min_length=1, max_length=3000)
    fixed_inputs: tuple[Identifier, ...] = Field(min_length=1)
    comparison_and_distinguishing_oracle: str = Field(min_length=1, max_length=3000)
    metric_ids: tuple[Identifier, ...] = Field(min_length=1)
    reused_evidence: tuple[Identifier, ...]
    new_integration_gate: str = Field(min_length=1, max_length=3000)
    backend_semantics: str = Field(min_length=1, max_length=1000)
    safety_bounds: str = Field(min_length=1, max_length=1000)
    operator_comparison: str = Field(min_length=1, max_length=3000)
    learning_value: str = Field(min_length=1, max_length=3000)
    proposals: tuple[ProposalOracleRecord, ...] = ()

    @model_validator(mode="after")
    def row_is_closed(self) -> CaseAdmissionRecord:
        unknown = set(self.metric_ids) - QUALIFICATION_METRIC_IDS
        if unknown:
            raise ValueError(f"admission row {self.case_id} has unknown metrics {sorted(unknown)}")
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError(f"admission row {self.case_id} repeats a metric")
        ids = tuple(item.submission_id for item in self.proposals)
        if len(ids) != len(set(ids)):
            raise ValueError(f"admission row {self.case_id} repeats a proposal")
        if (self.lifecycle is AdmissionLifecycle.SUBMISSIONS) != bool(self.proposals):
            raise ValueError(f"admission row {self.case_id} lifecycle/proposals mismatch")
        for proposal in self.proposals:
            relation_metrics = {
                item
                for item in QUALIFICATION_METRIC_IDS
                if f"({item}" in proposal.qualifying_relation
            }
            if not relation_metrics.issubset(self.metric_ids):
                raise ValueError(
                    f"admission proposal {self.case_id}/{proposal.submission_id} "
                    "uses a metric outside its closed row"
                )
        return self


class AdmissionRegistry(ContractModel):
    schema_version: Literal[1] = 1
    oracle_contract_version: Literal["wp52-56-r6-verified-oracle-v1"]
    rows: tuple[CaseAdmissionRecord, ...] = Field(min_length=55, max_length=55)
    source_payload_sha256: SHA256

    @model_validator(mode="after")
    def exact_identity(self) -> AdmissionRegistry:
        ids = tuple(item.case_id for item in self.rows)
        if len(ids) != len(set(ids)):
            raise ValueError("admission registry case IDs must be unique")
        payload = self.model_dump(mode="python", exclude={"source_payload_sha256"})
        if self.source_payload_sha256 != canonical_sha256(payload):
            raise ValueError("admission registry source payload hash mismatch")
        return self


class RegistrySubmissionSpec(ContractModel):
    submission_id: Identifier
    display_name: str = Field(min_length=1, max_length=160)
    layer: SubmissionLayer
    experiment_id: Identifier
    axis: ExperimentAxis
    axis_value: Identifier
    status: SubmissionStatus
    catalog_visible: bool = True
    rationale: str = Field(min_length=1, max_length=1000)
    causal_question: str = Field(min_length=1, max_length=1000)
    baseline_limitation: str = Field(min_length=1, max_length=1000)
    behavior_difference: str = Field(min_length=1, max_length=1000)
    distinguishing_oracle: str = Field(min_length=1, max_length=1000)
    learning_value: str = Field(min_length=1, max_length=1000)
    objective_focus: tuple[ObjectiveMetric, ...] = ()
    selection_oracle: PlanningSelectionOracle = PlanningSelectionOracle.OBJECTIVE_ORDER
    strategy_authority: tuple[PlannerStrategy, ...] = ()
    path_adherence_mode: PathAdherenceMode = PathAdherenceMode.REQUIRED_REGIONS
    maximum_centerline_deviation_m: float | None = Field(default=None, gt=0.0)
    synchronized: bool | None = None
    minimum_simultaneous_flight_s: float | None = Field(default=None, ge=0.0)
    fallback_policy: FallbackPolicy | None = None
    capability_id: Identifier | None = None
    execution_kind: ExecutionProfileKind | None = None
    execution_parameters: ExecutionProfileParameters = ExecutionProfileParameters()
    reused_evidence: tuple[Identifier, ...]
    prerequisite_submission_ids: tuple[Identifier, ...] = ()
    new_integration_gate: str = Field(min_length=1, max_length=1000)
    backend_semantics: str = Field(min_length=1, max_length=1000)
    safety_bounds: str = Field(min_length=1, max_length=1000)
    operator_comparison: str = Field(min_length=1, max_length=1000)
    support_reason: str = Field(
        default="Compiled through the declared campaign backend when the immutable case and owning capability are executable.",
        min_length=1,
        max_length=1000,
    )

    @model_validator(mode="after")
    def one_layer_and_axis(self) -> RegistrySubmissionSpec:
        if self.layer is SubmissionLayer.REPLANNING_POLICY and self.fallback_policy is None:
            raise ValueError("registry replanning row requires fallback_policy")
        if self.layer is not SubmissionLayer.REPLANNING_POLICY and self.fallback_policy is not None:
            raise ValueError("fallback_policy is only valid for replanning rows")
        if self.layer is SubmissionLayer.EXECUTION_PROFILE and self.execution_kind is None:
            raise ValueError("registry execution row requires execution_kind")
        if self.layer is SubmissionLayer.CORE_CAPABILITY and self.capability_id is None:
            raise ValueError("registry capability row requires capability_id")
        if (
            self.path_adherence_mode
            in {
                PathAdherenceMode.EXACT_ROUTE,
                PathAdherenceMode.HARD_TUBE,
                PathAdherenceMode.ROUTE_CORRIDOR,
                PathAdherenceMode.AUTHORED_CENTERLINE,
            }
            and self.maximum_centerline_deviation_m is None
        ):
            raise ValueError("registry hard-adherence row requires deviation")
        return self


class CaseSubmissionRegistryRow(ContractModel):
    case_id: Identifier
    expected_case_sha256: SHA256
    compatible_template_ids: tuple[Identifier, ...] = ()
    default_strategy_authority: tuple[PlannerStrategy, ...] = Field(min_length=1)
    baseline_only: bool = False
    retain_existing_only: bool = False
    baseline_only_rationale: str | None = Field(default=None, min_length=1, max_length=1000)
    submissions: tuple[RegistrySubmissionSpec, ...] = ()

    @model_validator(mode="after")
    def disposition_is_complete(self) -> CaseSubmissionRegistryRow:
        if self.baseline_only != bool(self.baseline_only_rationale):
            raise ValueError("baseline-only row requires exactly one rationale")
        if self.baseline_only and self.retain_existing_only:
            raise ValueError("registry row cannot be baseline-only and retain-existing-only")
        if self.baseline_only and self.submissions:
            raise ValueError("baseline-only row cannot contain submissions")
        if self.retain_existing_only and self.submissions:
            raise ValueError("retain-existing row cannot add registry submissions")
        if not self.baseline_only and not self.retain_existing_only and not self.submissions:
            raise ValueError("admitted row requires submissions")
        ids = tuple(item.submission_id for item in self.submissions)
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate registry submission in {self.case_id}")
        for experiment_id in {item.experiment_id for item in self.submissions}:
            experiment = tuple(
                item for item in self.submissions if item.experiment_id == experiment_id
            )
            axes = {item.axis for item in experiment}
            if len(axes) != 1:
                raise ValueError(f"experiment {experiment_id} changes multiple axes")
            values = tuple(item.axis_value for item in experiment)
            if len(set(values)) != len(values):
                raise ValueError(f"experiment {experiment_id} repeats an axis value")
            behavior_fields = {
                "layer",
                "objective_focus",
                "selection_oracle",
                "strategy_authority",
                "path_adherence_mode",
                "maximum_centerline_deviation_m",
                "synchronized",
                "minimum_simultaneous_flight_s",
                "fallback_policy",
                "capability_id",
                "execution_kind",
                "execution_parameters",
            }
            variable_fields = {
                ExperimentAxis.OBJECTIVE_ORDER: {"objective_focus", "selection_oracle"},
                ExperimentAxis.MANEUVER_DIMENSION: {"strategy_authority"},
                ExperimentAxis.FALLBACK_POLICY: {"fallback_policy"},
                ExperimentAxis.SCALAR_PARAMETER: {"execution_parameters"},
                ExperimentAxis.CAPABILITY_BINDING: {
                    "capability_id",
                    "execution_kind",
                    "execution_parameters",
                },
            }[next(iter(axes))]
            fixed_fields = behavior_fields - variable_fields
            reference = experiment[0].model_dump(mode="python")
            for alternative in experiment[1:]:
                candidate = alternative.model_dump(mode="python")
                changed_fixed = tuple(
                    field for field in sorted(fixed_fields) if reference[field] != candidate[field]
                )
                if changed_fixed:
                    raise ValueError(
                        f"experiment {experiment_id} changes fixed behavior fields "
                        f"{changed_fixed} outside {next(iter(axes)).value}"
                    )
        return self


class CaseSubmissionRegistry(ContractModel):
    schema_version: Literal[1] = 1
    reviewed_counts: dict[Literal["1d", "2d", "3d"], int]
    rows: tuple[CaseSubmissionRegistryRow, ...]

    @model_validator(mode="after")
    def unique_cases(self) -> CaseSubmissionRegistry:
        observed = {
            "1d": sum(item.case_id.startswith("1d.") for item in self.rows),
            "2d": sum(item.case_id.startswith("2d.") for item in self.rows),
            "3d": sum(
                item.case_id.startswith("3d.") or item.case_id == "three_drone_multi_conflict"
                for item in self.rows
            ),
        }
        if self.reviewed_counts != observed or observed != {"1d": 21, "2d": 18, "3d": 16}:
            raise ValueError(f"submission registry cardinality mismatch: {observed}")
        case_ids = tuple(item.case_id for item in self.rows)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("submission registry case IDs must be unique")
        return self


@lru_cache(maxsize=1)
def load_capability_registry() -> CapabilityRegistry:
    payload = yaml.safe_load(CAPABILITY_REGISTRY_PATH.read_text(encoding="utf-8"))
    return CapabilityRegistry.model_validate(payload)


@lru_cache(maxsize=1)
def load_admission_registry() -> AdmissionRegistry:
    payload = yaml.safe_load(ADMISSION_RECORDS_PATH.read_text(encoding="utf-8"))
    return AdmissionRegistry.model_validate(payload)


def validate_admission_registry(
    registry: CaseSubmissionRegistry,
    admissions: AdmissionRegistry,
) -> None:
    rows_by_id = {item.case_id: item for item in registry.rows}
    admissions_by_id = {item.case_id: item for item in admissions.rows}
    if set(rows_by_id) != set(admissions_by_id):
        raise ValueError(
            "admission registry coverage mismatch: "
            f"missing={sorted(set(rows_by_id) - set(admissions_by_id))}, "
            f"extra={sorted(set(admissions_by_id) - set(rows_by_id))}"
        )
    contextual_keys = set()
    for case_id, row in rows_by_id.items():
        admission = admissions_by_id[case_id]
        if admission.expected_case_sha256 != row.expected_case_sha256:
            raise ValueError(f"admission registry case hash mismatch for {case_id}")
        expected_lifecycle = (
            AdmissionLifecycle.BASELINE_ONLY
            if row.baseline_only
            else (
                AdmissionLifecycle.RETAIN_EXISTING_ONLY
                if row.retain_existing_only
                else AdmissionLifecycle.SUBMISSIONS
            )
        )
        if admission.lifecycle is not expected_lifecycle:
            raise ValueError(f"admission lifecycle mismatch for {case_id}")
        specs = {item.submission_id: item for item in row.submissions}
        oracles = {item.submission_id: item for item in admission.proposals}
        if set(specs) != set(oracles):
            raise ValueError(f"admission proposal coverage mismatch for {case_id}")
        for submission_id, spec in specs.items():
            oracle = oracles[submission_id]
            if (
                oracle.experiment_id != spec.experiment_id
                or oracle.axis is not spec.axis
                or oracle.axis_value != spec.axis_value
            ):
                raise ValueError(f"admission proposal axis mismatch for {case_id}/{submission_id}")
            if oracle.comparison_context_id is not None:
                contextual_keys.add(f"{case_id}/{submission_id}")
    expected_contextual_keys = {
        "2d.head_on_conflict.canonical_nominal/head_on.earliest_safe_release",
        "2d.merge.canonical_nominal/merge.fair_release",
        ("2d.perpendicular_crossing.nominal_equal_priority/crossing.earliest_equal_release"),
    }
    if contextual_keys != expected_contextual_keys:
        raise ValueError(
            f"admission registry overlap-capacity context mismatch: {sorted(contextual_keys)}"
        )
    hidden_keys = {
        f"{row.case_id}/{item.submission_id}"
        for row in registry.rows
        for item in row.submissions
        if not item.catalog_visible
    }
    admission_collapse_keys = {
        f"{row.case_id}/{item.submission_id}"
        for row in admissions.rows
        for item in row.proposals
        if item.qualifying_relation == "COLLAPSE_ALL"
    }
    if hidden_keys != admission_collapse_keys or len(hidden_keys) != 21:
        raise ValueError("current hidden/collapse partition must contain the same exact 21 keys")
    distinguished_keys = {
        f"{row.case_id}/{item.submission_id}"
        for row in admissions.rows
        for item in row.proposals
        if item.qualifying_relation == "DISTINGUISHABLE_AFTER_WP58_WHOLE_ROUTE_SMOOTHING"
    }
    if len(distinguished_keys) != 7 or distinguished_keys & hidden_keys:
        raise ValueError("WP58 distinguished proposals must be seven visible non-collapse keys")

    boundary = admissions_by_id["1d.boundary_constrained_route.canonical_nominal"]
    if "Continuous boundary clearance and reference deviation" not in (
        boundary.comparison_and_distinguishing_oracle
    ):
        raise ValueError("boundary admission lost its continuous-clearance oracle")
    rounded = admissions_by_id["1d.planar_shape_loop.rounded_square"]
    if not all(
        phrase in rounded.comparison_and_distinguishing_oracle
        for phrase in ("transition start", "corner cut", "curvature", "jerk", "loop closure")
    ):
        raise ValueError("rounded-square admission lost its steering oracle")
    head_on = admissions_by_id["2d.head_on_conflict.canonical_nominal"]
    if "cannot pass by full serialization" not in head_on.comparison_and_distinguishing_oracle:
        raise ValueError("head-on admission lost its both-role participation gate")
    selective = admissions_by_id["3d.single_pair_conflict.canonical_nominal"]
    if "Gamma path/delay" not in selective.comparison_and_distinguishing_oracle:
        raise ValueError("3D selective admission lost unaffected-role evidence")


@lru_cache(maxsize=1)
def load_case_submission_registry() -> CaseSubmissionRegistry:
    payload = yaml.safe_load(SUBMISSION_REGISTRY_PATH.read_text(encoding="utf-8"))
    registry = CaseSubmissionRegistry.model_validate(payload)
    validate_admission_registry(registry, load_admission_registry())
    return registry


def admission_record_for_case(case: CampaignCase) -> CaseAdmissionRecord:
    source = _registry_source_row_for_case(case)
    record = next(item for item in load_admission_registry().rows if item.case_id == source.case_id)
    if source.case_id == case.case_id:
        return record
    return record.model_copy(
        update={"case_id": case.case_id, "expected_case_sha256": case.case_sha256}
    )


def proposal_oracle_for_case(
    case: CampaignCase,
    submission_id: str,
) -> ProposalOracleRecord:
    record = admission_record_for_case(case)
    return next(item for item in record.proposals if item.submission_id == submission_id)


def _registry_source_row_for_case(case: CampaignCase) -> CaseSubmissionRegistryRow:
    registry = load_case_submission_registry()
    row = next(
        (item for item in registry.rows if item.case_id == case.case_id),
        None,
    )
    if row is not None:
        if row.expected_case_sha256 != case.case_sha256:
            raise ValueError(
                f"submission registry case hash mismatch for {case.case_id}: "
                f"expected {row.expected_case_sha256}, observed {case.case_sha256}"
            )
        return row
    if row is None and case.parent_case_sha256 is not None:
        parents = tuple(
            item
            for item in registry.rows
            if item.expected_case_sha256 == case.parent_case_sha256
            and case.template_id in item.compatible_template_ids
        )
        if len(parents) == 1:
            return parents[0]
    if row is None:
        compatible_rows = tuple(
            item for item in registry.rows if case.template_id in item.compatible_template_ids
        )
        if len(compatible_rows) == 1:
            return compatible_rows[0]
    raise ValueError(f"submission registry omits compatible case {case.case_id}")


def registry_row_for_case(case: CampaignCase) -> CaseSubmissionRegistryRow:
    source = _registry_source_row_for_case(case)
    if source.case_id == case.case_id:
        return source
    return source.model_copy(
        update={"case_id": case.case_id, "expected_case_sha256": case.case_sha256}
    )


def validate_registry_coverage(cases: tuple[CampaignCase, ...]) -> None:
    registry_ids = {item.case_id for item in load_case_submission_registry().rows}
    discovered_ids = {item.case_id for item in cases}
    if registry_ids != discovered_ids:
        raise ValueError(
            "submission registry coverage mismatch: "
            f"missing={sorted(discovered_ids - registry_ids)}, "
            f"extra={sorted(registry_ids - discovered_ids)}"
        )
    for case in cases:
        registry_row_for_case(case)


def _baseline_execution_profile(case: CampaignCase) -> ExecutionProfileSubmission:
    return _submission(
        case,
        submission_id=BASELINE_SUBMISSION_ID,
        display_name="Planner-retimed baseline",
        kind=ExecutionProfileKind.PLANNER_RETIMED_BASELINE,
        owner=ExecutionProfileOwner.PLANNER,
        status=(
            SubmissionStatus.EXECUTABLE
            if (
                case.environment is EnvironmentKind.SIMULATION
                and case.implementation_status is ImplementationStatus.EXECUTABLE
            )
            else SubmissionStatus.PLANNED_NOT_EXECUTABLE
        ),
        rationale="Retains the case's existing bounded planner and time-allocation behavior.",
        metric_ids=("route_tracking", "dynamics", "energy", "landing"),
        principal_variable="planner_selected_time_law",
        causal_question="What behavior does the existing bounded planner select for this case?",
        baseline_limitation="This is the comparison baseline rather than a claimed new behavior.",
        behavior_difference="No successor profile override; current compatible behavior is retained.",
        distinguishing_oracle="Accepted plan and trajectory identities reproduce the retained baseline.",
        new_gate="Baseline evidence must be complete and deterministic.",
        learning_value="Provides the immutable comparison point for eligible successor submissions.",
    )


def submissions_for_case(case: CampaignCase) -> tuple[ExecutionProfileSubmission, ...]:
    baseline = _baseline_execution_profile(case)
    if case.family != "altitude_transition":
        row = registry_row_for_case(case)
        return validate_submission_set(
            (
                baseline,
                *(
                    _execution_submission_from_spec(case, baseline, spec)
                    for spec in row.submissions
                    if spec.layer
                    in {SubmissionLayer.EXECUTION_PROFILE, SubmissionLayer.CORE_CAPABILITY}
                ),
            )
        )

    feasibility = _constant_path_speed_feasibility(case)
    slow_target_m_s = round(feasibility.maximum_path_speed_m_s * 0.36, 2)
    stress_target_m_s = round(
        min(0.30, feasibility.maximum_path_speed_m_s * 0.72),
        2,
    )
    vertical_rate_target_m_s = round(
        case.hard_constraints.dynamics.maximum_vertical_speed_m_s * 0.5333333333,
        2,
    )

    common = [baseline]
    source_case_id = _registry_source_row_for_case(case).case_id
    if source_case_id == "1d.altitude_transition.canonical_nominal":
        common.extend(
            (
                _submission(
                    case,
                    submission_id="constant_path_speed.slow",
                    display_name="Constant path speed · slow",
                    kind=ExecutionProfileKind.CONSTANT_PATH_SPEED,
                    owner=ExecutionProfileOwner.TIME_PARAMETERIZER,
                    parameters=ExecutionProfileParameters(target_path_speed_m_s=slow_target_m_s),
                    feasibility=feasibility,
                    baseline_submission_sha256=baseline.profile_sha256,
                    rationale="Establishes constant scalar route-speed tracking with generous authority margin.",
                    metric_ids=(
                        "path_speed_error",
                        "route_tracking",
                        "actuator_headroom",
                        "energy",
                    ),
                    principal_variable="target_path_speed_m_s",
                    causal_question="Can coupled horizontal/vertical motion retain a constant 0.18 m/s path speed?",
                    baseline_limitation="The planner-retimed baseline deliberately changes speed around altitude knots.",
                    behavior_difference="Segment times are derived from route arc length and one scalar speed target.",
                    distinguishing_oracle="Steady-window path-speed error remains inside the profile tolerance.",
                    new_gate="Qualify path-speed tracking while thrust and attitude remain controller-owned.",
                    learning_value="Qualifies the reusable low-stress constant-speed primitive once.",
                ),
                _submission(
                    case,
                    submission_id="constant_path_speed.stress",
                    display_name="Constant path speed · stress",
                    kind=ExecutionProfileKind.CONSTANT_PATH_SPEED,
                    owner=ExecutionProfileOwner.TIME_PARAMETERIZER,
                    parameters=ExecutionProfileParameters(target_path_speed_m_s=stress_target_m_s),
                    feasibility=feasibility,
                    baseline_submission_sha256=baseline.profile_sha256,
                    prerequisites=("constant_path_speed.slow",),
                    rationale="Probes a higher operating region without changing geometry or controller authority.",
                    metric_ids=(
                        "path_speed_error",
                        "route_tracking",
                        "actuator_headroom",
                        "energy",
                    ),
                    principal_variable="target_path_speed_m_s",
                    causal_question="Does higher constant path speed materially change tracking, headroom, or energy?",
                    baseline_limitation="The slow anchor cannot expose the higher-speed authority margin.",
                    behavior_difference="The same constant-speed law uses a 0.30 m/s target.",
                    distinguishing_oracle="The target is met and at least one declared operating metric differs from slow.",
                    new_gate="Slow-anchor qualification is reused; only the higher operating region is new.",
                    learning_value="Adds one bounded stress anchor rather than a dense arbitrary sweep.",
                ),
                _submission(
                    case,
                    submission_id="ramped_segment_speed.altitude_kinks",
                    display_name="Ramped speed changes at altitude knots",
                    kind=ExecutionProfileKind.RAMPED_SEGMENT_SPEED,
                    owner=ExecutionProfileOwner.TIME_PARAMETERIZER,
                    parameters=ExecutionProfileParameters(
                        segment_target_speeds_m_s=(
                            slow_target_m_s,
                            round(stress_target_m_s * 0.92, 2),
                            round(slow_target_m_s + 0.02, 2),
                            stress_target_m_s,
                        )
                    ),
                    feasibility=feasibility,
                    baseline_submission_sha256=baseline.profile_sha256,
                    prerequisites=("constant_path_speed.slow",),
                    rationale="Makes the speed changes at altitude knots intentional and machine-evaluable.",
                    metric_ids=(
                        "speed_transition_overshoot",
                        "settling_time",
                        "jerk",
                        "route_tracking",
                    ),
                    principal_variable="segment_target_speeds_m_s",
                    causal_question="Are deliberate slow/fast transitions tracked smoothly at altitude knots?",
                    baseline_limitation="Baseline changes are planner side-effects rather than an authored speed schedule.",
                    behavior_difference="Each segment receives one target and quintic interpolation ramps between them.",
                    distinguishing_oracle="Transition overshoot, settling, acceleration, and jerk remain bounded.",
                    new_gate="Reuse constant-speed tracking and qualify only requested transitions.",
                    learning_value="Separates acceptable planned speed variation from controller oscillation.",
                ),
            )
        )
    elif source_case_id == "1d.altitude_transition.wide":
        common.extend(
            (
                _submission(
                    case,
                    submission_id="constant_path_speed.stress",
                    display_name="Constant path speed · wide stress",
                    kind=ExecutionProfileKind.CONSTANT_PATH_SPEED,
                    owner=ExecutionProfileOwner.TIME_PARAMETERIZER,
                    parameters=ExecutionProfileParameters(target_path_speed_m_s=stress_target_m_s),
                    feasibility=feasibility,
                    baseline_submission_sha256=baseline.profile_sha256,
                    prerequisites=(
                        "1d.altitude_transition.canonical_nominal:constant_path_speed.stress",
                    ),
                    rationale="Repeats only the speed profile whose result can change under the wider altitude envelope.",
                    metric_ids=(
                        "path_speed_error",
                        "vertical_tracking",
                        "actuator_headroom",
                        "energy",
                    ),
                    principal_variable="altitude_envelope",
                    causal_question="Does the wider altitude envelope reduce constant-speed control margin?",
                    baseline_limitation="Canonical stress cannot expose the larger climb/descent amplitude.",
                    behavior_difference="The qualified stress law is applied to the immutable wide geometry.",
                    distinguishing_oracle="Wide/canonical deltas are reported for vertical tracking, headroom, and energy.",
                    new_gate="Reuse canonical profile qualification and test only envelope coupling.",
                    learning_value="Turns wide into a causal vertical-envelope comparison instead of a duplicate sweep.",
                ),
                _submission(
                    case,
                    submission_id="bounded_vertical_rate.wide",
                    display_name="Bounded vertical rate · wide",
                    kind=ExecutionProfileKind.BOUNDED_VERTICAL_RATE,
                    owner=ExecutionProfileOwner.TIME_PARAMETERIZER,
                    parameters=ExecutionProfileParameters(
                        target_vertical_rate_m_s=vertical_rate_target_m_s
                    ),
                    feasibility=feasibility,
                    baseline_submission_sha256=baseline.profile_sha256,
                    prerequisites=(
                        "1d.altitude_transition.canonical_nominal:constant_path_speed.slow",
                    ),
                    rationale="Holds a bounded climb/descent rate while horizontal pace adapts to the wide route.",
                    metric_ids=(
                        "vertical_rate_error",
                        "horizontal_progress",
                        "actuator_headroom",
                        "energy",
                    ),
                    principal_variable="target_vertical_rate_m_s",
                    causal_question="Can wide climbs and descents hold a bounded vertical rate without losing route capture?",
                    baseline_limitation="A scalar path-speed target does not isolate vertical-axis authority.",
                    behavior_difference="Climb/descent segment duration is derived from vertical distance and target rate.",
                    distinguishing_oracle="Vertical-rate error and horizontal progress remain bounded without route stops.",
                    new_gate="Reuse lower-level motion and qualify vertical-axis coupling only.",
                    learning_value="Adds a wide-specific control question rather than copying the canonical schedule.",
                ),
            )
        )

    common.append(
        _submission(
            case,
            submission_id="constant_rotor_speed",
            display_name="Constant rotor speed · unavailable",
            kind=ExecutionProfileKind.CONSTANT_ROTOR_SPEED,
            owner=ExecutionProfileOwner.LOW_LEVEL_ACTUATOR,
            status=SubmissionStatus.PLANNED_NOT_EXECUTABLE,
            baseline_submission_sha256=baseline.profile_sha256,
            rationale="Reserved for a calibrated, contained low-level actuator experiment.",
            metric_ids=("rotor_speed_error", "thrust", "containment"),
            principal_variable="rotor_speed",
            causal_question="What motion results from a fixed low-level rotor-speed command?",
            baseline_limitation="Trajectory tracking requires varying thrust and cannot answer an open-loop actuator question.",
            behavior_difference="Would replace trajectory-controller authority with a fixed low-level actuator objective.",
            distinguishing_oracle="Rotor speed, thrust, containment, and safe termination would be measured directly.",
            new_gate="Requires calibrated motor semantics, low-level adapter capability, and separate authorization.",
            learning_value="Documents the valid future diagnostic without pretending it is a successful path profile.",
        )
    )
    return validate_submission_set(tuple(common))


def _execution_submission_from_spec(
    case: CampaignCase,
    baseline: ExecutionProfileSubmission,
    spec: RegistrySubmissionSpec,
) -> ExecutionProfileSubmission:
    kind = spec.execution_kind
    if kind is None:
        raise ValueError(f"registry execution choice {spec.submission_id} has no execution kind")
    feasibility = (
        _constant_path_speed_feasibility(case)
        if kind
        in {
            ExecutionProfileKind.CONSTANT_PATH_SPEED,
            ExecutionProfileKind.CORNER_TRANSITION,
        }
        else None
    )
    owner = (
        ExecutionProfileOwner.TIME_PARAMETERIZER
        if kind is not ExecutionProfileKind.CORNER_TRANSITION
        else ExecutionProfileOwner.TRAJECTORY_TRACKER
    )
    return _submission(
        case,
        submission_id=spec.submission_id,
        display_name=spec.display_name,
        kind=kind,
        owner=owner,
        status=spec.status,
        parameters=spec.execution_parameters,
        feasibility=feasibility,
        baseline_submission_sha256=baseline.profile_sha256,
        rationale=spec.rationale,
        metric_ids=admission_record_for_case(case).metric_ids,
        principal_variable=spec.axis.value.lower(),
        causal_question=spec.causal_question,
        baseline_limitation="The retained planner time law cannot isolate this declared scalar or capability binding.",
        behavior_difference=spec.behavior_difference,
        distinguishing_oracle=spec.distinguishing_oracle,
        new_gate=spec.new_integration_gate,
        learning_value=spec.learning_value,
        prerequisites=spec.prerequisite_submission_ids,
        admission_override=_admission_from_record(case, spec),
    )


def validate_submission_set(
    submissions: tuple[ExecutionProfileSubmission, ...],
) -> tuple[ExecutionProfileSubmission, ...]:
    """Reject label-only duplicates before they become catalog-visible choices."""

    by_id: dict[str, ExecutionProfileSubmission] = {}
    by_fingerprint: dict[str, ExecutionProfileSubmission] = {}
    for submission in submissions:
        if submission.submission_id in by_id:
            raise ValueError(f"duplicate execution-profile ID: {submission.submission_id}")
        by_id[submission.submission_id] = submission
        existing = by_fingerprint.get(submission.semantic_fingerprint_sha256)
        if existing is not None and not submission.semantic_equivalence_reason:
            raise ValueError(
                "execution profiles "
                f"{existing.submission_id!r} and {submission.submission_id!r} have the same "
                "behavioral semantic fingerprint; change a behavior-driving input or provide "
                "an explicit accepted semantic-equivalence reason"
            )
        by_fingerprint[submission.semantic_fingerprint_sha256] = submission
    return submissions


def resolve_submission(
    case: CampaignCase,
    submission_id: str | None,
    *,
    require_executable: bool = True,
) -> ExecutionProfileSubmission:
    selected_id = submission_id or BASELINE_SUBMISSION_ID
    selected = next(
        (item for item in submissions_for_case(case) if item.submission_id == selected_id),
        None,
    )
    if selected is None:
        raise ValueError(f"submission {selected_id!r} is not admitted for case {case.case_id}")
    if require_executable and selected.status is not SubmissionStatus.EXECUTABLE:
        raise ValueError(
            f"submission {selected.submission_id} is {selected.status.value}: {selected.rationale}"
        )
    if (
        require_executable
        and case.execution.backend_profile_id not in selected.supported_backend_profile_ids
    ):
        raise ValueError(
            f"submission {selected.submission_id} does not support backend "
            f"{case.execution.backend_profile_id}"
        )
    return selected


def planning_submissions_for_case(case: CampaignCase) -> tuple[PlanningSubmission, ...]:
    """Return case-bound planning choices without changing the authored case/world."""

    profile = resolve_submission(case, None, require_executable=False)
    world = planning_world_definition(case)
    vehicle_model = planning_vehicle_model()
    coordination = case.semantics.coordination_constraints if case.semantics else None
    base = _planning_submission(
        case,
        profile=profile,
        world=world,
        vehicle_model=vehicle_model,
        planning_submission_id=BASELINE_PLANNING_SUBMISSION_ID,
        display_name="Authored case planning authority",
        rationale=(
            "Uses the immutable case constraints, every authored strategy, and explicit "
            "lexicographic objective semantics."
        ),
        path_adherence=(
            PathAdherencePolicy(
                mode=PathAdherenceMode.ROUTE_CORRIDOR,
                maximum_centerline_deviation_m=0.25,
            )
            if case.semantics and case.semantics.environment_constraints.required_corridors
            else PathAdherencePolicy()
        ),
        synchronized_launch_required=case.hard_constraints.synchronized_launch_required,
        synchronized_route_start_required=(
            coordination.synchronized_route_start_required if coordination else False
        ),
        minimum_simultaneous_flight_s=(
            coordination.minimum_simultaneous_flight_s if coordination else 0.0
        ),
    )
    row = registry_row_for_case(case)
    compiled = [base]
    for spec in row.submissions:
        if not spec.catalog_visible:
            continue
        if spec.layer not in {
            SubmissionLayer.PLANNING,
            SubmissionLayer.REPLANNING_POLICY,
        }:
            continue
        compiled.append(compile_registry_planning_submission(case, spec))
    return validate_planning_submission_set(tuple(compiled))


def compile_registry_planning_submission(
    case: CampaignCase,
    spec: RegistrySubmissionSpec,
    *,
    audit_hidden: bool = False,
) -> PlanningSubmission:
    """Compile one exact registry row, retaining hidden rows only for collapse proof."""

    if not spec.catalog_visible and not audit_hidden:
        raise ValueError("hidden registry submission may only compile for collapse audit")
    if spec.layer not in {SubmissionLayer.PLANNING, SubmissionLayer.REPLANNING_POLICY}:
        raise ValueError("registry submission is not planning-owned")
    profile = resolve_submission(case, None, require_executable=False)
    coordination = case.semantics.coordination_constraints if case.semantics else None
    synchronized = (
        spec.synchronized
        if spec.synchronized is not None
        else case.hard_constraints.synchronized_launch_required
    )
    audit_spec = (
        spec.model_copy(update={"status": SubmissionStatus.EXECUTABLE})
        if audit_hidden
        and case.implementation_status is ImplementationStatus.EXECUTABLE
        and case.execution.backend_profile_id == "fast-sim-v1"
        else spec
    )
    return _planning_submission(
        case,
        profile=profile,
        world=planning_world_definition(case),
        vehicle_model=planning_vehicle_model(),
        planning_submission_id=spec.submission_id,
        display_name=spec.display_name,
        rationale=spec.rationale,
        path_adherence=PathAdherencePolicy(
            mode=spec.path_adherence_mode,
            maximum_centerline_deviation_m=spec.maximum_centerline_deviation_m,
        ),
        synchronized_launch_required=synchronized,
        synchronized_route_start_required=synchronized,
        minimum_simultaneous_flight_s=(
            spec.minimum_simultaneous_flight_s
            if spec.minimum_simultaneous_flight_s is not None
            else (coordination.minimum_simultaneous_flight_s if coordination else 0.0)
        ),
        spec=audit_spec,
    )


def compile_contextual_planning_submission(
    case: CampaignCase,
    planning_submission_id: str | None = None,
    *,
    comparison_context_id: str,
) -> PlanningSubmission:
    """Compile the R6 symmetric positive-overlap capacity comparator."""

    if comparison_context_id != OVERLAP_CAPACITY_CONTEXT_ID:
        raise ValueError(f"unknown planning comparison context: {comparison_context_id}")
    if canonical_sha256(OVERLAP_CAPACITY_CONTEXT) != OVERLAP_CAPACITY_CONTEXT_SHA256:
        raise ValueError("overlap capacity context bytes no longer match their frozen hash")
    selected_id = planning_submission_id or BASELINE_PLANNING_SUBMISSION_ID
    baseline = resolve_planning_submission(case, BASELINE_PLANNING_SUBMISSION_ID)
    if selected_id == BASELINE_PLANNING_SUBMISSION_ID:
        source = baseline
        contextual_id = f"{BASELINE_PLANNING_SUBMISSION_ID}.{OVERLAP_CAPACITY_CONTEXT_ID}"
    else:
        oracle = proposal_oracle_for_case(case, selected_id)
        if oracle.comparison_context_id != OVERLAP_CAPACITY_CONTEXT_ID:
            raise ValueError(f"planning submission {selected_id} is outside overlap-capacity-v1")
        source = resolve_planning_submission(case, selected_id, require_executable=False)
        contextual_id = selected_id
    coordination = baseline.coordination.model_copy(update=OVERLAP_CAPACITY_CONTEXT)
    updates: dict[str, object] = {
        "planning_submission_id": contextual_id,
        "display_name": source.display_name,
        "status": source.status,
        "rationale": source.rationale,
        "coordination": coordination,
        "experiment_id": source.experiment_id,
        "experiment_axis": source.experiment_axis,
        "axis_value": source.axis_value,
        "layer": source.layer,
        "selection_oracle": source.selection_oracle,
        "fallback_policy": source.fallback_policy,
        "capability_id": source.capability_id,
        "admission": source.admission,
        "comparison_context_id": OVERLAP_CAPACITY_CONTEXT_ID,
        "comparison_context_sha256": OVERLAP_CAPACITY_CONTEXT_SHA256,
        "support_reason": (
            f"Qualification-only symmetric {OVERLAP_CAPACITY_CONTEXT_ID} binding; "
            "the immutable case and catalog remain unchanged."
        ),
    }
    if source.experiment_axis is ExperimentAxis.MANEUVER_DIMENSION:
        updates.update(
            {
                "strategy_authority": source.strategy_authority,
                "maneuver_dimensions": source.maneuver_dimensions,
            }
        )
    elif source.experiment_axis is ExperimentAxis.OBJECTIVE_ORDER:
        updates["objective"] = source.objective
    else:
        raise ValueError(f"overlap comparison does not define axis {source.experiment_axis.value}")
    return baseline.model_copy(update=updates)


def validate_planning_submission_set(
    submissions: tuple[PlanningSubmission, ...],
) -> tuple[PlanningSubmission, ...]:
    by_id: dict[str, PlanningSubmission] = {}
    by_fingerprint: dict[str, PlanningSubmission] = {}
    for submission in submissions:
        if submission.planning_submission_id in by_id:
            raise ValueError(
                f"duplicate planning-submission ID: {submission.planning_submission_id}"
            )
        by_id[submission.planning_submission_id] = submission
        existing = by_fingerprint.get(submission.semantic_fingerprint_sha256)
        if existing is not None:
            raise ValueError(
                "planning submissions "
                f"{existing.planning_submission_id!r} and "
                f"{submission.planning_submission_id!r} have the same behavioral "
                "semantic fingerprint"
            )
        by_fingerprint[submission.semantic_fingerprint_sha256] = submission
    return submissions


def resolve_planning_submission(
    case: CampaignCase,
    planning_submission_id: str | None,
    *,
    require_executable: bool = True,
) -> PlanningSubmission:
    selected_id = planning_submission_id or BASELINE_PLANNING_SUBMISSION_ID
    selected = next(
        (
            item
            for item in planning_submissions_for_case(case)
            if item.planning_submission_id == selected_id
        ),
        None,
    )
    if selected is None:
        raise ValueError(
            f"planning submission {selected_id!r} is not admitted for case {case.case_id}"
        )
    if require_executable and selected.status is not SubmissionStatus.EXECUTABLE:
        raise ValueError(
            f"planning submission {selected.planning_submission_id} is "
            f"{selected.status.value}: {selected.rationale}"
        )
    if (
        require_executable
        and case.execution.backend_profile_id not in selected.supported_backend_profile_ids
    ):
        raise ValueError(
            f"planning submission {selected.planning_submission_id} does not support backend "
            f"{case.execution.backend_profile_id}"
        )
    return selected


def planning_world_definition(case: CampaignCase) -> dict[str, object]:
    environment = case.semantics.environment_constraints if case.semantics else None
    return {
        "schema_version": 1,
        "coordinate_frame": "ENU",
        "flight_volume": case.hard_constraints.flight_volume.model_dump(mode="python"),
        "solid_regions": tuple(
            region.model_dump(mode="python")
            for region in (environment.keep_out_regions if environment else ())
        ),
        "traversable_regions": tuple(
            region.model_dump(mode="python")
            for region in (environment.required_corridors if environment else ())
        ),
    }


def planning_vehicle_model() -> dict[str, object]:
    return {
        "schema_version": 1,
        "model_id": "crazyflie-default-v1",
        "nominal_geometry": {
            "kind": "CYLINDER",
            "radius_m": 0.055,
            "half_height_m": 0.025,
        },
        "pose_model": "YAW_INVARIANT_LEVEL_FLIGHT",
        "qualification_scope": "SOFTWARE_SIMULATION_ONLY",
    }


def resolve_planning_package(
    case: CampaignCase,
    planning_submission_id: str | None = None,
    execution_profile_submission_id: str | None = None,
    *,
    comparison_context_id: str | None = None,
    planning_capability_request: PlanningCapabilityRequest | None = None,
    execution_capability_request: ExecutionCapabilityRequest | None = None,
    motion_preparation_request: MotionPreparationRequest | None = None,
    coordination_preparation_request: CoordinationPreparationRequest | None = None,
) -> ResolvedPlanningPackage:
    if motion_preparation_request is not None and any(
        value is not None
        for value in (
            execution_profile_submission_id,
            comparison_context_id,
            planning_capability_request,
            execution_capability_request,
        )
    ):
        raise ValueError(
            "plain motion preparation cannot be combined with execution-profile, "
            "comparison-context, or capability inputs"
        )
    if planning_submission_id is not None and planning_capability_request is not None:
        raise ValueError(
            "choose either a catalog planning submission or a core planning capability request"
        )
    if comparison_context_id is not None and planning_capability_request is not None:
        raise ValueError("comparison contexts cannot be combined with planning capabilities")
    if execution_profile_submission_id is not None and execution_capability_request is not None:
        raise ValueError(
            "choose either a catalog execution profile or a core execution capability request"
        )
    simulation_catalog_baseline = (
        case.environment is EnvironmentKind.SIMULATION
        and planning_submission_id in {None, BASELINE_PLANNING_SUBMISSION_ID}
        and execution_profile_submission_id in {None, BASELINE_SUBMISSION_ID}
        and comparison_context_id is None
        and planning_capability_request is None
        and execution_capability_request is None
        and motion_preparation_request is None
    )
    motion_preparation: MotionPreparationResolution | None = None
    if motion_preparation_request is not None:
        planning, profile, motion_preparation = _resolve_prepared_motion(
            case,
            motion_preparation_request,
            planning_submission_id=planning_submission_id,
        )
    else:
        planning = (
            compile_contextual_planning_submission(
                case,
                planning_submission_id,
                comparison_context_id=comparison_context_id,
            )
            if comparison_context_id is not None
            else (
                bind_planning_capability(case, planning_capability_request)
                if planning_capability_request is not None
                else resolve_planning_submission(
                    case,
                    planning_submission_id,
                    require_executable=not simulation_catalog_baseline,
                )
            )
        )
        profile = (
            bind_execution_capability(case, execution_capability_request)
            if execution_capability_request is not None
            else resolve_submission(
                case,
                execution_profile_submission_id or planning.execution_profile_submission_id,
                require_executable=not simulation_catalog_baseline,
            )
        )
    if planning.execution_profile_sha256 != profile.profile_sha256:
        planning = planning.model_copy(
            update={
                "execution_profile_submission_id": profile.submission_id,
                "execution_profile_sha256": profile.profile_sha256,
            }
        )
    if coordination_preparation_request is not None:
        if case.drone_count != 2:
            raise ValueError("launch-gap preparation is available only for two-drone cases")
        if planning.coordination.synchronized_route_start_required:
            raise ValueError("this resolution requires synchronized route starts")
        if not any(
            strategy in planning.strategy_authority
            for strategy in (PlannerStrategy.GROUND_DELAY, PlannerStrategy.AIRBORNE_STAGING)
        ):
            raise ValueError("the selected resolution has no launch-timing authority")
        if (
            coordination_preparation_request.launch_gap_s
            > planning.coordination.maximum_release_delay_s
        ):
            raise ValueError("requested launch gap exceeds the resolution's authored limit")
    world = planning_world_definition(case)
    vehicle_model = planning_vehicle_model()
    payload: dict[str, object] = {
        "schema_version": 1,
        "case": case,
        "planning_submission": planning,
        "execution_profile": profile,
        "world_definition": world,
        "vehicle_model": vehicle_model,
        "backend_configuration_sha256": case.execution.configuration_sha256,
        "capability_resolution": resolve_package_capability_resolution(case, planning, profile),
        "motion_preparation": motion_preparation,
        "coordination_preparation": coordination_preparation_request,
    }
    return ResolvedPlanningPackage(
        **payload,
        resolved_package_sha256=canonical_sha256(payload),
    )


def _resolve_prepared_motion(
    case: CampaignCase,
    request: MotionPreparationRequest,
    *,
    planning_submission_id: str | None = None,
) -> tuple[PlanningSubmission, ExecutionProfileSubmission, MotionPreparationResolution]:
    """Resolve plain sliders while preserving the selected coordination authority."""

    feasibility = _constant_path_speed_feasibility(case)
    balance_fraction = request.balance / 100.0
    requested_speed = request.speed_m_s or (
        feasibility.minimum_path_speed_m_s
        + balance_fraction
        * (feasibility.maximum_path_speed_m_s - feasibility.minimum_path_speed_m_s)
    )
    resolved_speed = min(
        feasibility.maximum_path_speed_m_s,
        max(feasibility.minimum_path_speed_m_s, requested_speed),
    )
    speed_cap_reason: str | None = None

    if request.accuracy_m is not None:
        requested_accuracy = request.accuracy_m
    elif request.balance <= 50:
        requested_accuracy = 0.01 * 5.0 ** (request.balance / 50.0)
    else:
        requested_accuracy = 0.05 * 2000.0 ** ((request.balance - 50.0) / 50.0)
    motion_limits = motion_preparation_limits_for_case(case)
    resolved_accuracy = min(requested_accuracy, motion_limits.accuracy_max_m)
    requested_smoothness = (
        request.smoothness if request.smoothness is not None else 100 - request.balance
    )
    # Even the Flow endpoint needs enough future geometry to preserve speed through
    # an easy bend. Smoothness extends that horizon; it never collapses the corner
    # transition into a short, low-speed kink.
    lookahead_s = 1.25 + requested_smoothness / 100.0 * 0.50

    preparation_key = canonical_sha256([case.case_sha256, request])[:20]
    has_semantic_stop = any(
        node.mode is not RouteNodeMode.FLY_THROUGH
        for drone in case.drones
        for node in case.route_nodes_for(drone.role_id)
    )
    if case.family == "takeoff_hover_land":
        speed_fraction = (resolved_speed - feasibility.minimum_path_speed_m_s) / (
            feasibility.maximum_path_speed_m_s - feasibility.minimum_path_speed_m_s
        )
        source = resolve_submission(case, "vertical_cycle.precision_first")
        profile = source.model_copy(
            update={
                "submission_id": f"prepared-motion.{preparation_key}",
                "display_name": "Prepared motion",
                "kind": ExecutionProfileKind.DURATION_SCALE,
                "owner": ExecutionProfileOwner.TIME_PARAMETERIZER,
                "parameters": ExecutionProfileParameters(
                    duration_scale=1.50 - speed_fraction * 0.75,
                    maximum_path_tube_error_m=resolved_accuracy,
                    smoothness_percent=requested_smoothness,
                    entry_exit_ramp_s=lookahead_s,
                ),
            }
        )
    elif has_semantic_stop:
        profile = bind_execution_capability(
            case,
            ExecutionCapabilityRequest(
                capability_id=CONSTANT_PATH_SPEED_CAPABILITY_ID,
                parameters=ExecutionProfileParameters(
                    target_path_speed_m_s=resolved_speed,
                    entry_exit_ramp_s=lookahead_s,
                ),
            ),
        )
        profile = profile.model_copy(
            update={
                "submission_id": f"prepared-motion.{preparation_key}",
                "parameters": profile.parameters.model_copy(
                    update={
                        "maximum_path_tube_error_m": resolved_accuracy,
                        "smoothness_percent": requested_smoothness,
                    }
                ),
            }
        )
    else:
        profile = bind_execution_capability(
            case,
            ExecutionCapabilityRequest(
                capability_id=CORNER_TRANSITION_CAPABILITY_ID,
                parameters=ExecutionProfileParameters(
                    target_path_speed_m_s=resolved_speed,
                    lookahead_time_s=lookahead_s,
                    maximum_path_tube_error_m=resolved_accuracy,
                    smoothness_percent=requested_smoothness,
                ),
            ),
        )
        profile = profile.model_copy(update={"submission_id": f"prepared-motion.{preparation_key}"})
    profile = profile.model_copy(
        update={
            "display_name": "Prepared motion",
            "rationale": "Resolved from the plain Balance and Tune controls.",
        }
    )
    baseline = resolve_planning_submission(
        case,
        planning_submission_id or BASELINE_PLANNING_SUBMISSION_ID,
        require_executable=(
            case.environment is not EnvironmentKind.SIMULATION
            or planning_submission_id not in {None, BASELINE_PLANNING_SUBMISSION_ID}
        ),
    )
    planning = baseline.model_copy(
        update={
            # Motion preparation never invents coordination authority. It preserves
            # the operator-selected fleet submission (or the catalog baseline) and
            # only binds the reusable execution profile below it.
            "display_name": (
                "Prepared motion"
                if planning_submission_id in {None, BASELINE_PLANNING_SUBMISSION_ID}
                else f"{baseline.display_name} · prepared motion"
            ),
            "rationale": (
                "The operator motion preference is bounded by immutable world, "
                "clearance, dynamics, actuator, energy, and terminal guards."
            ),
            # Accuracy is a direct route-shaping control only when the case owns a
            # reference path. Goal-seeking dynamic missions intentionally own no
            # centerline or rejoin route; binding their plain accuracy control to a
            # global hard tube would make the required obstacle detour illegal.
            # Coordinated missions likewise retain their case planning authority.
            "path_adherence": (
                PathAdherencePolicy(
                    mode=PathAdherenceMode.HARD_TUBE,
                    maximum_centerline_deviation_m=resolved_accuracy,
                )
                if case.drone_count == 1
                and (case.semantics is None or case.semantics.goal_seeking is None)
                else baseline.path_adherence
            ),
            "execution_profile_submission_id": profile.submission_id,
            "execution_profile_sha256": profile.profile_sha256,
            "capability_id": None,
        }
    )
    if profile.kind is ExecutionProfileKind.CORNER_TRANSITION:
        # Resolve the capability's independently sampled dynamics limit into the
        # actual profile, contract, and operator readout.  Keeping the authored
        # request as the contract target would falsely report a speed the bounded
        # allocator is not permitted to fly.
        capability = resolve_package_capability_resolution(case, planning, profile)
        if capability is None or capability.certified_entry_speed_m_s is None:
            raise ValueError("prepared corner motion lacks a certified entry speed")
        resolved_speed = capability.certified_entry_speed_m_s
        profile = profile.model_copy(
            update={
                "parameters": profile.parameters.model_copy(
                    update={"certified_path_speed_m_s": resolved_speed}
                )
            }
        )
        planning = planning.model_copy(update={"execution_profile_sha256": profile.profile_sha256})
        speed_cap_reason = capability.limiting_constraint
    speed_cap = (
        None
        if math.isclose(requested_speed, resolved_speed, abs_tol=1e-12)
        else speed_cap_reason
        or (
            "case speed feasibility "
            f"{feasibility.minimum_path_speed_m_s:.3f}.."
            f"{feasibility.maximum_path_speed_m_s:.3f} m/s"
        )
    )
    accuracy_cap = (
        None
        if math.isclose(requested_accuracy, resolved_accuracy, abs_tol=1e-12)
        else f"{motion_limits.accuracy_binding} {motion_limits.accuracy_max_m:.3f} m"
    )
    motion_contract = motion_contract_for_execution_profile(case, profile)
    resolution_payload: dict[str, object] = {
        "schema_version": 1,
        "request": request,
        "controls": (
            ResolvedMotionControl(
                label="Speed",
                unit="m/s",
                requested_value=requested_speed,
                resolved_value=resolved_speed,
                binding_safety_cap=speed_cap,
            ),
            ResolvedMotionControl(
                label="Accuracy",
                unit="m",
                requested_value=requested_accuracy,
                resolved_value=resolved_accuracy,
                binding_safety_cap=accuracy_cap,
            ),
            ResolvedMotionControl(
                label="Smoothness",
                unit="%",
                requested_value=float(requested_smoothness),
                resolved_value=float(requested_smoothness),
            ),
        ),
        "planning_submission_id": planning.planning_submission_id,
        "execution_profile_submission_id": profile.submission_id,
        "motion_quality_contract": motion_contract,
        "motion_quality_contract_sha256": canonical_sha256(motion_contract),
    }
    resolution = MotionPreparationResolution(
        **resolution_payload,
        resolution_sha256=canonical_sha256(resolution_payload),
    )
    return planning, profile, resolution


def bind_planning_capability(
    case: CampaignCase,
    request: PlanningCapabilityRequest,
) -> PlanningSubmission:
    """Bind a planner-owned reusable capability before any runtime is provisioned."""

    capability = next(
        (
            item
            for item in load_capability_registry().capabilities
            if item.capability_id == request.capability_id
        ),
        None,
    )
    if capability is None:
        raise ValueError(f"unknown core planning capability: {request.capability_id}")
    if (
        capability.owner is not ExecutionProfileOwner.PLANNER
        or capability.status is not SubmissionStatus.EXECUTABLE
        or case.execution.backend_profile_id not in capability.qualified_backend_profile_ids
        or case.implementation_status is not ImplementationStatus.EXECUTABLE
    ):
        raise ValueError(
            f"capability {request.capability_id} is not qualified for backend "
            f"{case.execution.backend_profile_id}"
        )
    source_row = _registry_source_row_for_case(case)
    if not (
        source_row.case_id == "1d.curved_route.canonical_nominal"
        or source_row.expected_case_sha256
        in {
            item.expected_case_sha256
            for item in load_case_submission_registry().rows
            if item.case_id == "1d.curved_route.canonical_nominal"
        }
    ):
        raise ValueError("core.route_fidelity is qualified only for the curved-route anchor family")
    if PlannerStrategy.DIRECT not in case.allowed_strategies:
        raise ValueError("compatible child removed required exact-route planning authority")

    baseline = resolve_planning_submission(case, BASELINE_PLANNING_SUBMISSION_ID)
    return baseline.model_copy(
        update={
            "planning_submission_id": ROUTE_FIDELITY_CAPABILITY_ID,
            "submission_version": "1.0.0",
            "display_name": "Core capability · exact route fidelity",
            "rationale": (
                "Requires the accepted route to remain on the authored centerline within "
                "the frozen 1e-6 m bound."
            ),
            "path_adherence": PathAdherencePolicy(
                mode=PathAdherenceMode.EXACT_ROUTE,
                maximum_centerline_deviation_m=1e-6,
            ),
            "experiment_id": "core.route_fidelity",
            "experiment_axis": ExperimentAxis.PATH_ADHERENCE_MODE,
            "axis_value": "EXACT_ROUTE_1E_6_M",
            "layer": SubmissionLayer.CORE_CAPABILITY,
            "capability_id": ROUTE_FIDELITY_CAPABILITY_ID,
            "support_reason": (
                "Qualified on the curved-route Fast-Sim anchor; child compatibility is "
                "rechecked before the package is created."
            ),
            "admission": baseline.admission.model_copy(
                update={
                    "causal_question": (
                        "Does exact authored-route adherence prevent line cutting while "
                        "holding every other planning and execution input fixed?"
                    ),
                    "baseline_limitation": (
                        "GOAL_SEQUENCE_ONLY may accept geometry between required regions "
                        "without a centerline bound."
                    ),
                    "principal_variable": "path_adherence_mode",
                    "behavior_difference": (
                        "PATH_ADHERENCE_MODE changes from GOAL_SEQUENCE_ONLY to EXACT_ROUTE "
                        "with a fixed 1e-6 m maximum centerline deviation."
                    ),
                    "distinguishing_oracle": (
                        "An independent continuous route-to-authored-polyline measurement "
                        "must be <= 1e-6 m for every role."
                    ),
                    "new_integration_gate": (
                        "The exact-route certificate, renamed child, removed-authority, "
                        "changed-geometry, and unsupported-backend boundaries must pass."
                    ),
                    "learning_value": (
                        "Separates exact line following from region-only mission completion."
                    ),
                }
            ),
        }
    )


def resolve_package_capability_resolution(
    case: CampaignCase,
    planning: PlanningSubmission,
    profile: ExecutionProfileSubmission,
) -> CapabilityResolution | None:
    if planning.capability_id == ROUTE_FIDELITY_CAPABILITY_ID:
        tolerance = planning.path_adherence.maximum_centerline_deviation_m
        if planning.path_adherence.mode is not PathAdherenceMode.EXACT_ROUTE or tolerance != 1e-6:
            raise ValueError("route-fidelity package lost its frozen exact-route authority")
        return CapabilityResolution(
            capability_id=ROUTE_FIDELITY_CAPABILITY_ID,
            capability_request_sha256=canonical_sha256(
                {
                    "capability_id": ROUTE_FIDELITY_CAPABILITY_ID,
                    "case_sha256": case.case_sha256,
                    "path_adherence_mode": planning.path_adherence.mode,
                    "maximum_centerline_deviation_m": tolerance,
                }
            ),
            exact_route_tolerance_m=tolerance,
        )
    return resolve_capability_resolution(case, profile)


def rebind_planning_submission(
    case: CampaignCase,
    source: PlanningSubmission,
) -> PlanningSubmission:
    """Bind a qualified authority shape to one explicit causal child-case snapshot."""

    profile = resolve_submission(
        case, source.execution_profile_submission_id, require_executable=False
    )
    world = planning_world_definition(case)
    vehicle_model = planning_vehicle_model()
    _registry_source_row_for_case(case)
    missing_strategies = tuple(
        strategy
        for strategy in source.strategy_authority
        if strategy not in case.allowed_strategies
    )
    if missing_strategies:
        raise ValueError(
            "compatible child removed required planning authority: "
            f"{tuple(item.value for item in missing_strategies)}"
        )
    if case.execution.backend_profile_id not in source.supported_backend_profile_ids:
        raise ValueError(
            f"compatible child backend {case.execution.backend_profile_id} is not qualified "
            f"for {source.planning_submission_id}"
        )
    if profile.status is not SubmissionStatus.EXECUTABLE:
        raise ValueError("compatible child execution profile is not executable")
    return source.model_copy(
        update={
            "case_id": case.case_id,
            "case_sha256": case.case_sha256,
            "world_definition_sha256": canonical_sha256(world),
            "vehicle_model_sha256": canonical_sha256(vehicle_model),
            "clearance": source.clearance.model_copy(
                update={
                    "required_pairwise_center_separation_m": (
                        case.hard_constraints.warning_separation_m
                        + case.hard_constraints.position_uncertainty_m
                    ),
                    "uncertainty_allowance_m": case.hard_constraints.position_uncertainty_m,
                }
            ),
            "execution_profile_sha256": profile.profile_sha256,
            "supported_backend_profile_ids": source.supported_backend_profile_ids,
        }
    )


def _admission_from_record(
    case: CampaignCase,
    spec: RegistrySubmissionSpec,
) -> VariationAdmissionRecord:
    row = admission_record_for_case(case)
    oracle = proposal_oracle_for_case(case, spec.submission_id)
    return VariationAdmissionRecord(
        causal_question=row.causal_question,
        baseline_limitation=row.baseline_limitation,
        principal_variable=spec.axis.value.lower(),
        fixed_inputs=row.fixed_inputs,
        behavior_difference=(
            f"{row.proposed_additions_or_disposition} Exact authored axis: "
            f"{spec.axis.value}={spec.axis_value}."
        ),
        distinguishing_oracle=(
            f"{row.comparison_and_distinguishing_oracle} Frozen relation: "
            f"{oracle.qualifying_relation}. Comparator: {oracle.comparator_id}."
        ),
        reused_evidence=row.reused_evidence,
        new_integration_gate=row.new_integration_gate,
        backend_semantics=row.backend_semantics,
        safety_bounds=row.safety_bounds,
        operator_comparison=row.operator_comparison,
        learning_value=row.learning_value,
    )


def _planning_submission(
    case: CampaignCase,
    *,
    profile: ExecutionProfileSubmission,
    world: dict[str, object],
    vehicle_model: dict[str, object],
    planning_submission_id: str,
    display_name: str,
    rationale: str,
    path_adherence: PathAdherencePolicy,
    synchronized_launch_required: bool,
    synchronized_route_start_required: bool,
    minimum_simultaneous_flight_s: float,
    spec: RegistrySubmissionSpec | None = None,
) -> PlanningSubmission:
    dimensions_by_strategy = {
        PlannerStrategy.DIRECT: (),
        PlannerStrategy.GROUND_DELAY: (ManeuverDimension.TIMING,),
        PlannerStrategy.AIRBORNE_STAGING: (ManeuverDimension.TIMING,),
        PlannerStrategy.SPEED_RETIMING: (ManeuverDimension.SPEED,),
        PlannerStrategy.HORIZONTAL_DETOUR: (ManeuverDimension.LATERAL,),
        PlannerStrategy.VERTICAL_LAYER: (ManeuverDimension.VERTICAL,),
        PlannerStrategy.COMBINED_TIMING_GEOMETRY: (
            ManeuverDimension.TIMING,
            ManeuverDimension.LATERAL,
            ManeuverDimension.VERTICAL,
        ),
    }
    strategy_authority = (
        spec.strategy_authority
        if spec is not None and spec.strategy_authority
        else (
            _registry_source_row_for_case(case).default_strategy_authority
            if spec is not None
            else case.allowed_strategies
        )
    )
    authority_supported = all(
        strategy in case.allowed_strategies for strategy in strategy_authority
    )
    maneuver_dimensions = tuple(
        dict.fromkeys(
            dimension
            for strategy in strategy_authority
            for dimension in dimensions_by_strategy[strategy]
        )
    )
    if not maneuver_dimensions:
        # A direct-only request still carries explicit timing authority for its
        # immutable route start; PlanningSubmission deliberately rejects an empty
        # authority set.
        maneuver_dimensions = (ManeuverDimension.TIMING,)
    status = (
        SubmissionStatus.EXECUTABLE
        if (
            case.environment is EnvironmentKind.SIMULATION
            and case.implementation_status is ImplementationStatus.EXECUTABLE
            and case.execution.backend_profile_id == "fast-sim-v1"
            and authority_supported
            and (spec is None or spec.status is SubmissionStatus.EXECUTABLE)
        )
        else SubmissionStatus.PLANNED_NOT_EXECUTABLE
    )
    objective_order = case.objective_order
    if spec is not None and spec.objective_focus:
        objective_order = tuple(dict.fromkeys((*spec.objective_focus, *case.objective_order)))
    admission = (
        _admission_from_record(case, spec)
        if spec is not None
        else VariationAdmissionRecord(
            causal_question=(
                spec.causal_question
                if spec is not None
                else "What behavior does the immutable case authority select?"
            ),
            baseline_limitation=(
                spec.baseline_limitation
                if spec is not None
                else "This is the comparison baseline rather than a new causal alternative."
            ),
            principal_variable=(spec.axis.value.lower() if spec is not None else "case_default"),
            fixed_inputs=(
                "case_hash",
                "world_hash",
                "vehicle_model_hash",
                "hard_constraints",
                "backend_configuration",
                "search_budget",
            ),
            behavior_difference=(
                spec.behavior_difference
                if spec is not None
                else "No authority or objective override is applied."
            ),
            distinguishing_oracle=(
                spec.distinguishing_oracle
                if spec is not None
                else "The accepted plan and evidence reproduce the retained case authority."
            ),
            reused_evidence=spec.reused_evidence if spec is not None else (),
            new_integration_gate=(
                spec.new_integration_gate
                if spec is not None
                else "Deterministic baseline planning and continuous certification must pass."
            ),
            backend_semantics=(
                spec.backend_semantics
                if spec is not None
                else "The configured fast-sim-v1 planner is supported; no runtime or physical equivalence is claimed."
            ),
            safety_bounds=(
                spec.safety_bounds
                if spec is not None
                else "Every immutable case safety, geometry, dynamics, energy, freshness, atomicity, and terminal gate remains hard."
            ),
            operator_comparison=(
                spec.operator_comparison
                if spec is not None
                else "Compare the identical case hash, accepted plan, trajectory, and continuous feasibility evidence."
            ),
            learning_value=(
                spec.learning_value
                if spec is not None
                else "Provides the immutable comparison point for admitted alternatives."
            ),
        )
    )
    return PlanningSubmission(
        planning_submission_id=planning_submission_id,
        submission_version="1.0.0",
        display_name=display_name,
        case_id=case.case_id,
        case_sha256=case.case_sha256,
        world_definition_sha256=canonical_sha256(world),
        vehicle_model_sha256=canonical_sha256(vehicle_model),
        status=status,
        rationale=rationale,
        strategy_authority=strategy_authority,
        maneuver_dimensions=maneuver_dimensions,
        path_adherence=path_adherence,
        clearance=ClearancePolicy(
            required_pairwise_center_separation_m=(
                case.hard_constraints.warning_separation_m
                + case.hard_constraints.position_uncertainty_m
            ),
            uncertainty_allowance_m=case.hard_constraints.position_uncertainty_m,
        ),
        coordination=CoordinationPolicy(
            synchronized_launch_required=synchronized_launch_required,
            synchronized_route_start_required=synchronized_route_start_required,
            maximum_route_start_skew_s=(
                case.semantics.coordination_constraints.maximum_route_start_skew_s
                if case.semantics
                else 0.0
            ),
            minimum_simultaneous_flight_s=minimum_simultaneous_flight_s,
            maximum_release_delay_s=max(case.search.delay_grid_s),
        ),
        objective=PlanningObjective(
            terms=tuple(PlanningObjectiveTerm(metric=metric) for metric in objective_order)
        ),
        selection_oracle=(
            spec.selection_oracle if spec is not None else PlanningSelectionOracle.OBJECTIVE_ORDER
        ),
        feasibility_oracle_ids=(
            "continuous_pairwise_clearance",
            "continuous_solid_clearance",
            "flight_volume_containment",
            "goal_and_path_adherence",
            "dynamics_and_deadline",
        ),
        experiment_id=spec.experiment_id if spec is not None else "baseline_case_authority",
        experiment_axis=spec.axis if spec is not None else ExperimentAxis.OBJECTIVE_ORDER,
        axis_value=spec.axis_value if spec is not None else "case_default",
        layer=spec.layer if spec is not None else SubmissionLayer.PLANNING,
        fallback_policy=spec.fallback_policy if spec is not None else None,
        capability_id=spec.capability_id if spec is not None else None,
        support_reason=(
            (
                spec.support_reason
                if authority_supported and case.execution.backend_profile_id == "fast-sim-v1"
                else "The compatible case removed required authority or selected an unqualified backend; selection issues no command."
            )
            if spec is not None
            else (
                "Retained case authority compiled for the configured backend."
                if case.execution.backend_profile_id == "fast-sim-v1"
                else "The configured backend is not qualified; selection issues no command."
            )
        ),
        admission=admission,
        execution_profile_sha256=profile.profile_sha256,
        supported_backend_profile_ids=(
            ("fast-sim-v1",) if status is SubmissionStatus.EXECUTABLE else ()
        ),
    )


def _submission(
    case: CampaignCase,
    *,
    submission_id: str,
    display_name: str,
    kind: ExecutionProfileKind,
    owner: ExecutionProfileOwner,
    rationale: str,
    metric_ids: tuple[str, ...],
    principal_variable: str,
    causal_question: str,
    baseline_limitation: str,
    behavior_difference: str,
    distinguishing_oracle: str,
    new_gate: str,
    learning_value: str,
    status: SubmissionStatus = SubmissionStatus.EXECUTABLE,
    parameters: ExecutionProfileParameters | None = None,
    feasibility: ProfileFeasibilityRecord | None = None,
    baseline_submission_sha256: str | None = None,
    prerequisites: tuple[str, ...] = (),
    admission_override: VariationAdmissionRecord | None = None,
) -> ExecutionProfileSubmission:
    effective_status = (
        status
        if (
            status is SubmissionStatus.PLANNED_NOT_EXECUTABLE
            or (
                case.implementation_status is ImplementationStatus.EXECUTABLE
                and case.execution.backend_profile_id == "fast-sim-v1"
            )
        )
        else SubmissionStatus.PLANNED_NOT_EXECUTABLE
    )
    return ExecutionProfileSubmission(
        submission_id=submission_id,
        submission_version="2.0.0",
        display_name=display_name,
        case_id=case.case_id,
        case_sha256=case.case_sha256,
        baseline_submission_id=(
            None if submission_id == BASELINE_SUBMISSION_ID else BASELINE_SUBMISSION_ID
        ),
        baseline_submission_sha256=baseline_submission_sha256,
        kind=kind,
        owner=owner,
        status=effective_status,
        rationale=rationale,
        parameters=parameters or ExecutionProfileParameters(),
        feasibility=feasibility,
        supported_backend_profile_ids=(case.execution.backend_profile_id,)
        if (
            effective_status is SubmissionStatus.EXECUTABLE
            and case.implementation_status is ImplementationStatus.EXECUTABLE
            and case.execution.backend_profile_id == "fast-sim-v1"
        )
        else (),
        prerequisite_submission_ids=prerequisites,
        metric_ids=metric_ids,
        admission=admission_override
        or VariationAdmissionRecord(
            causal_question=causal_question,
            baseline_limitation=baseline_limitation,
            principal_variable=principal_variable,
            fixed_inputs=("case_geometry", "hard_constraints", "landing_goal", "backend_model"),
            behavior_difference=behavior_difference,
            distinguishing_oracle=distinguishing_oracle,
            reused_evidence=prerequisites,
            new_integration_gate=new_gate,
            backend_semantics=(
                "Fast Sim consumes the accepted time-parameterized trajectory; no physical, "
                "RPM, PWM, or digital-twin equivalence is claimed."
            ),
            safety_bounds=(
                "Existing case volume, horizontal/vertical speed, acceleration, jerk, energy, "
                "landing, and terminal gates remain hard constraints."
            ),
            operator_comparison=(
                "Preview requested time law and compare achieved profile, tracking, dynamics, "
                "actuator headroom, energy, and landing against the exact baseline."
            ),
            learning_value=learning_value,
        ),
    )


def bind_execution_capability(
    case: CampaignCase,
    request: ExecutionCapabilityRequest,
) -> ExecutionProfileSubmission:
    """Bind a learned core capability to the current case at planning time.

    Catalog submissions remain useful for experiments and retained evidence.  Runtime
    planners use this entry point instead: they request the capability and parameters,
    then receive one exact case/hash-bound profile without adding a case-specific
    submission definition.
    """

    capability = next(
        (
            item
            for item in load_capability_registry().capabilities
            if item.capability_id == request.capability_id
        ),
        None,
    )
    if capability is None:
        raise ValueError(f"unknown core execution capability: {request.capability_id}")
    if (
        capability.status is not SubmissionStatus.EXECUTABLE
        or case.execution.backend_profile_id not in capability.qualified_backend_profile_ids
    ):
        raise ValueError(
            f"capability {request.capability_id} is not qualified for backend "
            f"{case.execution.backend_profile_id}"
        )
    if request.capability_id == ROUTE_FIDELITY_CAPABILITY_ID:
        raise ValueError(
            "core.route_fidelity is planning-owned and must be selected as planning authority"
        )
    kind_by_capability = {
        CONSTANT_PATH_SPEED_CAPABILITY_ID: ExecutionProfileKind.CONSTANT_PATH_SPEED,
        CORNER_TRANSITION_CAPABILITY_ID: ExecutionProfileKind.CORNER_TRANSITION,
        ENERGY_AWARE_RETIMING_CAPABILITY_ID: ExecutionProfileKind.DURATION_SCALE,
    }
    kind = kind_by_capability[request.capability_id]
    parameters = request.parameters
    feasibility = None
    if kind in {
        ExecutionProfileKind.CONSTANT_PATH_SPEED,
        ExecutionProfileKind.CORNER_TRANSITION,
    }:
        target = request.parameters.target_path_speed_m_s
        assert target is not None
        feasibility = _constant_path_speed_feasibility(case)
        if not feasibility.minimum_path_speed_m_s <= target <= feasibility.maximum_path_speed_m_s:
            raise ValueError(
                f"path speed {target:.3f} m/s is outside the case feasibility interval "
                f"{feasibility.minimum_path_speed_m_s:.3f}.."
                f"{feasibility.maximum_path_speed_m_s:.3f} m/s"
            )
    if request.capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID:
        source_case_id = _registry_source_row_for_case(case).case_id
        if source_case_id not in {
            "1d.point_to_point_relocation.canonical_nominal",
            "2d.parallel_routes.canonical_nominal",
        }:
            raise ValueError(
                "core.energy_aware_retiming is qualified only for its one- and two-role "
                "anchor families"
            )
        energy_retiming = _energy_retiming_resolution(case)
        parameters = ExecutionProfileParameters(duration_scale=energy_retiming.selected_factor)
    baseline = _baseline_execution_profile(case)
    return _submission(
        case,
        submission_id=request.capability_id,
        display_name=f"Core capability · {request.capability_id.removeprefix('core.').replace('_', ' ')}",
        kind=kind,
        owner=capability.owner,
        parameters=parameters,
        feasibility=feasibility,
        baseline_submission_sha256=baseline.profile_sha256,
        rationale=("Applies the qualified reusable time law to planner-selected geometry."),
        metric_ids=("path_speed_error", "route_tracking", "actuator_headroom", "energy"),
        principal_variable=(
            "compiler_selected_duration_factor"
            if request.capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID
            else "target_path_speed_m_s"
        ),
        causal_question=(
            "Can the bounded compiler reduce modeled and measured energy while preserving every hard gate?"
            if request.capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID
            else "Can the selected route retain the requested constant path speed?"
        ),
        baseline_limitation=(
            "The default time law is not ranked by the versioned coupled-powertrain energy oracle."
            if request.capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID
            else "The default planner time law does not require constant route speed."
        ),
        behavior_difference=(
            (
                "The compiler evaluates the frozen factors (0.80, 0.90, 1.00, 1.15, 1.30) "
                "and binds the lowest-energy feasible time law; the caller supplies no scalar."
            )
            if request.capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID
            else (
                "Every nonzero route segment is time-parameterized from its arc length and the "
                "requested scalar speed, with bounded transition windows."
            )
        ),
        distinguishing_oracle=(
            (
                "All five predicted dispositions and Wh values, the selected factor, raw command "
                "timing, and measured energy are retained against the exact baseline."
            )
            if request.capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID
            else (
                "Sampled steady-window commanded and observed path speed satisfy the retained "
                "capability gates."
            )
        ),
        new_gate=(
            (
                "Reconcile three accelerated raw-energy repeats against the exact baseline and "
                "retain tracking, dynamics, separation, reserve, and terminal evidence."
            )
            if request.capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID
            else (
                "Reuse core constant-speed tracking and revalidate case-specific geometry, "
                "dynamics, coordination, energy, and terminal capture."
            )
        ),
        learning_value=(
            "Consumes the learned motion primitive without creating another mission-specific "
            "implementation or catalog choice."
        ),
    )


def normalized_route_polyline(
    case: CampaignCase,
    role_id: str,
    positions: tuple[Vector3, ...] | None = None,
) -> NormalizedPolyline:
    """Return the semantic-polyline-v1 geometry while retaining raw capture identity."""

    drone = next(item for item in case.drones if item.role_id == role_id)
    node_by_region = {node.region_id: node for node in case.route_nodes_for(role_id)}
    if positions is None:
        first_goal = drone.goal_sequence[0].center_m
        last_goal = drone.goal_sequence[-1].center_m
        authored_positions = (
            drone.start_region.center_m.model_copy(update={"z": first_goal.z}),
            *(goal.center_m for goal in drone.goal_sequence),
            drone.landing_region.center_m.model_copy(update={"z": last_goal.z}),
        )
        deduplicated: list[Vector3] = []
        for point in authored_positions:
            if not deduplicated or _vector_distance(deduplicated[-1], point) > 1e-9:
                deduplicated.append(point)
        if len(deduplicated) < 2:
            # Cruise normalization projects launch and landing onto the first/last
            # route altitude.  A pure take-off/hover/land mission has no horizontal
            # cruise after that projection, so retain its real vertical legs as the
            # motion-preparation geometry.
            deduplicated = []
            for point in (
                drone.start_region.center_m,
                *(goal.center_m for goal in drone.goal_sequence),
                drone.landing_region.center_m,
            ):
                if not deduplicated or _vector_distance(deduplicated[-1], point) > 1e-9:
                    deduplicated.append(point)
        positions = tuple(deduplicated)

    remaining_goals = list(drone.goal_sequence)
    node_ids: list[str] = []
    node_modes: list[RouteNodeMode] = []
    for index, point in enumerate(positions):
        matched_index = next(
            (
                goal_index
                for goal_index, goal in enumerate(remaining_goals)
                if _vector_distance(point, goal.center_m) <= 1e-9
            ),
            None,
        )
        if matched_index is None:
            node_ids.append(f"@geometry-{index}")
            node_modes.append(RouteNodeMode.FLY_THROUGH)
            continue
        goal = remaining_goals.pop(matched_index)
        node = node_by_region[goal.region_id]
        node_ids.append(goal.region_id)
        node_modes.append(node.mode)

    retained = list(range(len(positions)))
    changed = True
    while changed and len(retained) > 2:
        changed = False
        for retained_position in range(1, len(retained) - 1):
            before_index = retained[retained_position - 1]
            current_index = retained[retained_position]
            after_index = retained[retained_position + 1]
            if node_modes[current_index] is not RouteNodeMode.FLY_THROUGH:
                continue
            before = positions[before_index]
            current = positions[current_index]
            after = positions[after_index]
            current_is_unidentified = node_ids[current_index].startswith("@geometry-")
            current_is_repeated_path_state = (
                sum(_vector_distance(current, candidate) <= 1e-9 for candidate in positions) > 1
            )
            if (_vector_distance(before, current) <= 1e-9 and current_is_unidentified) or (
                _forward_collinear(before, current, after) and not current_is_repeated_path_state
            ):
                retained.pop(retained_position)
                changed = True
                break

    raw_payload = {
        "role_id": role_id,
        "node_ids": tuple(node_ids),
        "node_modes": tuple(node_modes),
        "points_m": positions,
    }
    normalized_points = tuple(positions[index] for index in retained)
    normalized_payload = {
        "rule_version": SEMANTIC_POLYLINE_RULE_VERSION,
        "role_id": role_id,
        "points_m": normalized_points,
        "semantic_markers": tuple(
            {
                "normalized_index": normalized_index,
                "node_id": node_ids[raw_index],
                "mode": node_modes[raw_index],
            }
            for normalized_index, raw_index in enumerate(retained)
            if node_modes[raw_index] is not RouteNodeMode.FLY_THROUGH
        ),
    }
    return NormalizedPolyline(
        role_id=role_id,
        raw_node_ids=tuple(node_ids),
        raw_node_modes=tuple(node_modes),
        raw_points_m=positions,
        retained_raw_indices=tuple(retained),
        normalized_points_m=normalized_points,
        raw_capture_sha256=canonical_sha256(raw_payload),
        normalized_geometry_sha256=canonical_sha256(normalized_payload),
    )


def _forward_collinear(before: Vector3, current: Vector3, after: Vector3) -> bool:
    ac = (after.x - before.x, after.y - before.y, after.z - before.z)
    ab = (current.x - before.x, current.y - before.y, current.z - before.z)
    cb = (after.x - current.x, after.y - current.y, after.z - current.z)
    length_squared = sum(value * value for value in ac)
    if length_squared <= 1e-18:
        return False
    projection = sum(left * right for left, right in zip(ab, ac, strict=True)) / length_squared
    closest = Vector3(
        x=before.x + projection * ac[0],
        y=before.y + projection * ac[1],
        z=before.z + projection * ac[2],
    )
    forward_dot = sum(left * right for left, right in zip(ab, cb, strict=True))
    return (
        _vector_distance(current, closest) <= 1e-9
        and forward_dot >= -1e-12
        and -1e-12 <= projection <= 1.0 + 1e-12
    )


def _vector_distance(first: Vector3, second: Vector3) -> float:
    return math.dist(
        (first.x, first.y, first.z),
        (second.x, second.y, second.z),
    )


def resolve_capability_resolution(
    case: CampaignCase,
    profile: ExecutionProfileSubmission,
) -> CapabilityResolution | None:
    capability_id = (
        CORNER_TRANSITION_CAPABILITY_ID
        if profile.kind is ExecutionProfileKind.CORNER_TRANSITION
        else (
            profile.submission_id
            if profile.submission_id
            in {
                CONSTANT_PATH_SPEED_CAPABILITY_ID,
                ENERGY_AWARE_RETIMING_CAPABILITY_ID,
            }
            else None
        )
    )
    if capability_id is None:
        return None
    request_hash = canonical_sha256(
        {
            "capability_id": capability_id,
            "parameters": (
                ExecutionProfileParameters()
                if capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID
                else profile.parameters
            ),
            "case_sha256": case.case_sha256,
        }
    )
    if profile.kind is not ExecutionProfileKind.CORNER_TRANSITION:
        if capability_id == ENERGY_AWARE_RETIMING_CAPABILITY_ID:
            energy_retiming = _energy_retiming_resolution(case)
            if profile.parameters.duration_scale != energy_retiming.selected_factor:
                raise ValueError(
                    "energy-aware profile factor does not match the bounded compiler selection"
                )
            return CapabilityResolution(
                capability_id=capability_id,
                capability_request_sha256=request_hash,
                energy_retiming=energy_retiming,
            )
        return CapabilityResolution(
            capability_id=capability_id,
            capability_request_sha256=request_hash,
        )
    lookahead = profile.parameters.lookahead_time_s
    target_speed = profile.parameters.target_path_speed_m_s
    assert lookahead is not None and target_speed is not None
    normalized_polylines = tuple(
        normalized_route_polyline(case, drone.role_id)
        for drone in sorted(case.drones, key=lambda item: item.role_id)
    )
    normalized_geometry_sha256 = canonical_sha256(
        {
            "rule_version": SEMANTIC_POLYLINE_RULE_VERSION,
            "roles": tuple(
                {
                    "role_id": polyline.role_id,
                    "normalized_geometry_sha256": polyline.normalized_geometry_sha256,
                }
                for polyline in normalized_polylines
            ),
        }
    )
    request_hash = canonical_sha256(
        {
            "capability_id": capability_id,
            "parameters": profile.parameters,
            "case_sha256": case.case_sha256,
            "normalization_rule_version": SEMANTIC_POLYLINE_RULE_VERSION,
            "normalized_geometry_sha256": normalized_geometry_sha256,
        }
    )
    segment_lengths: list[float] = []
    route_points: list[tuple[Vector3, ...]] = []
    for polyline in normalized_polylines:
        points = polyline.normalized_points_m
        if len(points) >= 2:
            route_points.append(points)
        segment_lengths.extend(
            math.dist(
                (before.x, before.y, before.z),
                (after.x, after.y, after.z),
            )
            for before, after in pairwise(points)
        )
    positive_lengths = tuple(value for value in segment_lengths if value > 1e-9)
    if not positive_lengths:
        raise ValueError("corner-transition capability requires a nonzero authored route")
    adjacent_cap = min(positive_lengths, default=0.50) * 0.49
    profile_spec = next(
        (
            item
            for item in registry_row_for_case(case).submissions
            if item.submission_id == profile.submission_id
        ),
        None,
    )
    flight_volume = case.hard_constraints.flight_volume
    contract_deviation_cap = min(
        (
            profile.parameters.maximum_path_tube_error_m
            or case.motion_contract_for(case.drones[0].role_id).maximum_path_tube_error_m
        ),
        math.dist(
            (
                flight_volume.minimum_m.x,
                flight_volume.minimum_m.y,
                flight_volume.minimum_m.z,
            ),
            (
                flight_volume.maximum_m.x,
                flight_volume.maximum_m.y,
                flight_volume.maximum_m.z,
            ),
        ),
    )
    path_deviation_cap = min(
        contract_deviation_cap,
        (
            profile_spec.maximum_centerline_deviation_m
            if profile_spec is not None and profile_spec.maximum_centerline_deviation_m is not None
            else contract_deviation_cap
        ),
    )
    protected_radius = 0.055 + case.hard_constraints.position_uncertainty_m + 0.05
    free_clearances = []
    environment = case.semantics.environment_constraints if case.semantics else None
    for points in route_points:
        # Launch and landing contact points of the vertical-cycle mission are
        # intentionally on the floor boundary.  They are governed by terminal
        # contact authority, not by the in-flight corner free-space margin.
        clearance_points = (
            points[1:-1] if case.family == "takeoff_hover_land" and len(points) > 2 else points
        )
        for point in clearance_points:
            free_clearances.append(
                min(
                    point.x - flight_volume.minimum_m.x,
                    flight_volume.maximum_m.x - point.x,
                    point.y - flight_volume.minimum_m.y,
                    flight_volume.maximum_m.y - point.y,
                    point.z - flight_volume.minimum_m.z,
                    flight_volume.maximum_m.z - point.z,
                )
                - protected_radius
            )
            for solid in environment.keep_out_regions if environment is not None else ():
                dx = max(solid.minimum_m.x - point.x, 0.0, point.x - solid.maximum_m.x)
                dy = max(solid.minimum_m.y - point.y, 0.0, point.y - solid.maximum_m.y)
                dz = max(solid.minimum_m.z - point.z, 0.0, point.z - solid.maximum_m.z)
                free_clearances.append(math.sqrt(dx * dx + dy * dy + dz * dz) - protected_radius)
    minimum_free_clearance = min(free_clearances, default=0.0)
    # This is clearance normal to the route, not available lookahead distance along
    # it.  The previous quarter-clearance value incorrectly collapsed a long smooth
    # transition to a few centimetres.  The exact interpolated path/free-space bounds
    # are sampled independently in the capability certificate below.
    # This compiler runs before the planner and therefore sees only authored
    # geometry.  Keep a minimal smoothing cap when that geometry touches a protected
    # margin; the planner may be authorized to replace it, and its independent
    # certificate remains the authority for the selected route.
    protected_free_space_cap = max(minimum_free_clearance, 1e-6)
    maximum_radius = min(
        0.25,
        adjacent_cap,
    )
    limits = case.hard_constraints.dynamics
    speed_feasibility = _constant_path_speed_feasibility(case)
    dynamics_speed_cap = min(
        speed_feasibility.maximum_path_speed_m_s,
        math.sqrt(limits.maximum_acceleration_m_s2 * maximum_radius),
        (limits.maximum_jerk_m_s3 * maximum_radius * maximum_radius) ** (1.0 / 3.0),
    )
    base_speed = min(target_speed, dynamics_speed_cap)
    certified_speed = base_speed
    safety_retiming_factor = 1.0
    preliminary_distance = min(
        0.30,
        lookahead * certified_speed,
        adjacent_cap,
    )
    radius_candidate = min(0.25, max(0.08, preliminary_distance * 0.75))
    radius = min(
        radius_candidate,
        adjacent_cap,
        2.0 * protected_free_space_cap,
        2.0 * path_deviation_cap,
    )
    lookahead_distance = min(preliminary_distance, 2.0 * radius)
    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points, audit_trajectory
    from crazyswarm_app.domain.trajectory import TimeParameterizedTrajectory

    achieved_speeds = []
    allocated_accelerations = []
    for points in route_points:
        targets = (certified_speed,) * (len(points) - 1)
        durations = tuple(
            math.dist(
                (before.x, before.y, before.z),
                (after.x, after.y, after.z),
            )
            / certified_speed
            for before, after in pairwise(points)
        )
        allocated = allocate_trajectory_points(
            case,
            points,
            speed_factor=1.0,
            segment_durations_s=durations,
            path_speed_targets_m_s=targets,
            entry_exit_ramp_s=lookahead,
            transition_distance_m=lookahead_distance,
            turn_blend_radius_m=radius,
            corner_cut_tolerance_m=(path_deviation_cap if case.drone_count == 1 else None),
        )
        achieved_speeds.append(
            max(
                math.sqrt(
                    point.velocity_m_s.x**2 + point.velocity_m_s.y**2 + point.velocity_m_s.z**2
                )
                for point in allocated
            )
        )
        allocated_trajectory = TimeParameterizedTrajectory(
            trajectory_id=f"capability-reserve-{canonical_sha256(allocated)[:20]}",
            role_id="capability-reserve",
            vehicle_id="capability-reserve",
            route_sha256=canonical_sha256(points),
            points=allocated,
            declared_stop_sequences=(allocated[0].sequence, allocated[-1].sequence),
            completion_position_tolerance_m=0.05,
            completion_velocity_tolerance_m_s=0.05,
        )
        allocated_accelerations.append(
            audit_trajectory(case, allocated_trajectory).maximum_acceleration_m_s2
        )
    achieved = min(achieved_speeds)
    smoothness_fraction = (profile.parameters.smoothness_percent or 0) / 100.0
    tracking_acceleration_limit = limits.maximum_acceleration_m_s2 * (
        0.95 - 0.50 * smoothness_fraction
    )
    maximum_allocated_acceleration = max(allocated_accelerations, default=0.0)
    tracking_reserve_applied = maximum_allocated_acceleration > tracking_acceleration_limit
    if tracking_reserve_applied:
        achieved *= math.sqrt(tracking_acceleration_limit / maximum_allocated_acceleration)
    # Observe the allocator once at the bounded authored speed. Re-feeding its
    # already-retimed output as a new authored request recursively collapses speed
    # at every corner and reverses the operator's monotonic Speed control.
    if achieved < certified_speed and not math.isclose(
        achieved,
        certified_speed,
        rel_tol=1e-8,
        abs_tol=1e-9,
    ):
        certified_speed = achieved
        safety_retiming_factor = base_speed / certified_speed
        preliminary_distance = min(
            0.30,
            lookahead * certified_speed,
            adjacent_cap,
        )
        radius_candidate = min(0.25, max(0.08, preliminary_distance * 0.75))
        radius = min(
            radius_candidate,
            adjacent_cap,
            2.0 * protected_free_space_cap,
            2.0 * path_deviation_cap,
        )
        lookahead_distance = min(preliminary_distance, 2.0 * radius)

    # The final radius/lookahead changes after the first bounded observation. Recheck
    # that exact final geometry until its admitted speed and tracking reserve agree;
    # otherwise the profile could truthfully report the first pass while execution
    # performs an additional hidden retime.
    for _ in range(16):
        if not profile.submission_id.startswith("prepared-motion."):
            break
        final_speeds = []
        final_accelerations = []
        for points in route_points:
            allocated = allocate_trajectory_points(
                case,
                points,
                speed_factor=1.0,
                path_speed_targets_m_s=(certified_speed,) * (len(points) - 1),
                entry_exit_ramp_s=lookahead,
                transition_distance_m=lookahead_distance,
                turn_blend_radius_m=radius,
                corner_cut_tolerance_m=(path_deviation_cap if case.drone_count == 1 else None),
            )
            final_speeds.append(
                max(
                    math.sqrt(
                        point.velocity_m_s.x**2 + point.velocity_m_s.y**2 + point.velocity_m_s.z**2
                    )
                    for point in allocated
                )
            )
            allocated_trajectory = TimeParameterizedTrajectory(
                trajectory_id=f"capability-final-{canonical_sha256(allocated)[:20]}",
                role_id="capability-final",
                vehicle_id="capability-final",
                route_sha256=canonical_sha256(points),
                points=allocated,
                declared_stop_sequences=(allocated[0].sequence, allocated[-1].sequence),
                completion_position_tolerance_m=0.05,
                completion_velocity_tolerance_m_s=0.05,
            )
            final_accelerations.append(
                audit_trajectory(case, allocated_trajectory).maximum_acceleration_m_s2
            )
        reconciled_speed = min(final_speeds)
        maximum_final_acceleration = max(final_accelerations, default=0.0)
        if maximum_final_acceleration > tracking_acceleration_limit:
            reconciled_speed *= math.sqrt(tracking_acceleration_limit / maximum_final_acceleration)
            tracking_reserve_applied = True
        if math.isclose(reconciled_speed, certified_speed, rel_tol=1e-6, abs_tol=1e-8):
            break
        certified_speed = min(certified_speed, reconciled_speed)
        safety_retiming_factor = base_speed / certified_speed
        preliminary_distance = min(0.30, lookahead * certified_speed, adjacent_cap)
        radius_candidate = min(0.25, max(0.08, preliminary_distance * 0.75))
        radius = min(
            radius_candidate,
            adjacent_cap,
            2.0 * protected_free_space_cap,
            2.0 * path_deviation_cap,
        )
        lookahead_distance = min(preliminary_distance, 2.0 * radius)
    else:
        raise ValueError("corner-transition speed/reserve reconciliation did not converge")

    limiting = []
    if dynamics_speed_cap <= target_speed + 1e-12:
        limiting.append("dynamics speed/radius cap")
    if safety_retiming_factor > 1.0 + 1e-9:
        limiting.append("bounded acceleration/jerk retiming")
    if tracking_reserve_applied:
        limiting.append("smoothness tracking-acceleration reserve")
    if math.isclose(radius, 2.0 * path_deviation_cap, abs_tol=1e-12):
        limiting.append("sampled hard-tube tangent cap")
    if math.isclose(radius, 2.0 * protected_free_space_cap, abs_tol=1e-12):
        limiting.append("sampled protected-free-space tangent cap")
    if math.isclose(radius, adjacent_cap, abs_tol=1e-12):
        limiting.append("adjacent segment cap")
    if math.isclose(lookahead_distance, 2.0 * radius, abs_tol=1e-12):
        limiting.append("turn-blend transition cap")
    feasibility = _corner_capability_feasibility(
        case,
        route_points=tuple(route_points),
        target_speed_m_s=certified_speed,
        lookahead_time_s=lookahead,
        lookahead_distance_m=lookahead_distance,
        turn_blend_radius_m=radius,
        has_semantic_stop=any(
            mode is not RouteNodeMode.FLY_THROUGH
            for polyline in normalized_polylines
            for mode in polyline.raw_node_modes
        ),
        path_deviation_cap_m=path_deviation_cap,
        protected_free_space_cap_m=protected_free_space_cap,
    )
    return CapabilityResolution(
        capability_id=capability_id,
        capability_request_sha256=request_hash,
        normalization_rule_version=SEMANTIC_POLYLINE_RULE_VERSION,
        normalized_geometry_sha256=normalized_geometry_sha256,
        raw_capture_sha256s=tuple(polyline.raw_capture_sha256 for polyline in normalized_polylines),
        authored_lookahead_time_s=lookahead,
        authored_target_path_speed_m_s=target_speed,
        certified_entry_speed_m_s=certified_speed,
        derived_lookahead_distance_m=lookahead_distance,
        derived_turn_blend_radius_m=radius,
        adjacent_segment_cap_m=adjacent_cap,
        protected_free_space_cap_m=protected_free_space_cap,
        path_deviation_cap_m=path_deviation_cap,
        dynamics_speed_cap_m_s=dynamics_speed_cap,
        safety_retiming_factor=safety_retiming_factor,
        limiting_constraint="; ".join(limiting) or "authored lookahead/speed",
        feasibility=feasibility,
    )


def _energy_retiming_resolution(case: CampaignCase) -> EnergyRetimingResolution:
    return _energy_retiming_resolution_cached(
        case.case_sha256,
        case.model_dump_json(),
    )


@lru_cache(maxsize=64)
def _energy_retiming_resolution_cached(
    _case_sha256: str,
    case_payload_json: str,
) -> EnergyRetimingResolution:
    """Compile and rank the five frozen energy candidates on identical authored geometry."""

    case = CampaignCase.model_validate_json(case_payload_json)

    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points
    from crazyswarm_app.domain.trajectory import TimeParameterizedTrajectory, sample_trajectory
    from crazyswarm_app.simulation.physics import PhysicsModelConfig
    from crazyswarm_app.simulation.powertrain import solve_coupled_powertrain

    physics = PhysicsModelConfig()
    physics_hash = canonical_sha256(physics)
    candidates: list[EnergyRetimingCandidate] = []
    limits = case.hard_constraints.dynamics
    nominal_speed = min(0.25, limits.maximum_horizontal_speed_m_s * 0.65)
    execution_overhead_s = 8.0

    for factor in ENERGY_RETIMING_FACTORS:
        total_energy_wh = 0.0
        peak_current_a = 0.0
        maximum_horizontal_speed = 0.0
        maximum_vertical_speed = 0.0
        maximum_acceleration = 0.0
        maximum_jerk = 0.0
        maximum_route_duration = 0.0
        minimum_reserve = 100.0
        rejection_reasons: list[str] = []
        trajectory_hashes: list[str] = []

        for drone in sorted(case.drones, key=lambda item: item.role_id):
            polyline = normalized_route_polyline(case, drone.role_id)
            positions = polyline.raw_points_m
            distances = tuple(
                _vector_distance(first, second) for first, second in pairwise(positions)
            )
            baseline_durations = tuple(
                0.01 if distance <= 1e-9 else max(0.5, distance / max(0.02, nominal_speed))
                for distance in distances
            )
            requested_durations = tuple(value * factor for value in baseline_durations)
            points = allocate_trajectory_points(
                case,
                positions,
                speed_factor=1.0,
                sample_step_s=0.01,
                segment_durations_s=requested_durations,
            )
            actual_duration = points[-1].time_from_start_s
            maximum_route_duration = max(maximum_route_duration, actual_duration)
            trajectory = TimeParameterizedTrajectory(
                trajectory_id=f"energy-candidate-{drone.role_id}-{factor:.2f}",
                role_id=drone.role_id,
                vehicle_id=drone.role_id,
                route_sha256=polyline.raw_capture_sha256,
                points=points,
                declared_stop_sequences=(1, len(points)),
                completion_position_tolerance_m=0.05,
                completion_velocity_tolerance_m_s=0.05,
            )
            trajectory_hashes.append(trajectory.sha256)
            samples = []
            timestamp_s = 0.0
            while timestamp_s < trajectory.duration_s - 1e-12:
                samples.append((timestamp_s, sample_trajectory(trajectory, timestamp_s)))
                timestamp_s += 0.01
            samples.append(
                (trajectory.duration_s, sample_trajectory(trajectory, trajectory.duration_s))
            )

            powers_w: list[float] = []
            currents_a: list[float] = []
            drone_energy_wh = 0.0
            for _timestamp_s, sample in samples:
                acceleration = sample.acceleration_m_s2
                horizontal_speed = math.hypot(sample.velocity_m_s.x, sample.velocity_m_s.y)
                vertical_speed = abs(sample.velocity_m_s.z)
                acceleration_norm = math.sqrt(
                    acceleration.x**2 + acceleration.y**2 + acceleration.z**2
                )
                maximum_horizontal_speed = max(maximum_horizontal_speed, horizontal_speed)
                maximum_vertical_speed = max(maximum_vertical_speed, vertical_speed)
                maximum_acceleration = max(maximum_acceleration, acceleration_norm)
                required_collective_thrust = physics.total_mass_kg * math.sqrt(
                    acceleration.x**2
                    + acceleration.y**2
                    + (physics.gravity_m_s2 + acceleration.z) ** 2
                )
                motor_command = required_collective_thrust / (4.0 * physics.max_motor_thrust_n)
                solution = solve_coupled_powertrain(
                    physics,
                    state_of_charge=drone.initial_battery_percent / 100.0,
                    filtered_supply_voltage_v=physics.battery_full_voltage_v,
                    motor_commands=(motor_command,) * 4,
                    additional_current_a=0.0,
                )
                if (
                    motor_command > 1.0 + 1e-12
                    or solution.current_limited
                    or any(motor.saturated for motor in solution.motors)
                ):
                    rejection_reasons.append(f"ACTUATOR_HEADROOM_VIOLATION:{drone.role_id}")
                powers_w.append(solution.terminal_voltage_v * solution.total_current_a)
                currents_a.append(solution.total_current_a)
            for (before_t, _), (after_t, _), before_power, after_power in zip(
                samples[:-1],
                samples[1:],
                powers_w[:-1],
                powers_w[1:],
                strict=True,
            ):
                drone_energy_wh += (
                    0.5 * (before_power + after_power) * (after_t - before_t) / 3600.0
                )
            total_energy_wh += drone_energy_wh
            peak_current_a = max(peak_current_a, max(currents_a, default=0.0))
            reserve = drone.initial_battery_percent - (
                drone_energy_wh
                / (physics.effective_battery_capacity_ah * physics.battery_full_voltage_v)
                * 100.0
            )
            minimum_reserve = min(minimum_reserve, reserve)
            if reserve < drone.minimum_reserve_battery_percent - 1e-9:
                rejection_reasons.append(f"ENERGY_RESERVE_VIOLATION:{drone.role_id}")
            if _vector_distance(trajectory.points[-1].position_m, positions[-1]) > 1e-9:
                rejection_reasons.append(f"TERMINAL_GOAL_VIOLATION:{drone.role_id}")

            jerks = tuple(
                _vector_distance(after[1].acceleration_m_s2, before[1].acceleration_m_s2)
                / (after[0] - before[0])
                for before, after in pairwise(samples)
                if after[0] > before[0]
            )
            maximum_jerk = max(maximum_jerk, max(jerks, default=0.0))

        if maximum_route_duration + execution_overhead_s > case.hard_constraints.deadline_s + 1e-9:
            rejection_reasons.append("DEADLINE_VIOLATION")
        if maximum_horizontal_speed > limits.maximum_horizontal_speed_m_s + 1e-6:
            rejection_reasons.append("MAXIMUM_HORIZONTAL_SPEED")
        if maximum_vertical_speed > limits.maximum_vertical_speed_m_s + 1e-6:
            rejection_reasons.append("MAXIMUM_VERTICAL_SPEED")
        if maximum_acceleration > limits.maximum_acceleration_m_s2 + 1e-6:
            rejection_reasons.append("MAXIMUM_ACCELERATION")
        if maximum_jerk > limits.maximum_jerk_m_s3 + 1e-6:
            rejection_reasons.append("MAXIMUM_JERK")
        unique_reasons = tuple(sorted(set(rejection_reasons)))
        candidates.append(
            EnergyRetimingCandidate(
                duration_factor=factor,
                disposition=(
                    EnergyCandidateDisposition.REJECTED
                    if unique_reasons
                    else EnergyCandidateDisposition.FEASIBLE
                ),
                predicted_energy_wh=total_energy_wh,
                peak_current_a=peak_current_a,
                duration_s=maximum_route_duration,
                maximum_horizontal_speed_m_s=maximum_horizontal_speed,
                maximum_vertical_speed_m_s=maximum_vertical_speed,
                maximum_acceleration_m_s2=maximum_acceleration,
                maximum_jerk_m_s3=maximum_jerk,
                predicted_minimum_reserve_percent=minimum_reserve,
                rejection_reasons=unique_reasons,
                trajectory_set_sha256=canonical_sha256(tuple(trajectory_hashes)),
            )
        )

    feasible = tuple(
        item for item in candidates if item.disposition is EnergyCandidateDisposition.FEASIBLE
    )
    if not feasible:
        raise ValueError("energy-aware retiming has no candidate satisfying every hard gate")
    minimum_energy = min(item.predicted_energy_wh for item in feasible)
    ties = tuple(item for item in feasible if item.predicted_energy_wh <= minimum_energy + 1e-5)
    selected = min(
        ties,
        key=lambda item: (item.peak_current_a, item.duration_s, item.duration_factor),
    )
    limiting = (
        "energy minimum; 1e-5 Wh tie -> peak current -> duration -> factor"
        if len(ties) > 1
        else "predicted terminal-voltage x total-current energy minimum"
    )
    payload = {
        "oracle_id": "bounded-energy-retiming-v1",
        "physics_model_id": physics.model_id,
        "physics_model_version": physics.model_version,
        "powertrain_model": physics.powertrain_model.value,
        "physics_configuration_sha256": physics_hash,
        "sample_step_s": 0.01,
        "candidates": tuple(candidates),
        "selected_factor": selected.duration_factor,
        "limiting_constraint": limiting,
    }
    return EnergyRetimingResolution(
        **payload,
        evidence_sha256=canonical_sha256(payload),
    )


def _corner_capability_feasibility(
    case: CampaignCase,
    *,
    route_points: tuple[tuple[Vector3, ...], ...],
    target_speed_m_s: float,
    lookahead_time_s: float,
    lookahead_distance_m: float,
    turn_blend_radius_m: float,
    has_semantic_stop: bool,
    path_deviation_cap_m: float,
    protected_free_space_cap_m: float,
) -> CapabilityFeasibilityRecord:
    """Complete the bounded compiler and independently sample its exact deadline/dynamics."""

    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points
    from crazyswarm_app.domain.trajectory import TimeParameterizedTrajectory, sample_trajectory

    maximum_duration = 0.0
    maximum_acceleration = 0.0
    maximum_jerk = 0.0
    maximum_path_deviation = 0.0
    minimum_protected_free_space = float("inf")
    flight_volume = case.hard_constraints.flight_volume
    protected_radius = 0.055 + case.hard_constraints.position_uncertainty_m + 0.05
    environment = case.semantics.environment_constraints if case.semantics else None

    def distance_to_segment(point: Vector3, before: Vector3, after: Vector3) -> float:
        delta = (after.x - before.x, after.y - before.y, after.z - before.z)
        length_squared = sum(value * value for value in delta)
        if length_squared <= 1e-18:
            return _vector_distance(point, before)
        relative = (point.x - before.x, point.y - before.y, point.z - before.z)
        fraction = max(
            0.0,
            min(
                1.0,
                sum(left * right for left, right in zip(relative, delta, strict=True))
                / length_squared,
            ),
        )
        projection = Vector3(
            x=before.x + fraction * delta[0],
            y=before.y + fraction * delta[1],
            z=before.z + fraction * delta[2],
        )
        return _vector_distance(point, projection)

    def protected_free_space(point: Vector3) -> float:
        margins = [
            point.x - flight_volume.minimum_m.x,
            flight_volume.maximum_m.x - point.x,
            point.y - flight_volume.minimum_m.y,
            flight_volume.maximum_m.y - point.y,
            point.z - flight_volume.minimum_m.z,
            flight_volume.maximum_m.z - point.z,
        ]
        clearance = min(margins) - protected_radius
        for solid in environment.keep_out_regions if environment is not None else ():
            dx = max(solid.minimum_m.x - point.x, 0.0, point.x - solid.maximum_m.x)
            dy = max(solid.minimum_m.y - point.y, 0.0, point.y - solid.maximum_m.y)
            dz = max(solid.minimum_m.z - point.z, 0.0, point.z - solid.maximum_m.z)
            clearance = min(clearance, math.sqrt(dx * dx + dy * dy + dz * dz) - protected_radius)
        return clearance

    for role_index, points in enumerate(route_points):
        allocated = allocate_trajectory_points(
            case,
            points,
            speed_factor=1.0,
            path_speed_targets_m_s=(target_speed_m_s,) * (len(points) - 1),
            entry_exit_ramp_s=lookahead_time_s,
            transition_distance_m=lookahead_distance_m,
            turn_blend_radius_m=turn_blend_radius_m,
            corner_cut_tolerance_m=(path_deviation_cap_m if case.drone_count == 1 else None),
        )
        trajectory = TimeParameterizedTrajectory(
            trajectory_id=f"capability-feasibility-{role_index}",
            role_id=f"role-{role_index}",
            vehicle_id=f"role-{role_index}",
            route_sha256=canonical_sha256(points),
            points=allocated,
            declared_stop_sequences=(allocated[0].sequence, allocated[-1].sequence),
            completion_position_tolerance_m=0.05,
            completion_velocity_tolerance_m_s=0.05,
        )
        maximum_duration = max(maximum_duration, trajectory.duration_s)
        samples = []
        elapsed = 0.0
        while elapsed < trajectory.duration_s:
            samples.append((elapsed, sample_trajectory(trajectory, elapsed)))
            elapsed += 0.01
        samples.append(
            (trajectory.duration_s, sample_trajectory(trajectory, trajectory.duration_s))
        )
        maximum_path_deviation = max(
            maximum_path_deviation,
            *(
                min(
                    distance_to_segment(sample.position_m, before, after)
                    for before, after in pairwise(points)
                )
                for _, sample in samples
            ),
        )
        minimum_protected_free_space = min(
            minimum_protected_free_space,
            *(protected_free_space(sample.position_m) for _, sample in samples),
        )
        maximum_acceleration = max(
            maximum_acceleration,
            *(
                math.sqrt(
                    sample.acceleration_m_s2.x**2
                    + sample.acceleration_m_s2.y**2
                    + sample.acceleration_m_s2.z**2
                )
                for _, sample in samples
            ),
        )
        maximum_jerk = max(
            maximum_jerk,
            *(
                _vector_distance(after.acceleration_m_s2, before.acceleration_m_s2)
                / (after_time - before_time)
                for (before_time, before), (after_time, after) in pairwise(samples)
                if after_time > before_time
            ),
        )
    violations = []
    if has_semantic_stop:
        violations.append("SEMANTIC_STOP_INCOMPATIBLE_WITH_CORNER_PROFILE")
    if maximum_duration + 8.0 > case.hard_constraints.deadline_s + 1e-9:
        violations.append("DEADLINE_VIOLATION")
    if maximum_acceleration > case.hard_constraints.dynamics.maximum_acceleration_m_s2 + 1e-9:
        violations.append("ACCELERATION_VIOLATION")
    if maximum_jerk > case.hard_constraints.dynamics.maximum_jerk_m_s3 + 1e-9:
        violations.append("JERK_VIOLATION")
    if maximum_path_deviation > path_deviation_cap_m + 1e-9:
        violations.append("PATH_DEVIATION_VIOLATION")
    if minimum_protected_free_space < -1e-9:
        violations.append("PROTECTED_FREE_SPACE_VIOLATION")
    payload: dict[str, object] = {
        "schema_version": 1,
        "oracle_id": "independent-dense-capability-feasibility-v1",
        "disposition": (
            CapabilityFeasibilityDisposition.PROVEN_INFEASIBLE
            if violations
            else CapabilityFeasibilityDisposition.CERTIFIED
        ),
        "complete_bounded_compiler": True,
        "sample_step_s": 0.01,
        "maximum_route_duration_s": maximum_duration,
        "execution_overhead_s": 8.0,
        "deadline_s": case.hard_constraints.deadline_s,
        "maximum_acceleration_m_s2": maximum_acceleration,
        "maximum_jerk_m_s3": maximum_jerk,
        "maximum_path_deviation_m": maximum_path_deviation,
        "minimum_protected_free_space_m": minimum_protected_free_space,
        "violated_constraints": tuple(violations),
    }
    return CapabilityFeasibilityRecord(
        **payload,
        evidence_sha256=canonical_sha256(payload),
    )


def _constant_path_speed_feasibility(case: CampaignCase) -> ProfileFeasibilityRecord:
    """Compute a scalar-speed interval across every authored vehicle route."""

    segments: list[tuple[float, float, float, float]] = []
    limits = case.hard_constraints.dynamics

    def append_segment(before: Vector3, after: Vector3) -> None:
        horizontal = math.hypot(after.x - before.x, after.y - before.y)
        vertical = abs(after.z - before.z)
        length = math.hypot(horizontal, vertical)
        if length <= 1e-9:
            return
        horizontal_fraction = horizontal / length
        vertical_fraction = vertical / length
        bounds = [0.5]
        if horizontal_fraction > 1e-9:
            bounds.append(limits.maximum_horizontal_speed_m_s / horizontal_fraction)
        if vertical_fraction > 1e-9:
            bounds.append(limits.maximum_vertical_speed_m_s / vertical_fraction)
        segments.append((length, horizontal_fraction, vertical_fraction, min(bounds)))

    for drone in sorted(case.drones, key=lambda item: item.role_id):
        first_goal = drone.goal_sequence[0].center_m
        last_goal = drone.goal_sequence[-1].center_m
        points = (
            drone.start_region.center_m.model_copy(update={"z": first_goal.z}),
            *(goal.center_m for goal in drone.goal_sequence),
            drone.landing_region.center_m.model_copy(update={"z": last_goal.z}),
        )
        for before, after in pairwise(points):
            append_segment(before, after)
    if not segments:
        # A pure take-off/hover/land case intentionally has no cruise segment.
        # Its plain Speed control binds to the vertical legs instead of failing
        # preparation solely because the horizontal cruise projection is empty.
        for drone in sorted(case.drones, key=lambda item: item.role_id):
            points = (
                drone.start_region.center_m,
                *(goal.center_m for goal in drone.goal_sequence),
                drone.landing_region.center_m,
            )
            for before, after in pairwise(points):
                append_segment(before, after)
    if not segments:
        raise ValueError(f"case {case.case_id} has no nontrivial route for constant path speed")
    limiting_index = min(range(len(segments)), key=lambda index: segments[index][3])
    maximum = segments[limiting_index][3]
    minimum = max(0.05, limits.stop_speed_threshold_m_s * 4.0)
    if maximum <= minimum:
        raise ValueError(f"case {case.case_id} has no nontrivial constant-speed interval")
    return ProfileFeasibilityRecord(
        minimum_path_speed_m_s=minimum,
        maximum_path_speed_m_s=maximum,
        limiting_segment_index=limiting_index,
        maximum_horizontal_tangent_fraction=max(item[1] for item in segments),
        maximum_vertical_tangent_fraction=max(item[2] for item in segments),
        maximum_steady_window_curvature_m_inverse=0.0,
        route_segment_lengths_m=tuple(item[0] for item in segments),
        climb_descent_segment_indices=tuple(
            index for index, item in enumerate(segments) if item[2] > 1e-9
        ),
    )
