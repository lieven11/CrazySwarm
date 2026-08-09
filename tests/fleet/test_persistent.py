from pathlib import Path

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import Vector3, VehicleCapability
from crazyswarm_app.fleet.artifacts import DeploymentManifest, load_versioned_contract
from crazyswarm_app.fleet.persistent import (
    CoverageCandidate,
    CoverageVehicleState,
    HandoverPhase,
    PersistentCoverageCoordinator,
)

ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES = frozenset(
    {VehicleCapability.RELATIVE_POSITIONING, VehicleCapability.HIGH_LEVEL_COMMANDS}
)


def deployment() -> DeploymentManifest:
    return load_versioned_contract(
        ROOT / "config/fleet/three-drone-persistent-coverage-v1.yaml",
        DeploymentManifest,
    )


def candidates(*, reserve_available: bool = True) -> tuple[CoverageCandidate, ...]:
    return (
        CoverageCandidate(
            vehicle_id="cf01",
            capabilities=CAPABILITIES,
            battery_percent=82.0,
            position_m=Vector3(x=-1.2),
            state=CoverageVehicleState.ACTIVE,
        ),
        CoverageCandidate(
            vehicle_id="cf02",
            capabilities=CAPABILITIES,
            battery_percent=85.0,
            position_m=Vector3(x=1.2),
            state=CoverageVehicleState.ACTIVE,
        ),
        CoverageCandidate(
            vehicle_id="cf03",
            capabilities=CAPABILITIES,
            battery_percent=96.0,
            position_m=Vector3(y=-1.5),
            state=CoverageVehicleState.RESERVE,
            available=reserve_available,
        ),
    )


def coordinator() -> PersistentCoverageCoordinator:
    return PersistentCoverageCoordinator(
        fleet_session_id="coverage-session",
        fleet_run_id="coverage-run",
        deployment=deployment(),
    )


def test_atomic_handover_retains_then_invalidates_outgoing_lease() -> None:
    coverage = coordinator()
    initial = coverage.allocate_initial(candidates(), now_s=10.0)
    assert {item.task_id: item.vehicle_id for item in initial} == {
        "cover-zone-a": "cf01",
        "cover-zone-b": "cf02",
    }
    assert candidates()[2].reserve_ready

    handover = coverage.begin_handover(
        "cover-zone-a",
        reason="LOW_BATTERY",
        candidates=candidates(),
        now_s=11.0,
    )
    assert handover.phase is HandoverPhase.PREPARING
    assert handover.incoming_vehicle_id == "cf03"
    before = coverage.tasks.record("cover-zone-a")
    assert before.owner_vehicle_id == "cf01"
    assert before.lease_generation == 1

    with pytest.raises(CrazySwarmError, match="before confirmed takeover"):
        coverage.release_outgoing(handover.handover_id, now_s=12.0)

    coverage.confirm_replacement_ready(
        handover.handover_id,
        candidates=candidates(),
        now_s=12.0,
    )
    pending = coverage.tasks.record("cover-zone-a")
    assert pending.owner_vehicle_id == "cf01"
    confirmed = coverage.confirm_takeover(
        handover.handover_id,
        candidates=candidates(),
        now_s=13.0,
    )
    assert confirmed.takeover_confirmed
    transferred = coverage.tasks.record("cover-zone-a")
    assert transferred.owner_vehicle_id == "cf03"
    assert transferred.lease_generation == 2
    with pytest.raises(CrazySwarmError, match="current task ownership"):
        coverage.tasks.renew("cover-zone-a", "cf01", 1, now_s=14.0)

    completed = coverage.release_outgoing(handover.handover_id, now_s=14.0)
    assert completed.phase is HandoverPhase.COMPLETED
    assert completed.outgoing_released_at_monotonic_s is not None
    result = coverage.result()
    assert result.status == "SUCCEEDED"
    assert result.active_owners == {"cover-zone-a": "cf03", "cover-zone-b": "cf02"}
    assert len(set(result.active_owners.values())) == len(result.active_owners)


def test_unavailable_reserve_is_explicit_degradation_without_release() -> None:
    coverage = coordinator()
    coverage.allocate_initial(candidates(reserve_available=False), now_s=10.0)
    handover = coverage.begin_handover(
        "cover-zone-a",
        reason="VEHICLE_LOST",
        candidates=candidates(reserve_available=False),
        now_s=11.0,
    )
    assert handover.phase is HandoverPhase.DEGRADED
    assert coverage.tasks.record("cover-zone-a").owner_vehicle_id == "cf01"
    assert coverage.result().reason_code == "NO_SERVICEABLE_RESERVE"


def test_critical_separation_blocks_takeover_and_preserves_owner() -> None:
    coverage = coordinator()
    coverage.allocate_initial(candidates(), now_s=10.0)
    handover = coverage.begin_handover(
        "cover-zone-a", reason="COMMAND_LOSS", candidates=candidates(), now_s=11.0
    )
    coverage.confirm_replacement_ready(handover.handover_id, candidates=candidates(), now_s=12.0)
    unsafe = (*candidates()[:2], candidates()[2].model_copy(update={"position_m": Vector3(x=-1.1)}))
    with pytest.raises(CrazySwarmError, match="critical separation"):
        coverage.confirm_takeover(
            handover.handover_id,
            candidates=unsafe,
            now_s=13.0,
        )
    record = coverage.tasks.record("cover-zone-a")
    assert record.owner_vehicle_id == "cf01"
    assert record.lease_generation == 1
