from __future__ import annotations

import math
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.domain.models import EulerAttitude, Vector3


class PhysicsModelConfig(BaseModel):
    """Versioned, deterministic physical assumptions for the simulated Crazyflie."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = "crazyflie-6dof"
    model_version: str = "1.0.0"
    parameter_source: str = "CONFIGURED_UNQUALIFIED"
    gravity_m_s2: float = Field(default=9.80665, gt=0.0)
    mass_kg: float = Field(default=0.032, gt=0.0)
    payload_mass_kg: float = Field(default=0.0, ge=0.0)
    center_of_mass_body_m: Vector3 = Field(default_factory=Vector3)
    inertia_x_kg_m2: float = Field(default=1.43e-5, gt=0.0)
    inertia_y_kg_m2: float = Field(default=1.43e-5, gt=0.0)
    inertia_z_kg_m2: float = Field(default=2.89e-5, gt=0.0)
    arm_length_m: float = Field(default=0.046, gt=0.0)
    max_motor_thrust_n: float = Field(default=0.15, gt=0.0)
    thrust_curve_exponent: float = Field(default=1.0, gt=0.0)
    motor_time_constant_s: float = Field(default=0.035, gt=0.0)
    yaw_moment_per_thrust_m: float = Field(default=0.006, gt=0.0)
    linear_drag_n_s_m: float = Field(default=0.018, ge=0.0)
    angular_drag_n_m_s: float = Field(default=2.5e-5, ge=0.0)
    battery_capacity_ah: float = Field(default=0.25, gt=0.0)
    battery_full_voltage_v: float = Field(default=4.2, gt=0.0)
    battery_empty_voltage_v: float = Field(default=3.2, gt=0.0)
    battery_cutoff_voltage_v: float = Field(default=3.0, gt=0.0)
    battery_internal_resistance_ohm: float = Field(default=0.075, ge=0.0)
    battery_idle_current_a: float = Field(default=0.08, ge=0.0)
    motor_max_current_a: float = Field(default=1.2, gt=0.0)
    maximum_tilt_rad: float = Field(default=0.55, gt=0.0, lt=math.pi / 2.0)

    @property
    def total_mass_kg(self) -> float:
        return self.mass_kg + self.payload_mass_kg

    @model_validator(mode="after")
    def validate_thrust_and_voltage(self) -> PhysicsModelConfig:
        if 4.0 * self.max_motor_thrust_n <= self.total_mass_kg * self.gravity_m_s2:
            raise ValueError("configured motors cannot produce hover thrust")
        if self.battery_empty_voltage_v >= self.battery_full_voltage_v:
            raise ValueError("battery empty voltage must be below full voltage")
        if self.battery_cutoff_voltage_v >= self.battery_full_voltage_v:
            raise ValueError("battery cutoff voltage must be below full voltage")
        return self


@dataclass(frozen=True, slots=True)
class Quaternion:
    w: float = 1.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    @classmethod
    def from_yaw(cls, yaw_rad: float) -> Quaternion:
        return cls(w=math.cos(yaw_rad / 2.0), z=math.sin(yaw_rad / 2.0))

    def normalized(self) -> Quaternion:
        norm = math.sqrt(self.w**2 + self.x**2 + self.y**2 + self.z**2)
        if norm <= 1e-15:
            return Quaternion()
        return Quaternion(self.w / norm, self.x / norm, self.y / norm, self.z / norm)

    def rotate_body_to_world(self, value: Vector3) -> Vector3:
        # Quaternion rotation expanded to avoid allocating intermediate quaternions.
        xx, yy, zz = self.x * self.x, self.y * self.y, self.z * self.z
        xy, xz, yz = self.x * self.y, self.x * self.z, self.y * self.z
        wx, wy, wz = self.w * self.x, self.w * self.y, self.w * self.z
        return Vector3(
            x=(1 - 2 * (yy + zz)) * value.x + 2 * (xy - wz) * value.y + 2 * (xz + wy) * value.z,
            y=2 * (xy + wz) * value.x + (1 - 2 * (xx + zz)) * value.y + 2 * (yz - wx) * value.z,
            z=2 * (xz - wy) * value.x + 2 * (yz + wx) * value.y + (1 - 2 * (xx + yy)) * value.z,
        )

    def rotate_world_to_body(self, value: Vector3) -> Vector3:
        return Quaternion(self.w, -self.x, -self.y, -self.z).rotate_body_to_world(value)

    def integrate(self, angular_velocity_body_rad_s: Vector3, dt: float) -> Quaternion:
        wx, wy, wz = (
            angular_velocity_body_rad_s.x,
            angular_velocity_body_rad_s.y,
            angular_velocity_body_rad_s.z,
        )
        return Quaternion(
            w=self.w + 0.5 * (-self.x * wx - self.y * wy - self.z * wz) * dt,
            x=self.x + 0.5 * (self.w * wx + self.y * wz - self.z * wy) * dt,
            y=self.y + 0.5 * (self.w * wy + self.z * wx - self.x * wz) * dt,
            z=self.z + 0.5 * (self.w * wz + self.x * wy - self.y * wx) * dt,
        ).normalized()

    def euler(self) -> EulerAttitude:
        sin_roll = 2.0 * (self.w * self.x + self.y * self.z)
        cos_roll = 1.0 - 2.0 * (self.x**2 + self.y**2)
        sin_pitch = max(-1.0, min(1.0, 2.0 * (self.w * self.y - self.z * self.x)))
        sin_yaw = 2.0 * (self.w * self.z + self.x * self.y)
        cos_yaw = 1.0 - 2.0 * (self.y**2 + self.z**2)
        return EulerAttitude(
            roll_rad=math.atan2(sin_roll, cos_roll),
            pitch_rad=math.asin(sin_pitch),
            yaw_rad=math.atan2(sin_yaw, cos_yaw),
        )


@dataclass(slots=True)
class MotorState:
    command: float = 0.0
    thrust_n: float = 0.0
    current_a: float = 0.0


@dataclass(slots=True)
class PhysicsState:
    position_m: Vector3 = field(default_factory=Vector3)
    velocity_m_s: Vector3 = field(default_factory=Vector3)
    acceleration_world_m_s2: Vector3 = field(default_factory=Vector3)
    attitude: Quaternion = field(default_factory=Quaternion)
    angular_velocity_body_rad_s: Vector3 = field(default_factory=Vector3)
    battery_state_of_charge: float = 1.0
    battery_voltage_v: float = 4.2
    battery_current_a: float = 0.0
    motors: list[MotorState] = field(default_factory=lambda: [MotorState() for _ in range(4)])


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _wrap_angle(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


class SixDofPhysics:
    def __init__(
        self,
        config: PhysicsModelConfig,
        *,
        position_m: Vector3 | None = None,
        yaw_rad: float = 0.0,
        battery_percent: float = 100.0,
    ) -> None:
        self.config = config
        self.state = PhysicsState()
        self.reset(position_m or Vector3(), yaw_rad, battery_percent)

    def reset(self, position_m: Vector3, yaw_rad: float, battery_percent: float) -> None:
        soc = _clamp(battery_percent / 100.0, 0.0, 1.0)
        voltage = self.config.battery_empty_voltage_v + soc * (
            self.config.battery_full_voltage_v - self.config.battery_empty_voltage_v
        )
        self.state = PhysicsState(
            position_m=position_m,
            attitude=Quaternion.from_yaw(yaw_rad),
            battery_state_of_charge=soc,
            battery_voltage_v=voltage,
        )

    def step(
        self,
        motor_commands: tuple[float, float, float, float],
        dt: float,
        *,
        additional_current_a: float = 0.0,
    ) -> None:
        config = self.config
        state = self.state
        if state.battery_voltage_v <= config.battery_cutoff_voltage_v:
            motor_commands = (0.0, 0.0, 0.0, 0.0)
        alpha = 1.0 - math.exp(-dt / config.motor_time_constant_s)
        for motor, command in zip(state.motors, motor_commands, strict=True):
            motor.command = _clamp(command, 0.0, 1.0)
            target_thrust = motor.command**config.thrust_curve_exponent * config.max_motor_thrust_n
            motor.thrust_n += (target_thrust - motor.thrust_n) * alpha
            motor.current_a = (
                motor.thrust_n / config.max_motor_thrust_n * config.motor_max_current_a
            )

        total_thrust = sum(motor.thrust_n for motor in state.motors)
        m1, m2, m3, m4 = (motor.thrust_n for motor in state.motors)
        torque = Vector3(
            x=config.arm_length_m * (m2 - m4),
            y=config.arm_length_m * (m3 - m1),
            z=config.yaw_moment_per_thrust_m * (m1 - m2 + m3 - m4),
        )
        omega = state.angular_velocity_body_rad_s
        angular_acceleration = Vector3(
            x=(
                torque.x
                - (config.inertia_z_kg_m2 - config.inertia_y_kg_m2) * omega.y * omega.z
                - config.angular_drag_n_m_s * omega.x
            )
            / config.inertia_x_kg_m2,
            y=(
                torque.y
                - (config.inertia_x_kg_m2 - config.inertia_z_kg_m2) * omega.z * omega.x
                - config.angular_drag_n_m_s * omega.y
            )
            / config.inertia_y_kg_m2,
            z=(
                torque.z
                - (config.inertia_y_kg_m2 - config.inertia_x_kg_m2) * omega.x * omega.y
                - config.angular_drag_n_m_s * omega.z
            )
            / config.inertia_z_kg_m2,
        )
        state.angular_velocity_body_rad_s = Vector3(
            x=omega.x + angular_acceleration.x * dt,
            y=omega.y + angular_acceleration.y * dt,
            z=omega.z + angular_acceleration.z * dt,
        )
        state.attitude = state.attitude.integrate(state.angular_velocity_body_rad_s, dt)

        thrust_world = state.attitude.rotate_body_to_world(Vector3(z=total_thrust))
        velocity = state.velocity_m_s
        acceleration = Vector3(
            x=(thrust_world.x - config.linear_drag_n_s_m * velocity.x) / config.total_mass_kg,
            y=(thrust_world.y - config.linear_drag_n_s_m * velocity.y) / config.total_mass_kg,
            z=(thrust_world.z - config.linear_drag_n_s_m * velocity.z) / config.total_mass_kg
            - config.gravity_m_s2,
        )
        new_velocity = Vector3(
            x=velocity.x + acceleration.x * dt,
            y=velocity.y + acceleration.y * dt,
            z=velocity.z + acceleration.z * dt,
        )
        new_position = Vector3(
            x=state.position_m.x + new_velocity.x * dt,
            y=state.position_m.y + new_velocity.y * dt,
            z=state.position_m.z + new_velocity.z * dt,
        )
        if new_position.z < 0.0:
            new_position = new_position.model_copy(update={"z": 0.0})
            new_velocity = new_velocity.model_copy(update={"z": max(0.0, new_velocity.z)})
            if total_thrust <= config.total_mass_kg * config.gravity_m_s2 * 0.5:
                state.angular_velocity_body_rad_s = Vector3()
                state.attitude = Quaternion.from_yaw(state.attitude.euler().yaw_rad)
        state.acceleration_world_m_s2 = acceleration
        state.velocity_m_s = new_velocity
        state.position_m = new_position

        current = (
            config.battery_idle_current_a
            + max(0.0, additional_current_a)
            + sum(motor.current_a for motor in state.motors)
        )
        state.battery_current_a = current
        consumed_fraction = current * dt / (config.battery_capacity_ah * 3600.0)
        state.battery_state_of_charge = _clamp(
            state.battery_state_of_charge - consumed_fraction,
            0.0,
            1.0,
        )
        open_circuit_voltage = config.battery_empty_voltage_v + state.battery_state_of_charge * (
            config.battery_full_voltage_v - config.battery_empty_voltage_v
        )
        state.battery_voltage_v = max(
            0.0,
            open_circuit_voltage - current * config.battery_internal_resistance_ohm,
        )
        finite_values = (
            *state.position_m.model_dump().values(),
            *state.velocity_m_s.model_dump().values(),
            *state.acceleration_world_m_s2.model_dump().values(),
            state.attitude.w,
            state.attitude.x,
            state.attitude.y,
            state.attitude.z,
            *state.angular_velocity_body_rad_s.model_dump().values(),
            state.battery_state_of_charge,
            state.battery_voltage_v,
            state.battery_current_a,
        )
        if not all(math.isfinite(value) for value in finite_values):
            raise FloatingPointError("6-DOF state became non-finite")

    def motor_commands_for_trajectory(
        self,
        *,
        target_position_m: Vector3,
        target_velocity_m_s: Vector3,
        target_acceleration_world_m_s2: Vector3,
        target_yaw_rad: float,
        target_yaw_rate_rad_s: float = 0.0,
    ) -> tuple[float, float, float, float]:
        state = self.state
        config = self.config
        position_error = Vector3(
            x=target_position_m.x - state.position_m.x,
            y=target_position_m.y - state.position_m.y,
            z=target_position_m.z - state.position_m.z,
        )
        velocity_error = Vector3(
            x=target_velocity_m_s.x - state.velocity_m_s.x,
            y=target_velocity_m_s.y - state.velocity_m_s.y,
            z=target_velocity_m_s.z - state.velocity_m_s.z,
        )
        desired_acceleration = Vector3(
            x=_clamp(
                target_acceleration_world_m_s2.x + 3.0 * position_error.x + 2.4 * velocity_error.x,
                -4.0,
                4.0,
            ),
            y=_clamp(
                target_acceleration_world_m_s2.y + 3.0 * position_error.y + 2.4 * velocity_error.y,
                -4.0,
                4.0,
            ),
            z=_clamp(
                target_acceleration_world_m_s2.z + 7.0 * position_error.z + 3.6 * velocity_error.z,
                -5.0,
                5.0,
            ),
        )
        vertical_force = config.total_mass_kg * (config.gravity_m_s2 + desired_acceleration.z)
        cos_yaw, sin_yaw = math.cos(target_yaw_rad), math.sin(target_yaw_rad)
        desired_roll = _clamp(
            math.atan2(
                desired_acceleration.x * sin_yaw - desired_acceleration.y * cos_yaw,
                max(0.1, config.gravity_m_s2 + desired_acceleration.z),
            ),
            -config.maximum_tilt_rad,
            config.maximum_tilt_rad,
        )
        desired_pitch = _clamp(
            math.atan2(
                desired_acceleration.x * cos_yaw + desired_acceleration.y * sin_yaw,
                max(0.1, config.gravity_m_s2 + desired_acceleration.z),
            ),
            -config.maximum_tilt_rad,
            config.maximum_tilt_rad,
        )
        attitude = state.attitude.euler()
        omega = state.angular_velocity_body_rad_s
        torque_x = 0.0030 * _wrap_angle(desired_roll - attitude.roll_rad) - 0.00018 * omega.x
        torque_y = 0.0030 * _wrap_angle(desired_pitch - attitude.pitch_rad) - 0.00018 * omega.y
        torque_z = 0.0012 * _wrap_angle(target_yaw_rad - attitude.yaw_rad) + 0.00012 * (
            target_yaw_rate_rad_s - omega.z
        )
        tilt_compensation = max(0.35, math.cos(attitude.roll_rad) * math.cos(attitude.pitch_rad))
        collective = max(0.0, vertical_force / tilt_compensation)
        base = collective / 4.0
        roll_delta = torque_x / (2.0 * config.arm_length_m)
        pitch_delta = torque_y / (2.0 * config.arm_length_m)
        yaw_delta = torque_z / (4.0 * config.yaw_moment_per_thrust_m)
        thrusts = (
            base - pitch_delta + yaw_delta,
            base + roll_delta - yaw_delta,
            base + pitch_delta + yaw_delta,
            base - roll_delta - yaw_delta,
        )
        return tuple(_clamp(thrust / config.max_motor_thrust_n, 0.0, 1.0) for thrust in thrusts)  # type: ignore[return-value]
