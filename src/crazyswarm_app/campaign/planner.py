from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from itertools import combinations, pairwise, permutations
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from crazyswarm_app.campaign.geometry import (
    FeasibilityCertificate,
    RouteGeometry,
    certify_candidate_routes,
    minimum_continuous_route_center_distance,
)
from crazyswarm_app.campaign.models import (
    BehaviorOracleKind,
    CampaignCase,
    ObjectiveMetric,
    PlannerStrategy,
    RouteNodeMode,
)
from crazyswarm_app.campaign.submissions import (
    BASELINE_PLANNING_SUBMISSION_ID,
    BASELINE_SUBMISSION_ID,
    CapabilityFeasibilityDisposition,
    CapabilityResolution,
    ExecutionProfileKind,
    ExecutionProfileSubmission,
    ObjectiveComposition,
    PlanningSelectionOracle,
    PlanningSubmission,
    normalized_route_polyline,
    resolve_capability_resolution,
    resolve_package_capability_resolution,
    resolve_planning_submission,
    resolve_submission,
)
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import (
    TimeParameterizedTrajectory,
    sample_trajectory,
    sample_trajectory_segment,
)

DEFAULT_TAKEOFF_DURATION_S = 2.5
DEFAULT_STABILIZATION_S = 0.5
DEFAULT_LANDING_DURATION_S = 5.0
DEFAULT_RESERVATION_CLEARANCE_S = 0.8


class CandidateStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    REJECTED = "REJECTED"


class PlanningStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class SearchDisposition(StrEnum):
    SELECTED = "SELECTED"
    PROVEN_INFEASIBLE_WITHIN_DECLARED_BOUNDS = "PROVEN_INFEASIBLE_WITHIN_DECLARED_BOUNDS"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    INDEPENDENT_VERIFICATION_REJECTED = "INDEPENDENT_VERIFICATION_REJECTED"


class GeometryFamily(StrEnum):
    DIRECT = "DIRECT"
    LATERAL_SPLINE = "LATERAL_SPLINE"
    QUADRATIC_BEZIER = "QUADRATIC_BEZIER"
    ARC_CONFLICT_TUBE = "ARC_CONFLICT_TUBE"
    CORRIDOR_FOLLOWING = "CORRIDOR_FOLLOWING"
    VERTICAL_LAYER = "VERTICAL_LAYER"


class RouteStop(ContractModel):
    position_m: Vector3
    mode: RouteNodeMode
    dwell_s: float = Field(default=0.0, ge=0.0, le=60.0)


class CandidateRoute(ContractModel):
    role_id: Identifier
    points_m: tuple[Vector3, ...] = Field(min_length=2)
    route_start_s: float = Field(ge=0.0)
    route_duration_s: float = Field(gt=0.0)
    ground_wait_s: float = Field(default=0.0, ge=0.0)
    airborne_wait_s: float = Field(default=0.0, ge=0.0)
    speed_factor: float = Field(default=1.0, gt=0.0)
    geometry_family: GeometryFamily = GeometryFamily.DIRECT
    geometry_parameters: dict[str, float | str | int | bool] = Field(default_factory=dict)
    declared_stops: tuple[RouteStop, ...] = ()
    segment_durations_s: tuple[float, ...] = ()

    @model_validator(mode="after")
    def segment_timing_matches_geometry(self) -> CandidateRoute:
        if self.segment_durations_s and len(self.segment_durations_s) != len(self.points_m) - 1:
            raise ValueError("route segment durations do not match route geometry")
        if any(duration <= 0.0 for duration in self.segment_durations_s):
            raise ValueError("route segment durations must be positive")
        return self

    @property
    def path_length_m(self) -> float:
        return sum(
            _distance(first, second)
            for first, second in zip(self.points_m, self.points_m[1:], strict=False)
        )


class CandidateCost(ContractModel):
    priority_inversion: int = Field(ge=0)
    starvation: int = Field(ge=0)
    mission_completion_time_s: float = Field(ge=0.0)
    maximum_wait_s: float = Field(ge=0.0)
    total_energy_percent: float = Field(ge=0.0)
    airborne_hover_time_s: float = Field(ge=0.0)
    path_length_m: float = Field(ge=0.0)
    acceleration_m_s2: float = Field(ge=0.0)
    jerk_m_s3: float = Field(ge=0.0)
    negative_separation_robustness_m: float
    negative_boundary_robustness_m: float
    path_fidelity_m: float = Field(ge=0.0)
    region_capture_error_m: float = Field(ge=0.0)
    integrated_squared_acceleration_m2_s3: float = Field(ge=0.0)
    integrated_squared_jerk_m2_s5: float = Field(ge=0.0)
    negative_energy_reserve_percent: float
    affected_role_count: int = Field(ge=0)
    cutover_latency_s: float = Field(ge=0.0)

    @property
    def vector(self) -> tuple[float, ...]:
        return (
            float(self.priority_inversion),
            float(self.starvation),
            self.mission_completion_time_s,
            self.maximum_wait_s,
            self.total_energy_percent,
            self.airborne_hover_time_s,
            self.path_length_m,
            self.acceleration_m_s2,
            self.jerk_m_s3,
            self.negative_separation_robustness_m,
            self.negative_boundary_robustness_m,
            self.path_fidelity_m,
            self.region_capture_error_m,
            self.integrated_squared_acceleration_m2_s3,
            self.integrated_squared_jerk_m2_s5,
            self.negative_energy_reserve_percent,
            float(self.affected_role_count),
            self.cutover_latency_s,
        )

    def vector_for(self, objective_order: Sequence[ObjectiveMetric]) -> tuple[float, ...]:
        values = {
            ObjectiveMetric.PRIORITY_INVERSION: float(self.priority_inversion),
            ObjectiveMetric.STARVATION: float(self.starvation),
            ObjectiveMetric.MISSION_COMPLETION_TIME_S: self.mission_completion_time_s,
            ObjectiveMetric.MAXIMUM_WAIT_S: self.maximum_wait_s,
            ObjectiveMetric.TOTAL_ENERGY_PERCENT: self.total_energy_percent,
            ObjectiveMetric.AIRBORNE_HOVER_TIME_S: self.airborne_hover_time_s,
            ObjectiveMetric.PATH_LENGTH_M: self.path_length_m,
            ObjectiveMetric.ACCELERATION_M_S2: self.acceleration_m_s2,
            ObjectiveMetric.JERK_M_S3: self.jerk_m_s3,
            ObjectiveMetric.SEPARATION_ROBUSTNESS_M: self.negative_separation_robustness_m,
            ObjectiveMetric.BOUNDARY_ROBUSTNESS_M: self.negative_boundary_robustness_m,
            ObjectiveMetric.PATH_FIDELITY_M: self.path_fidelity_m,
            ObjectiveMetric.REGION_CAPTURE_ERROR_M: self.region_capture_error_m,
            ObjectiveMetric.INTEGRATED_SQUARED_ACCELERATION_M2_S3: (
                self.integrated_squared_acceleration_m2_s3
            ),
            ObjectiveMetric.INTEGRATED_SQUARED_JERK_M2_S5: (self.integrated_squared_jerk_m2_s5),
            ObjectiveMetric.ENERGY_RESERVE_PERCENT: self.negative_energy_reserve_percent,
            ObjectiveMetric.AFFECTED_ROLE_COUNT: float(self.affected_role_count),
            ObjectiveMetric.CUTOVER_LATENCY_S: self.cutover_latency_s,
        }
        return tuple(values[item] for item in objective_order)


class CandidateEvaluation(ContractModel):
    candidate_id: Identifier
    strategy: PlannerStrategy
    generator_id: Identifier
    parameters: dict[str, float | str | int | bool]
    routes: tuple[CandidateRoute, ...]
    status: CandidateStatus
    rejection_reasons: tuple[str, ...]
    predicted_minimum_separation_m: float | None = Field(default=None, ge=0.0)
    minimum_boundary_margin_m: float | None = None
    predicted_battery_end_percent: dict[Identifier, float]
    cost: CandidateCost
    candidate_sha256: SHA256

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"candidate_sha256"})


class BoundedPlanningResult(ContractModel):
    schema_version: Literal[1, 2, 3] = 3
    planner_id: Identifier
    planner_version: str
    case_id: Identifier
    case_sha256: SHA256
    submission_id: Identifier | None = None
    submission_sha256: SHA256 | None = None
    planning_submission_id: Identifier = BASELINE_PLANNING_SUBMISSION_ID
    planning_submission_sha256: SHA256
    status: PlanningStatus
    search_disposition: SearchDisposition
    retained_candidates: tuple[CandidateEvaluation, ...]
    selected_candidate_index: int | None = Field(default=None, ge=0)
    selected_candidate_sha256: SHA256 | None = None
    generated_candidate_count: int = Field(ge=0)
    retained_candidate_count: int = Field(ge=0)
    truncated: bool
    truncation_limit: int = Field(ge=1)
    prediction_step_s: float = Field(gt=0.0, le=0.02)
    diagnostic_search_duration_s: float = Field(ge=0.0)
    blocking_reason: str | None = None
    bounded_search_complete: bool
    representative_candidate_sha256s: tuple[SHA256, ...]
    feasibility_certificate: FeasibilityCertificate | None = None
    optimality_claim: str
    plan_sha256: SHA256

    @model_validator(mode="after")
    def authority_is_complete(self) -> BoundedPlanningResult:
        if self.status is PlanningStatus.READY:
            if self.selected_candidate_index is None or self.selected_candidate_sha256 is None:
                raise ValueError("ready planning result requires one selected candidate")
            if self.search_disposition is not SearchDisposition.SELECTED:
                raise ValueError("ready planning result requires SELECTED disposition")
            if self.feasibility_certificate is None or not self.feasibility_certificate.passed:
                raise ValueError("ready planning result requires an independent certificate")
        elif (
            self.selected_candidate_index is not None or self.selected_candidate_sha256 is not None
        ):
            raise ValueError("blocked planning result contains execution authority")
        if (
            self.search_disposition is SearchDisposition.BUDGET_EXHAUSTED
            and self.bounded_search_complete
        ):
            raise ValueError("budget-exhausted search cannot be complete")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(
            mode="python",
            exclude={"plan_sha256", "diagnostic_search_duration_s"},
        )
        # The plan digest is intentionally a Merkle-style outer snapshot: nested
        # candidate/certificate models contribute their canonical payloads rather
        # than redundantly hashing their already-derived identity fields. Rebuild
        # those nested model values here so post-parse verification matches the
        # exact payload used by _planning_result.
        payload["retained_candidates"] = self.retained_candidates
        payload["feasibility_certificate"] = self.feasibility_certificate
        if self.submission_id is None:
            payload.pop("submission_id", None)
            payload.pop("submission_sha256", None)
        return payload

    @property
    def selected(self) -> CandidateEvaluation | None:
        if self.selected_candidate_index is None:
            return None
        return self.retained_candidates[self.selected_candidate_index]


class _CandidateSeed:
    __slots__ = ("generator_id", "parameters", "routes", "strategy")

    def __init__(
        self,
        strategy: PlannerStrategy,
        generator_id: str,
        parameters: dict[str, float | str | int | bool],
        routes: tuple[CandidateRoute, ...],
    ) -> None:
        self.strategy = strategy
        self.generator_id = generator_id
        self.parameters = parameters
        self.routes = routes


GeometryGenerator = Callable[[CampaignCase, tuple[CandidateRoute, ...]], Iterable[_CandidateSeed]]
TrajectoryCacheKey = tuple[
    tuple[Vector3, ...],
    float,
    tuple[tuple[Vector3, RouteNodeMode, float], ...],
    tuple[float, ...],
]


class BoundedJointPlanner:
    def __init__(self) -> None:
        self._geometry_generators: tuple[tuple[str, GeometryGenerator], ...] = (
            ("lateral-spline-v1", _lateral_spline_candidates),
            ("quadratic-bezier-v1", _bezier_candidates),
            ("arc-conflict-tube-v1", _arc_candidates),
            ("corridor-following-v1", _corridor_candidates),
            ("vertical-layer-v1", _vertical_candidates),
        )

    def plan(
        self,
        case: CampaignCase,
        submission: ExecutionProfileSubmission | None = None,
        *,
        planning_submission: PlanningSubmission | None = None,
        capability_resolution: CapabilityResolution | None = None,
        first_certified_within_budget: bool = False,
    ) -> BoundedPlanningResult:
        selected_submission = submission or resolve_submission(case, None, require_executable=False)
        selected_planning_submission = planning_submission or resolve_planning_submission(
            case, None, require_executable=False
        )
        expected_capability_resolution = resolve_package_capability_resolution(
            case,
            selected_planning_submission,
            selected_submission,
        )
        if (
            capability_resolution is not None
            and capability_resolution != expected_capability_resolution
        ):
            raise ValueError("planner capability resolution does not match case/profile")
        selected_capability_resolution = capability_resolution or expected_capability_resolution
        if (
            selected_planning_submission.execution_profile_sha256
            != selected_submission.profile_sha256
        ):
            selected_planning_submission = selected_planning_submission.model_copy(
                update={
                    "execution_profile_submission_id": selected_submission.submission_id,
                    "execution_profile_sha256": selected_submission.profile_sha256,
                }
            )
        if (
            selected_capability_resolution is not None
            and selected_capability_resolution.feasibility is not None
            and selected_capability_resolution.feasibility.disposition
            is CapabilityFeasibilityDisposition.PROVEN_INFEASIBLE
        ):
            violated = ",".join(
                selected_capability_resolution.feasibility.violated_constraints
            )
            return _planning_result(
                case,
                submission=selected_submission,
                planning_submission=selected_planning_submission,
                evaluations=(),
                generated_count=0,
                truncated=False,
                duration_s=0.0,
                blocking_reason=(
                    "complete capability compiler and independent dense oracle proved "
                    f"{violated}"
                ),
                disposition=SearchDisposition.PROVEN_INFEASIBLE_WITHIN_DECLARED_BOUNDS,
                optimality_claim=(
                    "exact capability infeasibility proven by complete compiler and "
                    "independent dense deadline/dynamics oracle"
                ),
            )
        environment = case.semantics.environment_constraints if case.semantics else None
        obstacle_conditioned_submission = (
            selected_planning_submission.planning_submission_id != BASELINE_PLANNING_SUBMISSION_ID
            and case.parent_case_sha256 is not None
            and environment is not None
            and bool(environment.keep_out_regions)
        )
        first_certified_budget_s = (
            min(
                case.search.planning_budget_s,
                case.hard_constraints.planning_budget_s,
            )
            if first_certified_within_budget
            else case.search.planning_budget_s
        )
        first_certified_within_budget = (
            first_certified_within_budget or obstacle_conditioned_submission
        )
        started = time.perf_counter()
        base_routes = _direct_routes(case)
        seed_source: Iterable[_CandidateSeed] = self._generate(
            case,
            base_routes,
            selected_planning_submission,
        )
        if selected_submission.kind in {
            ExecutionProfileKind.CONSTANT_PATH_SPEED,
            ExecutionProfileKind.DURATION_SCALE,
            ExecutionProfileKind.CORNER_TRANSITION,
        }:
            seed_source = (
                _apply_execution_profile_to_seed(
                    case,
                    seed,
                    selected_submission,
                    selected_capability_resolution,
                )
                for seed in seed_source
            )
        elif selected_submission.kind is not ExecutionProfileKind.PLANNER_RETIMED_BASELINE:
            # Segment-indexed experiments remain bound to the authored reference
            # geometry until they gain their own geometry-remapping semantics.
            seed_source = (
                _CandidateSeed(
                    PlannerStrategy.DIRECT,
                    "execution-profile-v2",
                    {
                        "submission_id": selected_submission.submission_id,
                        "profile_kind": selected_submission.kind.value,
                    },
                    _apply_execution_profile(case, base_routes, selected_submission),
                ),
            )
        authorized_seeds = (
            seed
            for seed in seed_source
            if seed.strategy in selected_planning_submission.strategy_authority
        )
        if first_certified_within_budget:
            return self._first_certified_plan(
                case,
                submission=selected_submission,
                planning_submission=selected_planning_submission,
                seeds=authorized_seeds,
                started=started,
                budget_s=first_certified_budget_s,
            )
        seeds = list(authorized_seeds)
        generated_count = len(seeds)
        retained_seeds = seeds[: case.search.maximum_candidate_count]
        truncated = generated_count > len(retained_seeds)
        evaluations: list[CandidateEvaluation] = []
        trajectory_cache: dict[TrajectoryCacheKey, TimeParameterizedTrajectory] = {}
        position_cache: dict[TrajectoryCacheKey, tuple[Vector3, ...]] = {}
        dynamics_cache: dict[TrajectoryCacheKey, tuple[float, float]] = {}
        budget_expired = False
        for index, seed in enumerate(retained_seeds):
            if time.perf_counter() - started > case.search.planning_budget_s:
                budget_expired = True
                break
            evaluation = _evaluate_candidate(
                index,
                seed,
                case,
                planning_submission=selected_planning_submission,
                trajectory_cache=trajectory_cache,
                position_cache=position_cache,
                dynamics_cache=dynamics_cache,
            )
            evaluations.append(evaluation)
        duration = time.perf_counter() - started
        if budget_expired or len(evaluations) != len(retained_seeds):
            return _planning_result(
                case,
                submission=selected_submission,
                planning_submission=selected_planning_submission,
                evaluations=tuple(evaluations),
                generated_count=generated_count,
                truncated=truncated,
                duration_s=duration,
                blocking_reason=(
                    "planning budget expired before all retained candidates were validated"
                ),
                disposition=SearchDisposition.BUDGET_EXHAUSTED,
            )
        feasible = [
            index
            for index, item in enumerate(evaluations)
            if item.status is CandidateStatus.FEASIBLE
        ]
        if not feasible:
            return _planning_result(
                case,
                submission=selected_submission,
                planning_submission=selected_planning_submission,
                evaluations=tuple(evaluations),
                generated_count=generated_count,
                truncated=truncated,
                duration_s=duration,
                blocking_reason="no bounded generated candidate satisfies every hard constraint",
                disposition=SearchDisposition.PROVEN_INFEASIBLE_WITHIN_DECLARED_BOUNDS,
            )
        objective_order = tuple(
            term.metric for term in selected_planning_submission.objective.terms
        )
        if (
            selected_planning_submission.objective.composition
            is not ObjectiveComposition.LEXICOGRAPHIC
        ):
            raise ValueError("weighted planning objectives are not implemented by this backend")
        selected_index: int | None = None
        certificate: FeasibilityCertificate | None = None
        optimality_claim: str | None = None
        if (
            selected_planning_submission.selection_oracle
            is PlanningSelectionOracle.OBJECTIVE_ORDER
        ):
            ranked_feasible = sorted(
                feasible,
                key=lambda index: (
                    evaluations[index].cost.vector_for(objective_order),
                    evaluations[index].candidate_sha256,
                ),
            )
            for index in ranked_feasible:
                candidate = evaluations[index]
                checked = certify_candidate_routes(
                    case,
                    selected_planning_submission,
                    candidate.candidate_sha256,
                    cast(Sequence[RouteGeometry], candidate.routes),
                )
                if checked.passed:
                    selected_index = index
                    certificate = checked
                    break
        else:
            independently_certified: list[
                tuple[int, CandidateEvaluation, FeasibilityCertificate]
            ] = []
            for index in feasible:
                candidate = evaluations[index]
                checked = certify_candidate_routes(
                    case,
                    selected_planning_submission,
                    candidate.candidate_sha256,
                    cast(Sequence[RouteGeometry], candidate.routes),
                )
                if checked.passed:
                    independently_certified.append((index, candidate, checked))
            if (
                selected_planning_submission.selection_oracle
                is PlanningSelectionOracle.ARGMIN_BOUNDED_RELEASE
            ):
                independently_certified.sort(
                    key=lambda item: (
                        max(route.route_start_s for route in item[1].routes)
                        - min(route.route_start_s for route in item[1].routes),
                        item[1].cost.vector_for(objective_order),
                        item[1].candidate_sha256,
                    )
                )
                optimality_claim = (
                    "minimum route-release skew among all independently certified "
                    "candidates in the complete bounded family"
                )
            elif (
                selected_planning_submission.selection_oracle
                is PlanningSelectionOracle.ARGMAX_BOUNDED_CLEARANCE
            ):
                independently_certified.sort(
                    key=lambda item: (
                        -min(
                            item[2].minimum_pairwise_protected_clearance_m,
                            item[2].minimum_solid_protected_clearance_m,
                        ),
                        item[1].candidate_sha256,
                    )
                )
                optimality_claim = (
                    "maximum independently certified protected clearance among all "
                    "candidates in the complete bounded family"
                )
            else:
                raise ValueError(
                    "unknown planning selection oracle: "
                    f"{selected_planning_submission.selection_oracle}"
                )
            if independently_certified:
                selected_index, _, certificate = independently_certified[0]
        if selected_index is None:
            return _planning_result(
                case,
                submission=selected_submission,
                planning_submission=selected_planning_submission,
                evaluations=tuple(evaluations),
                generated_count=generated_count,
                truncated=truncated,
                duration_s=time.perf_counter() - started,
                blocking_reason=(
                    "sampled candidates failed independent continuous feasibility verification"
                ),
                disposition=SearchDisposition.INDEPENDENT_VERIFICATION_REJECTED,
            )
        return _planning_result(
            case,
            submission=selected_submission,
            planning_submission=selected_planning_submission,
            evaluations=tuple(evaluations),
            generated_count=generated_count,
            truncated=truncated,
            duration_s=duration,
            selected_index=selected_index,
            certificate=certificate,
            disposition=SearchDisposition.SELECTED,
            optimality_claim=optimality_claim,
        )

    def _first_certified_plan(
        self,
        case: CampaignCase,
        *,
        submission: ExecutionProfileSubmission,
        planning_submission: PlanningSubmission,
        seeds: Iterable[_CandidateSeed],
        started: float,
        budget_s: float,
    ) -> BoundedPlanningResult:
        """Evaluate a lazy deterministic prefix until one candidate is certified."""

        evaluations: list[CandidateEvaluation] = []
        trajectory_cache: dict[TrajectoryCacheKey, TimeParameterizedTrajectory] = {}
        position_cache: dict[TrajectoryCacheKey, tuple[Vector3, ...]] = {}
        dynamics_cache: dict[TrajectoryCacheKey, tuple[float, float]] = {}
        verifier_rejected = False
        exhausted = True
        for index, seed in enumerate(seeds):
            if index >= case.search.maximum_candidate_count:
                exhausted = False
                break
            elapsed = time.perf_counter() - started
            if elapsed > budget_s:
                return _planning_result(
                    case,
                    submission=submission,
                    planning_submission=planning_submission,
                    evaluations=tuple(evaluations),
                    generated_count=len(evaluations),
                    truncated=True,
                    duration_s=elapsed,
                    blocking_reason=("planning budget expired before a replacement was certified"),
                    disposition=SearchDisposition.BUDGET_EXHAUSTED,
                )
            evaluation = _evaluate_candidate(
                index,
                seed,
                case,
                planning_submission=planning_submission,
                trajectory_cache=trajectory_cache,
                position_cache=position_cache,
                dynamics_cache=dynamics_cache,
            )
            evaluations.append(evaluation)
            if evaluation.status is not CandidateStatus.FEASIBLE:
                continue
            certificate = certify_candidate_routes(
                case,
                planning_submission,
                evaluation.candidate_sha256,
                cast(Sequence[RouteGeometry], evaluation.routes),
            )
            elapsed = time.perf_counter() - started
            if elapsed > budget_s:
                return _planning_result(
                    case,
                    submission=submission,
                    planning_submission=planning_submission,
                    evaluations=tuple(evaluations),
                    generated_count=len(evaluations),
                    truncated=True,
                    duration_s=elapsed,
                    blocking_reason=(
                        "planning budget expired during independent replacement verification"
                    ),
                    disposition=SearchDisposition.BUDGET_EXHAUSTED,
                )
            if certificate.passed:
                return _planning_result(
                    case,
                    submission=submission,
                    planning_submission=planning_submission,
                    evaluations=tuple(evaluations),
                    generated_count=len(evaluations),
                    truncated=True,
                    duration_s=elapsed,
                    selected_index=len(evaluations) - 1,
                    certificate=certificate,
                    disposition=SearchDisposition.SELECTED,
                    bounded_search_complete=False,
                    optimality_claim=(
                        "first independently certified feasible candidate in "
                        "deterministic generator order; no optimality claim"
                    ),
                )
            verifier_rejected = True
        elapsed = time.perf_counter() - started
        disposition = (
            SearchDisposition.INDEPENDENT_VERIFICATION_REJECTED
            if verifier_rejected
            else SearchDisposition.PROVEN_INFEASIBLE_WITHIN_DECLARED_BOUNDS
        )
        return _planning_result(
            case,
            submission=submission,
            planning_submission=planning_submission,
            evaluations=tuple(evaluations),
            generated_count=len(evaluations),
            truncated=not exhausted,
            duration_s=elapsed,
            blocking_reason=(
                "no sampled candidate passed independent continuous verification"
                if verifier_rejected
                else "no generated candidate satisfies every hard constraint"
            ),
            disposition=disposition,
            bounded_search_complete=exhausted,
        )

    def _generate(
        self,
        case: CampaignCase,
        base_routes: tuple[CandidateRoute, ...],
        planning_submission: PlanningSubmission,
    ) -> Iterable[_CandidateSeed]:
        authorized_strategies = set(planning_submission.strategy_authority)
        in_flight = planning_submission.planning_submission_id.startswith("in_flight.")
        environment = case.semantics.environment_constraints if case.semantics else None
        prioritize_solids = in_flight or (
            planning_submission.planning_submission_id != BASELINE_PLANNING_SUBMISSION_ID
            and environment is not None
            and bool(environment.keep_out_regions)
        )
        # A changed-world head is feasibility/deadline driven.  Put candidates
        # derived from the changed solid geometry ahead of generic direct/retiming
        # probes so an executable certificate can be issued inside the reaction
        # horizon without weakening any constraint.
        if prioritize_solids and PlannerStrategy.HORIZONTAL_DETOUR in authorized_strategies:
            yield from _fleet_solid_lane_candidates(
                case,
                base_routes,
                planning_submission=planning_submission,
            )
            yield from _joint_solid_directed_candidates(
                case,
                base_routes,
                planning_submission=planning_submission,
                vertical=False,
            )
            yield from _solid_directed_candidates(
                case,
                base_routes,
                planning_submission=planning_submission,
                vertical=False,
            )
        if prioritize_solids and PlannerStrategy.VERTICAL_LAYER in authorized_strategies:
            yield from _joint_solid_directed_candidates(
                case,
                base_routes,
                planning_submission=planning_submission,
                vertical=True,
            )
            yield from _solid_directed_candidates(
                case,
                base_routes,
                planning_submission=planning_submission,
                vertical=True,
            )
        if PlannerStrategy.DIRECT in authorized_strategies:
            yield _CandidateSeed(PlannerStrategy.DIRECT, "direct-v1", {}, base_routes)
        if PlannerStrategy.GROUND_DELAY in authorized_strategies:
            if case.family == "bottleneck":
                yield from _bottleneck_serialized_candidates(
                    case,
                    base_routes,
                    planning_submission,
                )
            if (
                case.family == "constrained_volume"
                and planning_submission.planning_submission_id
                in {"constrained.timing_makespan", "constrained.robust_schedule"}
            ):
                yield from _joint_continuous_release_candidates(
                    base_routes,
                    planning_submission,
                )
            yield from _continuous_release_candidates(
                base_routes,
                planning_submission,
                ground=True,
            )
            for role in sorted(route.role_id for route in base_routes):
                for delay_s in case.search.delay_grid_s:
                    yield _retime_seed(base_routes, role, delay_s, ground=True)
            if len(base_routes) > 1:
                for order in permutations(sorted(route.role_id for route in base_routes)):
                    yield _joint_retime_seed(base_routes, order, ground=True)
        if PlannerStrategy.AIRBORNE_STAGING in authorized_strategies:
            yield from _continuous_release_candidates(
                base_routes,
                planning_submission,
                ground=False,
            )
            for role in sorted(route.role_id for route in base_routes):
                for delay_s in case.search.delay_grid_s:
                    yield _retime_seed(base_routes, role, delay_s, ground=False)
            if len(base_routes) > 1:
                for order in permutations(sorted(route.role_id for route in base_routes)):
                    yield _joint_retime_seed(base_routes, order, ground=False)
        if PlannerStrategy.SPEED_RETIMING in authorized_strategies:
            for role in sorted(route.role_id for route in base_routes):
                for factor in case.search.speed_factors:
                    yield _speed_seed(
                        case,
                        base_routes,
                        role,
                        factor,
                        retime_authored_segments=(
                            planning_submission.planning_submission_id
                            == "turnaround.continuity_first"
                        ),
                    )
        if PlannerStrategy.HORIZONTAL_DETOUR in authorized_strategies:
            if planning_submission.planning_submission_id != BASELINE_PLANNING_SUBMISSION_ID:
                if not prioritize_solids:
                    yield from _joint_solid_directed_candidates(
                        case,
                        base_routes,
                        planning_submission=planning_submission,
                        vertical=False,
                    )
                    yield from _solid_directed_candidates(
                        case,
                        base_routes,
                        planning_submission=planning_submission,
                        vertical=False,
                    )
                yield from _joint_lateral_clearance_candidates(case, base_routes)
                yield from _clearance_directed_individual_candidates(
                    case,
                    base_routes,
                    vertical=False,
                )
            for _, generator in self._geometry_generators[:-1]:
                yield from generator(case, base_routes)
        if PlannerStrategy.VERTICAL_LAYER in authorized_strategies:
            if planning_submission.planning_submission_id != BASELINE_PLANNING_SUBMISSION_ID:
                if not prioritize_solids:
                    yield from _joint_solid_directed_candidates(
                        case,
                        base_routes,
                        planning_submission=planning_submission,
                        vertical=True,
                    )
                    yield from _solid_directed_candidates(
                        case,
                        base_routes,
                        planning_submission=planning_submission,
                        vertical=True,
                    )
                yield from _joint_vertical_clearance_candidates(case, base_routes)
                yield from _clearance_directed_individual_candidates(
                    case,
                    base_routes,
                    vertical=True,
                )
            yield from self._geometry_generators[-1][1](case, base_routes)
        if PlannerStrategy.COMBINED_TIMING_GEOMETRY in authorized_strategies:
            geometry = list(_lateral_spline_candidates(case, base_routes)) + list(
                _vertical_candidates(case, base_routes)
            )
            for seed in geometry:
                for delay_s in case.search.delay_grid_s[:2]:
                    role = str(seed.parameters["role_id"])
                    routes = tuple(
                        route.model_copy(
                            update={
                                "route_start_s": route.route_start_s + delay_s,
                                "ground_wait_s": route.ground_wait_s + delay_s,
                            }
                        )
                        if route.role_id == role
                        else route
                        for route in seed.routes
                    )
                    yield _CandidateSeed(
                        PlannerStrategy.COMBINED_TIMING_GEOMETRY,
                        f"combined-{seed.generator_id}",
                        {**seed.parameters, "delay_s": delay_s},
                        routes,
                    )


def _direct_routes(case: CampaignCase) -> tuple[CandidateRoute, ...]:
    # Import lazily to keep the planner/trajectory model dependency acyclic at import time.
    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points

    routes = []
    for drone in sorted(case.drones, key=lambda item: item.role_id):
        first_goal = drone.goal_sequence[0].center_m
        last_goal = drone.goal_sequence[-1].center_m
        launch = Vector3(
            x=drone.start_region.center_m.x,
            y=drone.start_region.center_m.y,
            z=first_goal.z,
        )
        landing_approach = Vector3(
            x=drone.landing_region.center_m.x,
            y=drone.landing_region.center_m.y,
            z=last_goal.z,
        )
        points = _deduplicate_points(
            (launch, *(goal.center_m for goal in drone.goal_sequence), landing_approach)
        )
        if len(points) == 1:
            # A pure hover is still an executable time interval, represented by a
            # stationary two-knot trajectory at the authored location.
            points = (points[0], points[0])
        node_by_region = {node.region_id: node for node in case.route_nodes_for(drone.role_id)}
        declared_stops = tuple(
            RouteStop(position_m=goal.center_m, mode=node.mode, dwell_s=node.dwell_s)
            for goal in drone.goal_sequence
            for node in (node_by_region[goal.region_id],)
            if node.mode is not RouteNodeMode.FLY_THROUGH
        )
        allocated = allocate_trajectory_points(
            case,
            points,
            speed_factor=1.0,
            declared_stops=declared_stops,
        )
        authored_times = []
        search_start = 0
        for position in points:
            matched = next(
                index
                for index in range(search_start, len(allocated))
                if _distance(allocated[index].position_m, position) <= 1e-9
            )
            authored_times.append(allocated[matched].time_from_start_s)
            search_start = matched + 1
        segment_durations = tuple(
            after - before for before, after in pairwise(authored_times)
        )
        routes.append(
            CandidateRoute(
                role_id=drone.role_id,
                points_m=points,
                route_start_s=0.0,
                route_duration_s=allocated[-1].time_from_start_s,
                declared_stops=declared_stops,
                segment_durations_s=(
                    segment_durations
                    if not declared_stops
                    or all(stop.dwell_s <= 1e-12 for stop in declared_stops)
                    else ()
                ),
            )
        )
    output = tuple(routes)
    coordination = case.semantics.coordination_constraints if case.semantics else None
    if coordination is not None and coordination.maximum_formation_error_m is not None:
        point_counts = {len(route.points_m) for route in output}
        if len(point_counts) != 1:
            raise ValueError("formation roles require the same authored knot count")
        shared_durations = tuple(
            max(
                1.0,
                max(_distance(route.points_m[index], route.points_m[index + 1]) for route in output)
                / 0.12,
            )
            for index in range(len(output[0].points_m) - 1)
        )
        output = tuple(
            route.model_copy(
                update={
                    "segment_durations_s": shared_durations,
                    "route_duration_s": allocate_trajectory_points(
                        case,
                        route.points_m,
                        speed_factor=route.speed_factor,
                        declared_stops=route.declared_stops,
                        segment_durations_s=shared_durations,
                    )[-1].time_from_start_s,
                }
            )
            for route in output
        )
    return output


def _apply_execution_profile(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
    submission: ExecutionProfileSubmission,
    capability_resolution: CapabilityResolution | None = None,
) -> tuple[CandidateRoute, ...]:
    """Bind an admitted time law to immutable case geometry."""

    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points

    selected_resolution = capability_resolution or resolve_capability_resolution(case, submission)
    output = []
    for route in routes:
        allocation_positions = route.points_m
        if submission.kind is ExecutionProfileKind.CORNER_TRANSITION:
            allocation_positions = normalized_route_polyline(
                case,
                route.role_id,
                route.points_m,
            ).normalized_points_m
        distances = tuple(
            _distance(first, second) for first, second in pairwise(allocation_positions)
        )
        parameters = submission.parameters
        path_speed_targets_m_s: tuple[float, ...] = ()
        if submission.kind is ExecutionProfileKind.CONSTANT_PATH_SPEED:
            assert parameters.target_path_speed_m_s is not None
            path_speed_targets_m_s = (parameters.target_path_speed_m_s,) * len(distances)
            durations = tuple(
                max(0.01, distance / parameters.target_path_speed_m_s) for distance in distances
            )
        elif submission.kind is ExecutionProfileKind.RAMPED_SEGMENT_SPEED:
            speeds = parameters.segment_target_speeds_m_s
            if len(speeds) != len(distances):
                raise ValueError(
                    f"submission {submission.submission_id} declares {len(speeds)} "
                    f"segment speeds for {len(distances)} route segments"
                )
            path_speed_targets_m_s = speeds
            durations = tuple(
                max(0.01, distance / speed)
                for distance, speed in zip(distances, speeds, strict=True)
            )
        elif submission.kind is ExecutionProfileKind.BOUNDED_VERTICAL_RATE:
            assert parameters.target_vertical_rate_m_s is not None
            durations = tuple(
                max(
                    0.01,
                    abs(after.z - before.z) / parameters.target_vertical_rate_m_s
                    if abs(after.z - before.z) > 1e-9
                    else distance / 0.18,
                )
                for before, after, distance in zip(
                    route.points_m[:-1],
                    route.points_m[1:],
                    distances,
                    strict=True,
                )
            )
            path_speed_targets_m_s = tuple(
                distance / duration for distance, duration in zip(distances, durations, strict=True)
            )
        elif submission.kind is ExecutionProfileKind.DURATION_SCALE:
            assert parameters.duration_scale is not None
            baseline_durations = (
                route.segment_durations_s
                if route.segment_durations_s
                else tuple(max(0.01, distance / 0.18) for distance in distances)
            )
            durations = tuple(
                duration * parameters.duration_scale for duration in baseline_durations
            )
        elif submission.kind is ExecutionProfileKind.CORNER_TRANSITION:
            if selected_resolution is None:
                raise ValueError("corner-transition planning requires a capability resolution")
            assert parameters.target_path_speed_m_s is not None
            path_speed_targets_m_s = (parameters.target_path_speed_m_s,) * len(distances)
            durations = tuple(
                max(0.01, distance / parameters.target_path_speed_m_s) for distance in distances
            )
        else:
            raise ValueError(
                f"submission {submission.submission_id} has no executable trajectory time law"
            )
        points = allocate_trajectory_points(
            case,
            allocation_positions,
            speed_factor=1.0,
            declared_stops=route.declared_stops,
            segment_durations_s=durations,
            path_speed_targets_m_s=path_speed_targets_m_s,
            entry_exit_ramp_s=(
                parameters.lookahead_time_s
                if submission.kind is ExecutionProfileKind.CORNER_TRANSITION
                and parameters.lookahead_time_s is not None
                else parameters.entry_exit_ramp_s
            ),
            transition_distance_m=(
                selected_resolution.derived_lookahead_distance_m
                if selected_resolution is not None
                and submission.kind is ExecutionProfileKind.CORNER_TRANSITION
                else None
            ),
            turn_blend_radius_m=(
                selected_resolution.derived_turn_blend_radius_m
                if selected_resolution is not None
                and submission.kind is ExecutionProfileKind.CORNER_TRANSITION
                else None
            ),
        )
        duration_scale = points[-1].time_from_start_s / max(sum(durations), 1e-9)
        retimed_durations = (
            tuple(duration * duration_scale for duration in durations)
            if path_speed_targets_m_s and not route.declared_stops
            else durations
        )
        raw_distances = tuple(
            _distance(first, second) for first, second in pairwise(route.points_m)
        )
        raw_total = sum(raw_distances)
        raw_segment_durations = (
            tuple(
                points[-1].time_from_start_s * distance / raw_total
                for distance in raw_distances
            )
            if submission.kind is ExecutionProfileKind.CORNER_TRANSITION and raw_total > 1e-9
            else retimed_durations
        )
        output.append(
            route.model_copy(
                update={
                    "segment_durations_s": raw_segment_durations,
                    "route_duration_s": points[-1].time_from_start_s,
                    "speed_factor": 1.0,
                }
            )
        )
    return tuple(output)


def _apply_execution_profile_to_seed(
    case: CampaignCase,
    seed: _CandidateSeed,
    submission: ExecutionProfileSubmission,
    capability_resolution: CapabilityResolution | None,
) -> _CandidateSeed:
    """Layer a reusable time law over planner-selected geometry and coordination."""

    parameters: dict[str, float | str | int | bool] = {
        **seed.parameters,
        "execution_capability_id": submission.submission_id,
        "execution_profile_kind": submission.kind.value,
    }
    if capability_resolution is not None:
        parameters["capability_resolution_sha256"] = canonical_sha256(capability_resolution)
    return _CandidateSeed(
        seed.strategy,
        seed.generator_id,
        parameters,
        _apply_execution_profile(
            case,
            seed.routes,
            submission,
            capability_resolution,
        ),
    )


def _retime_seed(
    routes: tuple[CandidateRoute, ...], role_id: str, delay_s: float, *, ground: bool
) -> _CandidateSeed:
    strategy = PlannerStrategy.GROUND_DELAY if ground else PlannerStrategy.AIRBORNE_STAGING
    selected = tuple(
        route.model_copy(
            update={
                "route_start_s": route.route_start_s + delay_s,
                "ground_wait_s": delay_s if ground else 0.0,
                "airborne_wait_s": 0.0 if ground else delay_s,
            }
        )
        if route.role_id == role_id
        else route
        for route in routes
    )
    return _CandidateSeed(
        strategy,
        "ground-delay-v1" if ground else "airborne-staging-v1",
        {"role_id": role_id, "delay_s": delay_s},
        selected,
    )


def _continuous_release_candidates(
    routes: tuple[CandidateRoute, ...],
    planning_submission: PlanningSubmission,
    *,
    ground: bool,
) -> Iterable[_CandidateSeed]:
    """Find the earliest safe release boundary instead of relying on a delay grid."""

    if planning_submission.coordination.synchronized_route_start_required:
        return
    required = planning_submission.clearance.required_pairwise_center_separation_m
    maximum_delay_s = planning_submission.coordination.maximum_release_delay_s
    if maximum_delay_s <= 0.0:
        return
    for role_id in sorted(route.role_id for route in routes):
        if (
            _minimum_continuous_candidate_distance(
                _routes_with_release_delay(routes, role_id, 0.0, ground=ground)
            )
            >= required
        ):
            continue
        lower = 0.0
        upper: float | None = None
        for step in range(1, 65):
            probe = maximum_delay_s * step / 64.0
            if (
                _minimum_continuous_candidate_distance(
                    _routes_with_release_delay(routes, role_id, probe, ground=ground)
                )
                >= required
            ):
                upper = probe
                break
            lower = probe
        if upper is None:
            continue
        for _ in range(24):
            midpoint = (lower + upper) / 2.0
            if (
                _minimum_continuous_candidate_distance(
                    _routes_with_release_delay(routes, role_id, midpoint, ground=ground)
                )
                >= required
            ):
                upper = midpoint
            else:
                lower = midpoint
        selected = _routes_with_release_delay(routes, role_id, upper, ground=ground)
        yield _CandidateSeed(
            PlannerStrategy.GROUND_DELAY if ground else PlannerStrategy.AIRBORNE_STAGING,
            "continuous-ground-release-v1" if ground else "continuous-airborne-release-v1",
            {
                "role_id": role_id,
                "delay_s": upper,
                "solver": "BRACKETED_BISECTION",
            },
            selected,
        )


def _joint_continuous_release_candidates(
    routes: tuple[CandidateRoute, ...],
    planning_submission: PlanningSubmission,
) -> Iterable[_CandidateSeed]:
    """Enumerate exact earliest feasible releases for every role ordering."""

    if planning_submission.coordination.synchronized_route_start_required:
        return
    maximum_delay_s = planning_submission.coordination.maximum_release_delay_s
    required = planning_submission.clearance.required_pairwise_center_separation_m
    if maximum_delay_s <= 0.0:
        return
    route_by_role = {route.role_id: route for route in routes}
    for order in permutations(sorted(route_by_role)):
        scheduled: list[CandidateRoute] = []
        starts: dict[str, float] = {}
        feasible = True
        for role_id in order:
            route = route_by_role[role_id]
            if not scheduled:
                start_s = 0.0
            else:
                lower = 0.0
                upper: float | None = None
                for step in range(65):
                    probe = maximum_delay_s * step / 64.0
                    candidate = route.model_copy(
                        update={
                            "route_start_s": probe,
                            "ground_wait_s": probe,
                            "airborne_wait_s": 0.0,
                        }
                    )
                    if (
                        _minimum_continuous_candidate_distance(
                            (*scheduled, candidate)
                        )
                        >= required
                    ):
                        upper = probe
                        break
                    lower = probe
                if upper is None:
                    feasible = False
                    break
                for _ in range(24):
                    midpoint = (lower + upper) / 2.0
                    candidate = route.model_copy(
                        update={
                            "route_start_s": midpoint,
                            "ground_wait_s": midpoint,
                            "airborne_wait_s": 0.0,
                        }
                    )
                    if (
                        _minimum_continuous_candidate_distance(
                            (*scheduled, candidate)
                        )
                        >= required
                    ):
                        upper = midpoint
                    else:
                        lower = midpoint
                start_s = upper
            starts[role_id] = start_s
            scheduled.append(
                route.model_copy(
                    update={
                        "route_start_s": start_s,
                        "ground_wait_s": start_s,
                        "airborne_wait_s": 0.0,
                    }
                )
            )
        if not feasible:
            continue
        selected = tuple(
            route.model_copy(
                update={
                    "route_start_s": starts[route.role_id],
                    "ground_wait_s": starts[route.role_id],
                    "airborne_wait_s": 0.0,
                }
            )
            for route in routes
        )
        if _minimum_continuous_candidate_distance(selected) + 1e-9 < required:
            continue
        yield _CandidateSeed(
            PlannerStrategy.GROUND_DELAY,
            "joint-continuous-ground-release-v1",
            {
                "precedence_order": ",".join(order),
                "solver": "ORDERED_BRACKETED_BISECTION",
            },
            selected,
        )


def _minimum_continuous_candidate_distance(
    routes: tuple[CandidateRoute, ...],
) -> float:
    return minimum_continuous_route_center_distance(cast(Sequence[RouteGeometry], routes))


def _bottleneck_serialized_candidates(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
    planning_submission: PlanningSubmission,
) -> Iterable[_CandidateSeed]:
    staged = _joint_geometry_seed(
        case,
        routes,
        {route.role_id: _outward_goal_points(case, route) for route in routes},
        strategy=PlannerStrategy.HORIZONTAL_DETOUR,
        generator_id="joint-clearance-lateral-v1",
        family=GeometryFamily.CORRIDOR_FOLLOWING,
        parameters={"passage_staging": True},
        stop_at_authored_nodes=True,
    )
    if planning_submission.planning_submission_id == "bottleneck.earliest_safe_release":
        # The existing serialized candidate reserves the entire prior mission,
        # including landing, and is intentionally conservative. The earliest
        # objective instead resolves the first continuously certified release
        # boundary for the same staged geometry and authority.
        yield from _continuous_release_candidates(
            staged.routes,
            planning_submission,
            ground=True,
        )
    for order in permutations(sorted(route.role_id for route in routes)):
        retimed = _joint_retime_seed(staged.routes, order, ground=True)
        yield _CandidateSeed(
            PlannerStrategy.GROUND_DELAY,
            "constraint-directed-bottleneck-serialized-v1",
            {
                "precedence_order": ",".join(order),
                "passage_staging": True,
            },
            retimed.routes,
        )


def _routes_with_release_delay(
    routes: tuple[CandidateRoute, ...],
    role_id: str,
    delay_s: float,
    *,
    ground: bool,
) -> tuple[CandidateRoute, ...]:
    return tuple(
        route.model_copy(
            update={
                "route_start_s": route.route_start_s + delay_s,
                "ground_wait_s": delay_s if ground else 0.0,
                "airborne_wait_s": 0.0 if ground else delay_s,
            }
        )
        if route.role_id == role_id
        else route
        for route in routes
    )


def _joint_retime_seed(
    routes: tuple[CandidateRoute, ...], order: tuple[str, ...], *, ground: bool
) -> _CandidateSeed:
    route_by_role = {route.role_id: route for route in routes}
    starts: dict[str, float] = {}
    release_s = 0.0
    for role_id in order:
        starts[role_id] = release_s
        release_s += route_by_role[role_id].route_duration_s + DEFAULT_RESERVATION_CLEARANCE_S
        if ground:
            release_s += (
                DEFAULT_TAKEOFF_DURATION_S + DEFAULT_STABILIZATION_S + DEFAULT_LANDING_DURATION_S
            )
    selected = tuple(
        route.model_copy(
            update={
                "route_start_s": starts[route.role_id],
                "ground_wait_s": starts[route.role_id] if ground else 0.0,
                "airborne_wait_s": 0.0 if ground else starts[route.role_id],
            }
        )
        for route in routes
    )
    strategy = PlannerStrategy.GROUND_DELAY if ground else PlannerStrategy.AIRBORNE_STAGING
    return _CandidateSeed(
        strategy,
        "joint-ground-delay-v1" if ground else "joint-airborne-staging-v1",
        {"precedence_order": ",".join(order)},
        selected,
    )


def _speed_seed(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
    role_id: str,
    factor: float,
    *,
    retime_authored_segments: bool = False,
) -> _CandidateSeed:
    selected = tuple(
        _speed_retimed_route(
            case,
            route,
            factor,
            retime_authored_segments=retime_authored_segments,
        )
        if route.role_id == role_id
        else route
        for route in routes
    )
    return _CandidateSeed(
        PlannerStrategy.SPEED_RETIMING,
        "speed-retiming-v1",
        {"role_id": role_id, "speed_factor": factor},
        selected,
    )


def _speed_retimed_route(
    case: CampaignCase,
    route: CandidateRoute,
    factor: float,
    *,
    retime_authored_segments: bool,
) -> CandidateRoute:
    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points

    # The continuity experiment owns speed retiming as its only changed
    # planning axis. Other experiments retain their authored segment timing so
    # this fix cannot perturb their frozen comparison packages.
    authored = () if retime_authored_segments else route.segment_durations_s
    allocated = allocate_trajectory_points(
        case,
        route.points_m,
        speed_factor=factor,
        declared_stops=route.declared_stops,
        segment_durations_s=authored,
    )
    segment_durations = route.segment_durations_s
    if retime_authored_segments:
        authored_times: list[float] = []
        search_start = 0
        for position in route.points_m:
            matched = next(
                index
                for index in range(search_start, len(allocated))
                if _distance(allocated[index].position_m, position) <= 1e-9
            )
            authored_times.append(allocated[matched].time_from_start_s)
            search_start = matched + 1
        segment_durations = tuple(
            after - before for before, after in pairwise(authored_times)
        )
    return route.model_copy(
        update={
            "route_duration_s": allocated[-1].time_from_start_s,
            "speed_factor": factor,
            "segment_durations_s": segment_durations,
        }
    )


def _joint_lateral_clearance_candidates(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
) -> Iterable[_CandidateSeed]:
    required = (
        case.hard_constraints.warning_separation_m + case.hard_constraints.position_uncertainty_m
    )
    offset = required * 0.56
    for first, second in combinations(routes, 2):
        for pattern_id, second_sign in (("opposed-normals", 1.0), ("split-normals", -1.0)):
            replacements = {
                first.role_id: _multi_segment_detour_points(first.points_m, offset),
                second.role_id: _multi_segment_detour_points(second.points_m, offset * second_sign),
            }
            yield _joint_geometry_seed(
                case,
                routes,
                replacements,
                strategy=PlannerStrategy.HORIZONTAL_DETOUR,
                generator_id="joint-clearance-lateral-v1",
                family=GeometryFamily.LATERAL_SPLINE,
                parameters={
                    "role_pair": f"{first.role_id},{second.role_id}",
                    "lateral_offset_m": offset,
                    "pattern": pattern_id,
                },
            )


def _joint_vertical_clearance_candidates(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
) -> Iterable[_CandidateSeed]:
    required = (
        case.hard_constraints.warning_separation_m + case.hard_constraints.position_uncertainty_m
    )
    volume = case.hard_constraints.flight_volume
    available_height_m = volume.maximum_m.z - volume.minimum_m.z
    boundary_margin_m = 0.25 if available_height_m >= required + 0.50 else 0.095
    low_layer = volume.minimum_m.z + boundary_margin_m
    high_layer = volume.maximum_m.z - boundary_margin_m
    if high_layer - low_layer < required:
        return
    for first, second in combinations(routes, 2):
        for first_layer, second_layer in (
            (low_layer, high_layer),
            (high_layer, low_layer),
        ):
            first_points = (
                _outward_goal_points(case, first) if case.family == "bottleneck" else first.points_m
            )
            second_points = (
                _outward_goal_points(case, second)
                if case.family == "bottleneck"
                else second.points_m
            )
            replacements = {
                first.role_id: _layer_between_route_nodes(first_points, first_layer),
                second.role_id: _layer_between_route_nodes(second_points, second_layer),
            }
            yield _joint_geometry_seed(
                case,
                routes,
                replacements,
                strategy=PlannerStrategy.VERTICAL_LAYER,
                generator_id="joint-clearance-vertical-v1",
                family=GeometryFamily.VERTICAL_LAYER,
                parameters={
                    "role_pair": f"{first.role_id},{second.role_id}",
                    "first_layer_m": first_layer,
                    "second_layer_m": second_layer,
                },
                stop_at_authored_nodes=True,
            )


def _outward_goal_points(
    case: CampaignCase,
    route: CandidateRoute,
) -> tuple[Vector3, ...]:
    drone = next(item for item in case.drones if item.role_id == route.role_id)
    if len(route.points_m) < 4 or len(drone.goal_sequence) < 2:
        return route.points_m
    entry_goal, exit_goal = drone.goal_sequence[:2]
    entry = route.points_m[1].model_copy(
        update={
            "x": (entry_goal.minimum_m.x if route.points_m[1].x < 0.0 else entry_goal.maximum_m.x)
        }
    )
    exit_point = route.points_m[2].model_copy(
        update={
            "x": (exit_goal.minimum_m.x if route.points_m[2].x < 0.0 else exit_goal.maximum_m.x)
        }
    )
    entry_staging = entry.model_copy(update={"x": entry.x + math.copysign(0.20, entry.x)})
    exit_staging = exit_point.model_copy(
        update={"x": exit_point.x + math.copysign(0.20, exit_point.x)}
    )
    return (
        route.points_m[0],
        entry_staging,
        entry,
        exit_point,
        exit_staging,
        *route.points_m[3:],
    )


def _joint_geometry_seed(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
    replacements: dict[str, tuple[Vector3, ...]],
    *,
    strategy: PlannerStrategy,
    generator_id: str,
    family: GeometryFamily,
    parameters: dict[str, float | str | int | bool],
    stop_at_authored_nodes: bool = False,
) -> _CandidateSeed:
    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points

    prepared: dict[
        str,
        tuple[tuple[Vector3, ...], tuple[RouteStop, ...], tuple[float, ...]],
    ] = {}
    for route in routes:
        points = replacements.get(route.role_id)
        if points is None:
            continue
        declared_stops = route.declared_stops
        if stop_at_authored_nodes:
            declared_stops = tuple(
                dict.fromkeys(
                    (
                        *declared_stops,
                        *(
                            RouteStop(
                                position_m=point,
                                mode=RouteNodeMode.CAPTURE,
                                dwell_s=0.0,
                            )
                            for point in points[1:-1]
                        ),
                    )
                )
            )
        allocated = allocate_trajectory_points(
            case,
            points,
            speed_factor=route.speed_factor,
            declared_stops=declared_stops,
        )
        prepared[route.role_id] = (
            points,
            declared_stops,
            tuple(
                after.time_from_start_s - before.time_from_start_s
                for before, after in pairwise(allocated)
            ),
        )
    duration_counts = {len(item[2]) for item in prepared.values()}
    shared_durations: tuple[float, ...] | None = None
    if len(prepared) >= 2 and len(duration_counts) == 1:
        shared_durations = tuple(
            max(item[2][index] for item in prepared.values()) * 1.05
            for index in range(next(iter(duration_counts)))
        )

    selected = []
    for route in routes:
        prepared_route = prepared.get(route.role_id)
        if prepared_route is None:
            selected.append(route)
            continue
        points, declared_stops, initial_durations = prepared_route
        allocated = allocate_trajectory_points(
            case,
            points,
            speed_factor=route.speed_factor,
            declared_stops=declared_stops,
            segment_durations_s=shared_durations or initial_durations,
        )
        segment_durations_s = tuple(
            after.time_from_start_s - before.time_from_start_s
            for before, after in pairwise(allocated)
        )
        selected.append(
            route.model_copy(
                update={
                    "points_m": points,
                    "segment_durations_s": segment_durations_s,
                    "route_duration_s": allocated[-1].time_from_start_s,
                    "declared_stops": declared_stops,
                    "geometry_family": family,
                    "geometry_parameters": parameters,
                }
            )
        )
    return _CandidateSeed(
        strategy,
        generator_id,
        parameters,
        tuple(selected),
    )


def _multi_segment_detour_points(
    points: tuple[Vector3, ...],
    offset: float,
) -> tuple[Vector3, ...]:
    output = [points[0]]
    for start, end in pairwise(points):
        dx, dy = end.x - start.x, end.y - start.y
        length = math.hypot(dx, dy) or 1.0
        output.extend(
            (
                Vector3(
                    x=(start.x + end.x) / 2.0 - dy / length * offset,
                    y=(start.y + end.y) / 2.0 + dx / length * offset,
                    z=(start.z + end.z) / 2.0,
                ),
                end,
            )
        )
    return _deduplicate_points(tuple(output))


def _layer_between_route_nodes(
    points: tuple[Vector3, ...],
    layer_m: float,
) -> tuple[Vector3, ...]:
    output = [points[0]]
    for start, end in pairwise(points):
        output.extend(
            (
                Vector3(x=start.x, y=start.y, z=layer_m),
                Vector3(x=end.x, y=end.y, z=layer_m),
                end,
            )
        )
    return _deduplicate_points(tuple(output))


def _lateral_spline_candidates(
    case: CampaignCase, routes: tuple[CandidateRoute, ...]
) -> Iterable[_CandidateSeed]:
    for route in routes:
        for offset in case.search.lateral_offsets_m:
            points = _detour_points(route.points_m, offset, family=GeometryFamily.LATERAL_SPLINE)
            yield _geometry_seed(
                case,
                route,
                routes,
                points,
                "lateral-spline-v1",
                {"lateral_offset_m": offset},
            )


def _bezier_candidates(
    case: CampaignCase, routes: tuple[CandidateRoute, ...]
) -> Iterable[_CandidateSeed]:
    for route in routes:
        for offset in case.search.lateral_offsets_m:
            points = _detour_points(route.points_m, offset, family=GeometryFamily.QUADRATIC_BEZIER)
            yield _geometry_seed(
                case,
                route,
                routes,
                points,
                "quadratic-bezier-v1",
                {"control_offset_m": offset},
            )


def _arc_candidates(
    case: CampaignCase, routes: tuple[CandidateRoute, ...]
) -> Iterable[_CandidateSeed]:
    for route in routes:
        for radius in case.search.arc_radii_m:
            for sign in (-1.0, 1.0):
                points = _detour_points(
                    route.points_m, radius * sign, family=GeometryFamily.ARC_CONFLICT_TUBE
                )
                yield _geometry_seed(
                    case,
                    route,
                    routes,
                    points,
                    "arc-conflict-tube-v1",
                    {"radius_m": radius, "side": int(sign)},
                )


def _corridor_candidates(
    case: CampaignCase, routes: tuple[CandidateRoute, ...]
) -> Iterable[_CandidateSeed]:
    for route in routes:
        for offset in case.search.lateral_offsets_m[:2]:
            points = _detour_points(
                route.points_m, offset, family=GeometryFamily.CORRIDOR_FOLLOWING
            )
            yield _geometry_seed(
                case,
                route,
                routes,
                points,
                "corridor-following-v1",
                {"corridor_offset_m": offset},
            )


def _vertical_candidates(
    case: CampaignCase, routes: tuple[CandidateRoute, ...]
) -> Iterable[_CandidateSeed]:
    for route in routes:
        for offset in case.search.vertical_offsets_m:
            points = _vertical_points(route.points_m, offset)
            yield _geometry_seed(
                case,
                route,
                routes,
                points,
                "vertical-layer-v1",
                {"vertical_offset_m": offset},
            )


def _clearance_directed_individual_candidates(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
    *,
    vertical: bool,
) -> Iterable[_CandidateSeed]:
    required = (
        case.hard_constraints.warning_separation_m
        + case.hard_constraints.position_uncertainty_m
        + 0.10
    )
    for route in routes:
        for offset in (required, -required):
            points = (
                _vertical_points(route.points_m, offset)
                if vertical
                else _detour_points(
                    route.points_m,
                    offset,
                    family=GeometryFamily.LATERAL_SPLINE,
                )
            )
            yield _geometry_seed(
                case,
                route,
                routes,
                points,
                "vertical-layer-v1" if vertical else "lateral-spline-v1",
                {
                    "vertical_offset_m": offset if vertical else 0.0,
                    "lateral_offset_m": offset if not vertical else 0.0,
                    "derived_from_clearance": True,
                },
            )


def _joint_solid_directed_candidates(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
    *,
    planning_submission: PlanningSubmission,
    vertical: bool,
) -> Iterable[_CandidateSeed]:
    """Compose fleet-clearance routing with all solid-invalidated route segments."""

    environment = case.semantics.environment_constraints if case.semantics else None
    if environment is None or not environment.keep_out_regions:
        return
    policy = planning_submission.clearance
    horizontal_clearance = (
        policy.nominal_vehicle_radius_m
        + policy.required_solid_clearance_m
        + policy.uncertainty_allowance_m
    )
    vertical_clearance = (
        policy.nominal_vehicle_half_height_m
        + policy.required_solid_clearance_m
        + policy.uncertainty_allowance_m
    )
    joint_seeds = (
        _joint_vertical_clearance_candidates(case, routes)
        if vertical
        else _joint_lateral_clearance_candidates(case, routes)
    )
    for joint in joint_seeds:
        ordered_roles = tuple(sorted(route.role_id for route in joint.routes))
        for solid in environment.keep_out_regions:
            for pattern in ("negative", "positive", "alternating"):
                selected = joint.routes
                changed_roles: list[str] = []
                for role_index, role_id in enumerate(ordered_roles):
                    route = next(item for item in selected if item.role_id == role_id)
                    side = (
                        -1
                        if pattern == "negative"
                        else 1
                        if pattern == "positive"
                        else (-1 if role_index % 2 == 0 else 1)
                    )
                    if vertical:
                        layer = (
                            solid.maximum_m.z + vertical_clearance
                            if side > 0
                            else solid.minimum_m.z - vertical_clearance
                        )
                        points = _all_segment_vertical_detour_points(
                            route.points_m,
                            solid,
                            layer_m=layer,
                            margin_m=max(horizontal_clearance, vertical_clearance),
                        )
                        generator_id = "solid-directed-vertical-v1"
                    else:
                        points = _all_segment_lateral_detour_points(
                            route.points_m,
                            solid,
                            side=side,
                            clearance_m=horizontal_clearance,
                        )
                        generator_id = "solid-directed-lateral-v1"
                    if points == route.points_m:
                        continue
                    changed_roles.append(role_id)
                    selected = _geometry_seed(
                        case,
                        route,
                        selected,
                        points,
                        generator_id,
                        {
                            "solid_id": solid.region_id,
                            "side": side,
                            "all_invalidated_segments": True,
                        },
                    ).routes
                if changed_roles:
                    yield _CandidateSeed(
                        PlannerStrategy.VERTICAL_LAYER
                        if vertical
                        else PlannerStrategy.HORIZONTAL_DETOUR,
                        (
                            "joint-solid-directed-vertical-v1"
                            if vertical
                            else "joint-solid-directed-lateral-v1"
                        ),
                        {
                            **joint.parameters,
                            "solid_id": solid.region_id,
                            "detour_pattern": pattern,
                            "changed_roles": ",".join(changed_roles),
                            "joint_generator_id": joint.generator_id,
                        },
                        selected,
                    )


def _fleet_solid_lane_candidates(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
    *,
    planning_submission: PlanningSubmission,
) -> Iterable[_CandidateSeed]:
    """Route the affected fleet through deterministic obstacle-clear lanes.

    Replanning each role independently is insufficient for a head-on encounter:
    two individually clear dog-legs can still cross.  This generator assigns the
    whole affected fleet to clearance-separated lanes and gives the independent
    verifier the complete joint geometry in one candidate.
    """

    environment = case.semantics.environment_constraints if case.semantics else None
    if environment is None or not environment.keep_out_regions or len(routes) < 2:
        return
    policy = planning_submission.clearance
    required_center_separation = policy.required_pairwise_center_separation_m + 0.04
    solid_clearance = (
        policy.nominal_vehicle_radius_m
        + policy.required_solid_clearance_m
        + policy.uncertainty_allowance_m
        + 0.02
    )
    ordered = tuple(sorted(routes, key=lambda item: item.role_id))
    for solid in environment.keep_out_regions:
        half_y = (solid.maximum_m.y - solid.minimum_m.y) / 2.0
        lane_distance = max(
            half_y + solid_clearance,
            required_center_separation / 2.0,
        )
        lane_offsets: tuple[tuple[float, ...], ...]
        if len(ordered) == 2:
            lane_offsets = (
                (-lane_distance, lane_distance),
                (lane_distance, -lane_distance),
            )
        else:
            lane_offsets = (
                tuple((-1.5 + index) * required_center_separation for index in range(len(ordered))),
                tuple((1.5 - index) * required_center_separation for index in range(len(ordered))),
            )
        for pattern_index, offsets in enumerate(lane_offsets, start=1):
            replacements: dict[str, tuple[Vector3, ...]] = {}
            viable = True
            for route, offset in zip(ordered, offsets, strict=True):
                lane_y = solid.center_m.y + offset
                if not (
                    case.hard_constraints.flight_volume.minimum_m.y
                    + policy.nominal_vehicle_radius_m
                    <= lane_y
                    <= case.hard_constraints.flight_volume.maximum_m.y
                    - policy.nominal_vehicle_radius_m
                ):
                    viable = False
                    break
                replacements[route.role_id] = _all_segment_lateral_detour_points(
                    route.points_m,
                    solid,
                    side=1 if offset > 0.0 else -1,
                    clearance_m=max(solid_clearance, abs(offset) - half_y),
                )
            if viable and all(replacements[item.role_id] != item.points_m for item in ordered):
                yield _joint_geometry_seed(
                    case,
                    routes,
                    replacements,
                    strategy=PlannerStrategy.HORIZONTAL_DETOUR,
                    generator_id="fleet-solid-lanes-v1",
                    family=GeometryFamily.LATERAL_SPLINE,
                    parameters={
                        "solid_id": solid.region_id,
                        "lane_pattern": pattern_index,
                        "lane_spacing_m": required_center_separation,
                    },
                    stop_at_authored_nodes=True,
                )


def _solid_directed_candidates(
    case: CampaignCase,
    routes: tuple[CandidateRoute, ...],
    *,
    planning_submission: PlanningSubmission,
    vertical: bool,
) -> Iterable[_CandidateSeed]:
    """Generate detours at the actual obstructed segment, not only segment zero."""

    environment = case.semantics.environment_constraints if case.semantics else None
    if environment is None or not environment.keep_out_regions:
        return
    policy = planning_submission.clearance
    horizontal_clearance = (
        policy.nominal_vehicle_radius_m
        + policy.required_solid_clearance_m
        + policy.uncertainty_allowance_m
    )
    vertical_clearance = (
        policy.nominal_vehicle_half_height_m
        + policy.required_solid_clearance_m
        + policy.uncertainty_allowance_m
    )
    for route in routes:
        for segment_index, (start, end) in enumerate(pairwise(route.points_m)):
            for solid in environment.keep_out_regions:
                if not _segment_bounds_overlap_region(
                    start,
                    end,
                    solid,
                    margin_m=max(horizontal_clearance, vertical_clearance),
                ):
                    continue
                if vertical:
                    layers = (
                        solid.maximum_m.z + vertical_clearance,
                        solid.minimum_m.z - vertical_clearance,
                    )
                    for layer in layers:
                        points = _segment_vertical_detour_points(
                            route.points_m,
                            segment_index,
                            layer,
                        )
                        yield _geometry_seed(
                            case,
                            route,
                            routes,
                            points,
                            "solid-directed-vertical-v1",
                            {
                                "solid_id": solid.region_id,
                                "segment_index": segment_index,
                                "layer_m": layer,
                            },
                        )
                else:
                    for side in (-1, 1):
                        points = _segment_lateral_detour_points(
                            route.points_m,
                            segment_index,
                            solid,
                            side=side,
                            clearance_m=horizontal_clearance,
                        )
                        yield _geometry_seed(
                            case,
                            route,
                            routes,
                            points,
                            "solid-directed-lateral-v1",
                            {
                                "solid_id": solid.region_id,
                                "segment_index": segment_index,
                                "side": side,
                            },
                        )


def _segment_bounds_overlap_region(
    start: Vector3,
    end: Vector3,
    region: object,
    *,
    margin_m: float,
) -> bool:
    from crazyswarm_app.campaign.models import Region3D

    if not isinstance(region, Region3D):
        raise TypeError("solid-directed planning requires Region3D obstacles")
    return not (
        max(start.x, end.x) < region.minimum_m.x - margin_m
        or min(start.x, end.x) > region.maximum_m.x + margin_m
        or max(start.y, end.y) < region.minimum_m.y - margin_m
        or min(start.y, end.y) > region.maximum_m.y + margin_m
        or max(start.z, end.z) < region.minimum_m.z - margin_m
        or min(start.z, end.z) > region.maximum_m.z + margin_m
    )


def _segment_lateral_detour_points(
    points: tuple[Vector3, ...],
    segment_index: int,
    region: object,
    *,
    side: int,
    clearance_m: float,
) -> tuple[Vector3, ...]:
    from crazyswarm_app.campaign.models import Region3D

    if not isinstance(region, Region3D):
        raise TypeError("solid-directed planning requires Region3D obstacles")
    start, end = points[segment_index], points[segment_index + 1]
    dx, dy = end.x - start.x, end.y - start.y
    # Use an orthogonal dog-leg around the clearance-inflated AABB.  Two points
    # merely offset along the segment normal can leave the approach chord cutting
    # back through a box corner; the independent continuous verifier correctly
    # rejects that shape.  Keeping the two approach legs outside the tangent-axis
    # slab makes every segment of this polyline continuously clear.
    margin = clearance_m + 0.01
    if abs(dx) >= abs(dy):
        safe_y = region.maximum_m.y + margin if side > 0 else region.minimum_m.y - margin
        replacement = (
            Vector3(x=start.x, y=safe_y, z=start.z),
            Vector3(x=end.x, y=safe_y, z=end.z),
            end,
        )
    else:
        safe_x = region.maximum_m.x + margin if side > 0 else region.minimum_m.x - margin
        replacement = (
            Vector3(x=safe_x, y=start.y, z=start.z),
            Vector3(x=safe_x, y=end.y, z=end.z),
            end,
        )
    return _deduplicate_points(
        (*points[: segment_index + 1], *replacement, *points[segment_index + 2 :])
    )


def _segment_vertical_detour_points(
    points: tuple[Vector3, ...],
    segment_index: int,
    layer_m: float,
) -> tuple[Vector3, ...]:
    start, end = points[segment_index], points[segment_index + 1]
    replacement = (
        Vector3(x=start.x, y=start.y, z=layer_m),
        Vector3(x=end.x, y=end.y, z=layer_m),
        end,
    )
    return _deduplicate_points(
        (*points[: segment_index + 1], *replacement, *points[segment_index + 2 :])
    )


def _all_segment_lateral_detour_points(
    points: tuple[Vector3, ...],
    region: object,
    *,
    side: int,
    clearance_m: float,
) -> tuple[Vector3, ...]:
    output = [points[0]]
    changed = False
    for start, end in pairwise(points):
        if _segment_bounds_overlap_region(
            start,
            end,
            region,
            margin_m=clearance_m,
        ):
            detour = _segment_lateral_detour_points(
                (start, end),
                0,
                region,
                side=side,
                clearance_m=clearance_m,
            )
            output.extend(detour[1:])
            changed = True
        else:
            output.append(end)
    return _deduplicate_points(tuple(output)) if changed else points


def _all_segment_vertical_detour_points(
    points: tuple[Vector3, ...],
    region: object,
    *,
    layer_m: float,
    margin_m: float,
) -> tuple[Vector3, ...]:
    output = [points[0]]
    changed = False
    for start, end in pairwise(points):
        if _segment_bounds_overlap_region(start, end, region, margin_m=margin_m):
            detour = _segment_vertical_detour_points((start, end), 0, layer_m)
            output.extend(detour[1:])
            changed = True
        else:
            output.append(end)
    return _deduplicate_points(tuple(output)) if changed else points


def _geometry_seed(
    case: CampaignCase,
    route: CandidateRoute,
    routes: tuple[CandidateRoute, ...],
    points: tuple[Vector3, ...],
    generator_id: str,
    parameters: dict[str, float | str | int | bool],
) -> _CandidateSeed:
    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points

    family = {
        "lateral-spline-v1": GeometryFamily.LATERAL_SPLINE,
        "solid-directed-lateral-v1": GeometryFamily.LATERAL_SPLINE,
        "quadratic-bezier-v1": GeometryFamily.QUADRATIC_BEZIER,
        "arc-conflict-tube-v1": GeometryFamily.ARC_CONFLICT_TUBE,
        "corridor-following-v1": GeometryFamily.CORRIDOR_FOLLOWING,
        "vertical-layer-v1": GeometryFamily.VERTICAL_LAYER,
        "solid-directed-vertical-v1": GeometryFamily.VERTICAL_LAYER,
    }[generator_id]
    replacement = route.model_copy(
        update={
            "points_m": points,
            "segment_durations_s": (
                route.segment_durations_s
                if len(route.segment_durations_s) == len(points) - 1
                else ()
            ),
            "route_duration_s": allocate_trajectory_points(
                case,
                points,
                speed_factor=route.speed_factor,
                declared_stops=route.declared_stops,
                segment_durations_s=(
                    route.segment_durations_s
                    if len(route.segment_durations_s) == len(points) - 1
                    else ()
                ),
            )[-1].time_from_start_s,
            "geometry_family": family,
            "geometry_parameters": parameters,
        }
    )
    selected = tuple(replacement if item.role_id == route.role_id else item for item in routes)
    return _CandidateSeed(
        PlannerStrategy.VERTICAL_LAYER
        if family is GeometryFamily.VERTICAL_LAYER
        else PlannerStrategy.HORIZONTAL_DETOUR,
        generator_id,
        {"role_id": route.role_id, **parameters},
        selected,
    )


def _detour_points(
    points: tuple[Vector3, ...], offset: float, *, family: GeometryFamily
) -> tuple[Vector3, ...]:
    start, end = points[0], points[1]
    dx, dy = end.x - start.x, end.y - start.y
    length = math.hypot(dx, dy) or 1.0
    normal = (-dy / length, dx / length)
    midpoint = Vector3(
        x=(start.x + end.x) / 2.0 + normal[0] * offset,
        y=(start.y + end.y) / 2.0 + normal[1] * offset,
        z=(start.z + end.z) / 2.0,
    )
    if family is GeometryFamily.ARC_CONFLICT_TUBE:
        quarter = _lerp(start, midpoint, 0.65)
        three_quarter = _lerp(midpoint, end, 0.35)
        return (start, quarter, midpoint, three_quarter, *points[1:])
    if family is GeometryFamily.CORRIDOR_FOLLOWING:
        entry = Vector3(x=start.x + normal[0] * offset, y=start.y + normal[1] * offset, z=start.z)
        exit_point = Vector3(x=end.x + normal[0] * offset, y=end.y + normal[1] * offset, z=end.z)
        return (start, entry, exit_point, *points[1:])
    return (start, midpoint, *points[1:])


def _vertical_points(points: tuple[Vector3, ...], offset: float) -> tuple[Vector3, ...]:
    start, end = points[0], points[1]
    layer = (start.z + end.z) / 2.0 + offset
    return (
        start,
        Vector3(x=start.x, y=start.y, z=layer),
        Vector3(x=end.x, y=end.y, z=layer),
        *points[1:],
    )


def _evaluate_candidate(
    index: int,
    seed: _CandidateSeed,
    case: CampaignCase,
    *,
    planning_submission: PlanningSubmission,
    trajectory_cache: dict[TrajectoryCacheKey, TimeParameterizedTrajectory],
    position_cache: dict[TrajectoryCacheKey, tuple[Vector3, ...]],
    dynamics_cache: dict[TrajectoryCacheKey, tuple[float, float]],
) -> CandidateEvaluation:
    reasons: list[str] = []
    trajectories = _candidate_trajectories(seed.routes, case, trajectory_cache)
    margins = [
        _boundary_margin(point, case)
        for route, trajectory in zip(seed.routes, trajectories, strict=True)
        for point in _sample_trajectory_positions(
            route,
            trajectory,
            case.search.prediction_step_s,
            position_cache,
        )
    ]
    boundary = min(margins) if margins else None
    if boundary is None or boundary < 0.0:
        reasons.append("FLIGHT_VOLUME_VIOLATION")
    semantics = case.semantics
    if semantics is not None:
        environment = semantics.environment_constraints
        for route, trajectory in zip(seed.routes, trajectories, strict=True):
            samples = _sample_trajectory_positions(
                route,
                trajectory,
                case.search.prediction_step_s,
                position_cache,
            )
            if any(
                region.contains(point)
                for region in environment.keep_out_regions
                for point in samples
            ):
                reasons.append(f"KEEP_OUT_VIOLATION:{route.role_id}")
            if environment.required_corridors and any(
                not any(corridor.contains(point) for corridor in environment.required_corridors)
                for point in samples
            ):
                reasons.append(f"REQUIRED_CORRIDOR_VIOLATION:{route.role_id}")
    if (
        seed.strategy is PlannerStrategy.VERTICAL_LAYER
        and not case.hard_constraints.vertical_layers_allowed
    ):
        reasons.append("VERTICAL_LAYER_FORBIDDEN")
    if (
        seed.strategy is PlannerStrategy.AIRBORNE_STAGING
        and not case.hard_constraints.hover_allowed
    ):
        reasons.append("HOVER_FORBIDDEN")
    if any(route.airborne_wait_s > case.hard_constraints.maximum_hover_s for route in seed.routes):
        reasons.append("HOVER_LIMIT_EXCEEDED")
    if (
        not case.hard_constraints.synchronized_launch_required
        and PlannerStrategy.GROUND_DELAY in case.allowed_strategies
        and any(
            route.airborne_wait_s > case.hard_constraints.maximum_unrequired_airborne_wait_s
            for route in seed.routes
        )
    ):
        reasons.append("UNREQUIRED_AIRBORNE_WAIT_EXCEEDED")
    planning_coordination = planning_submission.coordination
    if (
        case.hard_constraints.synchronized_launch_required
        or planning_coordination.synchronized_launch_required
    ) and len({round(route.ground_wait_s, 9) for route in seed.routes}) > 1:
        reasons.append("SYNCHRONIZED_LAUNCH_VIOLATION")
    planning_route_starts = [route.route_start_s for route in seed.routes]
    planning_start_skew_s = max(planning_route_starts, default=0.0) - min(
        planning_route_starts, default=0.0
    )
    if (
        planning_coordination.synchronized_route_start_required
        and planning_start_skew_s
        > planning_coordination.maximum_route_start_skew_s + 1e-9
    ):
        reasons.append("PLANNING_SYNCHRONIZED_ROUTE_START_VIOLATION")
    if (
        _simultaneous_route_overlap_s(seed.routes)
        < planning_coordination.minimum_simultaneous_flight_s
    ):
        reasons.append("PLANNING_MINIMUM_SIMULTANEOUS_FLIGHT_VIOLATION")
    if semantics is not None:
        coordination = semantics.coordination_constraints
        route_starts = [route.route_start_s for route in seed.routes]
        route_start_skew_s = max(route_starts, default=0.0) - min(route_starts, default=0.0)
        if (
            coordination.synchronized_route_start_required
            and route_start_skew_s > coordination.maximum_route_start_skew_s
        ):
            reasons.append("SYNCHRONIZED_ROUTE_START_VIOLATION")
        overlap_s = _simultaneous_route_overlap_s(seed.routes)
        if overlap_s < coordination.minimum_simultaneous_flight_s:
            reasons.append("MINIMUM_SIMULTANEOUS_FLIGHT_VIOLATION")
        if coordination.maximum_formation_error_m is not None:
            formation_error = _maximum_formation_error(
                seed.routes,
                trajectories,
                coordination.formation_offsets_m,
                coordination.formation_offsets_by_node_m,
                case.search.prediction_step_s,
            )
            if formation_error > coordination.maximum_formation_error_m:
                reasons.append("FORMATION_ERROR_VIOLATION")
    separation = _minimum_smooth_joint_separation(
        seed.routes,
        trajectories,
        case.search.prediction_step_s,
        position_cache,
    )
    objective_separation = (
        _minimum_continuous_candidate_distance(seed.routes)
        if planning_submission.planning_submission_id
        == "constrained.robust_schedule"
        else separation
    )
    required = planning_submission.clearance.required_pairwise_center_separation_m
    if separation < required:
        reasons.append("GLOBAL_RESERVATION_SEPARATION_VIOLATION")
    drone_by_role = {drone.role_id: drone for drone in case.drones}
    battery_end: dict[str, float] = {}
    total_energy = 0.0
    for route in seed.routes:
        drone = drone_by_role[route.role_id]
        energy = route.path_length_m * 1.0 + route.airborne_wait_s * 0.25 + 1.0
        total_energy += energy
        battery_end[route.role_id] = drone.initial_battery_percent - energy
        if battery_end[route.role_id] < drone.minimum_reserve_battery_percent:
            reasons.append(f"BATTERY_RESERVE_VIOLATION:{route.role_id}")
        landing = drone.landing_region.center_m
        route_end = route.points_m[-1]
        if math.hypot(route_end.x - landing.x, route_end.y - landing.y) > 1e-9:
            reasons.append(f"TERMINAL_GOAL_VIOLATION:{route.role_id}")
        if any(
            not any(goal.contains(point) for point in route.points_m)
            for goal in drone.goal_sequence
        ):
            reasons.append(f"REQUIRED_GOAL_VIOLATION:{route.role_id}")
        maximum_speed = route.path_length_m / route.route_duration_s
        if maximum_speed > case.hard_constraints.dynamics.maximum_horizontal_speed_m_s:
            reasons.append(f"DYNAMICS_SPEED_VIOLATION:{route.role_id}")
    execution_overhead_s = (
        DEFAULT_TAKEOFF_DURATION_S + DEFAULT_STABILIZATION_S + DEFAULT_LANDING_DURATION_S
    )
    completion = max(
        route.route_start_s + route.route_duration_s + execution_overhead_s for route in seed.routes
    )
    if completion > case.hard_constraints.deadline_s:
        reasons.append("DEADLINE_VIOLATION")
    waits = [route.route_start_s for route in seed.routes]
    precedence_threshold = _priority_precedence_threshold(case)
    if precedence_threshold is not None:
        prioritized_routes = sorted(
            seed.routes,
            key=lambda route: (-drone_by_role[route.role_id].priority, route.role_id),
        )
        if any(
            later.route_start_s - earlier.route_start_s
            < precedence_threshold - 1e-9
            for earlier, later in pairwise(prioritized_routes)
        ):
            reasons.append("PRIORITY_PRECEDENCE_VIOLATION")
    priority_inversion = _priority_inversions(seed.routes, drone_by_role)
    dynamics = []
    for route, trajectory in zip(seed.routes, trajectories, strict=True):
        key = _trajectory_cache_key(route)
        if key not in dynamics_cache:
            dynamics_cache[key] = _trajectory_cost_dynamics(trajectory)
        dynamics.append(dynamics_cache[key])
    status = CandidateStatus.REJECTED if reasons else CandidateStatus.FEASIBLE
    cost = CandidateCost(
        priority_inversion=priority_inversion,
        starvation=sum(1 for value in waits if value > case.hard_constraints.deadline_s / 2.0),
        mission_completion_time_s=completion,
        maximum_wait_s=max(waits, default=0.0),
        total_energy_percent=total_energy,
        airborne_hover_time_s=sum(route.airborne_wait_s for route in seed.routes),
        path_length_m=sum(route.path_length_m for route in seed.routes),
        acceleration_m_s2=max((item[0] for item in dynamics), default=0.0),
        jerk_m_s3=max((item[1] for item in dynamics), default=0.0),
        negative_separation_robustness_m=-(objective_separation - required),
        negative_boundary_robustness_m=-(boundary or 0.0),
        path_fidelity_m=sum(
            max(0.0, route.path_length_m - _authored_route_length(case, route.role_id))
            for route in seed.routes
        ),
        region_capture_error_m=max(
            (
                min(_distance(point, goal.center_m) for point in route.points_m)
                for route in seed.routes
                for goal in drone_by_role[route.role_id].goal_sequence
            ),
            default=0.0,
        ),
        integrated_squared_acceleration_m2_s3=sum(
            item[0] ** 2 * route.route_duration_s
            for item, route in zip(dynamics, seed.routes, strict=True)
        ),
        integrated_squared_jerk_m2_s5=sum(
            item[1] ** 2 * route.route_duration_s
            for item, route in zip(dynamics, seed.routes, strict=True)
        ),
        negative_energy_reserve_percent=-min(battery_end.values(), default=0.0),
        affected_role_count=sum(
            route.geometry_family is not GeometryFamily.DIRECT
            or route.route_start_s > 0.0
            or not math.isclose(route.speed_factor, 1.0)
            for route in seed.routes
        ),
        cutover_latency_s=max(waits, default=0.0),
    )
    payload: dict[str, Any] = {
        "candidate_id": f"candidate-{index + 1:04d}",
        "strategy": seed.strategy,
        "generator_id": seed.generator_id,
        "parameters": seed.parameters,
        "routes": seed.routes,
        "status": status,
        "rejection_reasons": tuple(sorted(set(reasons))),
        "predicted_minimum_separation_m": separation,
        "minimum_boundary_margin_m": boundary,
        "predicted_battery_end_percent": battery_end,
        "cost": cost,
    }
    return CandidateEvaluation(**payload, candidate_sha256=canonical_sha256(payload))


def _planning_result(
    case: CampaignCase,
    *,
    submission: ExecutionProfileSubmission,
    planning_submission: PlanningSubmission,
    evaluations: tuple[CandidateEvaluation, ...],
    generated_count: int,
    truncated: bool,
    duration_s: float,
    selected_index: int | None = None,
    blocking_reason: str | None = None,
    disposition: SearchDisposition,
    certificate: FeasibilityCertificate | None = None,
    bounded_search_complete: bool | None = None,
    optimality_claim: str | None = None,
) -> BoundedPlanningResult:
    status = PlanningStatus.READY if selected_index is not None else PlanningStatus.BLOCKED
    selected_sha = (
        evaluations[selected_index].candidate_sha256 if selected_index is not None else None
    )
    representatives = _representative_candidate_sha256s(evaluations, selected_index)
    if bounded_search_complete is None:
        bounded_search_complete = disposition is not SearchDisposition.BUDGET_EXHAUSTED
    if optimality_claim is None and disposition is SearchDisposition.SELECTED:
        optimality_claim = (
            "optimal independently certified candidate among the completely evaluated "
            "declared bounded candidate set"
        )
    elif (
        optimality_claim is None
        and disposition is SearchDisposition.PROVEN_INFEASIBLE_WITHIN_DECLARED_BOUNDS
    ):
        optimality_claim = (
            "infeasible only within the completely evaluated declared bounded candidate set"
        )
    elif optimality_claim is None:
        optimality_claim = "no feasibility or optimality claim"
    payload: dict[str, Any] = {
        "schema_version": 3,
        "planner_id": case.search.implementation_id,
        "planner_version": case.search.implementation_version,
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "planning_submission_id": planning_submission.planning_submission_id,
        "planning_submission_sha256": planning_submission.planning_submission_sha256,
        "status": status,
        "search_disposition": disposition,
        "retained_candidates": evaluations,
        "selected_candidate_index": selected_index,
        "selected_candidate_sha256": selected_sha,
        "generated_candidate_count": generated_count,
        "retained_candidate_count": len(evaluations),
        "truncated": truncated,
        "truncation_limit": case.search.maximum_candidate_count,
        "prediction_step_s": case.search.prediction_step_s,
        "blocking_reason": blocking_reason,
        "bounded_search_complete": bounded_search_complete,
        "representative_candidate_sha256s": representatives,
        "feasibility_certificate": certificate,
        "optimality_claim": optimality_claim,
    }
    if submission.submission_id != BASELINE_SUBMISSION_ID:
        payload.update(
            {
                "submission_id": submission.submission_id,
                "submission_sha256": submission.profile_sha256,
            }
        )
    digest = canonical_sha256(payload)
    return BoundedPlanningResult(
        **payload,
        diagnostic_search_duration_s=duration_s,
        plan_sha256=digest,
    )


def _representative_candidate_sha256s(
    evaluations: Sequence[CandidateEvaluation],
    selected_index: int | None,
) -> tuple[str, ...]:
    selected_sha = (
        evaluations[selected_index].candidate_sha256 if selected_index is not None else None
    )
    output: list[str] = [selected_sha] if selected_sha is not None else []
    seen_strategies: set[PlannerStrategy] = set()
    seen_reasons: set[str] = set()
    for candidate in evaluations:
        if candidate.status is CandidateStatus.FEASIBLE:
            if candidate.strategy in seen_strategies:
                continue
            seen_strategies.add(candidate.strategy)
        else:
            reason = candidate.rejection_reasons[0] if candidate.rejection_reasons else "REJECTED"
            if reason in seen_reasons:
                continue
            seen_reasons.add(reason)
        if candidate.candidate_sha256 not in output:
            output.append(candidate.candidate_sha256)
        if len(output) >= 16:
            break
    return tuple(output)


def _sample_route(route: CandidateRoute, step_s: float) -> tuple[Vector3, ...]:
    samples = []
    elapsed = 0.0
    while elapsed < route.route_duration_s:
        samples.append(_position_on_route(route, route.route_start_s + elapsed))
        elapsed += step_s
    samples.append(route.points_m[-1])
    return tuple(samples)


def _position_on_route(route: CandidateRoute, time_s: float) -> Vector3:
    if time_s <= route.route_start_s:
        return route.points_m[0]
    if time_s >= route.route_start_s + route.route_duration_s:
        return route.points_m[-1]
    lengths = [
        _distance(first, second)
        for first, second in zip(route.points_m, route.points_m[1:], strict=False)
    ]
    total = sum(lengths)
    target = (time_s - route.route_start_s) / route.route_duration_s * total
    consumed = 0.0
    for index, length in enumerate(lengths):
        if consumed + length >= target:
            factor = 0.0 if length == 0.0 else (target - consumed) / length
            return _lerp(route.points_m[index], route.points_m[index + 1], factor)
        consumed += length
    return route.points_m[-1]


def _minimum_joint_separation(routes: Sequence[CandidateRoute], step_s: float) -> float:
    if len(routes) < 2:
        return 1_000_000.0
    end = max(
        route.route_start_s
        + DEFAULT_TAKEOFF_DURATION_S
        + DEFAULT_STABILIZATION_S
        + route.route_duration_s
        + DEFAULT_LANDING_DURATION_S
        for route in routes
    )
    minimum = float("inf")
    timestamp = 0.0
    while timestamp <= end + step_s * 0.25:
        for first, second in combinations(routes, 2):
            minimum = min(
                minimum,
                _distance(
                    _position_on_route(first, timestamp), _position_on_route(second, timestamp)
                ),
            )
        timestamp += step_s
    return minimum if math.isfinite(minimum) else 1_000_000.0


def _candidate_trajectories(
    routes: Sequence[CandidateRoute],
    case: CampaignCase,
    cache: dict[TrajectoryCacheKey, TimeParameterizedTrajectory],
) -> tuple[TimeParameterizedTrajectory, ...]:
    from crazyswarm_app.campaign.trajectory import (
        allocate_trajectory_points,
        declared_stop_sequences,
    )

    output = []
    for route in routes:
        key = _trajectory_cache_key(route)
        trajectory = cache.get(key)
        if trajectory is None:
            points = allocate_trajectory_points(
                case,
                route.points_m,
                speed_factor=route.speed_factor,
                sample_step_s=case.search.prediction_step_s,
                declared_stops=route.declared_stops,
                segment_durations_s=route.segment_durations_s,
            )
            trajectory = TimeParameterizedTrajectory(
                trajectory_id=f"candidate-audit-{canonical_sha256(key)[:20]}",
                role_id=route.role_id,
                vehicle_id=route.role_id,
                route_sha256=canonical_sha256(key),
                points=points,
                declared_stop_sequences=declared_stop_sequences(route, points),
                completion_position_tolerance_m=0.05,
                completion_velocity_tolerance_m_s=0.05,
            )
            cache[key] = trajectory
        output.append(trajectory)
    return tuple(output)


def _sample_trajectory_positions(
    route: CandidateRoute,
    trajectory: TimeParameterizedTrajectory,
    step_s: float,
    cache: dict[TrajectoryCacheKey, tuple[Vector3, ...]],
) -> tuple[Vector3, ...]:
    key = _trajectory_cache_key(route)
    if key in cache:
        return cache[key]
    output = []
    elapsed = 0.0
    while elapsed < route.route_duration_s:
        output.append(sample_trajectory(trajectory, elapsed).position_m)
        elapsed += step_s
    output.append(trajectory.points[-1].position_m)
    samples = tuple(output)
    cache[key] = samples
    return samples


def _minimum_smooth_joint_separation(
    routes: Sequence[CandidateRoute],
    trajectories: Sequence[TimeParameterizedTrajectory],
    step_s: float,
    cache: dict[TrajectoryCacheKey, tuple[Vector3, ...]],
) -> float:
    if len(routes) < 2:
        return 1_000_000.0
    relative_samples = tuple(
        _sample_trajectory_positions(route, trajectory, step_s, cache)
        for route, trajectory in zip(routes, trajectories, strict=True)
    )
    end = max(
        route.route_start_s
        + DEFAULT_TAKEOFF_DURATION_S
        + DEFAULT_STABILIZATION_S
        + route.route_duration_s
        + DEFAULT_LANDING_DURATION_S
        for route in routes
    )
    minimum = float("inf")
    timestamp = 0.0
    while timestamp <= end + step_s * 0.25:
        positions: list[Vector3] = []
        for route, trajectory, samples in zip(routes, trajectories, relative_samples, strict=True):
            route_start_s = (
                route.route_start_s + DEFAULT_TAKEOFF_DURATION_S + DEFAULT_STABILIZATION_S
            )
            route_end_s = route_start_s + route.route_duration_s
            # Every vehicle remains a physical obstacle while waiting on the
            # ground and after landing.  Use the route endpoint XY at the
            # conservative flight altitude so a serialized solution cannot
            # "resolve" a conflict by landing on a peer's occupied pad.
            if timestamp <= route_start_s:
                position = trajectory.points[0].position_m
            elif timestamp <= route_end_s and _is_step_aligned(route_start_s, step_s):
                sample_index = round((timestamp - route_start_s) / step_s)
                position = samples[max(0, min(sample_index, len(samples) - 1))]
            elif timestamp <= route_end_s:
                position = sample_trajectory(trajectory, timestamp - route_start_s).position_m
            else:
                position = trajectory.points[-1].position_m
            positions.append(position)
        for first, second in combinations(positions, 2):
            minimum = min(minimum, _distance(first, second))
        timestamp += step_s
    return minimum if math.isfinite(minimum) else 1_000_000.0


def _trajectory_cache_key(route: CandidateRoute) -> TrajectoryCacheKey:
    return (
        route.points_m,
        route.speed_factor,
        tuple((stop.position_m, stop.mode, stop.dwell_s) for stop in route.declared_stops),
        route.segment_durations_s,
    )


def _simultaneous_route_overlap_s(routes: Sequence[CandidateRoute]) -> float:
    if len(routes) < 2:
        return routes[0].route_duration_s if routes else 0.0
    overlap_start_s = max(route.route_start_s for route in routes)
    overlap_end_s = min(route.route_start_s + route.route_duration_s for route in routes)
    return max(0.0, overlap_end_s - overlap_start_s)


def _maximum_formation_error(
    routes: Sequence[CandidateRoute],
    trajectories: Sequence[TimeParameterizedTrajectory],
    offsets: dict[str, Vector3],
    offsets_by_node: dict[str, tuple[Vector3, ...]],
    step_s: float,
) -> float:
    overlap_start_s = max(route.route_start_s for route in routes)
    overlap_end_s = min(route.route_start_s + route.route_duration_s for route in routes)
    if overlap_end_s <= overlap_start_s:
        return float("inf")
    maximum = 0.0
    timestamp_s = overlap_start_s
    while timestamp_s <= overlap_end_s + step_s * 0.25:
        progress = min(
            1.0,
            max(0.0, (timestamp_s - overlap_start_s) / (overlap_end_s - overlap_start_s)),
        )
        normalized = []
        for route, trajectory in zip(routes, trajectories, strict=True):
            offset = (
                offsets[route.role_id]
                if offsets
                else _formation_offset_at_progress(offsets_by_node[route.role_id], progress)
            )
            position = sample_trajectory(
                trajectory,
                progress * trajectory.duration_s,
            ).position_m
            normalized.append(
                Vector3(
                    x=position.x - offset.x,
                    y=position.y - offset.y,
                    z=position.z - offset.z,
                )
            )
        maximum = max(
            maximum,
            max(
                (_distance(first, second) for first, second in combinations(normalized, 2)),
                default=0.0,
            ),
        )
        timestamp_s += step_s
    return maximum


def _formation_offset_at_progress(offsets: tuple[Vector3, ...], progress: float) -> Vector3:
    if len(offsets) == 1:
        return offsets[0]
    scaled = progress * (len(offsets) - 1)
    index = min(len(offsets) - 2, int(scaled))
    return _lerp(offsets[index], offsets[index + 1], scaled - index)


def _trajectory_cost_dynamics(
    trajectory: TimeParameterizedTrajectory,
) -> tuple[float, float]:
    acceleration_samples: list[tuple[float, Vector3]] = []
    for start, end in zip(trajectory.points, trajectory.points[1:], strict=False):
        duration_s = end.time_from_start_s - start.time_from_start_s
        for subdivision in range(11):
            timestamp_s = start.time_from_start_s + duration_s * subdivision / 10.0
            acceleration_samples.append(
                (
                    timestamp_s,
                    sample_trajectory_segment(start, end, timestamp_s).acceleration_m_s2,
                )
            )
    maximum_acceleration = max(
        (_vector_norm(item[1]) for item in acceleration_samples), default=0.0
    )
    maximum_jerk = max(
        (
            _distance(after[1], before[1]) / (after[0] - before[0])
            for before, after in pairwise(acceleration_samples)
            if after[0] > before[0]
        ),
        default=0.0,
    )
    return maximum_acceleration, maximum_jerk


def _is_step_aligned(value: float, step_s: float) -> bool:
    return math.isclose(value / step_s, round(value / step_s), abs_tol=1e-9)


def _priority_inversions(routes: Sequence[CandidateRoute], drones: dict[str, Any]) -> int:
    ordered = sorted(routes, key=lambda route: (route.route_start_s, route.role_id))
    return sum(
        max(0, drones[later.role_id].priority - drones[earlier.role_id].priority)
        for earlier_index, earlier in enumerate(ordered)
        for later in ordered[earlier_index + 1 :]
    )


def _priority_precedence_threshold(case: CampaignCase) -> float | None:
    if case.semantics is None:
        return None
    return next(
        (
            float(oracle.threshold or 0.0)
            for oracle in case.semantics.behavior_oracles
            if oracle.required and oracle.kind is BehaviorOracleKind.PRIORITY_PRECEDENCE
        ),
        None,
    )


def _boundary_margin(point: Vector3, case: CampaignCase) -> float:
    volume = case.hard_constraints.flight_volume
    return min(
        point.x - volume.minimum_m.x,
        volume.maximum_m.x - point.x,
        point.y - volume.minimum_m.y,
        volume.maximum_m.y - point.y,
        point.z - volume.minimum_m.z,
        volume.maximum_m.z - point.z,
    )


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )


def _authored_route_length(case: CampaignCase, role_id: str) -> float:
    drone = next(item for item in case.drones if item.role_id == role_id)
    first_goal = drone.goal_sequence[0].center_m
    last_goal = drone.goal_sequence[-1].center_m
    points = (
        drone.start_region.center_m.model_copy(update={"z": first_goal.z}),
        *(goal.center_m for goal in drone.goal_sequence),
        drone.landing_region.center_m.model_copy(update={"z": last_goal.z}),
    )
    return sum(_distance(before, after) for before, after in pairwise(points))


def _vector_norm(value: Vector3) -> float:
    return math.sqrt(value.x**2 + value.y**2 + value.z**2)


def _lerp(first: Vector3, second: Vector3, factor: float) -> Vector3:
    return Vector3(
        x=first.x + (second.x - first.x) * factor,
        y=first.y + (second.y - first.y) * factor,
        z=first.z + (second.z - first.z) * factor,
    )


def _deduplicate_points(points: tuple[Vector3, ...]) -> tuple[Vector3, ...]:
    result: list[Vector3] = []
    for point in points:
        if not result or _distance(result[-1], point) > 1e-9:
            result.append(point)
    return tuple(result)
