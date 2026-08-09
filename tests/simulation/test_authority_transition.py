from __future__ import annotations

import pytest

from crazyswarm_app.domain.commands import (
    ArmCommand,
    CommandEnvelope,
    DisarmCommand,
    FleetCommandBinding,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    CommandSource,
    OperatingMode,
    VehicleIdentity,
)
from crazyswarm_app.domain.simulation import (
    FleetAuthorityTransition,
    MissionRunBinding,
    canonical_sha256,
)
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig

DIGEST = canonical_sha256({"fixture": "fleet-authority-transition"})


def make_vehicle() -> SimulatedVehicle:
    return SimulatedVehicle(
        VehicleIdentity(vehicle_id="sim01", display_name="Simulation 1", adapter="sim"),
        IndoorWorld(WorldConfig(width_m=4.0, depth_m=4.0, height_m=2.5)),
    )


def run_binding(
    *,
    mission_run_id: str = "child-zone-a",
    task_id: str = "cover-zone-a",
    generation: int = 1,
) -> MissionRunBinding:
    return MissionRunBinding(
        mission_run_id=mission_run_id,
        fleet_session_id="fleet-session",
        fleet_run_id="fleet-run",
        deployment_sha256=DIGEST,
        task_id=task_id,
        task_lease_generation=generation,
        backend_namespace="fastsim://sim01",
        preparation_state="READY",
    )


def command_binding(*, task_id: str, generation: int) -> FleetCommandBinding:
    return FleetCommandBinding(
        fleet_session_id="fleet-session",
        fleet_run_id="fleet-run",
        deployment_sha256=DIGEST,
        task_id=task_id,
        task_lease_generation=generation,
        backend_namespace="fastsim://sim01",
    )


def command(
    vehicle: SimulatedVehicle,
    *,
    command_id: str,
    payload: ArmCommand | DisarmCommand,
    task_id: str,
    generation: int,
) -> CommandEnvelope:
    return CommandEnvelope(
        vehicle_id=vehicle.identity.vehicle_id,
        command_id=command_id,
        mission_run_id="child-zone-a",
        fleet=command_binding(task_id=task_id, generation=generation),
        issued_at_monotonic_s=vehicle.clock.now_s,
        source=CommandSource.MISSION,
        mode=OperatingMode.SIM,
        payload=payload,
    )


def transition(
    *,
    sequence: int = 1,
    vehicle_id: str = "sim01",
    mission_run_id: str = "child-zone-a",
    fleet_run_id: str = "fleet-run",
    expected_task_id: str = "cover-zone-a",
    expected_generation: int = 1,
    next_task_id: str = "return-zone-a",
    next_generation: int = 1,
) -> FleetAuthorityTransition:
    return FleetAuthorityTransition(
        transition_id=f"transition-{sequence}",
        sequence=sequence,
        vehicle_id=vehicle_id,
        mission_run_id=mission_run_id,
        fleet_session_id="fleet-session",
        fleet_run_id=fleet_run_id,
        deployment_sha256=DIGEST,
        expected_task_id=expected_task_id,
        expected_task_lease_generation=expected_generation,
        next_task_id=next_task_id,
        next_task_lease_generation=next_generation,
        reason_code="TAKEOVER_CONFIRMED",
        authorization_sha256=canonical_sha256({"handover": "zone-a-generation-2"}),
    )


@pytest.mark.asyncio
async def test_transition_invalidates_old_commands_and_accepts_only_new_authority() -> None:
    vehicle = make_vehicle()
    await vehicle.connect()
    await vehicle.bind_run(run_binding())
    await vehicle.execute(
        command(
            vehicle,
            command_id="arm-before-transition",
            payload=ArmCommand(),
            task_id="cover-zone-a",
            generation=1,
        )
    )

    receipt = await vehicle.transition_fleet_authority(transition())

    with pytest.raises(CrazySwarmError) as stale:
        await vehicle.execute(
            command(
                vehicle,
                command_id="stale-disarm",
                payload=DisarmCommand(),
                task_id="cover-zone-a",
                generation=1,
            )
        )
    assert stale.value.code is ErrorCode.IDENTITY_MISMATCH

    await vehicle.execute(
        command(
            vehicle,
            command_id="authorized-disarm",
            payload=DisarmCommand(),
            task_id="return-zone-a",
            generation=1,
        )
    )
    assert receipt.previous_task_id == "cover-zone-a"
    assert receipt.current_task_id == "return-zone-a"
    assert receipt.transition_sha256 == transition().sha256
    assert vehicle.authority_transition_receipts == (receipt,)


@pytest.mark.asyncio
async def test_transition_rejects_duplicate_skipped_and_cross_run_authority() -> None:
    vehicle = make_vehicle()
    await vehicle.connect()
    await vehicle.bind_run(run_binding())

    with pytest.raises(CrazySwarmError) as skipped:
        await vehicle.transition_fleet_authority(transition(sequence=2))
    assert skipped.value.code is ErrorCode.MODE_NOT_AUTHORIZED

    with pytest.raises(CrazySwarmError) as cross_run:
        await vehicle.transition_fleet_authority(transition(fleet_run_id="other-run"))
    assert cross_run.value.code is ErrorCode.IDENTITY_MISMATCH

    accepted = transition()
    await vehicle.transition_fleet_authority(accepted)
    with pytest.raises(CrazySwarmError) as duplicate:
        await vehicle.transition_fleet_authority(accepted)
    assert duplicate.value.code is ErrorCode.MODE_NOT_AUTHORIZED


@pytest.mark.asyncio
async def test_same_run_cannot_bypass_transition_with_direct_rebind() -> None:
    vehicle = make_vehicle()
    await vehicle.connect()
    await vehicle.bind_run(run_binding())

    with pytest.raises(CrazySwarmError) as bypass:
        await vehicle.bind_run(run_binding(task_id="return-zone-a"))
    assert bypass.value.code is ErrorCode.MODE_NOT_AUTHORIZED

    await vehicle.execute(
        command(
            vehicle,
            command_id="arm-current-run",
            payload=ArmCommand(),
            task_id="cover-zone-a",
            generation=1,
        )
    )
    with pytest.raises(CrazySwarmError) as hijack:
        await vehicle.bind_run(run_binding(mission_run_id="different-child-run"))
    assert hijack.value.code is ErrorCode.INVALID_STATE
