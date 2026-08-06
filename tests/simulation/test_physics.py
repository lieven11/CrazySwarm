from __future__ import annotations

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.simulation.physics import PhysicsModelConfig, SixDofPhysics


def test_six_dof_motor_and_battery_model_is_deterministic() -> None:
    config = PhysicsModelConfig()
    first = SixDofPhysics(config, position_m=Vector3(z=0.3))
    second = SixDofPhysics(config, position_m=Vector3(z=0.3))
    commands = (0.42, 0.64, 0.42, 0.20)
    for _ in range(80):
        first.step(commands, 0.01)
        second.step(commands, 0.01)
    assert first.state == second.state
    assert abs(first.state.attitude.euler().roll_rad) > 0.01
    assert first.state.battery_current_a > config.battery_idle_current_a
    assert first.state.battery_state_of_charge < 1.0
    assert first.state.battery_voltage_v < config.battery_full_voltage_v


def test_zero_thrust_applies_configured_gravity() -> None:
    config = PhysicsModelConfig()
    physics = SixDofPhysics(config, position_m=Vector3(z=0.5))
    physics.step((0.0, 0.0, 0.0, 0.0), 0.01)
    assert physics.state.acceleration_world_m_s2.z == -config.gravity_m_s2
    assert physics.state.velocity_m_s.z < 0.0
    assert physics.state.position_m.z < 0.5


def test_asymmetric_motor_inputs_have_expected_torque_directions() -> None:
    config = PhysicsModelConfig()
    cases = (
        ((0.4, 0.6, 0.4, 0.2), "x"),
        ((0.2, 0.4, 0.6, 0.4), "y"),
        ((0.6, 0.2, 0.6, 0.2), "z"),
    )
    for commands, axis in cases:
        physics = SixDofPhysics(config, position_m=Vector3(z=0.5))
        for _ in range(10):
            physics.step(commands, 0.01)
        assert getattr(physics.state.angular_velocity_body_rad_s, axis) > 0.0
