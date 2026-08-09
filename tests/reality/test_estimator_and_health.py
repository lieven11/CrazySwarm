from __future__ import annotations

import inspect
import math
from itertools import pairwise
from pathlib import Path

import pytest

from crazyswarm_app.domain.models import Vector3, VehicleIdentity, VehicleState
from crazyswarm_app.domain.telemetry import RangeStatus
from crazyswarm_app.missions.models import MissionStatus
from crazyswarm_app.missions.registry import MissionRegistry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.missions.script import ScriptMission, parse_python_mission
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.faults import FaultInjector, FaultType, FaultWindow
from crazyswarm_app.simulation.models import (
    ControllerProfile,
    DisturbanceConfig,
    FlowEnvironmentConfig,
    FlowSurfaceClass,
    LightingClass,
    SimulationConfig,
)
from crazyswarm_app.simulation.physics import PhysicsModelConfig, SixDofPhysics
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig

ROOT = Path(__file__).resolve().parents[2]


def vehicle_for(
    source: str, *, fault: FaultWindow | None = None
) -> tuple[MissionRunner, SimulatedVehicle, str]:
    record = parse_python_mission(filename="phase.py", name="phase", source=source)
    registry = MissionRegistry()
    registry.register(ScriptMission(record))
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="sim01", display_name="Fast", adapter="arbitrary-adapter-id"),
        IndoorWorld(WorldConfig()),
        faults=FaultInjector(() if fault is None else (fault,)),
    )
    supervisor = SafetySupervisor()
    supervisor.register_vehicle(vehicle)
    return MissionRunner(supervisor, registry), vehicle, record.mission_id


def test_operator_default_is_estimator_in_loop_and_pure_controller_has_no_truth_access() -> None:
    assert SimulationConfig().controller_profile is ControllerProfile.ESTIMATOR_IN_LOOP_REFERENCE
    source = inspect.getsource(SixDofPhysics.motor_commands_for_control_state)
    assert "self.state" not in source
    assert "ground_truth" not in source


@pytest.mark.asyncio
async def test_physical_v2_estimator_does_not_copy_horizontal_physics_truth() -> None:
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="truth-isolation", display_name="Truth", adapter="sim"),
        IndoorWorld(WorldConfig()),
        initial_position_m=Vector3(z=0.5),
        config=SimulationConfig(
            position_noise_std_m=0.0,
            flow_drift_std_m_sqrt_s=0.0,
        ),
    )
    await vehicle._elapse(0.05)
    vehicle.physics.state.position_m = Vector3(x=0.75, z=vehicle.true_position_m.z)
    await vehicle._elapse(0.05)

    assert vehicle.true_position_m.x == pytest.approx(0.75)
    assert vehicle._estimated_position.x == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_flow_drift_is_accumulated_state_and_resets_deterministically() -> None:
    config = SimulationConfig(
        position_noise_std_m=0.0,
        flow_drift_std_m_sqrt_s=0.02,
    )
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="sim01", display_name="Fast", adapter="fast"),
        IndoorWorld(WorldConfig()),
        config=config,
    )
    await vehicle._elapse(2.0)
    drift = vehicle._estimator_drift
    assert abs(drift.x) + abs(drift.y) > 0.0
    first = (drift.x, drift.y)
    vehicle.reset()
    await vehicle._elapse(2.0)
    second = (vehicle._estimator_drift.x, vehicle._estimator_drift.y)
    assert first == second


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fault_start_s", "fault_end_s"),
    [
        (0.5, None),  # takeoff
        (2.2, None),  # hover
        (3.2, None),  # relative move
        (5.2, 5.8),  # landing; finish landing, then fail the run
    ],
)
async def test_localization_loss_changes_outcome_in_every_flight_phase(
    fault_start_s: float,
    fault_end_s: float | None,
) -> None:
    source = """\
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=0.5)
    await drone.move_relative(x_m=0.2, duration_s=2.0, frame="home")
    await drone.hover(duration_s=0.5)
    await drone.land(duration_s=2.0)
"""
    runner, vehicle, mission_id = vehicle_for(
        source,
        fault=FaultWindow(
            fault=FaultType.LOCALIZATION_LOSS,
            start_s=fault_start_s,
            end_s=fault_end_s,
        ),
    )
    result = await runner.run(mission_id, vehicle.identity.vehicle_id)
    assert result.status is MissionStatus.FAILED
    assert result.reason_code == "LOCALIZATION_INVALID"
    telemetry = await vehicle.snapshot()
    assert not telemetry.telemetry.flying
    assert not telemetry.telemetry.armed


@pytest.mark.asyncio
async def test_complete_imu_flow_loss_uses_distinct_emergency_recovery() -> None:
    source = """\
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=10.0)
    await drone.land(duration_s=2.0)
"""
    runner, vehicle, mission_id = vehicle_for(
        source,
        fault=FaultWindow(fault=FaultType.SENSOR_FAILURE, start_s=2.5),
    )
    result = await runner.run(mission_id, vehicle.identity.vehicle_id)
    assert result.status is MissionStatus.FAILED
    assert result.reason_code == "LOCALIZATION_INVALID"
    assert runner.supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.EMERGENCY
    telemetry = await vehicle.snapshot()
    assert not telemetry.telemetry.armed
    assert not telemetry.telemetry.flying


@pytest.mark.asyncio
async def test_qf01_estimator_in_loop_meets_nominal_software_hover_thresholds() -> None:
    source = (ROOT / "missions/qualification/hover_30s.py").read_text()
    runner, vehicle, mission_id = vehicle_for(source)
    result = await runner.run(mission_id, vehicle.identity.vehicle_id)
    assert result.status is MissionStatus.SUCCEEDED

    hover = [
        sample
        for sample in vehicle.telemetry_history
        if sample.telemetry.state is VehicleState.FLYING
        and sample.telemetry.ground_truth_position_m is not None
    ]
    assert len(hover) >= 3000
    truth = [sample.telemetry.ground_truth_position_m for sample in hover]
    assert all(position is not None for position in truth)
    positions = [position for position in truth if position is not None]
    altitude_errors = [position.z - 0.3 for position in positions]
    assert abs(positions[0].z - 0.3) <= 0.03
    assert math.sqrt(sum(error**2 for error in altitude_errors) / len(altitude_errors)) <= 0.02
    assert max(abs(error) for error in altitude_errors) <= 0.05
    origin = positions[0]
    assert (
        max(math.hypot(position.x - origin.x, position.y - origin.y) for position in positions)
        <= 0.05
    )
    assert all(
        later.source_timestamp_s - earlier.source_timestamp_s <= 0.5
        for earlier, later in pairwise(hover)
    )

    saturated_duration_s = 0.0
    maximum_saturated_duration_s = 0.0
    for earlier, later in pairwise(hover):
        motors = earlier.telemetry.motors
        saturated = motors is not None and any(
            reading.command_percent >= 100.0 for reading in motors.readings
        )
        saturated_duration_s = (
            saturated_duration_s + later.source_timestamp_s - earlier.source_timestamp_s
            if saturated
            else 0.0
        )
        maximum_saturated_duration_s = max(maximum_saturated_duration_s, saturated_duration_s)
    assert maximum_saturated_duration_s <= 0.1

    final = await vehicle.snapshot()
    assert final.telemetry.ground_truth_position_m is not None
    assert final.telemetry.ground_truth_position_m.z <= 0.01
    assert not final.telemetry.armed
    assert not final.telemetry.flying
    assert final.telemetry.motors is not None
    assert all(
        reading.command_percent == reading.thrust_n == reading.current_a == 0.0
        for reading in final.telemetry.motors.readings
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fault", "expected_status"),
    [
        (FaultType.RANGE_STALE, RangeStatus.STALE),
        (FaultType.RANGE_UNAVAILABLE, RangeStatus.UNAVAILABLE),
    ],
)
async def test_stale_and_unavailable_ranges_are_explicit_and_fail_closed(
    fault: FaultType,
    expected_status: RangeStatus,
) -> None:
    source = (ROOT / "missions/qualification/range_approach_stop.py").read_text()
    runner, vehicle, mission_id = vehicle_for(
        source,
        fault=FaultWindow(fault=fault, start_s=0.0),
    )
    result = await runner.run(mission_id, vehicle.identity.vehicle_id)
    assert result.status is MissionStatus.FAILED
    assert result.reason_code == "TELEMETRY_STALE"
    ranges = (await vehicle.snapshot()).telemetry.ranges
    assert ranges is not None
    assert set(ranges.statuses.values()) == {expected_status}


@pytest.mark.asyncio
async def test_stale_telemetry_mid_hover_escalates_when_landing_cannot_be_observed() -> None:
    source = """\
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=5.0)
    await drone.land(duration_s=2.0)
"""
    runner, vehicle, mission_id = vehicle_for(
        source,
        fault=FaultWindow(fault=FaultType.STALE_TELEMETRY, start_s=2.5),
    )
    result = await runner.run(mission_id, vehicle.identity.vehicle_id)
    session = runner.supervisor.session(vehicle.identity.vehicle_id)
    assert result.status is MissionStatus.FAILED
    assert result.reason_code == "TELEMETRY_STALE"
    assert session.state is VehicleState.EMERGENCY
    assert session.lease is None
    assert session.active_execute_task is None
    assert not vehicle._flying
    assert not vehicle._armed
    assert all(
        motor.command == motor.thrust_n == motor.current_a == 0.0
        for motor in vehicle.physics.state.motors
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("roll_deg", "pitch_deg", "velocity_x_m_s"),
    [
        (5.0, 0.0, 0.1),
        (-5.0, 0.0, 0.2),
        (10.0, 0.0, 0.1),
        (-10.0, 0.0, 0.2),
        (0.0, 5.0, 0.1),
        (0.0, -5.0, 0.2),
        (0.0, 10.0, 0.1),
        (0.0, -10.0, 0.2),
    ],
)
async def test_initial_attitude_velocity_and_force_disturbance_matrix_is_bounded(
    roll_deg: float,
    pitch_deg: float,
    velocity_x_m_s: float,
) -> None:
    disturbance = DisturbanceConfig(
        initial_roll_rad=math.radians(roll_deg),
        initial_pitch_rad=math.radians(pitch_deg),
        initial_velocity_m_s=Vector3(x=velocity_x_m_s),
        force_impulse_n_s=Vector3(x=0.001),
        force_impulse_at_s=1.0,
    )
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="disturbance", display_name="Disturbance", adapter="opaque"),
        IndoorWorld(WorldConfig()),
        config=SimulationConfig(disturbance=disturbance),
    )
    initial = vehicle.physics.state.attitude.euler()
    assert initial.roll_rad == pytest.approx(math.radians(roll_deg))
    assert initial.pitch_rad == pytest.approx(math.radians(pitch_deg))
    await vehicle._elapse(1.1)
    assert vehicle._force_impulse_applied
    assert all(
        math.isfinite(value)
        for value in (
            *vehicle.physics.state.position_m.model_dump().values(),
            *vehicle.physics.state.velocity_m_s.model_dump().values(),
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mass_scale", "thrust_scale", "actuator_scale"),
    [
        (0.9, 1.0, 1.0),
        (1.1, 1.0, 1.0),
        (1.0, 0.9, 1.0),
        (1.0, 1.1, 1.0),
        (1.0, 1.0, 0.9),
        (1.0, 1.0, 1.1),
    ],
)
async def test_plant_controller_mismatch_matrix_remains_explicit_and_safe(
    mass_scale: float,
    thrust_scale: float,
    actuator_scale: float,
) -> None:
    nominal = PhysicsModelConfig()
    physics = nominal.model_copy(
        update={
            "mass_kg": nominal.mass_kg * mass_scale,
            "max_motor_thrust_n": nominal.max_motor_thrust_n * thrust_scale,
            "motor_time_constant_s": nominal.motor_time_constant_s * actuator_scale,
        }
    )
    config = SimulationConfig(
        physics=physics,
        controller_nominal_mass_kg=nominal.total_mass_kg,
        controller_nominal_max_motor_thrust_n=nominal.max_motor_thrust_n,
    )
    source = """\
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=2.0)
    await drone.land(duration_s=2.0)
"""
    record = parse_python_mission(filename="mismatch.py", name="mismatch", source=source)
    registry = MissionRegistry()
    registry.register(ScriptMission(record))
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="mismatch", display_name="Mismatch", adapter="opaque"),
        IndoorWorld(WorldConfig()),
        config=config,
    )
    supervisor = SafetySupervisor()
    supervisor.register_vehicle(vehicle)
    result = await MissionRunner(supervisor, registry).run(record.mission_id, "mismatch")
    assert result.status is MissionStatus.SUCCEEDED
    assert not vehicle._armed
    assert not vehicle._flying


@pytest.mark.asyncio
async def test_surface_and_lighting_classes_change_modeled_flow_quality_only() -> None:
    baseline = SimulatedVehicle(
        VehicleIdentity(vehicle_id="baseline", display_name="Baseline", adapter="opaque"),
        IndoorWorld(WorldConfig()),
        initial_position_m=Vector3(z=0.3),
    )
    degraded = SimulatedVehicle(
        VehicleIdentity(vehicle_id="degraded", display_name="Degraded", adapter="opaque"),
        IndoorWorld(WorldConfig()),
        initial_position_m=Vector3(z=0.3),
        config=SimulationConfig(
            flow_environment=FlowEnvironmentConfig(
                surface=FlowSurfaceClass.LOW_TEXTURE,
                lighting=LightingClass.LOW,
            )
        ),
    )
    baseline_flow = (await baseline.snapshot()).telemetry.flow
    degraded_flow = (await degraded.snapshot()).telemetry.flow
    assert baseline_flow is not None and degraded_flow is not None
    assert degraded_flow.quality_percent == pytest.approx(
        baseline_flow.quality_percent * 0.55 * 0.6
    )


@pytest.mark.asyncio
async def test_snapshot_polling_cannot_change_estimator_or_physics_outcome() -> None:
    first = SimulatedVehicle(
        VehicleIdentity(vehicle_id="first", display_name="First", adapter="opaque"),
        IndoorWorld(WorldConfig()),
    )
    second = SimulatedVehicle(
        VehicleIdentity(vehicle_id="second", display_name="Second", adapter="opaque"),
        IndoorWorld(WorldConfig()),
    )
    for _ in range(100):
        await first.snapshot()
    await first._elapse(2.0)
    await second._elapse(2.0)
    assert first.physics.state.position_m == second.physics.state.position_m
    assert first.physics.state.velocity_m_s == second.physics.state.velocity_m_s
    assert first._estimated_position == second._estimated_position
    assert first._estimator_drift == second._estimator_drift


@pytest.mark.asyncio
async def test_estimator_bias_clipping_and_latency_are_stateful_and_explicit() -> None:
    clipped = SimulatedVehicle(
        VehicleIdentity(vehicle_id="clipped", display_name="Clipped", adapter="opaque"),
        IndoorWorld(WorldConfig()),
        config=SimulationConfig(
            position_noise_std_m=0.0,
            flow_drift_std_m_sqrt_s=0.0,
            position_bias_m=Vector3(x=0.2, y=-0.2),
            estimator_error_clip_m=0.05,
        ),
    )
    await clipped._elapse(0.02)
    assert clipped._estimated_position.x == pytest.approx(0.05)
    assert clipped._estimated_position.y == pytest.approx(-0.05)

    delayed = SimulatedVehicle(
        VehicleIdentity(vehicle_id="delayed", display_name="Delayed", adapter="opaque"),
        IndoorWorld(WorldConfig()),
        initial_position_m=Vector3(z=1.0),
        config=SimulationConfig(
            position_noise_std_m=0.0,
            flow_drift_std_m_sqrt_s=0.0,
            estimator_latency_s=0.2,
        ),
    )
    await delayed._elapse(0.1)
    delayed.physics.state.velocity_m_s = Vector3(x=0.5)
    await delayed._elapse(0.05)
    assert delayed._estimated_position.x == pytest.approx(0.0)
    await delayed._elapse(0.25)
    assert delayed._estimated_position.x == pytest.approx(0.05, abs=0.01)


@pytest.mark.asyncio
async def test_range_no_hit_and_clipping_are_not_reported_as_valid() -> None:
    no_hit = SimulatedVehicle(
        VehicleIdentity(vehicle_id="no-hit", display_name="No hit", adapter="opaque"),
        IndoorWorld(WorldConfig(width_m=20.0, depth_m=20.0, height_m=10.0)),
        initial_position_m=Vector3(z=0.3),
        config=SimulationConfig(range_noise_std_m=0.0, max_range_m=1.0),
    )
    no_hit_ranges = (await no_hit.snapshot()).telemetry.ranges
    assert no_hit_ranges is not None
    assert no_hit_ranges.statuses["front"] is RangeStatus.NO_HIT
    assert no_hit_ranges.statuses["up"] is RangeStatus.NO_HIT
    assert no_hit_ranges.statuses["down"] is RangeStatus.VALID

    clipped = SimulatedVehicle(
        VehicleIdentity(vehicle_id="range-clip", display_name="Range clip", adapter="opaque"),
        IndoorWorld(WorldConfig(width_m=2.0, depth_m=2.0, height_m=2.0)),
        initial_position_m=Vector3(z=0.3),
        config=SimulationConfig(range_noise_std_m=10.0),
    )
    clipped_ranges = (await clipped.snapshot()).telemetry.ranges
    assert clipped_ranges is not None
    assert RangeStatus.CLIPPED in clipped_ranges.statuses.values()
