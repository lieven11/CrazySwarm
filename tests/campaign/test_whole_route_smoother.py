from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import RouteNodeMode
from crazyswarm_app.campaign.planner import RouteStop
from crazyswarm_app.campaign.trajectory import allocate_trajectory_points
from crazyswarm_app.domain.models import Vector3


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
