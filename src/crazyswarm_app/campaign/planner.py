from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from itertools import combinations, pairwise, permutations
from typing import Any, Literal

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import CampaignCase, ObjectiveMetric, PlannerStrategy
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import (
    TimeParameterizedTrajectory,
    sample_trajectory,
    sample_trajectory_segment,
)

DEFAULT_TAKEOFF_DURATION_S = 2.0
DEFAULT_STABILIZATION_S = 0.5
DEFAULT_LANDING_DURATION_S = 2.0
DEFAULT_RESERVATION_CLEARANCE_S = 0.8


class CandidateStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    REJECTED = "REJECTED"


class PlanningStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class GeometryFamily(StrEnum):
    DIRECT = "DIRECT"
    LATERAL_SPLINE = "LATERAL_SPLINE"
    QUADRATIC_BEZIER = "QUADRATIC_BEZIER"
    ARC_CONFLICT_TUBE = "ARC_CONFLICT_TUBE"
    CORRIDOR_FOLLOWING = "CORRIDOR_FOLLOWING"
    VERTICAL_LAYER = "VERTICAL_LAYER"


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
    schema_version: Literal[1] = 1
    planner_id: Identifier
    planner_version: str
    case_id: Identifier
    case_sha256: SHA256
    status: PlanningStatus
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
    optimality_claim: Literal["optimal among the bounded generated candidates"] = (
        "optimal among the bounded generated candidates"
    )
    plan_sha256: SHA256

    @model_validator(mode="after")
    def authority_is_complete(self) -> BoundedPlanningResult:
        if self.status is PlanningStatus.READY:
            if self.selected_candidate_index is None or self.selected_candidate_sha256 is None:
                raise ValueError("ready planning result requires one selected candidate")
        elif (
            self.selected_candidate_index is not None or self.selected_candidate_sha256 is not None
        ):
            raise ValueError("blocked planning result contains execution authority")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(
            mode="python",
            exclude={"plan_sha256", "diagnostic_search_duration_s"},
        )

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
TrajectoryCacheKey = tuple[tuple[Vector3, ...], float]


class BoundedJointPlanner:
    def __init__(self) -> None:
        self._geometry_generators: tuple[tuple[str, GeometryGenerator], ...] = (
            ("lateral-spline-v1", _lateral_spline_candidates),
            ("quadratic-bezier-v1", _bezier_candidates),
            ("arc-conflict-tube-v1", _arc_candidates),
            ("corridor-following-v1", _corridor_candidates),
            ("vertical-layer-v1", _vertical_candidates),
        )

    def plan(self, case: CampaignCase) -> BoundedPlanningResult:
        started = time.perf_counter()
        base_routes = _direct_routes(case)
        seeds = list(self._generate(case, base_routes))
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
            evaluations.append(
                _evaluate_candidate(
                    index,
                    seed,
                    case,
                    trajectory_cache=trajectory_cache,
                    position_cache=position_cache,
                    dynamics_cache=dynamics_cache,
                )
            )
        duration = time.perf_counter() - started
        if budget_expired or len(evaluations) != len(retained_seeds):
            return _planning_result(
                case,
                evaluations=tuple(evaluations),
                generated_count=generated_count,
                truncated=truncated,
                duration_s=duration,
                blocking_reason=(
                    "planning budget expired before all retained candidates were validated"
                ),
            )
        feasible = [
            index
            for index, item in enumerate(evaluations)
            if item.status is CandidateStatus.FEASIBLE
        ]
        if not feasible:
            return _planning_result(
                case,
                evaluations=tuple(evaluations),
                generated_count=generated_count,
                truncated=truncated,
                duration_s=duration,
                blocking_reason="no bounded generated candidate satisfies every hard constraint",
            )
        selected_index = min(
            feasible,
            key=lambda index: (
                evaluations[index].cost.vector_for(case.objective_order),
                evaluations[index].candidate_id,
            ),
        )
        return _planning_result(
            case,
            evaluations=tuple(evaluations),
            generated_count=generated_count,
            truncated=truncated,
            duration_s=duration,
            selected_index=selected_index,
        )

    def _generate(
        self, case: CampaignCase, base_routes: tuple[CandidateRoute, ...]
    ) -> Iterable[_CandidateSeed]:
        if PlannerStrategy.DIRECT in case.allowed_strategies:
            yield _CandidateSeed(PlannerStrategy.DIRECT, "direct-v1", {}, base_routes)
        if PlannerStrategy.GROUND_DELAY in case.allowed_strategies:
            for role in sorted(route.role_id for route in base_routes):
                for delay_s in case.search.delay_grid_s:
                    yield _retime_seed(base_routes, role, delay_s, ground=True)
            if len(base_routes) > 1:
                for order in permutations(sorted(route.role_id for route in base_routes)):
                    yield _joint_retime_seed(base_routes, order, ground=True)
        if PlannerStrategy.AIRBORNE_STAGING in case.allowed_strategies:
            for role in sorted(route.role_id for route in base_routes):
                for delay_s in case.search.delay_grid_s:
                    yield _retime_seed(base_routes, role, delay_s, ground=False)
            if len(base_routes) > 1:
                for order in permutations(sorted(route.role_id for route in base_routes)):
                    yield _joint_retime_seed(base_routes, order, ground=False)
        if PlannerStrategy.SPEED_RETIMING in case.allowed_strategies:
            for role in sorted(route.role_id for route in base_routes):
                for factor in case.search.speed_factors:
                    yield _speed_seed(case, base_routes, role, factor)
        if PlannerStrategy.HORIZONTAL_DETOUR in case.allowed_strategies:
            for _, generator in self._geometry_generators[:-1]:
                yield from generator(case, base_routes)
        if PlannerStrategy.VERTICAL_LAYER in case.allowed_strategies:
            yield from self._geometry_generators[-1][1](case, base_routes)
        if PlannerStrategy.COMBINED_TIMING_GEOMETRY in case.allowed_strategies:
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
        allocated = allocate_trajectory_points(case, points, speed_factor=1.0)
        routes.append(
            CandidateRoute(
                role_id=drone.role_id,
                points_m=points,
                route_start_s=0.0,
                route_duration_s=allocated[-1].time_from_start_s,
            )
        )
    return tuple(routes)


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
                DEFAULT_TAKEOFF_DURATION_S
                + DEFAULT_STABILIZATION_S
                + DEFAULT_LANDING_DURATION_S
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
) -> _CandidateSeed:
    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points

    selected = tuple(
        route.model_copy(
            update={
                "route_duration_s": allocate_trajectory_points(
                    case, route.points_m, speed_factor=factor
                )[-1].time_from_start_s,
                "speed_factor": factor,
            }
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
        "quadratic-bezier-v1": GeometryFamily.QUADRATIC_BEZIER,
        "arc-conflict-tube-v1": GeometryFamily.ARC_CONFLICT_TUBE,
        "corridor-following-v1": GeometryFamily.CORRIDOR_FOLLOWING,
        "vertical-layer-v1": GeometryFamily.VERTICAL_LAYER,
    }[generator_id]
    replacement = route.model_copy(
        update={
            "points_m": points,
            "route_duration_s": allocate_trajectory_points(
                case, points, speed_factor=route.speed_factor
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
            route.airborne_wait_s
            > case.hard_constraints.maximum_unrequired_airborne_wait_s
            for route in seed.routes
        )
    ):
        reasons.append("UNREQUIRED_AIRBORNE_WAIT_EXCEEDED")
    if case.hard_constraints.synchronized_launch_required and len(
        {round(route.ground_wait_s, 9) for route in seed.routes}
    ) > 1:
        reasons.append("SYNCHRONIZED_LAUNCH_VIOLATION")
    separation = _minimum_smooth_joint_separation(
        seed.routes,
        trajectories,
        case.search.prediction_step_s,
        position_cache,
    )
    required = (
        case.hard_constraints.warning_separation_m + case.hard_constraints.position_uncertainty_m
    )
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
        route.route_start_s + route.route_duration_s + execution_overhead_s
        for route in seed.routes
    )
    if completion > case.hard_constraints.deadline_s:
        reasons.append("DEADLINE_VIOLATION")
    waits = [route.route_start_s for route in seed.routes]
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
        negative_separation_robustness_m=-(separation - required),
        negative_boundary_robustness_m=-(boundary or 0.0),
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
    evaluations: tuple[CandidateEvaluation, ...],
    generated_count: int,
    truncated: bool,
    duration_s: float,
    selected_index: int | None = None,
    blocking_reason: str | None = None,
) -> BoundedPlanningResult:
    status = PlanningStatus.READY if selected_index is not None else PlanningStatus.BLOCKED
    selected_sha = (
        evaluations[selected_index].candidate_sha256 if selected_index is not None else None
    )
    payload: dict[str, Any] = {
        "planner_id": case.search.implementation_id,
        "planner_version": case.search.implementation_version,
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "status": status,
        "retained_candidates": evaluations,
        "selected_candidate_index": selected_index,
        "selected_candidate_sha256": selected_sha,
        "generated_candidate_count": generated_count,
        "retained_candidate_count": len(evaluations),
        "truncated": truncated,
        "truncation_limit": case.search.maximum_candidate_count,
        "prediction_step_s": case.search.prediction_step_s,
        "blocking_reason": blocking_reason,
    }
    digest = canonical_sha256(payload)
    return BoundedPlanningResult(
        **payload,
        diagnostic_search_duration_s=duration_s,
        plan_sha256=digest,
    )


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
    from crazyswarm_app.campaign.trajectory import allocate_trajectory_points

    output = []
    for route in routes:
        key = _trajectory_cache_key(route)
        trajectory = cache.get(key)
        if trajectory is None:
            trajectory = TimeParameterizedTrajectory(
                trajectory_id=f"candidate-audit-{canonical_sha256(key)[:20]}",
                role_id=route.role_id,
                vehicle_id=route.role_id,
                route_sha256=canonical_sha256(key),
                points=allocate_trajectory_points(
                    case,
                    route.points_m,
                    speed_factor=route.speed_factor,
                    sample_step_s=case.search.prediction_step_s,
                ),
                declared_stop_sequences=(1, len(route.points_m)),
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
        for route, trajectory, samples in zip(
            routes, trajectories, relative_samples, strict=True
        ):
            takeoff_start_s = route.ground_wait_s
            route_start_s = (
                route.route_start_s + DEFAULT_TAKEOFF_DURATION_S + DEFAULT_STABILIZATION_S
            )
            route_end_s = route_start_s + route.route_duration_s
            landing_end_s = route_end_s + DEFAULT_LANDING_DURATION_S
            if timestamp < takeoff_start_s or timestamp > landing_end_s:
                continue
            if timestamp <= route_start_s:
                position = trajectory.points[0].position_m
            elif timestamp <= route_end_s and _is_step_aligned(route_start_s, step_s):
                sample_index = round((timestamp - route_start_s) / step_s)
                position = samples[max(0, min(sample_index, len(samples) - 1))]
            elif timestamp <= route_end_s:
                position = sample_trajectory(
                    trajectory, timestamp - route_start_s
                ).position_m
            else:
                position = trajectory.points[-1].position_m
            positions.append(position)
        for first, second in combinations(positions, 2):
            minimum = min(minimum, _distance(first, second))
        timestamp += step_s
    return minimum if math.isfinite(minimum) else 1_000_000.0


def _trajectory_cache_key(route: CandidateRoute) -> TrajectoryCacheKey:
    return route.points_m, route.speed_factor


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
    if len(result) < 2:
        raise ValueError("campaign route requires at least two distinct points")
    return tuple(result)
