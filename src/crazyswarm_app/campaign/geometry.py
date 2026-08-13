from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum
from itertools import combinations, pairwise
from typing import Protocol

from pydantic import Field

from crazyswarm_app.campaign.models import CampaignCase, Region3D
from crazyswarm_app.campaign.submissions import (
    ClearancePolicy,
    PathAdherenceMode,
    PlanningSubmission,
)
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class GeometryLayer(StrEnum):
    NOMINAL_PHYSICAL = "NOMINAL_PHYSICAL"
    PROTECTED_OCCUPANCY = "PROTECTED_OCCUPANCY"
    POLICY = "POLICY"


class ClearanceDisposition(StrEnum):
    CLEAR = "CLEAR"
    PROTECTED_CLEARANCE_BREACH = "PROTECTED_CLEARANCE_BREACH"
    PHYSICAL_CONTACT_AUTHORIZED = "PHYSICAL_CONTACT_AUTHORIZED"
    PHYSICAL_CONTACT_PROHIBITED = "PHYSICAL_CONTACT_PROHIBITED"


class RouteGeometry(Protocol):
    role_id: str
    points_m: tuple[Vector3, ...]
    route_start_s: float
    route_duration_s: float
    segment_durations_s: tuple[float, ...]


class VehicleGeometryModel(ContractModel):
    model_id: Identifier = "crazyflie-default-v1"
    nominal_radius_m: float = Field(default=0.055, gt=0.0)
    nominal_half_height_m: float = Field(default=0.025, gt=0.0)
    pose_model: str = "YAW_INVARIANT_LEVEL_FLIGHT"
    qualification_scope: str = "SOFTWARE_SIMULATION_ONLY"


class SolidGeometry(ContractModel):
    solid_id: Identifier
    bounds: Region3D


class TraversableGeometry(ContractModel):
    passage_id: Identifier
    bounds: Region3D


class StructuredWorld(ContractModel):
    schema_version: int = 1
    flight_volume: Region3D
    solids: tuple[SolidGeometry, ...] = ()
    traversable_passages: tuple[TraversableGeometry, ...] = ()
    world_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"world_sha256"})


class PassageCapacity(ContractModel):
    passage_id: Identifier
    horizontal_free_width_m: float
    vertical_free_height_m: float
    passable: bool


class WorldGeometryReport(ContractModel):
    valid: bool
    contradictions: tuple[str, ...]
    passage_capacities: tuple[PassageCapacity, ...]


class ContactAssessment(ContractModel):
    role_id: Identifier
    target_id: Identifier
    signed_nominal_clearance_m: float
    disposition: ClearanceDisposition


class FeasibilityCertificate(ContractModel):
    schema_version: int = 1
    verifier_id: Identifier = "independent-continuous-clearance-v1"
    case_id: Identifier
    case_sha256: SHA256
    planning_submission_id: Identifier
    planning_submission_sha256: SHA256
    candidate_sha256: SHA256
    passed: bool
    minimum_pairwise_nominal_clearance_m: float
    minimum_pairwise_protected_clearance_m: float
    minimum_solid_nominal_clearance_m: float
    minimum_solid_protected_clearance_m: float
    minimum_boundary_clearance_m: float
    maximum_path_deviation_m: float | None = None
    contact_assessments: tuple[ContactAssessment, ...] = ()
    violations: tuple[str, ...]
    certificate_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"certificate_sha256"})


def structured_world_from_case(case: CampaignCase) -> StructuredWorld:
    environment = case.semantics.environment_constraints if case.semantics else None
    payload: dict[str, object] = {
        "schema_version": 1,
        "flight_volume": case.hard_constraints.flight_volume,
        "solids": tuple(
            SolidGeometry(solid_id=region.region_id, bounds=region)
            for region in (environment.keep_out_regions if environment else ())
        ),
        "traversable_passages": tuple(
            TraversableGeometry(passage_id=region.region_id, bounds=region)
            for region in (environment.required_corridors if environment else ())
        ),
    }
    return StructuredWorld(**payload, world_sha256=canonical_sha256(payload))


def validate_structured_world(
    world: StructuredWorld,
    policy: ClearancePolicy,
) -> WorldGeometryReport:
    contradictions: list[str] = []
    capacities: list[PassageCapacity] = []
    volume = world.flight_volume
    for solid in world.solids:
        if not _region_inside(solid.bounds, volume):
            contradictions.append(f"SOLID_OUTSIDE_FLIGHT_VOLUME:{solid.solid_id}")
    for passage in world.traversable_passages:
        if not _region_inside(passage.bounds, volume):
            contradictions.append(f"PASSAGE_OUTSIDE_FLIGHT_VOLUME:{passage.passage_id}")
        for solid in world.solids:
            if _regions_overlap(passage.bounds, solid.bounds):
                contradictions.append(
                    f"SOLID_FREE_SPACE_CONTRADICTION:{solid.solid_id}:{passage.passage_id}"
                )
        bounds = passage.bounds
        horizontal_width = min(
            bounds.maximum_m.x - bounds.minimum_m.x,
            bounds.maximum_m.y - bounds.minimum_m.y,
        ) - 2.0 * (
            policy.nominal_vehicle_radius_m
            + policy.required_solid_clearance_m
            + policy.uncertainty_allowance_m
        )
        vertical_height = (
            bounds.maximum_m.z
            - bounds.minimum_m.z
            - 2.0
            * (
                policy.nominal_vehicle_half_height_m
                + policy.required_solid_clearance_m
                + policy.uncertainty_allowance_m
            )
        )
        passable = horizontal_width >= 0.0 and vertical_height >= 0.0
        capacities.append(
            PassageCapacity(
                passage_id=passage.passage_id,
                horizontal_free_width_m=horizontal_width,
                vertical_free_height_m=vertical_height,
                passable=passable,
            )
        )
        if not passable:
            contradictions.append(f"PASSAGE_TOO_SMALL:{passage.passage_id}")
    return WorldGeometryReport(
        valid=not contradictions,
        contradictions=tuple(sorted(set(contradictions))),
        passage_capacities=tuple(capacities),
    )


def assess_contact(
    *,
    role_id: str,
    target_id: str,
    signed_nominal_clearance_m: float,
    policy: ClearancePolicy,
) -> ContactAssessment:
    protected_requirement = policy.required_solid_clearance_m + policy.uncertainty_allowance_m
    if signed_nominal_clearance_m >= protected_requirement:
        disposition = ClearanceDisposition.CLEAR
    elif signed_nominal_clearance_m > 0.0:
        disposition = ClearanceDisposition.PROTECTED_CLEARANCE_BREACH
    elif role_id in policy.contact_allowed_role_ids and target_id in policy.contact_target_ids:
        disposition = ClearanceDisposition.PHYSICAL_CONTACT_AUTHORIZED
    else:
        disposition = ClearanceDisposition.PHYSICAL_CONTACT_PROHIBITED
    return ContactAssessment(
        role_id=role_id,
        target_id=target_id,
        signed_nominal_clearance_m=signed_nominal_clearance_m,
        disposition=disposition,
    )


def certify_candidate_routes(
    case: CampaignCase,
    planning_submission: PlanningSubmission,
    candidate_sha256: str,
    routes: Sequence[RouteGeometry],
) -> FeasibilityCertificate:
    """Verify route geometry independently of the planner's sampled evaluator."""

    policy = planning_submission.clearance
    world = structured_world_from_case(case)
    world_report = validate_structured_world(world, policy)
    violations = list(world_report.contradictions)

    nominal_pairwise = 1_000_000.0
    protected_pairwise = 1_000_000.0
    for first, second in combinations(routes, 2):
        center_distance = _continuous_route_distance(first, second)
        nominal_pairwise = min(
            nominal_pairwise,
            center_distance - 2.0 * policy.nominal_vehicle_radius_m,
        )
        protected_pairwise = min(
            protected_pairwise,
            center_distance - policy.required_pairwise_center_separation_m,
        )
    if protected_pairwise < -1e-9:
        violations.append("PAIRWISE_PROTECTED_CLEARANCE_VIOLATION")

    solid_nominal = 1_000_000.0
    solid_protected = 1_000_000.0
    for route in routes:
        for solid in world.solids:
            distance = min(
                _segment_aabb_distance(first, second, solid.bounds)
                for first, second in pairwise(route.points_m)
            )
            nominal = distance - policy.nominal_vehicle_radius_m
            protected = nominal - (
                policy.required_solid_clearance_m + policy.uncertainty_allowance_m
            )
            solid_nominal = min(solid_nominal, nominal)
            solid_protected = min(solid_protected, protected)
            if protected < -1e-9:
                violations.append(f"SOLID_PROTECTED_CLEARANCE_VIOLATION:{solid.solid_id}")

    boundary_clearance = min(
        _boundary_clearance(point, world.flight_volume, policy)
        for route in routes
        for point in route.points_m
    )
    if boundary_clearance < -1e-9:
        violations.append("PHYSICAL_FLIGHT_VOLUME_VIOLATION")

    maximum_path_deviation = _path_adherence_deviation(case, planning_submission, routes)
    violations.extend(_path_adherence_violations(case, planning_submission, routes))

    starts = [route.route_start_s for route in routes]
    coordination = planning_submission.coordination
    if (
        coordination.synchronized_route_start_required
        and starts
        and max(starts) - min(starts)
        > coordination.maximum_route_start_skew_s + 1e-9
    ):
        violations.append("PLANNING_SYNCHRONIZED_ROUTE_START_VIOLATION")
    overlap = _route_overlap(routes)
    if overlap + 1e-9 < coordination.minimum_simultaneous_flight_s:
        violations.append("PLANNING_MINIMUM_SIMULTANEOUS_FLIGHT_VIOLATION")

    unique_violations = tuple(sorted(set(violations)))
    payload: dict[str, object] = {
        "schema_version": 1,
        "verifier_id": "independent-continuous-clearance-v1",
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "planning_submission_id": planning_submission.planning_submission_id,
        "planning_submission_sha256": planning_submission.planning_submission_sha256,
        "candidate_sha256": candidate_sha256,
        "passed": not unique_violations,
        "minimum_pairwise_nominal_clearance_m": nominal_pairwise,
        "minimum_pairwise_protected_clearance_m": protected_pairwise,
        "minimum_solid_nominal_clearance_m": solid_nominal,
        "minimum_solid_protected_clearance_m": solid_protected,
        "minimum_boundary_clearance_m": boundary_clearance,
        "maximum_path_deviation_m": maximum_path_deviation,
        "contact_assessments": (),
        "violations": unique_violations,
    }
    return FeasibilityCertificate(
        **payload,
        certificate_sha256=canonical_sha256(payload),
    )


def minimum_continuous_route_center_distance(
    routes: Sequence[RouteGeometry],
) -> float:
    return min(
        (_continuous_route_distance(first, second) for first, second in combinations(routes, 2)),
        default=1_000_000.0,
    )


def _route_knot_times(route: RouteGeometry) -> tuple[float, ...]:
    if route.segment_durations_s:
        durations = route.segment_durations_s
    else:
        lengths = tuple(_distance(first, second) for first, second in pairwise(route.points_m))
        total = sum(lengths)
        if total <= 1e-12:
            durations = tuple(route.route_duration_s / len(lengths) for _ in lengths)
        else:
            durations = tuple(route.route_duration_s * length / total for length in lengths)
    output = [route.route_start_s]
    for duration in durations:
        output.append(output[-1] + duration)
    return tuple(output)


def _position_at(route: RouteGeometry, timestamp_s: float) -> Vector3:
    times = _route_knot_times(route)
    if timestamp_s <= times[0]:
        return route.points_m[0]
    if timestamp_s >= times[-1]:
        return route.points_m[-1]
    for index, (start, end) in enumerate(pairwise(times)):
        if timestamp_s <= end:
            fraction = (timestamp_s - start) / (end - start)
            return _lerp(route.points_m[index], route.points_m[index + 1], fraction)
    return route.points_m[-1]


def _continuous_route_distance(first: RouteGeometry, second: RouteGeometry) -> float:
    breakpoints = sorted(
        set(
            (
                0.0,
                *_route_knot_times(first),
                *_route_knot_times(second),
                max(_route_knot_times(first)[-1], _route_knot_times(second)[-1]),
            )
        )
    )
    minimum = float("inf")
    for start, end in pairwise(breakpoints):
        first_start = _position_at(first, start)
        second_start = _position_at(second, start)
        first_end = _position_at(first, end)
        second_end = _position_at(second, end)
        relative_start = _subtract(first_start, second_start)
        relative_delta = _subtract(
            _subtract(first_end, second_end),
            relative_start,
        )
        denominator = _dot(relative_delta, relative_delta)
        fraction = (
            0.0
            if denominator <= 1e-18
            else max(0.0, min(1.0, -_dot(relative_start, relative_delta) / denominator))
        )
        minimum = min(minimum, _norm(_add(relative_start, _scale(relative_delta, fraction))))
    return minimum


def _segment_aabb_distance(start: Vector3, end: Vector3, bounds: Region3D) -> float:
    if _segment_intersects_aabb(start, end, bounds):
        return 0.0
    low, high = 0.0, 1.0
    for _ in range(64):
        first = low + (high - low) / 3.0
        second = high - (high - low) / 3.0
        if _point_aabb_distance(_lerp(start, end, first), bounds) <= _point_aabb_distance(
            _lerp(start, end, second), bounds
        ):
            high = second
        else:
            low = first
    return _point_aabb_distance(_lerp(start, end, (low + high) / 2.0), bounds)


def _segment_intersects_aabb(start: Vector3, end: Vector3, bounds: Region3D) -> bool:
    entry, exit_ = 0.0, 1.0
    for before, after, minimum, maximum in (
        (start.x, end.x, bounds.minimum_m.x, bounds.maximum_m.x),
        (start.y, end.y, bounds.minimum_m.y, bounds.maximum_m.y),
        (start.z, end.z, bounds.minimum_m.z, bounds.maximum_m.z),
    ):
        delta = after - before
        if abs(delta) <= 1e-15:
            if before < minimum or before > maximum:
                return False
            continue
        near, far = (minimum - before) / delta, (maximum - before) / delta
        if near > far:
            near, far = far, near
        entry, exit_ = max(entry, near), min(exit_, far)
        if entry > exit_:
            return False
    return True


def _point_aabb_distance(point: Vector3, bounds: Region3D) -> float:
    dx = max(bounds.minimum_m.x - point.x, 0.0, point.x - bounds.maximum_m.x)
    dy = max(bounds.minimum_m.y - point.y, 0.0, point.y - bounds.maximum_m.y)
    dz = max(bounds.minimum_m.z - point.z, 0.0, point.z - bounds.maximum_m.z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _boundary_clearance(
    point: Vector3,
    volume: Region3D,
    policy: ClearancePolicy,
) -> float:
    return min(
        point.x - volume.minimum_m.x - policy.nominal_vehicle_radius_m,
        volume.maximum_m.x - point.x - policy.nominal_vehicle_radius_m,
        point.y - volume.minimum_m.y - policy.nominal_vehicle_radius_m,
        volume.maximum_m.y - point.y - policy.nominal_vehicle_radius_m,
        point.z - volume.minimum_m.z - policy.nominal_vehicle_half_height_m,
        volume.maximum_m.z - point.z - policy.nominal_vehicle_half_height_m,
    )


def _path_adherence_violations(
    case: CampaignCase,
    planning: PlanningSubmission,
    routes: Sequence[RouteGeometry],
) -> tuple[str, ...]:
    violations: list[str] = []
    drone_by_role = {drone.role_id: drone for drone in case.drones}
    mode = planning.path_adherence.mode
    for route in routes:
        drone = drone_by_role[route.role_id]
        if any(
            not any(goal.contains(point) for point in route.points_m)
            for goal in drone.goal_sequence
        ):
            violations.append(f"REQUIRED_GOAL_VIOLATION:{route.role_id}")
        if mode is PathAdherenceMode.ROUTE_CORRIDOR:
            corridors = (
                case.semantics.environment_constraints.required_corridors if case.semantics else ()
            )
            for start, end in pairwise(route.points_m):
                if not any(
                    corridor.contains(start) and corridor.contains(end) for corridor in corridors
                ):
                    violations.append(f"ROUTE_CORRIDOR_VIOLATION:{route.role_id}")
                    break
        if mode in {
            PathAdherenceMode.EXACT_ROUTE,
            PathAdherenceMode.HARD_TUBE,
            PathAdherenceMode.AUTHORED_CENTERLINE,
        }:
            limit = planning.path_adherence.maximum_centerline_deviation_m
            assert limit is not None
            if _route_centerline_deviation(case, route) > limit + 1e-9:
                violations.append(f"CENTERLINE_DEVIATION_VIOLATION:{route.role_id}")
    return tuple(violations)


def _path_adherence_deviation(
    case: CampaignCase,
    planning: PlanningSubmission,
    routes: Sequence[RouteGeometry],
) -> float | None:
    if planning.path_adherence.mode in {
        PathAdherenceMode.GOAL_SEQUENCE_ONLY,
        PathAdherenceMode.REQUIRED_REGIONS,
        PathAdherenceMode.SOFT_REFERENCE,
    }:
        return None
    if planning.path_adherence.mode is PathAdherenceMode.ROUTE_CORRIDOR:
        return 0.0 if not _path_adherence_violations(case, planning, routes) else float("inf")
    return max((_route_centerline_deviation(case, route) for route in routes), default=0.0)


def _route_centerline_deviation(case: CampaignCase, route: RouteGeometry) -> float:
    drone = next(item for item in case.drones if item.role_id == route.role_id)
    authored = (
        Vector3(
            x=drone.start_region.center_m.x,
            y=drone.start_region.center_m.y,
            z=drone.goal_sequence[0].center_m.z,
        ),
        *(goal.center_m for goal in drone.goal_sequence),
        Vector3(
            x=drone.landing_region.center_m.x,
            y=drone.landing_region.center_m.y,
            z=drone.goal_sequence[-1].center_m.z,
        ),
    )
    return max(
        min(_point_segment_distance(point, start, end) for start, end in pairwise(authored))
        for point in route.points_m
    )


def _point_segment_distance(point: Vector3, start: Vector3, end: Vector3) -> float:
    delta = _subtract(end, start)
    denominator = _dot(delta, delta)
    fraction = (
        0.0
        if denominator <= 1e-18
        else max(0.0, min(1.0, _dot(_subtract(point, start), delta) / denominator))
    )
    return _distance(point, _add(start, _scale(delta, fraction)))


def _route_overlap(routes: Sequence[RouteGeometry]) -> float:
    if not routes:
        return 0.0
    return max(
        0.0,
        min(route.route_start_s + route.route_duration_s for route in routes)
        - max(route.route_start_s for route in routes),
    )


def _region_inside(inner: Region3D, outer: Region3D) -> bool:
    return outer.contains(inner.minimum_m) and outer.contains(inner.maximum_m)


def _regions_overlap(first: Region3D, second: Region3D) -> bool:
    return not (
        first.maximum_m.x <= second.minimum_m.x
        or second.maximum_m.x <= first.minimum_m.x
        or first.maximum_m.y <= second.minimum_m.y
        or second.maximum_m.y <= first.minimum_m.y
        or first.maximum_m.z <= second.minimum_m.z
        or second.maximum_m.z <= first.minimum_m.z
    )


def _lerp(first: Vector3, second: Vector3, fraction: float) -> Vector3:
    return Vector3(
        x=first.x + (second.x - first.x) * fraction,
        y=first.y + (second.y - first.y) * fraction,
        z=first.z + (second.z - first.z) * fraction,
    )


def _distance(first: Vector3, second: Vector3) -> float:
    return _norm(_subtract(first, second))


def _subtract(first: Vector3, second: Vector3) -> Vector3:
    return Vector3(x=first.x - second.x, y=first.y - second.y, z=first.z - second.z)


def _add(first: Vector3, second: Vector3) -> Vector3:
    return Vector3(x=first.x + second.x, y=first.y + second.y, z=first.z + second.z)


def _scale(value: Vector3, factor: float) -> Vector3:
    return Vector3(x=value.x * factor, y=value.y * factor, z=value.z * factor)


def _dot(first: Vector3, second: Vector3) -> float:
    return first.x * second.x + first.y * second.y + first.z * second.z


def _norm(value: Vector3) -> float:
    return math.sqrt(_dot(value, value))
