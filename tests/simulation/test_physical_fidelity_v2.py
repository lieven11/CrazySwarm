from __future__ import annotations

import math

import pytest

from crazyswarm_app.domain.models import Vector3, VehicleIdentity
from crazyswarm_app.domain.telemetry import FlowStatus
from crazyswarm_app.simulation.calibration import (
    PhysicalCalibrationArtifact,
    PhysicalCalibrationUpdates,
    import_physical_calibration,
)
from crazyswarm_app.simulation.faults import FaultInjector, FaultType, FaultWindow
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.physics import PhysicsModelConfig, SixDofPhysics
from crazyswarm_app.simulation.powertrain import BatteryCutoffReason, PowertrainModel
from crazyswarm_app.simulation.sensors import FlowModelConfig, ImuModelConfig, RangeModelConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig


def _run_collective(
    state_of_charge_percent: float,
    command: float,
    *,
    duration_s: float = 2.0,
) -> SixDofPhysics:
    physics = SixDofPhysics(
        PhysicsModelConfig(),
        position_m=Vector3(z=2.0),
        battery_percent=state_of_charge_percent,
    )
    dt = 0.01
    for _ in range(round(duration_s / dt)):
        physics.step((command, command, command, command), dt)
    return physics


def test_v2_is_explicit_and_v1_replay_plant_remains_selectable() -> None:
    current = PhysicsModelConfig()
    legacy = PhysicsModelConfig.legacy_v1()

    assert current.model_version == "2.0.0"
    assert current.powertrain_model is PowertrainModel.BATTERY_COUPLED_V2
    assert current.rotor_layout == "X"
    assert current.parameter_source == "CONFIGURED_UNQUALIFIED"
    assert current.parameter_provenance
    assert legacy.model_version == "1.0.0"
    assert legacy.powertrain_model is PowertrainModel.LEGACY_UNCOUPLED_V1
    assert legacy.rotor_layout == "PLUS_LEGACY"


def test_v2_rejects_legacy_energy_drain_and_invalid_physical_contracts() -> None:
    with pytest.raises(ValueError, match="legacy-v1-only"):
        SimulationConfig(battery_flight_drain_percent_s=0.1)
    legacy = SimulationConfig(
        physics=PhysicsModelConfig.legacy_v1(),
        battery_flight_drain_percent_s=0.1,
    )
    assert legacy.battery_flight_drain_percent_s == 0.1

    with pytest.raises(ValueError, match="triangle inequality"):
        PhysicsModelConfig(inertia_z_kg_m2=1.0)
    with pytest.raises(ValueError, match="provenance"):
        PhysicsModelConfig(parameter_provenance=())
    positions = PhysicsModelConfig().rotor_positions_body_m
    with pytest.raises(ValueError, match="rotor positions must be unique"):
        PhysicsModelConfig(rotor_positions_body_m=(positions[0], positions[0], *positions[2:]))


def test_calibration_import_creates_new_unqualified_version_without_mutating_default() -> None:
    base = PhysicsModelConfig()
    base_sha256 = SimulationConfig(physics=base).vehicle_parameters().sha256
    artifact = PhysicalCalibrationArtifact(
        calibration_id="bench-import-example",
        base_configuration_sha256=base_sha256,
        source_id="bench-dataset-example",
        source_url="evidence://bench/example.json",
        source_version="1",
        hardware_configuration="selected-aircraft-placeholder",
        uncertainty="Example software-path evidence; no physical qualification claim.",
        updates=PhysicalCalibrationUpdates(
            battery_internal_resistance_ohm=0.08,
            motor_time_constant_s=0.04,
        ),
    )
    imported = import_physical_calibration(artifact, base=base)

    assert base.model_version == "2.0.0"
    assert base.battery_internal_resistance_ohm == 0.075
    assert imported.model_version.startswith("2.0.0-cal.")
    assert imported.parameter_source == "CONFIGURED_UNQUALIFIED"
    assert imported.imported_configuration_sha256 != base_sha256
    imported_sources = {
        name: source.source_id
        for source in imported.physics.parameter_provenance
        for name in source.parameter_names
    }
    assert imported_sources["battery_internal_resistance_ohm"] == "bench-dataset-example"

    with pytest.raises(ValueError, match="does not match"):
        import_physical_calibration(
            artifact.model_copy(update={"base_configuration_sha256": "0" * 64}),
            base=base,
        )


def test_low_soc_compensation_uses_more_pwm_and_has_less_maximum_authority() -> None:
    config = PhysicsModelConfig()
    hover_command = config.total_mass_kg * config.gravity_m_s2 / (4.0 * config.max_motor_thrust_n)
    full_hover = _run_collective(100.0, hover_command)
    low_hover = _run_collective(5.0, hover_command)

    assert low_hover.state.motors[0].applied_pwm > full_hover.state.motors[0].applied_pwm
    assert low_hover.state.battery_current_a > full_hover.state.battery_current_a
    assert sum(motor.thrust_n for motor in low_hover.state.motors) == pytest.approx(
        sum(motor.thrust_n for motor in full_hover.state.motors),
        rel=0.01,
    )

    full_collective = _run_collective(100.0, 1.0)
    low_collective = _run_collective(5.0, 1.0)
    assert sum(motor.thrust_n for motor in low_collective.state.motors) < sum(
        motor.thrust_n for motor in full_collective.state.motors
    )
    assert all(motor.saturated for motor in low_collective.state.motors)
    assert low_collective.state.battery_current_a <= config.battery_max_current_a + 1e-7


def test_zero_soc_is_an_authoritative_cutoff_and_cannot_sustain_thrust() -> None:
    depleted = _run_collective(0.0, 1.0, duration_s=0.5)
    assert depleted.state.battery_cutoff_active is True
    assert depleted.state.battery_cutoff_reason is BatteryCutoffReason.DEPLETED
    assert all(motor.applied_pwm == 0.0 for motor in depleted.state.motors)
    assert all(motor.thrust_n == pytest.approx(0.0, abs=1e-9) for motor in depleted.state.motors)
    assert depleted.state.position_m.z < 2.0


def test_invalid_cell_state_fails_closed_without_nonfinite_dynamics() -> None:
    physics = SixDofPhysics(PhysicsModelConfig(), position_m=Vector3(z=1.0))
    physics.state.battery_filtered_voltage_v = math.nan
    physics.step((1.0, 1.0, 1.0, 1.0), 0.01)
    assert physics.state.battery_cutoff_active is True
    assert physics.state.battery_cutoff_reason is BatteryCutoffReason.INVALID_CELL_STATE
    assert all(motor.applied_pwm == 0.0 for motor in physics.state.motors)


def test_undervoltage_cutoff_uses_persistence_not_a_single_crossing() -> None:
    config = PhysicsModelConfig(
        battery_cutoff_voltage_v=3.3,
        battery_cutoff_persistence_s=0.05,
    )
    physics = SixDofPhysics(config, position_m=Vector3(z=1.0), battery_percent=5.0)
    for _ in range(4):
        physics.step((1.0, 1.0, 1.0, 1.0), 0.01)
    assert physics.state.battery_voltage_v < config.battery_cutoff_voltage_v
    assert physics.state.battery_cutoff_active is False
    physics.step((1.0, 1.0, 1.0, 1.0), 0.01)
    assert physics.state.battery_cutoff_active is True
    assert physics.state.battery_cutoff_reason is BatteryCutoffReason.UNDERVOLTAGE


@pytest.mark.parametrize(
    ("motor_index", "expected_signs"),
    (
        (0, (-1, -1, -1)),
        (1, (-1, 1, 1)),
        (2, (1, 1, -1)),
        (3, (1, -1, 1)),
    ),
)
def test_each_x_layout_rotor_has_firmware_force_torque_signs(
    motor_index: int,
    expected_signs: tuple[int, int, int],
) -> None:
    commands = [0.0, 0.0, 0.0, 0.0]
    commands[motor_index] = 0.7
    physics = SixDofPhysics(PhysicsModelConfig(), position_m=Vector3(z=1.0))
    physics.step(tuple(commands), 0.01)  # type: ignore[arg-type]
    omega = physics.state.angular_velocity_body_rad_s
    for value, sign in zip((omega.x, omega.y, omega.z), expected_signs, strict=True):
        assert math.copysign(1.0, value) == sign


def test_payload_position_changes_combined_center_of_mass_and_inertia_response() -> None:
    config = PhysicsModelConfig(
        payload_mass_kg=0.01,
        payload_position_body_m=Vector3(x=0.02),
    )
    assert config.combined_center_of_mass_body_m.x > 0.0
    assert config.total_inertia_y_kg_m2 > config.inertia_y_kg_m2
    assert config.total_inertia_z_kg_m2 > config.inertia_z_kg_m2

    physics = SixDofPhysics(config, position_m=Vector3(z=1.0))
    physics.step((0.7, 0.7, 0.7, 0.7), 0.01)
    assert physics.state.angular_velocity_body_rad_s.y > 0.0


def test_per_motor_variation_and_runtime_actuator_loss_are_plant_visible() -> None:
    varied = PhysicsModelConfig(
        motor_thrust_scales=(0.8, 1.0, 1.0, 1.0),
        motor_current_scales=(0.9, 1.0, 1.0, 1.0),
        motor_time_constant_scales=(1.2, 1.0, 1.0, 1.0),
    )
    first = SixDofPhysics(varied, position_m=Vector3(z=1.0))
    second = SixDofPhysics(varied, position_m=Vector3(z=1.0))
    for _ in range(100):
        first.step((0.7, 0.7, 0.7, 0.7), 0.01)
        second.step((0.7, 0.7, 0.7, 0.7), 0.01)
    assert first.state == second.state
    assert first.state.motors[0].thrust_n < first.state.motors[1].thrust_n

    failed = SixDofPhysics(PhysicsModelConfig(), position_m=Vector3(z=1.0))
    for _ in range(100):
        failed.step(
            (0.7, 0.7, 0.7, 0.7),
            0.01,
            actuator_health_scales=(0.0, 1.0, 1.0, 1.0),
        )
    assert failed.state.motors[0].health_scale == 0.0
    assert failed.state.motors[0].available_thrust_n == 0.0
    assert failed.state.motors[0].thrust_n < failed.state.motors[1].thrust_n
    assert failed.state.motors[0].saturated is True


@pytest.mark.asyncio
async def test_actuator_fault_schedule_is_identity_scoped_and_evidence_visible() -> None:
    faults = FaultInjector(
        (
            FaultWindow(
                fault=FaultType.ACTUATOR_DEGRADATION,
                start_s=0.0,
                motor_index=0,
                actuator_health_scale=0.4,
            ),
        )
    )
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="motor-fault", display_name="motor-fault", adapter="sim"),
        IndoorWorld(WorldConfig()),
        faults=faults,
        initial_position_m=Vector3(z=1.0),
    )
    for _ in range(25):
        await vehicle._step(0.01, motor_commands=(0.7, 0.7, 0.7, 0.7))
    telemetry = (await vehicle.snapshot()).telemetry
    assert telemetry.motors is not None
    assert telemetry.motors.readings[0].health_percent == 40.0
    assert telemetry.motors.readings[0].faulted is True
    assert telemetry.motors.readings[1].faulted is False
    assert "ACTUATOR_DEGRADED_M1" in telemetry.faults


def test_body_drag_dissipates_energy_and_optional_ground_effect_is_bounded() -> None:
    drag = PhysicsModelConfig(
        linear_drag_body_scale=Vector3(x=2.0, y=1.0, z=0.5),
        quadratic_drag_body_n_s2_m2=Vector3(x=0.02, y=0.01, z=0.005),
    )
    physics = SixDofPhysics(
        drag,
        position_m=Vector3(z=2.0),
        initial_velocity_m_s=Vector3(x=1.0, y=-0.5),
    )
    initial_speed_squared = physics.state.velocity_m_s.x**2 + physics.state.velocity_m_s.y**2
    physics.step((0.0, 0.0, 0.0, 0.0), 0.01)
    final_speed_squared = physics.state.velocity_m_s.x**2 + physics.state.velocity_m_s.y**2
    assert final_speed_squared < initial_speed_squared

    effect = PhysicsModelConfig(
        ground_effect_strength=0.2,
        ground_effect_maximum_multiplier=1.15,
    )
    near = SixDofPhysics(effect, position_m=Vector3(z=0.01))
    far = SixDofPhysics(effect, position_m=Vector3(z=1.0))
    near.step((0.7, 0.7, 0.7, 0.7), 0.01)
    far.step((0.7, 0.7, 0.7, 0.7), 0.01)
    assert near.state.acceleration_world_m_s2.z > far.state.acceleration_world_m_s2.z


@pytest.mark.asyncio
async def test_imu_sample_clock_and_snapshot_polling_are_independent() -> None:
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="imu01", display_name="imu01", adapter="sim"),
        IndoorWorld(WorldConfig()),
        config=SimulationConfig(
            fixed_step_s=0.01,
            imu=ImuModelConfig(
                sample_rate_hz=10.0,
                acceleration_noise_std_m_s2=Vector3(x=0.01, y=0.01, z=0.01),
            ),
        ),
        initial_position_m=Vector3(z=1.0),
    )
    initial = await vehicle.snapshot()
    repeated = await vehicle.snapshot()
    assert initial.telemetry.imu == repeated.telemetry.imu
    assert initial.telemetry.imu is not None
    assert initial.telemetry.imu.source_timestamp_s == 0.0

    await vehicle._step(0.01, motor_commands=(0.0, 0.0, 0.0, 0.0))
    held = await vehicle.snapshot()
    assert held.telemetry.imu is not None
    assert held.telemetry.imu.source_timestamp_s == 0.0
    for _ in range(9):
        await vehicle._step(0.01, motor_commands=(0.0, 0.0, 0.0, 0.0))
    refreshed = await vehicle.snapshot()
    assert refreshed.telemetry.imu is not None
    assert refreshed.telemetry.imu.source_timestamp_s == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_flow_and_range_have_independent_held_sample_clocks() -> None:
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="sampled", display_name="sampled", adapter="sim"),
        IndoorWorld(WorldConfig()),
        config=SimulationConfig(
            flow=FlowModelConfig(sample_rate_hz=10.0),
            range_sensor=RangeModelConfig(sample_rate_hz=5.0),
            range_noise_std_m=0.0,
        ),
        initial_position_m=Vector3(z=0.3),
    )
    for _ in range(5):
        await vehicle._step(0.01, motor_commands=(0.0, 0.0, 0.0, 0.0))
    held = (await vehicle.snapshot()).telemetry
    assert held.flow is not None and held.ranges is not None
    assert held.flow.source_timestamp_s == 0.0
    assert held.ranges.source_timestamp_s == 0.0

    for _ in range(5):
        await vehicle._step(0.01, motor_commands=(0.0, 0.0, 0.0, 0.0))
    flow_refreshed = (await vehicle.snapshot()).telemetry
    assert flow_refreshed.flow is not None and flow_refreshed.ranges is not None
    assert flow_refreshed.flow.source_timestamp_s == pytest.approx(0.1)
    assert flow_refreshed.ranges.source_timestamp_s == 0.0

    for _ in range(10):
        await vehicle._step(0.01, motor_commands=(0.0, 0.0, 0.0, 0.0))
    range_refreshed = (await vehicle.snapshot()).telemetry.ranges
    assert range_refreshed is not None
    assert range_refreshed.source_timestamp_s == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_flow_quality_dropout_and_mounting_error_reach_estimator() -> None:
    unavailable = SimulatedVehicle(
        VehicleIdentity(vehicle_id="flow-off", display_name="flow-off", adapter="sim"),
        IndoorWorld(WorldConfig()),
        config=SimulationConfig(flow=FlowModelConfig(dropout_probability=1.0)),
        initial_position_m=Vector3(z=0.3),
    )
    unavailable_flow = (await unavailable.snapshot()).telemetry.flow
    assert unavailable_flow is not None
    assert unavailable_flow.status is FlowStatus.UNAVAILABLE
    assert unavailable_flow.velocity_body_m_s is None

    mounted = SimulatedVehicle(
        VehicleIdentity(vehicle_id="flow-mount", display_name="flow-mount", adapter="sim"),
        IndoorWorld(WorldConfig()),
        config=SimulationConfig(
            flow=FlowModelConfig(mounting_yaw_rad=math.pi / 2.0),
            position_noise_std_m=0.0,
            flow_drift_std_m_sqrt_s=0.0,
        ),
        initial_position_m=Vector3(z=0.3),
    )
    mounted.physics.state.velocity_m_s = Vector3(x=0.2)
    await mounted._step(0.01, motor_commands=(0.0, 0.0, 0.0, 0.0))
    assert mounted._estimated_velocity.y < -0.1


@pytest.mark.asyncio
async def test_configured_gyro_bias_reaches_estimator_controller_state() -> None:
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="imu02", display_name="imu02", adapter="sim"),
        IndoorWorld(WorldConfig()),
        config=SimulationConfig(
            imu=ImuModelConfig(angular_velocity_bias_rad_s=Vector3(z=0.1)),
        ),
        initial_position_m=Vector3(z=1.0),
    )
    await vehicle._step(0.01, motor_commands=(0.0, 0.0, 0.0, 0.0))
    sample = await vehicle.snapshot()
    assert sample.telemetry.imu is not None
    assert sample.telemetry.imu.angular_velocity_body_rad_s.z == pytest.approx(0.1)
    assert vehicle._estimated_angular_velocity.z == pytest.approx(0.1)
