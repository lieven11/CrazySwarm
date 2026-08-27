from pathlib import Path
from types import SimpleNamespace

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.execution_head import (
    CampaignExecutionHead,
    _event_can_reduce_clearance,
)
from crazyswarm_app.campaign.replanning import (
    DynamicEventKind,
    SafeFallbackCommand,
    SafePrefixCertificate,
)
from crazyswarm_app.campaign.submissions import resolve_planning_submission
from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
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


def test_one_drone_execution_head_requires_sensor_source_and_auto_authority() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    event = WorldTruthEvent.create(
        event_id="rock",
        sequence=1,
        source_timestamp_s=2.0,
        effective_source_s=3.0,
        kind=WorldTruthEventKind.SOLID_APPEARED,
        solid_id="rock",
        obstacle=ObstacleConfig(
            obstacle_id="rock",
            minimum_m=Vector3(x=0.1, y=-0.1, z=0.1),
            maximum_m=Vector3(x=0.3, y=0.1, z=0.6),
        ),
    )
    source = SimulatedPerceptionObservationSource(
        timeline=DynamicWorldTimeline((), (event,)),
        config=PerceptionModelConfig(),
        mission_id="mission",
        run_id="run",
        vehicle_id="Alpha",
    )
    assert not CampaignExecutionHead(
        case=case,
        planning_submission=resolve_planning_submission(case, None),
    ).enabled
    assert CampaignExecutionHead(
        case=case,
        planning_submission=resolve_planning_submission(case, None),
        perception_source=source,
        mission_id="mission",
        run_id="run",
    ).enabled


def test_only_hazard_increasing_events_can_force_immediate_fallback() -> None:
    assert _event_can_reduce_clearance(DynamicEventKind.OBSTACLE_ADDED)
    assert _event_can_reduce_clearance(DynamicEventKind.OBSTACLE_MOVED)
    assert _event_can_reduce_clearance(DynamicEventKind.PASSAGE_CLOSED)
    assert not _event_can_reduce_clearance(DynamicEventKind.OBSTACLE_REMOVED)
    assert not _event_can_reduce_clearance(DynamicEventKind.PASSAGE_OPENED)


@pytest.mark.asyncio
async def test_certified_hold_terminates_superseded_program_via_vertical_landing() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.online_obstacle_replan.dynamic_nominal")
    head = CampaignExecutionHead(
        case=case,
        planning_submission=resolve_planning_submission(case, None),
    )

    class FallbackContext:
        def __init__(self) -> None:
            self.stop_reasons: list[str] = []
            self.land_targets: list[Vector3] = []

        async def stop_and_hold_for_replan(self, *, reason: str) -> None:
            self.stop_reasons.append(reason)

        async def observe(self, *, timeout_s: float) -> object:
            del timeout_s
            return SimpleNamespace(
                valid=True,
                sequence=7,
                source_timestamp_s=5.2,
                estimated_position_m=Vector3(x=-1.0, y=0.2, z=0.4),
                velocity_m_s=Vector3(),
            )

        async def certified_abort_and_land_for_replan(
            self,
            *,
            target_position_m: Vector3,
            certificate_sha256: str,
            reason: str,
        ) -> None:
            assert len(certificate_sha256) == 64
            assert "terminated" in reason
            self.land_targets.append(target_position_m)

    context = FallbackContext()
    head._contexts = {"Alpha": context}
    payload = {
        "schema_version": 1,
        "case_sha256": case.case_sha256,
        "event_sha256": "a" * 64,
        "observation_sha256s": ("b" * 64,),
        "perceived_world_sha256": head._perceived_world_state.state_sha256,
        "old_world_sha256": "c" * 64,
        "active_trajectory_sha256s": ("d" * 64,),
        "safe_until_source_s": 8.0,
        "stopping_envelope_m": 0.10,
        "certified_clearance_m": 0.50,
        "observation_fresh_until_source_s": 5.25,
        "fallback_command": SafeFallbackCommand.STOP_AND_HOLD,
        "fallback_route_sha256": None,
        "passed": True,
    }
    certificate = SafePrefixCertificate(
        **payload,
        certificate_sha256=canonical_sha256(payload),
    )

    with pytest.raises(CrazySwarmError, match="accepted execution program terminated") as caught:
        await head._execute_certified_fallback(
            certificate,
            reason="forced planner failure",
        )

    assert caught.value.details["recovery_already_completed"] is True
    assert context.stop_reasons == ["forced planner failure"]
    assert context.land_targets == [Vector3(x=-1.0, y=0.2, z=0.0)]
    assert [record["stage"] for record in head._records] == [
        "SAFE_FALLBACK_EXECUTED",
        "TERMINAL_CERTIFIED_VERTICAL_LANDING_EXECUTED",
    ]
