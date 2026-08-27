from pathlib import Path

import pytest

import crazyswarm_app.campaign.corridor as corridor_module
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.corridor import (
    GoalCorridorDisposition,
    search_goal_corridor,
)
from crazyswarm_app.campaign.models import CampaignCase, MissionCluster, Region3D
from crazyswarm_app.campaign.planner import (
    DEFAULT_LANDING_DURATION_S,
    BoundedJointPlanner,
)
from crazyswarm_app.campaign.replanning import (
    ReplanObservation,
    _cutover_turn_time_scale,
    _forward_projection_along_observation,
    _project_goal_corridor_start,
)
from crazyswarm_app.campaign.scheduling import LaunchActionKind, build_ground_first_schedule
from crazyswarm_app.domain.models import Vector3


def _volume() -> Region3D:
    return Region3D(
        region_id="flight-volume",
        minimum_m=Vector3(x=-1.5, y=-1.0, z=0.0),
        maximum_m=Vector3(x=1.5, y=1.0, z=1.0),
    )


def _obstacle(region_id: str = "object-a") -> Region3D:
    return Region3D(
        region_id=region_id,
        minimum_m=Vector3(x=-0.2, y=-0.2, z=0.0),
        maximum_m=Vector3(x=0.2, y=0.2, z=1.0),
    )


def _search(*, obstacles: tuple[Region3D, ...] = (), expansion_limit: int = 8192):
    return search_goal_corridor(
        start_m=Vector3(x=-1.3, y=0.0, z=0.4),
        goal_m=Vector3(x=1.3, y=0.0, z=0.4),
        flight_volume=_volume(),
        obstacles=obstacles,
        inflation_m=0.255,
        boundary_horizontal_margin_m=0.055,
        expansion_limit=expansion_limit,
    )


def test_straight_goal_corridor_matches_frozen_metric_witness() -> None:
    result = _search()

    assert result.disposition is GoalCorridorDisposition.SELECTED
    assert result.expanded_state_count == 52
    assert result.path_length_m == pytest.approx(2.6)
    assert result.integrated_absolute_heading_change_rad == pytest.approx(0.0)
    assert result.path_points_m[0].x == pytest.approx(-1.3)
    assert result.path_points_m[0].y == pytest.approx(0.0)
    assert result.path_points_m[0].z == pytest.approx(0.4)
    assert result.path_points_m[-1].x == pytest.approx(1.3)
    assert result.path_points_m[-1].y == pytest.approx(0.0)
    assert result.path_points_m[-1].z == pytest.approx(0.4)


def test_obstacle_identity_and_enumeration_do_not_change_corridor() -> None:
    normal = _search(obstacles=(_obstacle("first-name"),))
    renamed = search_goal_corridor(
        start_m=Vector3(x=-1.3, y=0.0, z=0.4),
        goal_m=Vector3(x=1.3, y=0.0, z=0.4),
        flight_volume=_volume(),
        obstacles=(_obstacle("renamed-object"),),
        inflation_m=0.255,
        boundary_horizontal_margin_m=0.055,
        neighbor_primitives=((1, 1), (1, 0), (1, -1), (0, 1), (0, -1), (-1, 1), (-1, 0), (-1, -1)),
    )

    assert normal.disposition is GoalCorridorDisposition.SELECTED
    assert renamed.disposition is GoalCorridorDisposition.SELECTED
    assert renamed.path_points_m == normal.path_points_m
    assert renamed.path_length_m == pytest.approx(3.0142135623730955)
    assert renamed.integrated_absolute_heading_change_rad == pytest.approx(
        2.356194490192345,
    )
    assert renamed.minimum_center_clearance_m == pytest.approx(0.3)


def test_frozen_euclidean_obstacle_witness_matches_exact_expansion_count() -> None:
    volume = Region3D(
        region_id="frozen-volume",
        minimum_m=Vector3(x=-1.8, y=-1.8, z=0.0),
        maximum_m=Vector3(x=1.8, y=1.8, z=1.0),
    )
    result = search_goal_corridor(
        start_m=Vector3(x=-1.3, y=0.0, z=0.4),
        goal_m=Vector3(x=1.3, y=0.0, z=0.4),
        flight_volume=volume,
        obstacles=(_obstacle(),),
        inflation_m=0.255,
        boundary_horizontal_margin_m=0.255,
    )

    assert result.disposition is GoalCorridorDisposition.SELECTED
    assert result.expanded_state_count == 4060
    assert result.path_length_m == pytest.approx(3.0142135623730955)
    assert result.integrated_absolute_heading_change_rad == pytest.approx(2.356194490192345)
    assert result.minimum_center_clearance_m == pytest.approx(0.3)


def test_zero_budget_and_post_certificate_expiry_dispatch_no_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zero = search_goal_corridor(
        start_m=Vector3(x=-1.3, y=0.0, z=0.4),
        goal_m=Vector3(x=1.3, y=0.0, z=0.4),
        flight_volume=_volume(),
        obstacles=(),
        inflation_m=0.255,
        boundary_horizontal_margin_m=0.055,
        wall_budget_s=0.0,
    )
    assert zero.disposition is GoalCorridorDisposition.BUDGET_EXHAUSTED
    assert zero.expanded_state_count == 0
    assert zero.path_points_m == ()

    now = [0.0]
    original_result = corridor_module._result

    def delayed_result(*args, **kwargs):
        result = original_result(*args, **kwargs)
        if result.disposition is GoalCorridorDisposition.SELECTED:
            now[0] = 0.51
        return result

    monkeypatch.setattr(corridor_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(corridor_module, "_result", delayed_result)
    delayed = search_goal_corridor(
        start_m=Vector3(x=-1.3, y=0.0, z=0.4),
        goal_m=Vector3(x=1.3, y=0.0, z=0.4),
        flight_volume=_volume(),
        obstacles=(),
        inflation_m=0.255,
        boundary_horizontal_margin_m=0.055,
    )
    assert delayed.disposition is GoalCorridorDisposition.BUDGET_EXHAUSTED
    assert delayed.path_points_m == ()


def test_moving_corridor_start_projects_forward_only_with_protected_clearance() -> None:
    observation = ReplanObservation.create(
        observation_id="moving-start",
        role_id="Alpha",
        source_timestamp_s=1.0,
        captured_at_source_s=1.0,
        position_m=Vector3(x=-0.5, y=0.0, z=0.4),
        velocity_m_s=Vector3(x=0.4, y=0.0, z=0.0),
    )

    projected = _project_goal_corridor_start(
        observation,
        flight_volume=_volume(),
        obstacles=(),
        protected_inflation_m=0.255,
        boundary_horizontal_margin_m=0.055,
        stop_speed_threshold_m_s=0.02,
    )
    blocked = _project_goal_corridor_start(
        observation,
        flight_volume=_volume(),
        obstacles=(
            Region3D(
                region_id="close-object",
                minimum_m=Vector3(x=-0.49, y=-0.2, z=0.0),
                maximum_m=Vector3(x=0.0, y=0.2, z=1.0),
            ),
        ),
        protected_inflation_m=0.255,
        boundary_horizontal_margin_m=0.055,
        stop_speed_threshold_m_s=0.02,
    )

    # The longest safe candidate covers one second of worker planning latency.
    assert projected.x == pytest.approx(-0.1)
    assert blocked == observation.position_m


def test_forward_projection_rejects_a_knot_passed_during_planning() -> None:
    observation = ReplanObservation.create(
        observation_id="fresh-cutover",
        role_id="Alpha",
        source_timestamp_s=2.0,
        captured_at_source_s=2.0,
        position_m=Vector3(x=-1.148, y=0.0, z=0.4),
        velocity_m_s=Vector3(x=0.208, y=0.0, z=0.0),
    )

    assert (
        _forward_projection_along_observation(
            observation,
            Vector3(x=-1.199, y=0.0, z=0.4),
        )
        < 0.0
    )
    assert (
        _forward_projection_along_observation(
            observation,
            Vector3(x=-1.100, y=0.0, z=0.4),
        )
        > observation.velocity_m_s.x**2 * 0.10
    )


def test_cutover_retiming_preserves_easy_turns_and_slows_hard_turns() -> None:
    observation = ReplanObservation.create(
        observation_id="moving-turn",
        role_id="Alpha",
        source_timestamp_s=2.0,
        captured_at_source_s=2.0,
        position_m=Vector3(),
        velocity_m_s=Vector3(x=0.3, y=0.0, z=0.0),
    )

    assert _cutover_turn_time_scale(
        observation,
        Vector3(x=1.0, y=0.5, z=0.0),
    ) == pytest.approx(1.0)
    assert _cutover_turn_time_scale(
        observation,
        Vector3(x=0.0, y=1.0, z=0.0),
    ) == pytest.approx(4.0 / 3.0)
    assert _cutover_turn_time_scale(
        observation,
        Vector3(x=-1.0, y=0.0, z=0.0),
    ) == pytest.approx(2.0)


def test_expansion_exhaustion_dispatches_no_corridor() -> None:
    result = _search(obstacles=(_obstacle(),), expansion_limit=1)

    assert result.disposition is GoalCorridorDisposition.BUDGET_EXHAUSTED
    assert result.path_points_m == ()


def test_diagonal_corner_cutting_is_rejected() -> None:
    volume = Region3D(
        region_id="small-volume",
        minimum_m=Vector3(x=-0.1, y=-0.1, z=0.0),
        maximum_m=Vector3(x=0.1, y=0.1, z=1.0),
    )
    blockers = (
        Region3D(
            region_id="east-blocker",
            minimum_m=Vector3(x=-0.005, y=-0.055, z=0.0),
            maximum_m=Vector3(x=0.005, y=-0.045, z=1.0),
        ),
        Region3D(
            region_id="north-blocker",
            minimum_m=Vector3(x=-0.055, y=-0.005, z=0.0),
            maximum_m=Vector3(x=-0.045, y=0.005, z=1.0),
        ),
    )

    result = search_goal_corridor(
        start_m=Vector3(x=-0.05, y=-0.05, z=0.4),
        goal_m=Vector3(x=0.05, y=0.05, z=0.4),
        flight_volume=volume,
        obstacles=blockers,
        inflation_m=0.01,
        boundary_horizontal_margin_m=0.05,
    )

    assert result.disposition is GoalCorridorDisposition.NO_SOLUTION
    assert result.path_points_m == ()


@pytest.mark.parametrize(
    "field",
    ("authored_reference_route", "authored_centerline", "authored_rejoin_waypoint"),
)
def test_goal_seeking_case_rejects_authored_geometry(field: str) -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    payload = catalog.get(
        "1d.online_obstacle_replan.dynamic_nominal",
    ).model_dump(mode="python")
    payload["semantics"]["goal_seeking"][field] = {"x": 0.0, "y": 0.0, "z": 0.4}

    with pytest.raises(ValueError, match=field):
        CampaignCase.model_validate(payload)


def test_dynamic_cluster_contains_only_the_online_goal_seeking_case() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    dynamic = [
        item for item in catalog.cases() if item.cluster is MissionCluster.DYNAMIC_REPLANNING
    ]

    assert [item.case_id for item in dynamic] == ["1d.online_obstacle_replan.dynamic_nominal"]
    assert dynamic[0].semantics is not None
    assert dynamic[0].semantics.goal_seeking is not None


def test_dynamic_watchdog_reserves_a_full_route_after_the_last_event() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    plan = BoundedJointPlanner().plan(case)
    assert plan.selected is not None
    schedule = build_ground_first_schedule(case, plan.selected)
    assert case.semantics is not None
    route_start_s = next(
        action.starts_at_source_s
        for action in schedule.roles[0].actions
        if action.kind is LaunchActionKind.START_ROUTE
    )
    expected_source_reserve_s = (
        route_start_s
        + max(event.trigger_time_s for event in case.semantics.scenario_events)
        + case.hard_constraints.planning_budget_s
        + plan.selected.routes[0].route_duration_s
        + DEFAULT_LANDING_DURATION_S
    )

    assert schedule.source_schedule_duration_s == pytest.approx(expected_source_reserve_s)
    assert schedule.wall_watchdog_s == pytest.approx(
        expected_source_reserve_s / case.hard_constraints.minimum_realtime_factor
        + case.hard_constraints.watchdog_guard_s
    )
