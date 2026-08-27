import inspect
from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.execution_head import CampaignExecutionHead
from crazyswarm_app.campaign.perception import PerceivedWorldState, PerceptionObservation
from crazyswarm_app.campaign.planner import BoundedJointPlanner
from crazyswarm_app.campaign.replanning import (
    DynamicEventKind,
    InFlightEnvironmentEvent,
    InFlightReplanCoordinator,
    ReplanObservation,
    commit_changed_world_replacement,
    plan_changed_world_replacement,
)
from crazyswarm_app.campaign.submissions import (
    MotionPreparationRequest,
    resolve_planning_package,
    resolve_planning_submission,
)
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.trajectory import sample_trajectory
from crazyswarm_app.simulation.sensors import (
    PerceptionModelConfig,
    SimulatedPerceptionObservationSource,
)
from crazyswarm_app.simulation.world import (
    DynamicWorldTimeline,
    ObstacleConfig,
    WorldTruthEvent,
    WorldTruthEventKind,
)


def _event(*, x: float = 0.0) -> WorldTruthEvent:
    return WorldTruthEvent.create(
        event_id="future-rock",
        sequence=1,
        source_timestamp_s=2.0,
        effective_source_s=5.0,
        kind=WorldTruthEventKind.SOLID_APPEARED,
        solid_id="rock",
        obstacle=ObstacleConfig(
            obstacle_id="rock",
            minimum_m=Vector3(x=x - 0.1, y=-0.1, z=0.1),
            maximum_m=Vector3(x=x + 0.1, y=0.1, z=0.7),
        ),
    )


def test_future_world_truth_is_absent_from_initial_plan_identity() -> None:
    first = DynamicWorldTimeline((), (_event(x=0.0),))
    alternate = DynamicWorldTimeline((), (_event(x=0.4),))
    assert first.initial_world_sha256 == alternate.initial_world_sha256
    assert first.events[0].truth_sha256 != alternate.events[0].truth_sha256


def test_sensor_adapter_emits_delayed_hash_bound_observation() -> None:
    source = SimulatedPerceptionObservationSource(
        timeline=DynamicWorldTimeline((), (_event(),)),
        config=PerceptionModelConfig(latency_s=0.12),
        mission_id="mission",
        run_id="run",
        vehicle_id="Alpha",
    )
    assert source.pop_ready(2.11) is None
    observation = source.pop_ready(2.12)
    assert observation is not None
    assert observation.received_timestamp_s - observation.source_timestamp_s == pytest.approx(0.12)
    state = PerceivedWorldState.empty().apply(observation)
    assert state.revision == 1
    assert "rock" in state.solids

    payload = observation.model_dump(mode="python")
    payload["world_revision"] = 9
    with pytest.raises(ValueError, match="hash mismatch"):
        PerceptionObservation.model_validate(payload)


def test_production_head_enables_one_drone_only_with_sensor_source() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    source = SimulatedPerceptionObservationSource(
        timeline=DynamicWorldTimeline((), (_event(),)),
        config=PerceptionModelConfig(),
        mission_id="mission",
        run_id="run",
        vehicle_id="Alpha",
    )
    head = CampaignExecutionHead(
        case=case,
        planning_submission=resolve_planning_submission(case, None),
        perception_source=source,
        mission_id="mission",
        run_id="run",
    )
    assert head.enabled
    InFlightReplanCoordinator(case)
    assert (
        "old_epoch_still_safe" not in inspect.signature(commit_changed_world_replacement).parameters
    )


def test_prepared_motion_profile_is_rebound_into_changed_world_child() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    package = resolve_planning_package(
        case,
        motion_preparation_request=MotionPreparationRequest(
            speed_m_s=0.48,
            accuracy_m=0.05,
            smoothness=70,
        ),
    )
    assert package.execution_profile.submission_id.startswith("prepared-motion.")
    initial_plan = BoundedJointPlanner().plan(
        case,
        package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
        first_certified_within_budget=True,
    )
    assert initial_plan.selected is not None
    initial = generate_smooth_trajectories(
        case,
        initial_plan.selected,
        submission=package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
    ).trajectories[0]
    sampled = sample_trajectory(initial, initial.duration_s * 0.20)
    observation = ReplanObservation.create(
        observation_id="prepared-motion-cutover",
        role_id="Alpha",
        source_timestamp_s=5.0,
        captured_at_source_s=5.0,
        position_m=sampled.position_m,
        velocity_m_s=sampled.velocity_m_s,
        acceleration_m_s2=Vector3(),
    )
    obstacle = _event().obstacle
    assert obstacle is not None
    proposal = plan_changed_world_replacement(
        case=case,
        planning_submission=package.planning_submission,
        execution_profile=package.execution_profile,
        capability_resolution=package.capability_resolution,
        event=InFlightEnvironmentEvent(
            event_id="prepared-motion-obstacle",
            kind=DynamicEventKind.OBSTACLE_ADDED,
            source_id="simulated-depth-range",
            sequence=1,
            source_timestamp_s=5.0,
            received_source_s=5.12,
            effective_source_s=8.0,
            affected_role_ids=("Alpha",),
            world_generation=1,
            region_id=obstacle.obstacle_id,
            region={
                "region_id": obstacle.obstacle_id,
                "minimum_m": obstacle.minimum_m,
                "maximum_m": obstacle.maximum_m,
            },
        ),
        observations=(observation,),
        old_trajectories={"Alpha": initial},
    )

    assert proposal.execution_profile.submission_id == package.execution_profile.submission_id
    assert proposal.execution_profile.case_sha256 == proposal.replacement_case.case_sha256
    assert (
        proposal.planning_submission.execution_profile_sha256
        == proposal.execution_profile.profile_sha256
    )
    assert proposal.capability_resolution == package.capability_resolution
    assert proposal.trajectories.execution_profile_fallback == ("PLANNER_CANDIDATE_NATIVE_TIMING")
