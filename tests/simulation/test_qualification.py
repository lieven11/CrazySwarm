from __future__ import annotations

import asyncio
import copy
import json
import math
import time
from itertools import pairwise
from pathlib import Path

import pytest

from crazyswarm_app.domain.commands import (
    ArmCommand,
    CommandEnvelope,
    CommandPayload,
    HoverCommand,
    LandCommand,
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
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.factory import vehicles_from_scenario
from crazyswarm_app.simulation.faults import FaultInjector, FaultType, FaultWindow
from crazyswarm_app.simulation.models import DEFAULT_FIDELITY_MANIFEST, SimulationConfig
from crazyswarm_app.simulation.physical_qualification import _normalized_report_sha256
from crazyswarm_app.simulation.physics import PhysicsModelConfig, Quaternion, SixDofPhysics
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import (
    IndoorWorld,
    ObstacleConfig,
    ScenarioConfig,
    WorldConfig,
    load_scenario,
)


def make_vehicle(
    *,
    vehicle_id: str = "sim01",
    config: SimulationConfig | None = None,
    world: IndoorWorld | None = None,
    position_m: Vector3 | None = None,
    yaw_rad: float = 0.0,
    faults: FaultInjector | None = None,
) -> SimulatedVehicle:
    return SimulatedVehicle(
        VehicleIdentity(vehicle_id=vehicle_id, display_name=vehicle_id, adapter="sim"),
        world or IndoorWorld(WorldConfig(width_m=6.0, depth_m=6.0, height_m=3.0)),
        config=config,
        initial_position_m=position_m,
        initial_yaw_rad=yaw_rad,
        faults=faults,
    )


def command(vehicle: SimulatedVehicle, command_id: str, payload: CommandPayload) -> CommandEnvelope:
    return CommandEnvelope(
        vehicle_id=vehicle.identity.vehicle_id,
        command_id=command_id,
        issued_at_monotonic_s=vehicle.clock.now_s,
        source=CommandSource.TEST,
        mode=OperatingMode.SIM,
        payload=payload,
    )


async def canonical_maneuver(fixed_step_s: float) -> SimulatedVehicle:
    vehicle = make_vehicle(
        config=SimulationConfig(
            fixed_step_s=fixed_step_s,
            position_noise_std_m=0.0,
            flow_drift_std_m_sqrt_s=0.0,
            range_noise_std_m=0.0,
        )
    )
    await vehicle.connect()
    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    await vehicle.execute(command(vehicle, "takeoff", TakeoffCommand(height_m=0.4, duration_s=2.0)))
    await vehicle.execute(
        command(
            vehicle,
            "move",
            MoveRelativeCommand(x_m=0.2, y_m=-0.1, yaw_rad=0.3, duration_s=2.0),
        )
    )
    await vehicle.execute(command(vehicle, "hover", HoverCommand(duration_s=2.0)))
    return vehicle


@pytest.mark.asyncio
async def test_cross_timestep_convergence() -> None:
    vehicles = [await canonical_maneuver(step) for step in (0.005, 0.01, 0.02)]
    reference = vehicles[0]
    reference_attitude = reference.physics.state.attitude.euler()
    for candidate in vehicles[1:]:
        position_delta = math.dist(
            tuple(reference.true_position_m.model_dump().values()),
            tuple(candidate.true_position_m.model_dump().values()),
        )
        attitude = candidate.physics.state.attitude.euler()
        attitude_delta = math.dist(
            tuple(reference_attitude.model_dump().values()),
            tuple(attitude.model_dump().values()),
        )
        assert position_delta <= 0.04
        assert attitude_delta <= 0.08


@pytest.mark.asyncio
async def test_long_duration_hover_move_idle_land_and_energy_invariants() -> None:
    idle = make_vehicle()
    await idle.connect()
    idle_start = idle.battery_percent
    await idle._elapse(30.0)
    assert idle.true_position_m.z == 0.0
    assert idle.battery_percent < idle_start

    vehicle = make_vehicle(
        config=SimulationConfig(
            fixed_step_s=0.01,
            position_noise_std_m=0.0,
            flow_drift_std_m_sqrt_s=0.0,
        )
    )
    await vehicle.connect()
    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    await vehicle.execute(command(vehicle, "takeoff", TakeoffCommand(height_m=0.3)))
    await vehicle.execute(command(vehicle, "hover-long", HoverCommand(duration_s=120.0)))
    await vehicle.execute(command(vehicle, "move", MoveRelativeCommand(x_m=0.2, duration_s=2.0)))
    await vehicle.execute(command(vehicle, "land", LandCommand(duration_s=2.0)))

    source_times = [sample.source_timestamp_s for sample in vehicle.telemetry_history]
    battery = [
        sample.telemetry.battery_percent
        for sample in vehicle.telemetry_history
        if sample.telemetry.battery_percent is not None
    ]
    assert all(later >= earlier for earlier, later in pairwise(source_times))
    assert all(later <= earlier for earlier, later in pairwise(battery))
    assert all(
        math.isfinite(value)
        for sample in vehicle.telemetry_history
        for vector in (sample.telemetry.ground_truth_position_m, sample.telemetry.velocity_m_s)
        if vector is not None
        for value in vector.model_dump().values()
    )
    attitude = vehicle.physics.state.attitude
    assert attitude.w**2 + attitude.x**2 + attitude.y**2 + attitude.z**2 == pytest.approx(
        1.0, abs=1e-9
    )
    assert vehicle.true_position_m.z == 0.0
    assert all(
        motor.command == motor.thrust_n == motor.current_a == 0.0
        for motor in vehicle.physics.state.motors
    )


def test_analytic_physics_invariants() -> None:
    # The exact closed-form hover reference belongs to the preserved uncoupled v1 plant.
    config = PhysicsModelConfig.legacy_v1()
    hover_command = config.total_mass_kg * config.gravity_m_s2 / (4.0 * config.max_motor_thrust_n)
    physics = SixDofPhysics(config, position_m=Vector3(z=1.0))
    for motor in physics.state.motors:
        motor.command = hover_command
        motor.thrust_n = config.total_mass_kg * config.gravity_m_s2 / 4.0
    for _ in range(2000):
        physics.step((hover_command,) * 4, 0.001)
    assert physics.state.position_m.z == pytest.approx(1.0, abs=0.015)
    assert physics.state.attitude.w**2 == pytest.approx(1.0, abs=1e-12)

    yaw = Quaternion.from_yaw(4.0 * math.pi + 0.2).euler().yaw_rad
    assert yaw == pytest.approx(0.2)
    saturated = physics.motor_commands_for_trajectory(
        target_position_m=Vector3(x=100.0, y=-100.0, z=100.0),
        target_velocity_m_s=Vector3(x=100.0, y=-100.0, z=100.0),
        target_acceleration_world_m_s2=Vector3(x=100.0, y=-100.0, z=100.0),
        target_yaw_rad=100.0,
    )
    assert all(0.0 <= value <= 1.0 for value in saturated)


def test_independent_free_fall_reference() -> None:
    config = PhysicsModelConfig(linear_drag_n_s_m=0.0)
    physics = SixDofPhysics(config, position_m=Vector3(z=1.0))
    dt = 0.001
    elapsed = 0.1
    for _ in range(round(elapsed / dt)):
        physics.step((0.0, 0.0, 0.0, 0.0), dt)
    analytic_velocity = -config.gravity_m_s2 * elapsed
    analytic_position = 1.0 - 0.5 * config.gravity_m_s2 * elapsed**2
    assert physics.state.velocity_m_s.z == pytest.approx(analytic_velocity, abs=1e-12)
    assert physics.state.position_m.z == pytest.approx(analytic_position, abs=0.001)


def test_independent_actuator_reference() -> None:
    config = PhysicsModelConfig.legacy_v1()
    physics = SixDofPhysics(config, position_m=Vector3(z=2.0))
    dt = 0.001
    steps = 100
    for _ in range(steps):
        physics.step((1.0, 0.0, 0.0, 0.0), dt)
    analytic = config.max_motor_thrust_n * (
        1.0 - math.exp(-(steps * dt) / config.motor_time_constant_s)
    )
    assert physics.state.motors[0].thrust_n == pytest.approx(analytic, abs=1e-12)


@pytest.mark.asyncio
async def test_collision_is_configured_termination_not_resolved_crash() -> None:
    world = IndoorWorld(
        WorldConfig(
            width_m=4.0,
            depth_m=4.0,
            height_m=2.0,
            obstacles=(
                ObstacleConfig(
                    obstacle_id="thin-wall",
                    minimum_m=Vector3(x=0.10, y=-0.4, z=0.0),
                    maximum_m=Vector3(x=0.20, y=0.4, z=0.8),
                ),
            ),
        )
    )
    vehicle = make_vehicle(world=world)
    await vehicle.connect()
    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    await vehicle.execute(command(vehicle, "takeoff", TakeoffCommand(height_m=0.3)))
    with pytest.raises(CrazySwarmError) as collision:
        await vehicle.execute(
            command(vehicle, "cross-wall", MoveRelativeCommand(x_m=0.4, duration_s=2.0))
        )
    assert collision.value.code is ErrorCode.GEOFENCE_BREACH
    assert collision.value.details == {"contact_model": "termination_only"}
    assert vehicle.state is VehicleState.FAULT
    assert "COLLISION_CONFIGURED_TERMINATION" in (await vehicle.snapshot()).telemetry.faults


@pytest.mark.asyncio
async def test_sensor_models_and_frames() -> None:
    config = SimulationConfig(
        position_noise_std_m=0.0,
        flow_drift_std_m_sqrt_s=0.0,
        range_noise_std_m=0.0,
    )
    vehicle = make_vehicle(
        config=config,
        world=IndoorWorld(WorldConfig(width_m=4.0, depth_m=6.0, height_m=3.0)),
        position_m=Vector3(z=0.5),
        yaw_rad=math.pi / 2.0,
    )
    initial = await vehicle.snapshot()
    assert initial.telemetry.imu is not None
    assert initial.telemetry.flow is not None
    assert initial.telemetry.ranges is not None
    assert initial.telemetry.imu.acceleration_body_m_s2.z == pytest.approx(
        config.physics.gravity_m_s2
    )
    assert initial.telemetry.imu.angular_velocity_body_rad_s == Vector3()
    assert initial.telemetry.flow.velocity_body_m_s == Vector3()
    assert initial.telemetry.flow.quality_percent == pytest.approx(100.0)
    assert initial.telemetry.ranges.front_m == pytest.approx(3.0)
    assert initial.telemetry.ranges.left_m == pytest.approx(2.0)
    assert initial.telemetry.ranges.down_m == pytest.approx(0.5)

    await vehicle._step(0.01, motor_commands=(0.0, 0.0, 0.0, 0.0))
    falling = await vehicle.snapshot()
    assert falling.telemetry.imu is not None
    assert falling.telemetry.imu.acceleration_body_m_s2.z == pytest.approx(0.0, abs=1e-12)

    failed = make_vehicle(
        faults=FaultInjector((FaultWindow(fault=FaultType.SENSOR_FAILURE, start_s=0.0),))
    )
    await failed.connect()
    failed_sample = await failed.snapshot()
    assert failed_sample.telemetry.imu is None
    assert failed_sample.telemetry.flow is None
    assert failed_sample.telemetry.ranges is None


def test_battery_energy_and_cutoff() -> None:
    config = PhysicsModelConfig()
    physics = SixDofPhysics(config, position_m=Vector3(z=1.0))
    charge = []
    voltage = []
    current = []
    command_value = config.total_mass_kg * config.gravity_m_s2 / (4.0 * config.max_motor_thrust_n)
    for _ in range(1000):
        physics.step((command_value,) * 4, 0.01)
        charge.append(physics.state.battery_state_of_charge)
        voltage.append(physics.state.battery_voltage_v)
        current.append(physics.state.battery_current_a)
    assert all(later <= earlier for earlier, later in pairwise(charge))
    assert min(voltage) < config.battery_full_voltage_v
    assert min(current) > config.battery_idle_current_a


@pytest.mark.asyncio
async def test_modeled_battery_cutoff_zeros_motors_and_faults() -> None:
    vehicle = make_vehicle(
        config=SimulationConfig(
            physics=PhysicsModelConfig(battery_cutoff_voltage_v=4.19),
        )
    )
    await vehicle.connect()
    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    with pytest.raises(CrazySwarmError) as cutoff:
        await vehicle.execute(command(vehicle, "takeoff", TakeoffCommand(height_m=0.3)))
    assert cutoff.value.code is ErrorCode.CRITICAL_BATTERY
    assert vehicle.state is VehicleState.FAULT
    assert all(
        motor.command == motor.thrust_n == motor.current_a == 0.0
        for motor in vehicle.physics.state.motors
    )


@pytest.mark.asyncio
async def test_airborne_battery_cutoff_falls_to_ground_before_terminal_sample() -> None:
    vehicle = make_vehicle()
    await vehicle.connect()
    await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    await vehicle.execute(
        command(
            vehicle,
            "takeoff-before-cutoff",
            TakeoffCommand(height_m=0.3, duration_s=2.0),
        )
    )
    airborne_height = vehicle.true_position_m.z
    assert airborne_height > 0.2

    await vehicle.set_battery_level(0.0)
    with pytest.raises(CrazySwarmError) as cutoff:
        await vehicle.execute(
            command(vehicle, "hover-through-cutoff", HoverCommand(duration_s=1.0))
        )

    assert cutoff.value.code is ErrorCode.CRITICAL_BATTERY
    assert vehicle.state is VehicleState.FAULT
    assert vehicle.true_position_m.z == pytest.approx(0.0, abs=1e-9)
    terminal = await vehicle.snapshot()
    assert terminal.telemetry.state is VehicleState.FAULT
    assert terminal.telemetry.armed is False
    assert terminal.telemetry.flying is False
    assert terminal.telemetry.battery_cutoff_active is True
    assert terminal.telemetry.ground_truth_position_m is not None
    assert terminal.telemetry.ground_truth_position_m.z == pytest.approx(0.0, abs=1e-9)
    assert terminal.telemetry.position_m is not None
    assert terminal.telemetry.position_m.z == pytest.approx(0.0, abs=0.01)
    descending_heights = [
        sample.telemetry.ground_truth_position_m.z
        for sample in vehicle.telemetry_history
        if sample.telemetry.ground_truth_position_m is not None
        and 0.0 < sample.telemetry.ground_truth_position_m.z < airborne_height
    ]
    assert descending_heights


async def failure_outcome(fault: FaultType, seed: int) -> tuple[object, ...]:
    if fault is FaultType.ACTUATOR_DEGRADATION:
        window = FaultWindow(
            fault=fault,
            start_s=0.0,
            motor_index=0,
            actuator_health_scale=0.5,
        )
    elif fault is FaultType.ACTUATOR_LOSS:
        window = FaultWindow(fault=fault, start_s=0.0, motor_index=0)
    else:
        window = FaultWindow(fault=fault, start_s=0.0)
    vehicle = make_vehicle(
        config=SimulationConfig(seed=seed),
        faults=FaultInjector((window,)),
    )
    code: str | None = None
    try:
        await vehicle.connect()
        if fault is FaultType.COMMAND_DROP:
            await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    except CrazySwarmError as error:
        code = error.code.value
    try:
        sample = await vehicle.snapshot()
    except CrazySwarmError as error:
        code = code or error.code.value
        sample = vehicle._last_published
    return (
        code,
        vehicle.state.value,
        sample.telemetry.position_m is not None,
        sample.telemetry.imu is not None,
        tuple(sample.telemetry.faults),
        None
        if sample.telemetry.battery_percent is None
        else round(sample.telemetry.battery_percent, 6),
    )


@pytest.mark.asyncio
async def test_failure_classes_reproduce_for_100_seeded_repetitions() -> None:
    expected_codes = {
        FaultType.COMMAND_DROP: ErrorCode.COMMAND_DROPPED.value,
        FaultType.DISCONNECT: ErrorCode.LINK_LOST.value,
        FaultType.STALE_TELEMETRY: ErrorCode.TELEMETRY_STALE.value,
        FaultType.GEOFENCE_BREACH: ErrorCode.GEOFENCE_BREACH.value,
        FaultType.COLLISION: ErrorCode.GEOFENCE_BREACH.value,
        FaultType.NUMERICAL_FAILURE: ErrorCode.INTERNAL_ERROR.value,
    }
    for fault in FaultType:
        for seed in range(100):
            first = await failure_outcome(fault, seed)
            second = await failure_outcome(fault, seed)
            assert first == second
            if fault in expected_codes:
                assert first[0] == expected_codes[fault]


async def transport_outcome(seed: int) -> tuple[str, float, tuple[tuple[int, float, float], ...]]:
    vehicle = make_vehicle(
        config=SimulationConfig(
            seed=seed,
            command_latency_s=0.08,
            acknowledgement_latency_s=0.03,
            packet_loss_probability=0.25,
        )
    )
    await vehicle.connect()
    result = "COMPLETED"
    try:
        await vehicle.execute(command(vehicle, "arm", ArmCommand()))
    except CrazySwarmError as error:
        result = error.code.value
    times = tuple(
        (sample.sequence, sample.source_timestamp_s, sample.received_timestamp_s)
        for sample in vehicle.telemetry_history
    )
    return result, vehicle.clock.now_s, times


@pytest.mark.asyncio
async def test_seeded_transport_reproducibility() -> None:
    outcomes = []
    for seed in range(100):
        first = await transport_outcome(seed)
        second = await transport_outcome(seed)
        assert first == second
        assert all(receive - source == pytest.approx(0.03) for _, source, receive in first[2])
        outcomes.append(first[0])
    assert "COMPLETED" in outcomes
    assert ErrorCode.COMMAND_DROPPED.value in outcomes


@pytest.mark.asyncio
async def test_one_and_three_vehicle_identity_isolation_and_separation() -> None:
    one = load_scenario(Path("config/worlds/one_drone.yaml"))
    assert len(vehicles_from_scenario(one)) == 1

    three = load_scenario(Path("config/worlds/three_drone.yaml"))
    accelerated = three.model_copy(
        update={
            "simulation": three.simulation.model_copy(update={"clock_mode": ClockMode.ACCELERATED})
        }
    )
    vehicles = vehicles_from_scenario(accelerated)
    assert [vehicle.identity.vehicle_id for vehicle in vehicles] == ["sim01", "sim02", "sim03"]
    for vehicle in vehicles:
        await vehicle.connect()
        await vehicle.execute(command(vehicle, f"arm-{vehicle.identity.vehicle_id}", ArmCommand()))
        await vehicle.execute(
            command(
                vehicle,
                f"takeoff-{vehicle.identity.vehicle_id}",
                TakeoffCommand(height_m=0.3),
            )
        )
        await vehicle.execute(
            command(vehicle, f"hover-{vehicle.identity.vehicle_id}", HoverCommand(duration_s=2.0))
        )
    separations = [
        math.dist(
            tuple(left.true_position_m.model_dump().values()),
            tuple(right.true_position_m.model_dump().values()),
        )
        for index, left in enumerate(vehicles)
        for right in vehicles[index + 1 :]
    ]
    assert min(separations) > 1.4
    assert all(
        sample.vehicle_id == vehicle.identity.vehicle_id
        for vehicle in vehicles
        for sample in vehicle.telemetry_history
    )

    wrong_target = command(vehicles[1], "wrong-target", HoverCommand(duration_s=1.0))
    with pytest.raises(CrazySwarmError) as mismatch:
        await vehicles[0].execute(wrong_target)
    assert mismatch.value.code is ErrorCode.IDENTITY_MISMATCH

    scoped = ScenarioConfig.model_validate(
        three.model_dump()
        | {
            "simulation": three.simulation.model_copy(update={"clock_mode": ClockMode.ACCELERATED}),
            "faults": (
                FaultWindow(
                    fault=FaultType.DISCONNECT,
                    start_s=0.0,
                    vehicle_id="sim02",
                ),
            ),
        }
    )
    scoped_vehicles = vehicles_from_scenario(scoped)
    await scoped_vehicles[0].connect()
    with pytest.raises(CrazySwarmError, match="disconnected"):
        await scoped_vehicles[1].connect()
    await scoped_vehicles[2].connect()
    assert scoped_vehicles[0].state is scoped_vehicles[2].state is VehicleState.READY


@pytest.mark.asyncio
async def test_three_vehicle_realtime_telemetry_load_stays_on_wall_clock() -> None:
    scenario = load_scenario(Path("config/worlds/three_drone.yaml"))
    realtime = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"fixed_step_s": 0.005, "clock_mode": ClockMode.REALTIME, "speed": 1.0}
            )
        }
    )
    vehicles = vehicles_from_scenario(realtime)
    await asyncio.gather(*(vehicle.connect() for vehicle in vehicles))
    await asyncio.gather(
        *(
            vehicle.execute(command(vehicle, f"arm-{vehicle.identity.vehicle_id}", ArmCommand()))
            for vehicle in vehicles
        )
    )
    wall_started = time.perf_counter()
    await asyncio.gather(
        *(
            vehicle.execute(
                command(
                    vehicle,
                    f"takeoff-{vehicle.identity.vehicle_id}",
                    TakeoffCommand(height_m=0.02, duration_s=0.25),
                )
            )
            for vehicle in vehicles
        )
    )
    await asyncio.gather(
        *(
            vehicle.execute(
                command(
                    vehicle,
                    f"hover-{vehicle.identity.vehicle_id}",
                    HoverCommand(duration_s=0.15),
                )
            )
            for vehicle in vehicles
        )
    )
    wall_elapsed_s = time.perf_counter() - wall_started

    assert 0.35 <= wall_elapsed_s < 1.5
    assert all(vehicle.clock.now_s >= 0.4 for vehicle in vehicles)
    assert all(len(vehicle.telemetry_history) >= 75 for vehicle in vehicles)
    assert all(
        [sample.sequence for sample in vehicle.telemetry_history]
        == sorted(sample.sequence for sample in vehicle.telemetry_history)
        for vehicle in vehicles
    )


def test_qualification_scenarios_and_fidelity_manifest_are_complete() -> None:
    for path in (
        "config/scenarios/link_loss.yaml",
        "config/scenarios/low_battery.yaml",
        "config/scenarios/transport_faults.yaml",
        "config/scenarios/sensor_faults.yaml",
        "config/scenarios/termination_faults.yaml",
    ):
        assert load_scenario(Path(path)).scenario_id

    report = json.loads(Path(DEFAULT_FIDELITY_MANIFEST.qualification_report).read_text())
    assert report["failure_repetitions_per_class"] == 100
    assert report["hardware_qualified"] is False
    assert report["decision"] == "SOFTWARE_QUALIFIED_CONFIGURED_UNQUALIFIED"
    assert len(report["powertrain_matrix"]) == 168
    assert len(report["mechanical_and_actuator_matrix"]) == 6
    assert len(report["sensor_matrix"]) == 15
    assert all(report["verified_invariants"].values())
    assert set(report["external_evidence"].values()) == {"NOT_RUN"}
    assert report["normalized_report_exclusions"] == [
        "performance_and_long_duration.performance_wall_s",
        "performance_and_long_duration.represented_vehicle_seconds_per_wall_second",
    ]
    assert report["normalized_report_sha256"] == _normalized_report_sha256(report)
    slower = copy.deepcopy(report)
    slower["performance_and_long_duration"]["performance_wall_s"] *= 2.0
    slower["performance_and_long_duration"]["represented_vehicle_seconds_per_wall_second"] /= 2.0
    assert _normalized_report_sha256(slower) == report["normalized_report_sha256"]
    assert {item.output for item in DEFAULT_FIDELITY_MANIFEST.output_evidence} == set(
        DEFAULT_FIDELITY_MANIFEST.modeled_outputs
    )
    assert "resolved_contact_impulse" in DEFAULT_FIDELITY_MANIFEST.omitted_outputs
    assert "transport_jitter" in DEFAULT_FIDELITY_MANIFEST.omitted_outputs
