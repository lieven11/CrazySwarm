from __future__ import annotations

import time

import pytest

from crazyswarm_app.domain.commands import (
    AbortCommand,
    ArmCommand,
    CommandEnvelope,
    CommandPayload,
    EmergencyStopCommand,
    HoverCommand,
    MoveRelativeCommand,
    TakeoffCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    CommandSource,
    OperatingMode,
    Vector3,
    VehicleIdentity,
    VehicleState,
)
from crazyswarm_app.simulation.faults import FaultInjector, FaultType, FaultWindow
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig


def make_vehicle(
    *,
    config: SimulationConfig | None = None,
    faults: FaultInjector | None = None,
) -> SimulatedVehicle:
    return SimulatedVehicle(
        VehicleIdentity(vehicle_id="sim01", display_name="Simulation 1", adapter="sim"),
        IndoorWorld(WorldConfig(width_m=4.0, depth_m=4.0, height_m=2.5)),
        config=config,
        faults=faults,
    )


def command(
    vehicle: SimulatedVehicle,
    command_id: str,
    payload: CommandPayload,
) -> CommandEnvelope:
    return CommandEnvelope(
        vehicle_id=vehicle.identity.vehicle_id,
        command_id=command_id,
        issued_at_monotonic_s=vehicle.clock.now_s,
        source=CommandSource.TEST,
        mode=OperatingMode.SIM,
        payload=payload,
    )


def assert_state(vehicle: SimulatedVehicle, expected: VehicleState) -> None:
    assert vehicle.state is expected


@pytest.mark.asyncio
async def test_nominal_hover_move_and_land() -> None:
    vehicle = make_vehicle()
    await vehicle.connect()
    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    await vehicle.execute(command(vehicle, "takeoff", TakeoffCommand(height_m=0.3, duration_s=2.0)))
    assert_state(vehicle, VehicleState.FLYING)
    assert vehicle.true_position_m.z == pytest.approx(0.3, abs=0.02)

    await vehicle.execute(command(vehicle, "hover", HoverCommand(duration_s=5.0)))
    assert vehicle.true_position_m.z == pytest.approx(0.3, abs=0.03)
    await vehicle.execute(
        command(
            vehicle,
            "move",
            MoveRelativeCommand(x_m=0.2, duration_s=2.0),
        )
    )
    await vehicle.execute(command(vehicle, "abort", AbortCommand(reason="test complete")))

    assert_state(vehicle, VehicleState.READY)
    assert vehicle.true_position_m.z == 0.0
    assert vehicle.true_position_m.x == pytest.approx(0.2, abs=0.03)
    assert vehicle.battery_percent < 100.0
    assert vehicle.telemetry_history[-1].telemetry.ranges is not None
    assert vehicle.telemetry_history[-1].telemetry.flow is not None
    assert vehicle.telemetry_history[-1].telemetry.motors is not None
    assert vehicle.telemetry_history[-1].telemetry.battery_current_a is not None


@pytest.mark.asyncio
async def test_lateral_motion_is_produced_by_motor_torque_and_full_attitude() -> None:
    vehicle = make_vehicle()
    await vehicle.connect()
    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    await vehicle.execute(command(vehicle, "takeoff", TakeoffCommand(height_m=0.3)))
    start = len(vehicle.telemetry_history)
    await vehicle.execute(command(vehicle, "move", MoveRelativeCommand(x_m=0.2, duration_s=2.0)))
    movement = vehicle.telemetry_history[start:]
    assert any(
        item.telemetry.attitude is not None and abs(item.telemetry.attitude.pitch_rad) > 0.01
        for item in movement
    )
    assert any(
        len({round(motor.thrust_n, 5) for motor in item.telemetry.motors.readings}) > 1
        for item in movement
        if item.telemetry.motors is not None
    )


@pytest.mark.asyncio
async def test_deterministic_seed_produces_same_telemetry() -> None:
    first = make_vehicle()
    second = make_vehicle()
    for vehicle in (first, second):
        await vehicle.connect()
        await vehicle.execute(command(vehicle, "arm", ArmCommand()))
        await vehicle.execute(
            command(vehicle, "takeoff", TakeoffCommand(height_m=0.3, duration_s=2.0))
        )
        await vehicle.execute(command(vehicle, "hover", HoverCommand(duration_s=1.0)))

    first_values = [item.telemetry.position_m for item in first.telemetry_history]
    second_values = [item.telemetry.position_m for item in second.telemetry_history]
    assert first_values == second_values


@pytest.mark.asyncio
async def test_invalid_state_and_bounds_fail() -> None:
    vehicle = make_vehicle()
    await vehicle.connect()
    with pytest.raises(CrazySwarmError) as unarmed:
        await vehicle.execute(
            command(vehicle, "takeoff", TakeoffCommand(height_m=0.3, duration_s=2.0))
        )
    assert unarmed.value.code is ErrorCode.INVALID_STATE

    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    with pytest.raises(CrazySwarmError) as too_fast:
        await vehicle.execute(
            command(vehicle, "takeoff-fast", TakeoffCommand(height_m=1.0, duration_s=0.1))
        )
    assert too_fast.value.code is ErrorCode.INVALID_COMMAND


@pytest.mark.asyncio
async def test_fault_injection_is_visible() -> None:
    faults = FaultInjector((FaultWindow(fault=FaultType.SENSOR_FAILURE, start_s=0.0),))
    vehicle = make_vehicle(faults=faults)
    await vehicle.connect()
    snapshot = await vehicle.snapshot()
    assert snapshot.telemetry.imu is None
    assert snapshot.telemetry.flow is None
    assert "SENSOR_FAILURE" in snapshot.telemetry.faults


@pytest.mark.asyncio
async def test_localization_loss_and_stale_telemetry() -> None:
    localization = make_vehicle(
        faults=FaultInjector((FaultWindow(fault=FaultType.LOCALIZATION_LOSS, start_s=0.0),))
    )
    await localization.connect()
    snapshot = await localization.snapshot()
    assert snapshot.telemetry.position_m is None
    assert snapshot.telemetry.localization_quality_percent is None
    assert "LOCALIZATION_LOSS" in snapshot.telemetry.faults

    stale = make_vehicle(
        faults=FaultInjector((FaultWindow(fault=FaultType.STALE_TELEMETRY, start_s=0.0),))
    )
    await stale.connect()
    assert stale.telemetry_history == []


@pytest.mark.asyncio
async def test_link_loss_and_low_battery_are_reproducible() -> None:
    link_loss = make_vehicle(
        faults=FaultInjector((FaultWindow(fault=FaultType.DISCONNECT, start_s=0.0),))
    )
    with pytest.raises(CrazySwarmError) as disconnected:
        await link_loss.connect()
    assert disconnected.value.code is ErrorCode.LINK_LOST
    assert_state(link_loss, VehicleState.DISCONNECTED)

    low_battery = make_vehicle(
        config=SimulationConfig(
            battery_start_percent=10.1,
            battery_flight_drain_percent_s=0.1,
            critical_battery_percent=10.0,
        )
    )
    await low_battery.connect()
    await low_battery.execute(command(low_battery, "arm", ArmCommand()))
    await low_battery.execute(
        command(low_battery, "takeoff", TakeoffCommand(height_m=0.3, duration_s=2.0))
    )
    assert "CRITICAL_BATTERY" in (await low_battery.snapshot()).telemetry.faults


@pytest.mark.asyncio
async def test_command_drop_and_emergency_stop() -> None:
    dropped = make_vehicle(
        faults=FaultInjector((FaultWindow(fault=FaultType.COMMAND_DROP, start_s=0.0),))
    )
    await dropped.connect()
    with pytest.raises(CrazySwarmError) as error:
        await dropped.execute(command(dropped, "arm", ArmCommand()))
    assert error.value.code is ErrorCode.COMMAND_DROPPED

    vehicle = make_vehicle()
    await vehicle.connect()
    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    await vehicle.execute(command(vehicle, "takeoff", TakeoffCommand(height_m=0.3)))
    await vehicle.execute(
        command(vehicle, "emergency", EmergencyStopCommand(reason="operator test"))
    )
    assert_state(vehicle, VehicleState.EMERGENCY)
    assert not (await vehicle.snapshot()).telemetry.armed


@pytest.mark.asyncio
async def test_accelerated_simulation_runs_faster_than_wall_time() -> None:
    vehicle = make_vehicle()
    await vehicle.connect()
    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    await vehicle.execute(command(vehicle, "takeoff", TakeoffCommand(height_m=0.3)))
    start = time.monotonic()
    await vehicle.execute(command(vehicle, "hover", HoverCommand(duration_s=10.0)))
    wall_duration = time.monotonic() - start
    assert wall_duration < 1.0
    assert vehicle.clock.now_s >= 12.0


def test_initial_position_must_be_in_world() -> None:
    with pytest.raises(ValueError, match="outside"):
        SimulatedVehicle(
            VehicleIdentity(vehicle_id="sim01", display_name="Simulation", adapter="sim"),
            IndoorWorld(WorldConfig(width_m=2.0, depth_m=2.0, height_m=1.0)),
            initial_position_m=Vector3(x=3.0),
        )
