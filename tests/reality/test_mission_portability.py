from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import VehicleIdentity, VehicleState
from crazyswarm_app.missions.models import MissionResult, MissionStatus
from crazyswarm_app.missions.registry import MissionRegistry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.missions.script import (
    MissionTier,
    ScriptMission,
    parse_python_mission,
)
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.faults import FaultInjector, FaultType, FaultWindow
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig
from crazyswarm_app.vehicles.base import Vehicle
from crazyswarm_app.vehicles.mock_isaac import MockIsaacSimVehicle

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "missions" / "qualification"
POSITIVE = (
    "hover_30s.py",
    "move_return.py",
    "square_relative.py",
    "body_yaw.py",
    "range_approach_stop.py",
    "range_direction_escape.py",
    "flow_out_back.py",
    "observation_timeout.py",
    "hover_cancel.py",
    "hover_emergency.py",
    "floor_height_transition.py",
)


def fast_vehicle(*, faults: FaultInjector | None = None) -> SimulatedVehicle:
    return SimulatedVehicle(
        VehicleIdentity(vehicle_id="vehicle01", display_name="Fast", adapter="fast-v1"),
        IndoorWorld(WorldConfig(width_m=4.0, depth_m=4.0, height_m=2.5)),
        faults=faults,
    )


async def execute(path: Path, vehicle: Vehicle) -> MissionResult:
    record = parse_python_mission(filename=path.name, name=path.stem, source=path.read_text())
    registry = MissionRegistry()
    registry.register(ScriptMission(record))
    supervisor = SafetySupervisor()
    supervisor.register_vehicle(vehicle)
    return await MissionRunner(supervisor, registry).run(
        record.mission_id,
        vehicle.identity.vehicle_id,
    )


def test_canonical_corpus_validates_and_freezes_hover_source_identity() -> None:
    records = {
        name: parse_python_mission(
            filename=name,
            name=Path(name).stem,
            source=(CORPUS / name).read_text(),
        )
        for name in POSITIVE
    }
    assert records["hover_30s.py"].source == (ROOT / "missions" / "hover30s.py").read_text()
    assert records["hover_30s.py"].source_sha256 == (
        "fd00838a0fe5beb13e6fc52c39555b9e284b4da5951207f510844dca904c36dc"
    )
    assert records["hover_30s.py"].tier is MissionTier.LINEAR
    assert records["range_approach_stop.py"].tier is MissionTier.BOUNDED_OBSERVATION
    assert records["range_approach_stop.py"].planned_observation_budget == 4
    assert all(record.language_version == "bounded-python-1" for record in records.values())


@pytest.mark.parametrize("path", sorted((CORPUS / "negative").glob("*.py")))
def test_negative_artifacts_are_rejected_before_connection(path: Path) -> None:
    with pytest.raises(CrazySwarmError):
        parse_python_mission(filename=path.name, name=path.stem, source=path.read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("name", POSITIVE)
async def test_every_canonical_mission_executes_through_fast_and_mock(name: str) -> None:
    path = CORPUS / name
    fast = await execute(path, fast_vehicle())
    mock = await execute(path, MockIsaacSimVehicle(vehicle_id="vehicle01"))
    assert fast.status is MissionStatus.SUCCEEDED
    assert mock.status is MissionStatus.SUCCEEDED
    assert fast.mission_source_sha256 == mock.mission_source_sha256
    assert fast.normalized_intent_trace == mock.normalized_intent_trace
    assert fast.backend_role == "FAST_SIM"
    assert mock.backend_role == "ISAAC_SIM"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["range_approach_stop.py", "range_direction_escape.py", "flow_out_back.py"],
)
async def test_equivalent_online_observations_drive_equivalent_decisions(name: str) -> None:
    path = CORPUS / name
    first = await execute(path, fast_vehicle())
    second = await execute(path, MockIsaacSimVehicle(vehicle_id="vehicle01"))
    assert first.observations_read
    assert second.observations_read
    assert first.normalized_intent_trace == second.normalized_intent_trace


@pytest.mark.asyncio
async def test_required_observation_loss_cannot_become_success() -> None:
    path = CORPUS / "observation_timeout.py"
    fast = await execute(
        path,
        fast_vehicle(
            faults=FaultInjector((FaultWindow(fault=FaultType.LOCALIZATION_LOSS, start_s=2.0),))
        ),
    )
    mock = await execute(
        path,
        MockIsaacSimVehicle(vehicle_id="vehicle01", withhold_position_after_s=2.0),
    )
    assert fast.status is not MissionStatus.SUCCEEDED
    assert mock.status is not MissionStatus.SUCCEEDED
    assert fast.reason_code == "LOCALIZATION_INVALID"
    assert mock.reason_code == "LOCALIZATION_INVALID"


@pytest.mark.asyncio
async def test_mock_gateway_is_a_real_process_and_resets_source_epoch() -> None:
    vehicle = MockIsaacSimVehicle()
    await vehicle.connect()
    assert vehicle._process is not None  # process boundary is the behavior under test
    assert vehicle._process.pid != 0
    before = await vehicle.snapshot()
    reset = await vehicle.reset_source_clock()
    assert reset.source_clock_epoch == before.source_clock_epoch + 1
    assert reset.source_timestamp_s == 0.0
    await vehicle.disconnect()
    assert vehicle._process is None


@pytest.mark.asyncio
async def test_cancellation_leaves_no_worker_lease_or_flight() -> None:
    path = CORPUS / "hover_cancel.py"
    record = parse_python_mission(filename=path.name, name=path.stem, source=path.read_text())
    registry = MissionRegistry()
    registry.register(ScriptMission(record))
    vehicle = fast_vehicle()
    supervisor = SafetySupervisor()
    supervisor.register_vehicle(vehicle)
    runner = MissionRunner(supervisor, registry)
    task = asyncio.create_task(runner.run(record.mission_id, vehicle.identity.vehicle_id))
    for _ in range(2000):
        runs = runner.list_runs()
        if runs and supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.FLYING:
            await runner.cancel(runs[0].mission_run_id)
            break
        await asyncio.sleep(0.001)
    result = await asyncio.wait_for(task, timeout=5.0)
    assert result.status is MissionStatus.ABORTED
    assert result.reason_code == "MISSION_CANCELLED"
    session = supervisor.session(vehicle.identity.vehicle_id)
    assert session.lease is None
    assert session.state is VehicleState.DISCONNECTED
    assert not (await vehicle.snapshot()).telemetry.flying


@pytest.mark.asyncio
async def test_qf10_supervised_emergency_preempts_worker_and_flight() -> None:
    path = CORPUS / "hover_emergency.py"
    record = parse_python_mission(filename=path.name, name=path.stem, source=path.read_text())
    registry = MissionRegistry()
    registry.register(ScriptMission(record))
    vehicle = fast_vehicle()
    supervisor = SafetySupervisor()
    supervisor.register_vehicle(vehicle)
    runner = MissionRunner(supervisor, registry)
    run_id = "qf10-emergency-run"
    task = asyncio.create_task(
        runner.run(record.mission_id, vehicle.identity.vehicle_id, mission_run_id=run_id)
    )
    for _ in range(2000):
        if supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.FLYING:
            await supervisor.emergency_stop(
                vehicle.identity.vehicle_id,
                f"mission:{run_id}",
                reason="QF-10 qualification emergency",
            )
            break
        await asyncio.sleep(0.001)
    else:
        raise AssertionError("QF-10 did not reach the emergency injection phase")
    result = await asyncio.wait_for(task, timeout=5.0)
    session = supervisor.session(vehicle.identity.vehicle_id)
    assert result.status is not MissionStatus.SUCCEEDED
    assert result.reason_code == "EMERGENCY_STOPPED"
    assert session.state is VehicleState.EMERGENCY
    assert session.lease is None
    assert session.active_execute_task is None
    assert not vehicle._armed
    assert not vehicle._flying


@pytest.mark.asyncio
async def test_counter_bounded_while_executes_online_with_equal_backend_intent() -> None:
    source = """\
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    attempt = 0
    while attempt < 3:
        observation = await drone.observe(timeout_s=0.5, required="front_range")
        if observation.ranges.front_m <= 0.6:
            break
        await drone.move_relative(x_m=0.05, duration_s=1.0, frame="body")
        attempt = attempt + 1
    await drone.land(duration_s=2.0)
"""
    record = parse_python_mission(filename="bounded_while.py", name="bounded while", source=source)
    assert record.planned_observation_budget == 3
    assert record.planned_command_budget == 5
    registry = MissionRegistry()
    registry.register(ScriptMission(record))

    async def run(vehicle: Vehicle) -> MissionResult:
        supervisor = SafetySupervisor()
        supervisor.register_vehicle(vehicle)
        return await MissionRunner(supervisor, registry).run(
            record.mission_id, vehicle.identity.vehicle_id
        )

    fast = await run(fast_vehicle())
    mock = await run(MockIsaacSimVehicle(vehicle_id="vehicle01"))
    assert fast.status is mock.status is MissionStatus.SUCCEEDED
    assert fast.normalized_intent_trace == mock.normalized_intent_trace
