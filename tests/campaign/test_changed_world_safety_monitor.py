from pathlib import Path

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.geometry import structured_world_from_case
from crazyswarm_app.campaign.models import Region3D
from crazyswarm_app.campaign.planner import BoundedJointPlanner
from crazyswarm_app.campaign.replanning import (
    ChangedWorldSafetyMonitor,
    DynamicEventKind,
    InFlightEnvironmentEvent,
    ReplanObservation,
    SafeFallbackCommand,
)
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.models import Vector3


def test_safe_prefix_derives_hold_or_abort_without_caller_boolean() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    plan = BoundedJointPlanner().plan(case)
    assert plan.selected is not None
    trajectory = generate_smooth_trajectories(case, plan.selected).trajectories[0]
    observation = ReplanObservation.create(
        observation_id="stopped-alpha",
        role_id="Alpha",
        source_timestamp_s=2.0,
        captured_at_source_s=2.0,
        position_m=Vector3(x=0.0, y=0.0, z=0.45),
        velocity_m_s=Vector3(),
    )
    obstacle = Region3D(
        region_id="rock",
        minimum_m=Vector3(x=0.4, y=-0.1, z=0.1),
        maximum_m=Vector3(x=0.6, y=0.1, z=0.7),
    )
    event = InFlightEnvironmentEvent(
        event_id="rock-seen",
        kind=DynamicEventKind.OBSTACLE_ADDED,
        source_id="sensor",
        sequence=1,
        source_timestamp_s=1.9,
        received_source_s=2.0,
        effective_source_s=3.0,
        affected_role_ids=("Alpha",),
        region_id="rock",
        region=obstacle,
    )
    certificate = ChangedWorldSafetyMonitor(case).certify(
        event=event,
        observations=(observation,),
        active_trajectories={"Alpha": trajectory},
        perceived_world_sha256="b" * 64,
        old_world_sha256=structured_world_from_case(case).world_sha256,
        minimum_clearance_m=0.15,
    )
    assert certificate.passed
    assert certificate.fallback_command is SafeFallbackCommand.STOP_AND_HOLD
    assert certificate.safe_until_source_s == event.effective_source_s
    assert certificate.observation_fresh_until_source_s == 2.25
