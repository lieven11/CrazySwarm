from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PowertrainModel(StrEnum):
    """Versioned interpretation of the normalized actuator command."""

    LEGACY_UNCOUPLED_V1 = "LEGACY_UNCOUPLED_V1"
    BATTERY_COUPLED_V2 = "BATTERY_COUPLED_V2"


class BatteryCutoffReason(StrEnum):
    DEPLETED = "DEPLETED"
    UNDERVOLTAGE = "UNDERVOLTAGE"
    INVALID_CELL_STATE = "INVALID_CELL_STATE"


class QualificationClass(StrEnum):
    CONFIGURED_UNQUALIFIED = "CONFIGURED_UNQUALIFIED"
    MEASURED_QUALIFIED = "MEASURED_QUALIFIED"


class ParameterProvenance(BaseModel):
    """Traceability for a set of executable physical coefficients."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_names: tuple[str, ...] = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    hardware_configuration: str = Field(min_length=1)
    qualification: QualificationClass = QualificationClass.CONFIGURED_UNQUALIFIED
    uncertainty: str | None = None


class BatteryCurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state_of_charge: float = Field(ge=0.0, le=1.0)
    voltage_v: float = Field(gt=0.0)


class MotorVoltageThrustCurve(BaseModel):
    """Cubic ``thrust_N = c0 + c1*V + c2*V^2 + c3*V^3`` model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    coefficient_0_n: float
    coefficient_1_n_v: float
    coefficient_2_n_v2: float
    coefficient_3_n_v3: float
    minimum_voltage_v: float = Field(default=0.0, ge=0.0)
    maximum_voltage_v: float = Field(default=4.2, gt=0.0)

    @model_validator(mode="after")
    def ordered_voltage_range(self) -> MotorVoltageThrustCurve:
        if self.minimum_voltage_v >= self.maximum_voltage_v:
            raise ValueError("motor curve voltage range must be increasing")
        return self

    def thrust_n(self, voltage_v: float) -> float:
        voltage = max(self.minimum_voltage_v, min(self.maximum_voltage_v, voltage_v))
        return max(
            0.0,
            self.coefficient_0_n
            + self.coefficient_1_n_v * voltage
            + self.coefficient_2_n_v2 * voltage**2
            + self.coefficient_3_n_v3 * voltage**3,
        )

    def voltage_for_thrust(self, thrust_n: float) -> float:
        if thrust_n <= 0.0:
            return 0.0
        maximum = self.thrust_n(self.maximum_voltage_v)
        if thrust_n > maximum + 1e-12:
            return math.inf
        lower = self.minimum_voltage_v
        upper = self.maximum_voltage_v
        for _ in range(60):
            midpoint = 0.5 * (lower + upper)
            if self.thrust_n(midpoint) < thrust_n:
                lower = midpoint
            else:
                upper = midpoint
        return 0.5 * (lower + upper)


class CoupledPowertrainParameters(Protocol):
    @property
    def max_motor_thrust_n(self) -> float: ...

    @property
    def minimum_motor_thrust_n(self) -> float: ...

    @property
    def battery_internal_resistance_ohm(self) -> float: ...

    @property
    def battery_idle_current_a(self) -> float: ...

    @property
    def battery_max_current_a(self) -> float: ...

    @property
    def motor_max_current_a(self) -> float: ...

    @property
    def battery_resistance_scale(self) -> float: ...

    @property
    def battery_compensation_enabled(self) -> bool: ...

    @property
    def battery_compensation_minimum_voltage_v(self) -> float: ...

    @property
    def battery_ocv_curve(self) -> tuple[BatteryCurvePoint, ...]: ...

    @property
    def motor_voltage_thrust_curve(self) -> MotorVoltageThrustCurve: ...

    @property
    def motor_thrust_scales(self) -> tuple[float, float, float, float]: ...

    @property
    def motor_current_scales(self) -> tuple[float, float, float, float]: ...


@dataclass(frozen=True, slots=True)
class MotorElectricalSolution:
    requested_thrust_n: float
    applied_pwm: float
    motor_voltage_v: float
    target_thrust_n: float
    available_thrust_n: float
    current_a: float
    saturated: bool


@dataclass(frozen=True, slots=True)
class PowertrainSolution:
    open_circuit_voltage_v: float
    terminal_voltage_v: float
    total_current_a: float
    motors: tuple[
        MotorElectricalSolution,
        MotorElectricalSolution,
        MotorElectricalSolution,
        MotorElectricalSolution,
    ]
    current_limited: bool


def open_circuit_voltage(curve: tuple[BatteryCurvePoint, ...], state_of_charge: float) -> float:
    """Piecewise-linear OCV interpolation over a strictly ordered curve."""

    soc = max(0.0, min(1.0, state_of_charge))
    if soc <= curve[0].state_of_charge:
        return curve[0].voltage_v
    for lower, upper in pairwise(curve):
        if soc <= upper.state_of_charge:
            span = upper.state_of_charge - lower.state_of_charge
            fraction = (soc - lower.state_of_charge) / span
            return lower.voltage_v + fraction * (upper.voltage_v - lower.voltage_v)
    return curve[-1].voltage_v


def validate_ocv_curve(curve: tuple[BatteryCurvePoint, ...]) -> None:
    if len(curve) < 2:
        raise ValueError("battery OCV curve requires at least two points")
    if curve[0].state_of_charge != 0.0 or curve[-1].state_of_charge != 1.0:
        raise ValueError("battery OCV curve must cover state of charge 0 through 1")
    for lower, upper in pairwise(curve):
        if upper.state_of_charge <= lower.state_of_charge:
            raise ValueError("battery OCV state-of-charge points must be strictly increasing")
        if upper.voltage_v < lower.voltage_v:
            raise ValueError("battery OCV voltage must be non-decreasing")


def solve_coupled_powertrain(
    config: CoupledPowertrainParameters,
    *,
    state_of_charge: float,
    filtered_supply_voltage_v: float,
    motor_commands: tuple[float, float, float, float],
    additional_current_a: float,
    actuator_health_scales: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
) -> PowertrainSolution:
    """Solve the bounded battery load line and averaged per-motor electrical state.

    Commands are normalized desired thrust. With compensation enabled they are inverted
    through the firmware-style cubic curve to requested motor voltage, then converted to
    duty cycle using the filtered supply voltage. The solve is deterministic and bounded;
    it never carries a stale electrical state forward.
    """

    ocv = open_circuit_voltage(config.battery_ocv_curve, state_of_charge)
    parasitic_current = config.battery_idle_current_a + max(0.0, additional_current_a)
    resistance = config.battery_internal_resistance_ohm * config.battery_resistance_scale
    requested = tuple(
        max(0.0, min(1.0, command)) * config.max_motor_thrust_n for command in motor_commands
    )
    base_pwm: list[float] = []
    for index, (command, requested_thrust) in enumerate(
        zip(motor_commands, requested, strict=True)
    ):
        thrust_scale = config.motor_thrust_scales[index]
        if requested_thrust < config.minimum_motor_thrust_n or thrust_scale <= 0.0:
            base_pwm.append(0.0)
            continue
        if config.battery_compensation_enabled:
            required_voltage = config.motor_voltage_thrust_curve.voltage_for_thrust(
                requested_thrust / thrust_scale
            )
            if not math.isfinite(required_voltage):
                base_pwm.append(1.0)
            elif filtered_supply_voltage_v < config.battery_compensation_minimum_voltage_v:
                base_pwm.append(0.0)
            else:
                base_pwm.append(max(0.0, min(1.0, required_voltage / filtered_supply_voltage_v)))
        else:
            # This matches the uncompensated firmware path: normalized thrust is raw PWM.
            base_pwm.append(max(0.0, min(1.0, command)))

    def evaluate(
        terminal_voltage_v: float,
    ) -> tuple[
        tuple[
            MotorElectricalSolution,
            MotorElectricalSolution,
            MotorElectricalSolution,
            MotorElectricalSolution,
        ],
        float,
        bool,
    ]:
        def with_pwm_scale(pwm_scale: float) -> tuple[list[MotorElectricalSolution], float]:
            motor_states: list[MotorElectricalSolution] = []
            motor_current = 0.0
            for index, (requested_thrust, raw_pwm) in enumerate(
                zip(requested, base_pwm, strict=True)
            ):
                pwm = raw_pwm * pwm_scale
                voltage = pwm * terminal_voltage_v
                thrust_scale = config.motor_thrust_scales[index]
                health_scale = max(0.0, min(1.0, actuator_health_scales[index]))
                physical_thrust = min(
                    config.max_motor_thrust_n * thrust_scale * health_scale,
                    config.motor_voltage_thrust_curve.thrust_n(voltage)
                    * thrust_scale
                    * health_scale,
                )
                if pwm == 0.0:
                    physical_thrust = 0.0
                available = min(
                    config.max_motor_thrust_n * thrust_scale * health_scale,
                    config.motor_voltage_thrust_curve.thrust_n(terminal_voltage_v)
                    * thrust_scale
                    * health_scale,
                )
                normalized_load = (
                    0.0
                    if config.max_motor_thrust_n * thrust_scale <= 0.0
                    else physical_thrust / (config.max_motor_thrust_n * thrust_scale)
                )
                # Averaged supply current for a PWM-driven brushed motor. This deliberately
                # omits switching ripple; the current coefficient remains unqualified.
                current = min(
                    config.motor_max_current_a * config.motor_current_scales[index],
                    pwm
                    * config.motor_max_current_a
                    * config.motor_current_scales[index]
                    * normalized_load,
                )
                motor_current += current
                motor_states.append(
                    MotorElectricalSolution(
                        requested_thrust_n=requested_thrust,
                        applied_pwm=pwm,
                        motor_voltage_v=voltage,
                        target_thrust_n=physical_thrust,
                        available_thrust_n=available,
                        current_a=current,
                        saturated=(
                            requested_thrust > physical_thrust + 1e-9
                            and (
                                raw_pwm >= 1.0 - 1e-12
                                or pwm_scale < 1.0 - 1e-12
                                or health_scale < 1.0 - 1e-12
                            )
                        ),
                    )
                )
            return motor_states, parasitic_current + motor_current

        states, total_current = with_pwm_scale(1.0)
        if total_current <= config.battery_max_current_a:
            return tuple(states), total_current, False  # type: ignore[return-value]
        if parasitic_current >= config.battery_max_current_a:
            states, _ = with_pwm_scale(0.0)
            return tuple(states), parasitic_current, True  # type: ignore[return-value]
        lower_scale = 0.0
        upper_scale = 1.0
        for _ in range(28):
            midpoint = 0.5 * (lower_scale + upper_scale)
            _, candidate_current = with_pwm_scale(midpoint)
            if candidate_current > config.battery_max_current_a:
                upper_scale = midpoint
            else:
                lower_scale = midpoint
        states, total_current = with_pwm_scale(lower_scale)
        return tuple(states), min(total_current, config.battery_max_current_a), True  # type: ignore[return-value]

    if resistance == 0.0:
        motors, current, limited = evaluate(ocv)
        return PowertrainSolution(ocv, ocv, current, motors, limited)

    # If the collective current ceiling is active, the load line has the direct solution
    # V = OCV - I_limit*R. Avoid nesting the current-limit and load-line bisections.
    current_limited_voltage = max(0.0, ocv - config.battery_max_current_a * resistance)
    limited_state = evaluate(current_limited_voltage)
    if limited_state[2]:
        motors, current, limited = limited_state
        return PowertrainSolution(ocv, current_limited_voltage, current, motors, limited)

    lower_voltage = 0.0
    upper_voltage = ocv
    lower_state = evaluate(lower_voltage)
    upper_state = evaluate(upper_voltage)
    lower_residual = lower_voltage + resistance * lower_state[1] - ocv
    upper_residual = upper_voltage + resistance * upper_state[1] - ocv
    if lower_residual > 0.0 or upper_residual < 0.0:
        raise FloatingPointError("battery load-line root is not bracketed")
    for _ in range(40):
        terminal_voltage = 0.5 * (lower_voltage + upper_voltage)
        candidate = evaluate(terminal_voltage)
        residual = terminal_voltage + resistance * candidate[1] - ocv
        if residual < 0.0:
            lower_voltage = terminal_voltage
        else:
            upper_voltage = terminal_voltage
    terminal_voltage = 0.5 * (lower_voltage + upper_voltage)
    motors, current, limited = evaluate(terminal_voltage)
    return PowertrainSolution(ocv, terminal_voltage, current, motors, limited)
