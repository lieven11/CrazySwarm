from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.domain.models import EulerAttitude, Vector3
from crazyswarm_app.simulation.powertrain import (
    BatteryCurvePoint,
    BatteryCutoffReason,
    MotorVoltageThrustCurve,
    ParameterProvenance,
    PowertrainModel,
    open_circuit_voltage,
    solve_coupled_powertrain,
    validate_ocv_curve,
)


def _crazyflie_x_rotor_positions() -> tuple[Vector3, Vector3, Vector3, Vector3]:
    arm_projection = 0.046 / math.sqrt(2.0)
    return (
        Vector3(x=arm_projection, y=-arm_projection),
        Vector3(x=-arm_projection, y=-arm_projection),
        Vector3(x=-arm_projection, y=arm_projection),
        Vector3(x=arm_projection, y=arm_projection),
    )


def _upward_rotor_axes() -> tuple[Vector3, Vector3, Vector3, Vector3]:
    return (Vector3(z=1.0), Vector3(z=1.0), Vector3(z=1.0), Vector3(z=1.0))


def _crazyflie_21_plus_ocv_curve() -> tuple[BatteryCurvePoint, ...]:
    return tuple(
        BatteryCurvePoint(state_of_charge=percent / 100.0, voltage_v=voltage)
        for percent, voltage in (
            (0, 3.00),
            (10, 3.78),
            (20, 3.83),
            (30, 3.87),
            (40, 3.89),
            (50, 3.92),
            (60, 3.96),
            (70, 4.00),
            (80, 4.04),
            (90, 4.10),
            (100, 4.20),
        )
    )


def _crazyflie_21_plus_thrust_curve() -> MotorVoltageThrustCurve:
    return MotorVoltageThrustCurve(
        coefficient_0_n=-0.02476537915958403,
        coefficient_1_n_v=0.06523793527519485,
        coefficient_2_n_v2=-0.026792504967750107,
        coefficient_3_n_v3=0.006776789303971145,
        maximum_voltage_v=4.2,
    )


def _default_parameter_provenance() -> tuple[ParameterProvenance, ...]:
    firmware_url = "https://github.com/bitcraze/crazyflie-firmware/tree/2026.04"
    return (
        ParameterProvenance(
            parameter_names=(
                "arm_length_m",
                "max_motor_thrust_n",
                "minimum_motor_thrust_n",
                "yaw_moment_per_thrust_m",
                "motor_voltage_thrust_curve",
                "rotor_positions_body_m",
                "rotor_reaction_torque_signs",
            ),
            source_id="bitcraze-crazyflie-firmware",
            source_url=firmware_url,
            source_version="2026.04",
            hardware_configuration="Crazyflie 2.1 with 2.1+ propellers",
            uncertainty="Firmware defaults; not measured on the selected aircraft.",
        ),
        ParameterProvenance(
            parameter_names=("battery_ocv_curve",),
            source_id="bitcraze-lipo-typical-charge-curve",
            source_url=(
                "https://github.com/bitcraze/crazyflie-firmware/blob/2026.04/"
                "src/hal/src/pm_stm32f4.c"
            ),
            source_version="2026.04",
            hardware_configuration="Generic single-cell LiPo curve used by Crazyflie firmware",
            uncertainty="Typical voltage curve; not an exact-cell open-circuit characterization.",
        ),
        ParameterProvenance(
            parameter_names=(
                "gravity_m_s2",
                "mass_kg",
                "payload_mass_kg",
                "center_of_mass_body_m",
                "payload_position_body_m",
                "payload_inertia_x_kg_m2",
                "payload_inertia_y_kg_m2",
                "payload_inertia_z_kg_m2",
                "inertia_x_kg_m2",
                "inertia_y_kg_m2",
                "inertia_z_kg_m2",
                "motor_time_constant_s",
                "motor_time_constant_scales",
                "motor_thrust_scales",
                "motor_current_scales",
                "battery_capacity_ah",
                "battery_capacity_scale",
                "battery_temperature_capacity_scale",
                "battery_age_capacity_scale",
                "battery_internal_resistance_ohm",
                "battery_resistance_scale",
                "battery_idle_current_a",
                "battery_max_current_a",
                "motor_max_current_a",
                "linear_drag_n_s_m",
                "linear_drag_body_scale",
                "quadratic_drag_body_n_s2_m2",
                "angular_drag_n_m_s",
                "ground_effect_strength",
                "ground_effect_range_m",
                "ground_effect_maximum_multiplier",
                "battery_cutoff_voltage_v",
                "battery_cutoff_persistence_s",
                "battery_cutoff_recovery_hysteresis_v",
                "battery_compensation_enabled",
                "battery_compensation_filter_time_constant_s",
                "battery_compensation_minimum_voltage_v",
            ),
            source_id="crazyswarm-fast-sim-configured-baseline",
            source_url=("repo://docs/archive/planning-sources/FAST_SIM_PHYSICAL_FIDELITY_WP.txt"),
            source_version="FAST-SIM-PHYS-WP-00",
            hardware_configuration="Project reference Crazyflie with Flow-class payload",
            uncertainty="Configured software baseline; bench qualification required.",
        ),
    )


class PhysicsModelConfig(BaseModel):
    """Versioned, deterministic physical assumptions for the simulated Crazyflie."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = "crazyflie-6dof"
    model_version: str = "2.0.0"
    parameter_source: Literal["CONFIGURED_UNQUALIFIED", "MEASURED_QUALIFIED"] = (
        "CONFIGURED_UNQUALIFIED"
    )
    powertrain_model: PowertrainModel = PowertrainModel.BATTERY_COUPLED_V2
    actuator_command_semantics: Literal["NORMALIZED_DESIRED_THRUST"] = "NORMALIZED_DESIRED_THRUST"
    rotor_layout: Literal["X", "PLUS_LEGACY"] = "X"
    parameter_provenance: tuple[ParameterProvenance, ...] = Field(
        default_factory=_default_parameter_provenance
    )
    gravity_m_s2: float = Field(default=9.80665, gt=0.0)
    mass_kg: float = Field(default=0.032, gt=0.0)
    payload_mass_kg: float = Field(default=0.0, ge=0.0)
    center_of_mass_body_m: Vector3 = Field(default_factory=Vector3)
    payload_position_body_m: Vector3 = Field(default_factory=Vector3)
    payload_inertia_x_kg_m2: float = Field(default=0.0, ge=0.0)
    payload_inertia_y_kg_m2: float = Field(default=0.0, ge=0.0)
    payload_inertia_z_kg_m2: float = Field(default=0.0, ge=0.0)
    inertia_x_kg_m2: float = Field(default=1.43e-5, gt=0.0)
    inertia_y_kg_m2: float = Field(default=1.43e-5, gt=0.0)
    inertia_z_kg_m2: float = Field(default=2.89e-5, gt=0.0)
    arm_length_m: float = Field(default=0.046, gt=0.0)
    rotor_positions_body_m: tuple[Vector3, Vector3, Vector3, Vector3] = Field(
        default_factory=_crazyflie_x_rotor_positions
    )
    rotor_thrust_axes_body: tuple[Vector3, Vector3, Vector3, Vector3] = Field(
        default_factory=_upward_rotor_axes
    )
    rotor_reaction_torque_signs: tuple[float, float, float, float] = (-1.0, 1.0, -1.0, 1.0)
    max_motor_thrust_n: float = Field(default=0.12, gt=0.0)
    minimum_motor_thrust_n: float = Field(default=0.012817578393224994, ge=0.0)
    thrust_curve_exponent: float = Field(default=1.0, gt=0.0)
    motor_voltage_thrust_curve: MotorVoltageThrustCurve = Field(
        default_factory=_crazyflie_21_plus_thrust_curve
    )
    motor_time_constant_s: float = Field(default=0.035, gt=0.0)
    motor_time_constant_scales: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    motor_thrust_scales: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    motor_current_scales: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    yaw_moment_per_thrust_m: float = Field(default=0.0069928948992470565, gt=0.0)
    linear_drag_n_s_m: float = Field(default=0.018, ge=0.0)
    linear_drag_body_scale: Vector3 = Field(default_factory=lambda: Vector3(x=1.0, y=1.0, z=1.0))
    quadratic_drag_body_n_s2_m2: Vector3 = Field(default_factory=Vector3)
    angular_drag_n_m_s: float = Field(default=2.5e-5, ge=0.0)
    ground_effect_strength: float = Field(default=0.0, ge=0.0)
    ground_effect_range_m: float = Field(default=0.12, gt=0.0)
    ground_effect_maximum_multiplier: float = Field(default=1.25, ge=1.0)
    battery_capacity_ah: float = Field(default=0.25, gt=0.0)
    battery_capacity_scale: float = Field(default=1.0, gt=0.0, le=1.0)
    battery_temperature_capacity_scale: float = Field(default=1.0, gt=0.0, le=1.0)
    battery_age_capacity_scale: float = Field(default=1.0, gt=0.0, le=1.0)
    battery_full_voltage_v: float = Field(default=4.2, gt=0.0)
    battery_empty_voltage_v: float = Field(default=3.0, gt=0.0)
    battery_ocv_curve: tuple[BatteryCurvePoint, ...] = Field(
        default_factory=_crazyflie_21_plus_ocv_curve
    )
    battery_cutoff_voltage_v: float = Field(default=3.0, gt=0.0)
    battery_cutoff_persistence_s: float = Field(default=0.1, ge=0.0)
    battery_cutoff_recovery_hysteresis_v: float = Field(default=0.1, ge=0.0)
    battery_internal_resistance_ohm: float = Field(default=0.075, ge=0.0)
    battery_resistance_scale: float = Field(default=1.0, gt=0.0)
    battery_idle_current_a: float = Field(default=0.08, ge=0.0)
    battery_max_current_a: float = Field(default=3.75, gt=0.0)
    battery_compensation_enabled: bool = True
    battery_compensation_filter_time_constant_s: float = Field(default=0.2, gt=0.0)
    battery_compensation_minimum_voltage_v: float = Field(default=2.0, gt=0.0)
    motor_max_current_a: float = Field(default=1.2, gt=0.0)
    maximum_tilt_rad: float = Field(default=0.55, gt=0.0, lt=math.pi / 2.0)

    @property
    def total_mass_kg(self) -> float:
        return self.mass_kg + self.payload_mass_kg

    @property
    def combined_center_of_mass_body_m(self) -> Vector3:
        total = self.total_mass_kg
        return Vector3(
            x=(
                self.mass_kg * self.center_of_mass_body_m.x
                + self.payload_mass_kg * self.payload_position_body_m.x
            )
            / total,
            y=(
                self.mass_kg * self.center_of_mass_body_m.y
                + self.payload_mass_kg * self.payload_position_body_m.y
            )
            / total,
            z=(
                self.mass_kg * self.center_of_mass_body_m.z
                + self.payload_mass_kg * self.payload_position_body_m.z
            )
            / total,
        )

    def _parallel_axis_inertia(self, axis: Literal["x", "y", "z"]) -> float:
        combined = self.combined_center_of_mass_body_m
        base_offset = Vector3(
            x=self.center_of_mass_body_m.x - combined.x,
            y=self.center_of_mass_body_m.y - combined.y,
            z=self.center_of_mass_body_m.z - combined.z,
        )
        payload_offset = Vector3(
            x=self.payload_position_body_m.x - combined.x,
            y=self.payload_position_body_m.y - combined.y,
            z=self.payload_position_body_m.z - combined.z,
        )
        if axis == "x":
            base_distance_squared = base_offset.y**2 + base_offset.z**2
            payload_distance_squared = payload_offset.y**2 + payload_offset.z**2
            base_inertia = self.inertia_x_kg_m2
            payload_inertia = self.payload_inertia_x_kg_m2
        elif axis == "y":
            base_distance_squared = base_offset.x**2 + base_offset.z**2
            payload_distance_squared = payload_offset.x**2 + payload_offset.z**2
            base_inertia = self.inertia_y_kg_m2
            payload_inertia = self.payload_inertia_y_kg_m2
        else:
            base_distance_squared = base_offset.x**2 + base_offset.y**2
            payload_distance_squared = payload_offset.x**2 + payload_offset.y**2
            base_inertia = self.inertia_z_kg_m2
            payload_inertia = self.payload_inertia_z_kg_m2
        return (
            base_inertia
            + self.mass_kg * base_distance_squared
            + payload_inertia
            + self.payload_mass_kg * payload_distance_squared
        )

    @property
    def total_inertia_x_kg_m2(self) -> float:
        return self._parallel_axis_inertia("x")

    @property
    def total_inertia_y_kg_m2(self) -> float:
        return self._parallel_axis_inertia("y")

    @property
    def total_inertia_z_kg_m2(self) -> float:
        return self._parallel_axis_inertia("z")

    @property
    def effective_battery_capacity_ah(self) -> float:
        return (
            self.battery_capacity_ah
            * self.battery_capacity_scale
            * self.battery_temperature_capacity_scale
            * self.battery_age_capacity_scale
        )

    @classmethod
    def legacy_v1(cls) -> PhysicsModelConfig:
        """Explicit replay-compatible v1 plant; never selected by a v2 scenario implicitly."""

        arm = 0.046
        return cls(
            model_version="1.0.0",
            powertrain_model=PowertrainModel.LEGACY_UNCOUPLED_V1,
            rotor_layout="PLUS_LEGACY",
            rotor_positions_body_m=(
                Vector3(x=arm),
                Vector3(y=arm),
                Vector3(x=-arm),
                Vector3(y=-arm),
            ),
            rotor_reaction_torque_signs=(1.0, -1.0, 1.0, -1.0),
            max_motor_thrust_n=0.15,
            minimum_motor_thrust_n=0.0,
            yaw_moment_per_thrust_m=0.006,
            battery_empty_voltage_v=3.2,
            battery_compensation_enabled=False,
        )

    @model_validator(mode="after")
    def validate_thrust_and_voltage(self) -> PhysicsModelConfig:
        if 4.0 * self.max_motor_thrust_n <= self.total_mass_kg * self.gravity_m_s2:
            raise ValueError("configured motors cannot produce hover thrust")
        if self.battery_empty_voltage_v >= self.battery_full_voltage_v:
            raise ValueError("battery empty voltage must be below full voltage")
        if self.battery_cutoff_voltage_v >= self.battery_full_voltage_v:
            raise ValueError("battery cutoff voltage must be below full voltage")
        validate_ocv_curve(self.battery_ocv_curve)
        if self.powertrain_model is PowertrainModel.BATTERY_COUPLED_V2:
            if not self.model_version.startswith("2.0.0") or self.rotor_layout != "X":
                raise ValueError("coupled v2 powertrain requires model 2.0.0 lineage and X layout")
        elif self.model_version != "1.0.0" or self.rotor_layout != "PLUS_LEGACY":
            raise ValueError("legacy v1 powertrain requires model 1.0.0 and plus layout")
        if self.minimum_motor_thrust_n >= self.max_motor_thrust_n:
            raise ValueError("minimum motor thrust must be below maximum motor thrust")
        for name, values in (
            ("motor thrust scales", self.motor_thrust_scales),
            ("motor current scales", self.motor_current_scales),
        ):
            if any(value < 0.0 for value in values):
                raise ValueError(f"{name} cannot contain negative values")
        if any(value <= 0.0 for value in self.motor_time_constant_scales):
            raise ValueError("motor time-constant scales must be positive")
        total_inertia = (
            self.total_inertia_x_kg_m2,
            self.total_inertia_y_kg_m2,
            self.total_inertia_z_kg_m2,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in total_inertia):
            raise ValueError("combined inertia must be finite and positive definite")
        largest_inertia = max(total_inertia)
        other_inertia = sum(total_inertia) - largest_inertia
        if largest_inertia > other_inertia * 1.02:
            raise ValueError("combined inertia violates the rigid-body triangle inequality")
        for name, value in self.linear_drag_body_scale.model_dump().items():
            if value < 0.0:
                raise ValueError(f"linear drag body scale {name} cannot be negative")
        for name, value in self.quadratic_drag_body_n_s2_m2.model_dump().items():
            if value < 0.0:
                raise ValueError(f"quadratic body drag {name} cannot be negative")
        for index, axis in enumerate(self.rotor_thrust_axes_body, start=1):
            norm = math.sqrt(axis.x**2 + axis.y**2 + axis.z**2)
            if not math.isclose(norm, 1.0, abs_tol=1e-9):
                raise ValueError(f"rotor M{index} thrust axis must be a unit vector")
        if (
            len({(position.x, position.y, position.z) for position in self.rotor_positions_body_m})
            != 4
        ):
            raise ValueError("rotor positions must be unique")
        if set(self.rotor_reaction_torque_signs) - {-1.0, 1.0}:
            raise ValueError("rotor reaction torque signs must be exactly -1 or +1")
        covered_parameters = {
            parameter
            for source in self.parameter_provenance
            for parameter in source.parameter_names
        }
        required_provenance = {
            field_name
            for source in _default_parameter_provenance()
            for field_name in source.parameter_names
        }
        if not required_provenance.issubset(covered_parameters):
            raise ValueError("executable v2 physical coefficients require provenance")
        if len(covered_parameters) != sum(
            len(source.parameter_names) for source in self.parameter_provenance
        ):
            raise ValueError("physical parameter provenance cannot overlap")
        if self.parameter_source == "MEASURED_QUALIFIED" and any(
            source.qualification.value != "MEASURED_QUALIFIED"
            for source in self.parameter_provenance
        ):
            raise ValueError("measured-qualified parameter sets require qualified provenance")
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

    @classmethod
    def from_euler(cls, roll_rad: float, pitch_rad: float, yaw_rad: float) -> Quaternion:
        cr, sr = math.cos(roll_rad / 2.0), math.sin(roll_rad / 2.0)
        cp, sp = math.cos(pitch_rad / 2.0), math.sin(pitch_rad / 2.0)
        cy, sy = math.cos(yaw_rad / 2.0), math.sin(yaw_rad / 2.0)
        return cls(
            w=cr * cp * cy + sr * sp * sy,
            x=sr * cp * cy - cr * sp * sy,
            y=cr * sp * cy + sr * cp * sy,
            z=cr * cp * sy - sr * sp * cy,
        ).normalized()

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
    requested_thrust_n: float = 0.0
    applied_pwm: float = 0.0
    motor_voltage_v: float = 0.0
    thrust_n: float = 0.0
    available_thrust_n: float = 0.0
    current_a: float = 0.0
    saturated: bool = False
    health_scale: float = 1.0


@dataclass(slots=True)
class PhysicsState:
    position_m: Vector3 = field(default_factory=Vector3)
    velocity_m_s: Vector3 = field(default_factory=Vector3)
    acceleration_world_m_s2: Vector3 = field(default_factory=Vector3)
    attitude: Quaternion = field(default_factory=Quaternion)
    angular_velocity_body_rad_s: Vector3 = field(default_factory=Vector3)
    battery_state_of_charge: float = 1.0
    battery_open_circuit_voltage_v: float = 4.2
    battery_voltage_v: float = 4.2
    battery_filtered_voltage_v: float = 4.2
    battery_current_a: float = 0.0
    battery_cutoff_active: bool = False
    battery_cutoff_reason: BatteryCutoffReason | None = None
    battery_undervoltage_duration_s: float = 0.0
    powertrain_current_limited: bool = False
    motors: list[MotorState] = field(default_factory=lambda: [MotorState() for _ in range(4)])


@dataclass(frozen=True, slots=True)
class ControllerState:
    position_m: Vector3
    velocity_m_s: Vector3
    attitude: EulerAttitude
    angular_velocity_body_rad_s: Vector3


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _wrap_angle(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(
        x=left.y * right.z - left.z * right.y,
        y=left.z * right.x - left.x * right.z,
        z=left.x * right.y - left.y * right.x,
    )


class SixDofPhysics:
    def __init__(
        self,
        config: PhysicsModelConfig,
        *,
        position_m: Vector3 | None = None,
        yaw_rad: float = 0.0,
        battery_percent: float = 100.0,
        initial_roll_rad: float = 0.0,
        initial_pitch_rad: float = 0.0,
        initial_velocity_m_s: Vector3 | None = None,
    ) -> None:
        self.config = config
        self.state = PhysicsState()
        self.reset(
            position_m or Vector3(),
            yaw_rad,
            battery_percent,
            initial_roll_rad=initial_roll_rad,
            initial_pitch_rad=initial_pitch_rad,
            initial_velocity_m_s=initial_velocity_m_s,
        )

    def reset(
        self,
        position_m: Vector3,
        yaw_rad: float,
        battery_percent: float,
        *,
        initial_roll_rad: float = 0.0,
        initial_pitch_rad: float = 0.0,
        initial_velocity_m_s: Vector3 | None = None,
    ) -> None:
        soc = _clamp(battery_percent / 100.0, 0.0, 1.0)
        voltage = (
            open_circuit_voltage(self.config.battery_ocv_curve, soc)
            if self.config.powertrain_model is PowertrainModel.BATTERY_COUPLED_V2
            else self.config.battery_empty_voltage_v
            + soc * (self.config.battery_full_voltage_v - self.config.battery_empty_voltage_v)
        )
        self.state = PhysicsState(
            position_m=position_m,
            velocity_m_s=initial_velocity_m_s or Vector3(),
            attitude=Quaternion.from_euler(initial_roll_rad, initial_pitch_rad, yaw_rad),
            battery_state_of_charge=soc,
            battery_open_circuit_voltage_v=voltage,
            battery_voltage_v=voltage,
            battery_filtered_voltage_v=voltage,
            battery_cutoff_active=soc <= 0.0,
            battery_cutoff_reason=BatteryCutoffReason.DEPLETED if soc <= 0.0 else None,
        )

    def set_battery_percent(self, battery_percent: float) -> None:
        """Restore battery state without changing pose or vehicle dynamics."""

        soc = _clamp(battery_percent / 100.0, 0.0, 1.0)
        self.state.battery_state_of_charge = soc
        voltage = (
            open_circuit_voltage(self.config.battery_ocv_curve, soc)
            if self.config.powertrain_model is PowertrainModel.BATTERY_COUPLED_V2
            else self.config.battery_empty_voltage_v
            + soc * (self.config.battery_full_voltage_v - self.config.battery_empty_voltage_v)
        )
        self.state.battery_open_circuit_voltage_v = voltage
        self.state.battery_voltage_v = voltage
        self.state.battery_filtered_voltage_v = voltage
        self.state.battery_current_a = 0.0
        self.state.battery_cutoff_active = soc <= 0.0
        self.state.battery_cutoff_reason = BatteryCutoffReason.DEPLETED if soc <= 0.0 else None
        self.state.battery_undervoltage_duration_s = 0.0
        self.state.powertrain_current_limited = False

    def apply_force_impulse(self, impulse_world_n_s: Vector3) -> None:
        mass = self.config.total_mass_kg
        velocity = self.state.velocity_m_s
        self.state.velocity_m_s = Vector3(
            x=velocity.x + impulse_world_n_s.x / mass,
            y=velocity.y + impulse_world_n_s.y / mass,
            z=velocity.z + impulse_world_n_s.z / mass,
        )

    def step(
        self,
        motor_commands: tuple[float, float, float, float],
        dt: float,
        *,
        additional_current_a: float = 0.0,
        actuator_health_scales: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
    ) -> None:
        config = self.config
        state = self.state
        if dt <= 0.0 or not math.isfinite(dt):
            raise ValueError("physics step must be finite and positive")
        if any(
            not math.isfinite(scale) or scale < 0.0 or scale > 1.0
            for scale in actuator_health_scales
        ):
            raise ValueError("actuator health scales must be finite values from zero to one")
        selected_commands = tuple(_clamp(command, 0.0, 1.0) for command in motor_commands)
        if config.powertrain_model is PowertrainModel.BATTERY_COUPLED_V2:
            invalid_cell_state = not all(
                math.isfinite(value)
                for value in (
                    state.battery_state_of_charge,
                    state.battery_filtered_voltage_v,
                )
            )
            if invalid_cell_state:
                state.battery_cutoff_active = True
                state.battery_cutoff_reason = BatteryCutoffReason.INVALID_CELL_STATE
                state.battery_state_of_charge = 0.0
            if state.battery_cutoff_active:
                selected_commands = (0.0, 0.0, 0.0, 0.0)
            solution = solve_coupled_powertrain(
                config,
                state_of_charge=0.0 if invalid_cell_state else state.battery_state_of_charge,
                filtered_supply_voltage_v=(
                    0.0 if invalid_cell_state else state.battery_filtered_voltage_v
                ),
                motor_commands=selected_commands,  # type: ignore[arg-type]
                additional_current_a=additional_current_a,
                actuator_health_scales=actuator_health_scales,
            )
            for index, (motor, command, electrical) in enumerate(
                zip(state.motors, selected_commands, solution.motors, strict=True)
            ):
                motor.command = command
                motor.requested_thrust_n = electrical.requested_thrust_n
                motor.applied_pwm = electrical.applied_pwm
                motor.motor_voltage_v = electrical.motor_voltage_v
                motor.available_thrust_n = (
                    0.0 if state.battery_cutoff_active else electrical.available_thrust_n
                )
                motor.current_a = electrical.current_a
                motor.saturated = electrical.saturated
                motor.health_scale = actuator_health_scales[index]
                time_constant = (
                    config.motor_time_constant_s * config.motor_time_constant_scales[index]
                )
                alpha = 1.0 - math.exp(-dt / time_constant)
                motor.thrust_n += (electrical.target_thrust_n - motor.thrust_n) * alpha
            state.battery_open_circuit_voltage_v = solution.open_circuit_voltage_v
            state.battery_voltage_v = solution.terminal_voltage_v
            state.battery_current_a = solution.total_current_a
            state.powertrain_current_limited = solution.current_limited
            filter_alpha = 1.0 - math.exp(-dt / config.battery_compensation_filter_time_constant_s)
            if invalid_cell_state:
                state.battery_filtered_voltage_v = solution.terminal_voltage_v
            else:
                state.battery_filtered_voltage_v += filter_alpha * (
                    solution.terminal_voltage_v - state.battery_filtered_voltage_v
                )
            consumed_fraction = (
                solution.total_current_a * dt / (config.effective_battery_capacity_ah * 3600.0)
            )
            state.battery_state_of_charge = _clamp(
                state.battery_state_of_charge - consumed_fraction,
                0.0,
                1.0,
            )
            if invalid_cell_state:
                state.battery_cutoff_active = True
                state.battery_cutoff_reason = BatteryCutoffReason.INVALID_CELL_STATE
            elif state.battery_state_of_charge <= 0.0:
                state.battery_cutoff_active = True
                state.battery_cutoff_reason = BatteryCutoffReason.DEPLETED
            elif solution.terminal_voltage_v < config.battery_cutoff_voltage_v:
                state.battery_undervoltage_duration_s += dt
                if state.battery_undervoltage_duration_s >= config.battery_cutoff_persistence_s:
                    state.battery_cutoff_active = True
                    state.battery_cutoff_reason = BatteryCutoffReason.UNDERVOLTAGE
            else:
                state.battery_undervoltage_duration_s = 0.0
                if (
                    state.battery_cutoff_reason is BatteryCutoffReason.UNDERVOLTAGE
                    and solution.terminal_voltage_v
                    >= config.battery_cutoff_voltage_v + config.battery_cutoff_recovery_hysteresis_v
                ):
                    state.battery_cutoff_active = False
                    state.battery_cutoff_reason = None
        else:
            if state.battery_voltage_v <= config.battery_cutoff_voltage_v:
                selected_commands = (0.0, 0.0, 0.0, 0.0)
            alpha = 1.0 - math.exp(-dt / config.motor_time_constant_s)
            for index, (motor, command) in enumerate(
                zip(state.motors, selected_commands, strict=True)
            ):
                motor.command = command
                health_scale = actuator_health_scales[index]
                requested_thrust = command**config.thrust_curve_exponent * config.max_motor_thrust_n
                target_thrust = requested_thrust * health_scale
                motor.requested_thrust_n = requested_thrust
                motor.applied_pwm = command
                motor.motor_voltage_v = command * state.battery_voltage_v
                motor.available_thrust_n = config.max_motor_thrust_n * health_scale
                motor.thrust_n += (target_thrust - motor.thrust_n) * alpha
                motor.current_a = (
                    motor.thrust_n / config.max_motor_thrust_n * config.motor_max_current_a
                )
                motor.saturated = command > 0.0 and health_scale < 1.0
                motor.health_scale = health_scale
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
            legacy_ocv = config.battery_empty_voltage_v + state.battery_state_of_charge * (
                config.battery_full_voltage_v - config.battery_empty_voltage_v
            )
            state.battery_open_circuit_voltage_v = legacy_ocv
            state.battery_voltage_v = max(
                0.0,
                legacy_ocv - current * config.battery_internal_resistance_ohm,
            )
            state.battery_filtered_voltage_v = state.battery_voltage_v
            state.battery_cutoff_active = state.battery_voltage_v <= config.battery_cutoff_voltage_v
            state.battery_cutoff_reason = (
                BatteryCutoffReason.UNDERVOLTAGE if state.battery_cutoff_active else None
            )

        ground_effect_multiplier = 1.0
        if (
            config.ground_effect_strength > 0.0
            and state.position_m.z < config.ground_effect_range_m
        ):
            normalized_height = _clamp(
                state.position_m.z / config.ground_effect_range_m,
                0.0,
                1.0,
            )
            ground_effect_multiplier = min(
                config.ground_effect_maximum_multiplier,
                1.0 + config.ground_effect_strength * (1.0 - normalized_height) ** 2,
            )
        force_body = Vector3()
        torque = Vector3()
        center_of_mass = config.combined_center_of_mass_body_m
        for motor, position, axis, reaction_sign in zip(
            state.motors,
            config.rotor_positions_body_m,
            config.rotor_thrust_axes_body,
            config.rotor_reaction_torque_signs,
            strict=True,
        ):
            thrust = motor.thrust_n * ground_effect_multiplier
            rotor_force = Vector3(x=axis.x * thrust, y=axis.y * thrust, z=axis.z * thrust)
            force_body = Vector3(
                x=force_body.x + rotor_force.x,
                y=force_body.y + rotor_force.y,
                z=force_body.z + rotor_force.z,
            )
            moment_arm = Vector3(
                x=position.x - center_of_mass.x,
                y=position.y - center_of_mass.y,
                z=position.z - center_of_mass.z,
            )
            force_moment = _cross(moment_arm, rotor_force)
            reaction_scale = reaction_sign * config.yaw_moment_per_thrust_m * thrust
            torque = Vector3(
                x=torque.x + force_moment.x + axis.x * reaction_scale,
                y=torque.y + force_moment.y + axis.y * reaction_scale,
                z=torque.z + force_moment.z + axis.z * reaction_scale,
            )
        total_thrust = math.sqrt(force_body.x**2 + force_body.y**2 + force_body.z**2)
        omega = state.angular_velocity_body_rad_s
        inertia_x = config.total_inertia_x_kg_m2
        inertia_y = config.total_inertia_y_kg_m2
        inertia_z = config.total_inertia_z_kg_m2
        angular_acceleration = Vector3(
            x=(
                torque.x
                - (inertia_z - inertia_y) * omega.y * omega.z
                - config.angular_drag_n_m_s * omega.x
            )
            / inertia_x,
            y=(
                torque.y
                - (inertia_x - inertia_z) * omega.z * omega.x
                - config.angular_drag_n_m_s * omega.y
            )
            / inertia_y,
            z=(
                torque.z
                - (inertia_y - inertia_x) * omega.x * omega.y
                - config.angular_drag_n_m_s * omega.z
            )
            / inertia_z,
        )
        state.angular_velocity_body_rad_s = Vector3(
            x=omega.x + angular_acceleration.x * dt,
            y=omega.y + angular_acceleration.y * dt,
            z=omega.z + angular_acceleration.z * dt,
        )
        state.attitude = state.attitude.integrate(state.angular_velocity_body_rad_s, dt)

        thrust_world = state.attitude.rotate_body_to_world(force_body)
        velocity = state.velocity_m_s
        velocity_body = state.attitude.rotate_world_to_body(velocity)
        drag_body = Vector3(
            x=-config.linear_drag_n_s_m * config.linear_drag_body_scale.x * velocity_body.x
            - config.quadratic_drag_body_n_s2_m2.x * abs(velocity_body.x) * velocity_body.x,
            y=-config.linear_drag_n_s_m * config.linear_drag_body_scale.y * velocity_body.y
            - config.quadratic_drag_body_n_s2_m2.y * abs(velocity_body.y) * velocity_body.y,
            z=-config.linear_drag_n_s_m * config.linear_drag_body_scale.z * velocity_body.z
            - config.quadratic_drag_body_n_s2_m2.z * abs(velocity_body.z) * velocity_body.z,
        )
        drag_world = state.attitude.rotate_body_to_world(drag_body)
        acceleration = Vector3(
            x=(thrust_world.x + drag_world.x) / config.total_mass_kg,
            y=(thrust_world.y + drag_world.y) / config.total_mass_kg,
            z=(thrust_world.z + drag_world.z) / config.total_mass_kg - config.gravity_m_s2,
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
            state.battery_open_circuit_voltage_v,
            state.battery_voltage_v,
            state.battery_filtered_voltage_v,
            state.battery_current_a,
            *(
                value
                for motor in state.motors
                for value in (
                    motor.command,
                    motor.requested_thrust_n,
                    motor.applied_pwm,
                    motor.motor_voltage_v,
                    motor.thrust_n,
                    motor.available_thrust_n,
                    motor.current_a,
                )
            ),
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
        """Ideal-truth compatibility path, reserved for analytic tests."""

        state = self.state
        return self.motor_commands_for_control_state(
            ControllerState(
                position_m=state.position_m,
                velocity_m_s=state.velocity_m_s,
                attitude=state.attitude.euler(),
                angular_velocity_body_rad_s=state.angular_velocity_body_rad_s,
            ),
            target_position_m=target_position_m,
            target_velocity_m_s=target_velocity_m_s,
            target_acceleration_world_m_s2=target_acceleration_world_m_s2,
            target_yaw_rad=target_yaw_rad,
            target_yaw_rate_rad_s=target_yaw_rate_rad_s,
        )

    def motor_commands_for_control_state(
        self,
        control_state: ControllerState,
        *,
        target_position_m: Vector3,
        target_velocity_m_s: Vector3,
        target_acceleration_world_m_s2: Vector3,
        target_yaw_rad: float,
        target_yaw_rate_rad_s: float = 0.0,
        nominal_total_mass_kg: float | None = None,
        nominal_max_motor_thrust_n: float | None = None,
    ) -> tuple[float, float, float, float]:
        """Pure controller boundary: only explicit estimated/control state is visible."""

        config = self.config
        position_error = Vector3(
            x=target_position_m.x - control_state.position_m.x,
            y=target_position_m.y - control_state.position_m.y,
            z=target_position_m.z - control_state.position_m.z,
        )
        velocity_error = Vector3(
            x=target_velocity_m_s.x - control_state.velocity_m_s.x,
            y=target_velocity_m_s.y - control_state.velocity_m_s.y,
            z=target_velocity_m_s.z - control_state.velocity_m_s.z,
        )
        desired_acceleration = Vector3(
            x=_clamp(
                target_acceleration_world_m_s2.x + 3.2 * position_error.x + 2.6 * velocity_error.x,
                -4.0,
                4.0,
            ),
            y=_clamp(
                target_acceleration_world_m_s2.y + 3.2 * position_error.y + 2.6 * velocity_error.y,
                -4.0,
                4.0,
            ),
            z=_clamp(
                target_acceleration_world_m_s2.z + 7.0 * position_error.z + 3.6 * velocity_error.z,
                -5.0,
                5.0,
            ),
        )
        controller_mass_kg = nominal_total_mass_kg or config.total_mass_kg
        vertical_force = controller_mass_kg * (config.gravity_m_s2 + desired_acceleration.z)
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
        attitude = control_state.attitude
        omega = control_state.angular_velocity_body_rad_s
        torque_x = 0.0030 * _wrap_angle(desired_roll - attitude.roll_rad) - 0.00018 * omega.x
        torque_y = 0.0030 * _wrap_angle(desired_pitch - attitude.pitch_rad) - 0.00018 * omega.y
        torque_z = 0.0012 * _wrap_angle(target_yaw_rad - attitude.yaw_rad) + 0.00012 * (
            target_yaw_rate_rad_s - omega.z
        )
        tilt_compensation = max(0.35, math.cos(attitude.roll_rad) * math.cos(attitude.pitch_rad))
        collective = max(0.0, vertical_force / tilt_compensation)
        base = collective / 4.0
        yaw_delta = torque_z / (4.0 * config.yaw_moment_per_thrust_m)
        if config.rotor_layout == "X":
            projected_arm = config.arm_length_m / math.sqrt(2.0)
            roll_delta = torque_x / (4.0 * projected_arm)
            pitch_delta = torque_y / (4.0 * projected_arm)
            # Force/torque distribution pinned to Crazyflie firmware 2026.04.
            thrusts = (
                base - roll_delta - pitch_delta - yaw_delta,
                base - roll_delta + pitch_delta + yaw_delta,
                base + roll_delta + pitch_delta - yaw_delta,
                base + roll_delta - pitch_delta + yaw_delta,
            )
        else:
            roll_delta = torque_x / (2.0 * config.arm_length_m)
            pitch_delta = torque_y / (2.0 * config.arm_length_m)
            thrusts = (
                base - pitch_delta + yaw_delta,
                base + roll_delta - yaw_delta,
                base + pitch_delta + yaw_delta,
                base - roll_delta - yaw_delta,
            )
        controller_maximum_thrust_n = nominal_max_motor_thrust_n or config.max_motor_thrust_n
        return tuple(_clamp(thrust / controller_maximum_thrust_n, 0.0, 1.0) for thrust in thrusts)  # type: ignore[return-value]
