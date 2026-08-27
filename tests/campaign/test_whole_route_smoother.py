import math
from itertools import pairwise
from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import RouteNodeMode
from crazyswarm_app.campaign.planner import BoundedJointPlanner, PlanningStatus, RouteStop
from crazyswarm_app.campaign.submissions import (
    CoordinationPreparationRequest,
    MotionPreparationRequest,
    resolve_planning_package,
)
from crazyswarm_app.campaign.trajectory import (
    allocate_trajectory_points,
    generate_smooth_trajectories,
)
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.trajectory import sample_trajectory, sample_trajectory_segment


def _case():
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    return catalog.get("1d.continuous_waypoint_sequence.canonical_nominal")


def test_collinear_fly_through_knots_keep_continuous_speed() -> None:
    points = allocate_trajectory_points(
        _case(),
        (Vector3(), Vector3(x=0.2), Vector3(x=0.4), Vector3(x=0.6)),
        speed_factor=1.0,
        segment_durations_s=(1.0, 1.0, 1.0),
    )
    for index in (1, 2):
        before_speed = 0.2 / (
            points[index].time_from_start_s - points[index - 1].time_from_start_s
        )
        after_speed = 0.2 / (
            points[index + 1].time_from_start_s - points[index].time_from_start_s
        )
        target = min(before_speed, after_speed)
        assert points[index].velocity_m_s.x / target >= 0.85


def test_fly_through_tangent_rule_is_invariant_to_fleet_size() -> None:
    positions = (
        Vector3(x=-1.0, y=-0.25, z=0.35),
        Vector3(x=-0.25, y=0.0, z=0.35),
        Vector3(x=0.25, y=0.0, z=0.35),
        Vector3(x=1.0, y=0.25, z=0.35),
    )
    durations = (3.0, 2.0, 3.0)
    one_drone = allocate_trajectory_points(
        _case(),
        positions,
        speed_factor=1.0,
        segment_durations_s=durations,
    )
    two_drone_case = _case().model_copy(update={"drone_count": 2})
    two_drone = allocate_trajectory_points(
        two_drone_case,
        positions,
        speed_factor=1.0,
        segment_durations_s=durations,
    )

    assert two_drone == one_drone
    assert all(_speed(point.velocity_m_s) > 0.02 for point in two_drone[1:-1])


def test_bottleneck_staging_knots_remain_fly_through() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("2d.bottleneck.canonical_nominal")
    package = resolve_planning_package(
        case,
        planning_submission_id="bottleneck.earliest_safe_release",
        motion_preparation_request=MotionPreparationRequest(balance=50),
    )
    plan = BoundedJointPlanner().plan(
        case,
        package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
        first_certified_within_budget=True,
    )
    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
    )

    assert all(not route.declared_stops for route in plan.selected.routes)
    assert all(audit.generated_unintended_stop_count == 0 for audit in trajectories.audits)
    assert all(
        _speed(point.velocity_m_s) > case.hard_constraints.dynamics.stop_speed_threshold_m_s
        for trajectory in trajectories.trajectories
        for point in trajectory.points[1:-1]
    )


def test_two_drone_launch_gap_is_an_exact_coordination_input_not_a_motion_change() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("2d.perpendicular_crossing.nominal_equal_priority")
    automatic = resolve_planning_package(
        case,
        "crossing.earliest_equal_release",
        motion_preparation_request=MotionPreparationRequest(balance=50),
    )
    prepared = resolve_planning_package(
        case,
        "crossing.earliest_equal_release",
        motion_preparation_request=MotionPreparationRequest(balance=50),
        coordination_preparation_request=CoordinationPreparationRequest(launch_gap_s=8.0),
    )
    assert automatic.execution_profile == prepared.execution_profile
    assert prepared.coordination_preparation is not None

    plan = BoundedJointPlanner().plan(
        case,
        prepared.execution_profile,
        planning_submission=prepared.planning_submission,
        capability_resolution=prepared.capability_resolution,
        requested_release_delay_s=prepared.coordination_preparation.launch_gap_s,
    )
    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    assert sorted(route.route_start_s for route in plan.selected.routes) == [0.0, 8.0]


def test_bottleneck_launch_gap_reuses_the_certified_passage_geometry() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("2d.bottleneck.canonical_nominal")
    prepared = resolve_planning_package(
        case,
        "bottleneck.earliest_safe_release",
        motion_preparation_request=MotionPreparationRequest(balance=50),
        coordination_preparation_request=CoordinationPreparationRequest(launch_gap_s=12.0),
    )

    plan = BoundedJointPlanner().plan(
        case,
        prepared.execution_profile,
        planning_submission=prepared.planning_submission,
        capability_resolution=prepared.capability_resolution,
        requested_release_delay_s=12.0,
    )

    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    assert sorted(route.route_start_s for route in plan.selected.routes) == [0.0, 12.0]
    assert all(route.geometry_parameters.get("passage_staging") for route in plan.selected.routes)
    assert all(not route.declared_stops for route in plan.selected.routes)


def test_authored_checkpoint_still_stops_and_holds() -> None:
    checkpoint = Vector3(x=0.2)
    points = allocate_trajectory_points(
        _case(),
        (Vector3(), checkpoint, Vector3(x=0.4)),
        speed_factor=1.0,
        segment_durations_s=(1.0, 1.0),
        declared_stops=(
            RouteStop(
                position_m=checkpoint,
                mode=RouteNodeMode.CAPTURE_AND_HOLD,
                dwell_s=0.4,
            ),
        ),
    )
    captures = [point for point in points if point.position_m == checkpoint]
    assert len(captures) == 2
    assert all(point.velocity_m_s == Vector3() for point in captures)
    assert captures[1].time_from_start_s - captures[0].time_from_start_s == pytest.approx(0.4)


def _speed(vector: Vector3) -> float:
    return math.sqrt(vector.x**2 + vector.y**2 + vector.z**2)


def _segment_speed(first: Vector3, second: Vector3, duration_s: float) -> float:
    return math.sqrt(
        (second.x - first.x) ** 2
        + (second.y - first.y) ** 2
        + (second.z - first.z) ** 2
    ) / duration_s


def test_easy_bend_preserves_at_least_95_percent_of_admitted_speed() -> None:
    authored = (
        Vector3(x=-1.0),
        Vector3(),
        Vector3(x=1.0, y=0.2),
    )
    points = allocate_trajectory_points(
        _case(),
        authored,
        speed_factor=1.0,
        segment_durations_s=(2.0, 2.04),
    )
    before = _segment_speed(
        authored[0], authored[1], points[1].time_from_start_s
    )
    after = _segment_speed(
        authored[1],
        authored[2],
        points[2].time_from_start_s - points[1].time_from_start_s,
    )

    assert _speed(points[1].velocity_m_s) / min(before, after) >= 0.95


def test_hard_bend_slows_without_an_instantaneous_velocity_change() -> None:
    authored = (
        Vector3(x=-1.0),
        Vector3(),
        Vector3(x=-0.173648, y=0.984808),
    )
    points = allocate_trajectory_points(
        _case(),
        authored,
        speed_factor=1.0,
        segment_durations_s=(2.0, 2.0),
    )
    before = _segment_speed(
        authored[0], authored[1], points[1].time_from_start_s
    )
    after = _segment_speed(
        authored[1],
        authored[2],
        points[2].time_from_start_s - points[1].time_from_start_s,
    )
    knot_speed = _speed(points[1].velocity_m_s)

    assert 0.0 < knot_speed < 0.95 * min(before, after)
    assert _speed(points[1].acceleration_m_s2) <= (
        _case().hard_constraints.dynamics.maximum_acceleration_m_s2
    )


def test_corner_transition_stays_inside_the_turn_instead_of_swinging_outward() -> None:
    points = allocate_trajectory_points(
        _case(),
        (
            Vector3(x=-1.0, z=0.35),
            Vector3(z=0.35),
            Vector3(y=1.0, z=0.35),
        ),
        speed_factor=1.0,
        path_speed_targets_m_s=(0.3, 0.3),
        transition_distance_m=0.3,
        turn_blend_radius_m=0.25,
        corner_cut_tolerance_m=0.25,
    )
    transition_start, transition_end = points[2:4]
    midpoint = sample_trajectory_segment(
        transition_start,
        transition_end,
        (transition_start.time_from_start_s + transition_end.time_from_start_s) / 2.0,
    ).position_m

    assert midpoint.x < -0.04
    assert midpoint.y > 0.04
    assert math.hypot(midpoint.x, midpoint.y) > 0.06


def _prepared_trajectory(case_id: str, accuracy_m: float):
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get(case_id)
    package = resolve_planning_package(
        case,
        motion_preparation_request=MotionPreparationRequest(
            balance=100,
            accuracy_m=accuracy_m,
            smoothness=0,
        ),
    )
    plan = BoundedJointPlanner().plan(
        case,
        package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
        first_certified_within_budget=True,
    )
    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    trajectory = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
    ).trajectories[0]
    return case, package, trajectory


def _distance_to_segment(point: Vector3, start: Vector3, end: Vector3) -> float:
    delta = Vector3(x=end.x - start.x, y=end.y - start.y, z=end.z - start.z)
    relative = Vector3(x=point.x - start.x, y=point.y - start.y, z=point.z - start.z)
    length_squared = delta.x**2 + delta.y**2 + delta.z**2
    fraction = max(
        0.0,
        min(
            1.0,
            (
                relative.x * delta.x
                + relative.y * delta.y
                + relative.z * delta.z
            )
            / length_squared,
        ),
    )
    projection = Vector3(
        x=start.x + fraction * delta.x,
        y=start.y + fraction * delta.y,
        z=start.z + fraction * delta.z,
    )
    return math.dist(
        (point.x, point.y, point.z),
        (projection.x, projection.y, projection.z),
    )


def _maximum_deviation_from_direct(trajectory) -> float:
    start = trajectory.points[0].position_m
    end = trajectory.points[-1].position_m
    return max(
        _distance_to_segment(
            sample_trajectory(
                trajectory,
                trajectory.duration_s * sample_index / 200.0,
            ).position_m,
            start,
            end,
        )
        for sample_index in range(201)
    )


def test_continuous_accuracy_cuts_corners_without_touching_every_fly_through_knot() -> None:
    case, package, trajectory = _prepared_trajectory(
        "1d.continuous_waypoint_sequence.canonical_nominal",
        0.25,
    )
    assert package.capability_resolution is not None
    assert package.capability_resolution.feasibility is not None
    assert package.capability_resolution.feasibility.maximum_path_deviation_m <= 0.25

    control_positions = {point.position_m for point in trajectory.points}
    assert all(
        goal.center_m not in control_positions
        for goal in case.drones[0].goal_sequence[:-1]
    )


def test_accuracy_sweep_converges_continuously_before_direct_line_boundary() -> None:
    accuracies = (0.43, 0.44, 0.445, 0.449, 0.45)
    trajectories = [
        _prepared_trajectory(
            "1d.continuous_waypoint_sequence.canonical_nominal",
            accuracy,
        )[2]
        for accuracy in accuracies
    ]
    deviations = tuple(_maximum_deviation_from_direct(value) for value in trajectories)

    assert all(after < before for before, after in pairwise(deviations))
    assert deviations[-2] < 0.001
    assert deviations[-1] <= 1e-9
    # The control topology collapses only after the pre-boundary curve is already
    # geometrically indistinguishable from the admitted direct line.
    assert len(trajectories[-2].points) > 4
    assert len(trajectories[-1].points) == 4


def test_3d_accuracy_relaxes_every_bend_instead_of_deleting_one_waypoint() -> None:
    trajectories = [
        _prepared_trajectory(
            "1d.altitude_transition.canonical_nominal",
            accuracy,
        )[2]
        for accuracy in (0.15, 0.17, 0.20)
    ]

    assert {len(value.points) for value in trajectories} == {10}
    deviations = tuple(_maximum_deviation_from_direct(value) for value in trajectories)
    assert deviations[0] > deviations[1] > deviations[2]


@pytest.mark.parametrize(
    "case_id",
    (
        "1d.continuous_waypoint_sequence.canonical_nominal",
        "1d.curved_route.canonical_nominal",
        "1d.altitude_transition.canonical_nominal",
    ),
)
def test_room_scale_accuracy_compiles_a_direct_safe_fly_through(case_id: str) -> None:
    _case_value, _package, trajectory = _prepared_trajectory(case_id, 4.0)
    start = trajectory.points[0].position_m
    end = trajectory.points[-1].position_m
    timestamp_s = 0.0
    maximum_direct_deviation_m = 0.0
    while timestamp_s <= trajectory.duration_s + 1e-9:
        sample = sample_trajectory(trajectory, timestamp_s)
        maximum_direct_deviation_m = max(
            maximum_direct_deviation_m,
            _distance_to_segment(sample.position_m, start, end),
        )
        timestamp_s += 0.02

    assert len(trajectory.points) == 4
    assert maximum_direct_deviation_m <= 1e-8


def test_multi_goal_preparation_still_stops_at_every_checkpoint() -> None:
    case, package, trajectory = _prepared_trajectory(
        "1d.static_multi_goal_sequence.canonical_nominal",
        0.08,
    )
    assert package.execution_profile.kind.value == "CONSTANT_PATH_SPEED"
    for goal in case.drones[0].goal_sequence:
        captures = [
            point
            for point in trajectory.points
            if math.dist(
                (point.position_m.x, point.position_m.y, point.position_m.z),
                (goal.center_m.x, goal.center_m.y, goal.center_m.z),
            )
            <= 1e-9
        ]
        assert len(captures) == 2
        assert all(_speed(point.velocity_m_s) == 0.0 for point in captures)
