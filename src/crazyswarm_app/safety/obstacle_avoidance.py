from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TypeGuard

from crazyswarm_app.domain.commands import HoverCommand, MoveRelativeCommand, TakeoffCommand
from crazyswarm_app.domain.models import CoordinateFrame
from crazyswarm_app.vehicles.crazyflie_link import CrazyflieRawSample

VEHICLE_RADIUS_M = 0.055
SENSOR_OFFSET_M = 0.012
MINIMUM_ESTIMATOR_UNCERTAINTY_M = 0.05
RANGE_UNCERTAINTY_M = 0.02
POLICY_MARGIN_M = 0.05
REACTION_LATENCY_S = 0.80
MAXIMUM_ACCELERATION_M_S2 = 1.0
MAXIMUM_JERK_M_S3 = 8.0
SPEED_CAP_M_S = 0.10
SPEED_FLOOR_M_S = 0.02
MAXIMUM_SAMPLE_AGE_S = 0.40
SAMPLE_AGE_ROUNDING_TOLERANCE_S = 1e-12
DEFAULT_MAXIMUM_RANGE_M = 4.0

RAYS = ("front", "back", "left", "right", "up", "down")
RAY_VECTORS = (
    ("front", 1.0, 0.0, 0.0),
    ("back", -1.0, 0.0, 0.0),
    ("left", 0.0, 1.0, 0.0),
    ("right", 0.0, -1.0, 0.0),
    ("up", 0.0, 0.0, 1.0),
    ("down", 0.0, 0.0, -1.0),
)
RANGE_VARIABLES = {
    "front": "range.front",
    "back": "range.back",
    "left": "range.left",
    "right": "range.right",
    "up": "range.up",
    "down": "range.zrange",
}
KINEMATIC_VARIABLES = (
    "stabilizer.yaw",
    "stateEstimate.vx",
    "stateEstimate.vy",
    "stateEstimate.vz",
    "stateEstimate.z",
    "kalman.varPX",
    "kalman.varPY",
    "kalman.varPZ",
)


class AvoidanceMode(StrEnum):
    MONITOR_ONLY = "MONITOR_ONLY"
    ENFORCED = "ENFORCED"


class AvoidanceDecision(StrEnum):
    CLEAR = "CLEAR"
    LIMIT = "LIMIT"
    BLOCK_BEFORE_DISPATCH = "BLOCK_BEFORE_DISPATCH"
    STOP_AND_HOLD = "STOP_AND_HOLD"
    HOLD_CONFIRMED = "HOLD_CONFIRMED"
    HOLD_FAILED = "HOLD_FAILED"
    RECOVER_ABORT_LAND = "RECOVER_ABORT_LAND"
    RECORD_ONLY = "RECORD_ONLY"


@dataclass(frozen=True, slots=True)
class RayMargin:
    ray: str
    measured_range_m: float
    closing_speed_m_s: float
    required_range_m: float
    margin_m: float


@dataclass(frozen=True, slots=True)
class AvoidanceEvaluation:
    mode: AvoidanceMode
    decision: AvoidanceDecision
    minimum_margin_m: float | None
    binding_ray: str | None
    intervention_reason: str
    requested_speed_m_s: float
    safe_speed_m_s: float | None
    command: MoveRelativeCommand | HoverCommand | TakeoffCommand
    rays: tuple[RayMargin, ...] = ()
    invalid_fields: tuple[str, ...] = ()

    def evidence(self, *, phase: str) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "decision": self.decision.value,
            "phase": phase,
            "minimum_margin_m": self.minimum_margin_m,
            "binding_ray": self.binding_ray,
            "intervention_reason": self.intervention_reason,
            "requested_speed_m_s": self.requested_speed_m_s,
            "safe_speed_m_s": self.safe_speed_m_s,
            "command_duration_s": self.command.duration_s,
            "invalid_fields": list(self.invalid_fields),
            "rays": [
                {
                    "ray": item.ray,
                    "measured_range_m": item.measured_range_m,
                    "closing_speed_m_s": item.closing_speed_m_s,
                    "required_range_m": item.required_range_m,
                    "margin_m": item.margin_m,
                }
                for item in self.rays
            ],
        }


def jerk_limited_braking_distance_m(speed_m_s: float) -> float:
    if speed_m_s <= 0.0:
        return 0.0
    ramp_s = MAXIMUM_ACCELERATION_M_S2 / MAXIMUM_JERK_M_S3
    ramp_delta_m_s = 0.5 * MAXIMUM_ACCELERATION_M_S2 * ramp_s
    if speed_m_s <= 2.0 * ramp_delta_m_s:
        return speed_m_s * math.sqrt(speed_m_s / MAXIMUM_JERK_M_S3)
    hold_s = (speed_m_s - 2.0 * ramp_delta_m_s) / MAXIMUM_ACCELERATION_M_S2
    first_m = (
        speed_m_s * ramp_s
        - MAXIMUM_JERK_M_S3 * ramp_s**3 / 6.0
    )
    first_end_m_s = speed_m_s - ramp_delta_m_s
    middle_m = (
        first_end_m_s * hold_s
        - 0.5 * MAXIMUM_ACCELERATION_M_S2 * hold_s**2
    )
    final_m = (
        ramp_delta_m_s * ramp_s
        - 0.5 * MAXIMUM_ACCELERATION_M_S2 * ramp_s**2
        + MAXIMUM_JERK_M_S3 * ramp_s**3 / 6.0
    )
    return first_m + middle_m + final_m


def required_range_m(
    closing_speed_m_s: float,
    *,
    var_px_m2: float,
    var_py_m2: float,
) -> float:
    estimator_uncertainty_m = max(
        MINIMUM_ESTIMATOR_UNCERTAINTY_M,
        2.0 * math.sqrt(max(var_px_m2, var_py_m2)),
    )
    return (
        VEHICLE_RADIUS_M
        + estimator_uncertainty_m
        + RANGE_UNCERTAINTY_M
        + closing_speed_m_s * REACTION_LATENCY_S
        + jerk_limited_braking_distance_m(closing_speed_m_s)
        + POLICY_MARGIN_M
        - SENSOR_OFFSET_M
    )


def evaluate_move_relative(
    sample: CrazyflieRawSample | None,
    command: MoveRelativeCommand,
    *,
    mode: AvoidanceMode,
    evaluation_time_monotonic_s: float,
    maximum_range_m: float = DEFAULT_MAXIMUM_RANGE_M,
) -> AvoidanceEvaluation:
    return _evaluate_command(
        sample,
        command,
        mode=mode,
        evaluation_time_monotonic_s=evaluation_time_monotonic_s,
        maximum_range_m=maximum_range_m,
    )


def evaluate_hover(
    sample: CrazyflieRawSample | None,
    command: HoverCommand,
    *,
    mode: AvoidanceMode,
    evaluation_time_monotonic_s: float,
    maximum_range_m: float = DEFAULT_MAXIMUM_RANGE_M,
) -> AvoidanceEvaluation:
    return _evaluate_command(
        sample,
        command,
        mode=mode,
        evaluation_time_monotonic_s=evaluation_time_monotonic_s,
        maximum_range_m=maximum_range_m,
    )


def evaluate_takeoff(
    sample: CrazyflieRawSample | None,
    command: TakeoffCommand,
    *,
    mode: AvoidanceMode,
    evaluation_time_monotonic_s: float,
    maximum_range_m: float = DEFAULT_MAXIMUM_RANGE_M,
) -> AvoidanceEvaluation:
    return _evaluate_command(
        sample,
        command,
        mode=mode,
        evaluation_time_monotonic_s=evaluation_time_monotonic_s,
        maximum_range_m=maximum_range_m,
    )


def _evaluate_command(
    sample: CrazyflieRawSample | None,
    command: MoveRelativeCommand | HoverCommand | TakeoffCommand,
    *,
    mode: AvoidanceMode,
    evaluation_time_monotonic_s: float,
    maximum_range_m: float,
) -> AvoidanceEvaluation:
    invalid_fields = _invalid_fields(
        sample,
        evaluation_time_monotonic_s=evaluation_time_monotonic_s,
        maximum_range_m=maximum_range_m,
        closing_rays=None,
    )
    if invalid_fields:
        return AvoidanceEvaluation(
            mode=mode,
            decision=AvoidanceDecision.BLOCK_BEFORE_DISPATCH,
            minimum_margin_m=0.0,
            binding_ray=None,
            intervention_reason="invalid_binding_input",
            requested_speed_m_s=0.0,
            safe_speed_m_s=None,
            command=command,
            invalid_fields=invalid_fields,
        )

    assert sample is not None
    values = sample.values
    displacement_x_m, displacement_y_m, displacement_z_m = _command_displacement(
        command,
        current_z_m=values["stateEstimate.z"],
    )
    distance_m = math.sqrt(
        displacement_x_m**2 + displacement_y_m**2 + displacement_z_m**2
    )
    requested_speed_m_s = distance_m / command.duration_s
    yaw_rad = math.radians(values["stabilizer.yaw"])
    measured_body_x, measured_body_y = _home_to_body(
        values["stateEstimate.vx"],
        values["stateEstimate.vy"],
        yaw_rad,
    )
    measured_body_z = values["stateEstimate.vz"]
    unit_x = displacement_x_m / distance_m if distance_m > 1e-12 else 0.0
    unit_y = displacement_y_m / distance_m if distance_m > 1e-12 else 0.0
    unit_z = displacement_z_m / distance_m if distance_m > 1e-12 else 0.0
    if isinstance(command, MoveRelativeCommand) and command.frame is CoordinateFrame.HOME:
        command_body_unit_x, command_body_unit_y = _home_to_body(
            unit_x,
            unit_y,
            yaw_rad,
        )
    else:
        command_body_unit_x, command_body_unit_y = unit_x, unit_y
    command_body_x_m_s = command_body_unit_x * requested_speed_m_s
    command_body_y_m_s = command_body_unit_y * requested_speed_m_s
    command_body_z_m_s = unit_z * requested_speed_m_s
    closing_rays = {
        ray
        for ray, ray_x, ray_y, ray_z in RAY_VECTORS
        if max(
            ray_x * measured_body_x + ray_y * measured_body_y + ray_z * measured_body_z,
            ray_x * command_body_x_m_s
            + ray_y * command_body_y_m_s
            + ray_z * command_body_z_m_s,
        )
        > 1e-12
    }
    invalid_fields = _invalid_fields(
        sample,
        evaluation_time_monotonic_s=evaluation_time_monotonic_s,
        maximum_range_m=maximum_range_m,
        closing_rays=closing_rays,
    )
    if invalid_fields:
        return AvoidanceEvaluation(
            mode=mode,
            decision=AvoidanceDecision.BLOCK_BEFORE_DISPATCH,
            minimum_margin_m=0.0,
            binding_ray=None,
            intervention_reason="invalid_binding_input",
            requested_speed_m_s=requested_speed_m_s,
            safe_speed_m_s=None,
            command=command,
            invalid_fields=invalid_fields,
        )
    ranges_m: dict[str, float] = {}
    for ray, variable in RANGE_VARIABLES.items():
        value = values.get(variable)
        if _finite(value) and 0.0 <= value < maximum_range_m * 1_000.0:
            ranges_m[ray] = value / 1_000.0
    var_px_m2 = values["kalman.varPX"]
    var_py_m2 = values["kalman.varPY"]
    var_pz_m2 = values["kalman.varPZ"]

    requested_rays = _ray_margins(
        ranges_m=ranges_m,
        measured_body_x_m_s=measured_body_x,
        measured_body_y_m_s=measured_body_y,
        measured_body_z_m_s=measured_body_z,
        command_body_x_m_s=command_body_x_m_s,
        command_body_y_m_s=command_body_y_m_s,
        command_body_z_m_s=command_body_z_m_s,
        var_px_m2=var_px_m2,
        var_py_m2=var_py_m2,
        var_pz_m2=var_pz_m2,
    )
    binding = (
        min(requested_rays, key=lambda item: item.margin_m)
        if requested_rays
        else None
    )
    safe_speed_m_s = _maximum_safe_speed(
        ranges_m=ranges_m,
        measured_body_x_m_s=measured_body_x,
        measured_body_y_m_s=measured_body_y,
        measured_body_z_m_s=measured_body_z,
        command_body_unit_x=command_body_unit_x,
        command_body_unit_y=command_body_unit_y,
        command_body_unit_z=unit_z,
        var_px_m2=var_px_m2,
        var_py_m2=var_py_m2,
        var_pz_m2=var_pz_m2,
    )

    if (
        requested_speed_m_s <= 0.0
        and binding is not None
        and binding.margin_m < -1e-12
    ) or (
        requested_speed_m_s > 0.0
        and safe_speed_m_s < SPEED_FLOOR_M_S - 1e-12
    ):
        decision = AvoidanceDecision.BLOCK_BEFORE_DISPATCH
        retimed_command = command
        reason = "insufficient_clearance"
    elif requested_speed_m_s <= safe_speed_m_s + 1e-12:
        decision = AvoidanceDecision.CLEAR
        retimed_command = command
        reason = "none"
    else:
        decision = AvoidanceDecision.LIMIT
        assert isinstance(command, MoveRelativeCommand | TakeoffCommand)
        retimed_command = command.model_copy(
            update={"duration_s": distance_m / safe_speed_m_s}
        )
        reason = "insufficient_clearance"
    if mode is AvoidanceMode.MONITOR_ONLY:
        retimed_command = command
    return AvoidanceEvaluation(
        mode=mode,
        decision=decision,
        minimum_margin_m=binding.margin_m if binding else None,
        binding_ray=binding.ray if binding else None,
        intervention_reason=reason,
        requested_speed_m_s=requested_speed_m_s,
        safe_speed_m_s=safe_speed_m_s,
        command=retimed_command,
        rays=requested_rays,
    )


def as_post_dispatch(evaluation: AvoidanceEvaluation) -> AvoidanceEvaluation:
    if (
        evaluation.mode is AvoidanceMode.ENFORCED
        and evaluation.decision
        in {AvoidanceDecision.LIMIT, AvoidanceDecision.BLOCK_BEFORE_DISPATCH}
    ):
        return replace(
            evaluation,
            decision=AvoidanceDecision.STOP_AND_HOLD,
            intervention_reason=(
                "invalid_binding_input"
                if evaluation.invalid_fields
                else "unsafe_closing_speed"
            ),
        )
    return evaluation


def _invalid_fields(
    sample: CrazyflieRawSample | None,
    *,
    evaluation_time_monotonic_s: float,
    maximum_range_m: float,
    closing_rays: set[str] | None,
) -> tuple[str, ...]:
    if sample is None:
        return ("sample",)
    invalid: list[str] = []
    if not _finite(evaluation_time_monotonic_s):
        invalid.append("evaluation_time")
    if not _finite(maximum_range_m) or maximum_range_m <= 0.0:
        invalid.append("maximum_range")
    values = sample.values
    for variable in KINEMATIC_VARIABLES:
        value = values.get(variable)
        if not _finite(value) or (variable.startswith("kalman.varP") and value < 0.0):
            invalid.append(variable)
        received_at = _received_at(sample, variable)
        if not _finite(received_at):
            invalid.append(f"{variable}.received_at")
        elif _finite(evaluation_time_monotonic_s):
            age_s = evaluation_time_monotonic_s - received_at
            if not _sample_age_is_valid(age_s):
                invalid.append(f"{variable}.age")
    if closing_rays is None or invalid:
        return tuple(dict.fromkeys(invalid))
    for ray, variable in RANGE_VARIABLES.items():
        value = values.get(variable)
        valid = _finite(value) and 0.0 <= value < maximum_range_m * 1_000.0
        received_at = _received_at(sample, variable)
        age_valid = False
        if _finite(received_at) and _finite(evaluation_time_monotonic_s):
            age_s = evaluation_time_monotonic_s - received_at
            age_valid = _sample_age_is_valid(age_s)
        if ray not in closing_rays:
            continue
        if not valid:
            invalid.append(variable)
        if not _finite(received_at):
            invalid.append(f"{variable}.received_at")
        elif not age_valid:
            invalid.append(f"{variable}.age")
    return tuple(dict.fromkeys(invalid))


def _received_at(sample: CrazyflieRawSample, variable: str) -> float | None:
    timestamps = sample.value_received_at_monotonic_s
    if not timestamps:
        return sample.received_at_monotonic_s
    return timestamps.get(variable)


def _sample_age_is_valid(age_s: float) -> bool:
    return age_s >= 0.0 and (
        age_s <= MAXIMUM_SAMPLE_AGE_S
        or math.isclose(
            age_s,
            MAXIMUM_SAMPLE_AGE_S,
            rel_tol=0.0,
            abs_tol=SAMPLE_AGE_ROUNDING_TOLERANCE_S,
        )
    )


def _maximum_safe_speed(
    *,
    ranges_m: dict[str, float],
    measured_body_x_m_s: float,
    measured_body_y_m_s: float,
    measured_body_z_m_s: float,
    command_body_unit_x: float,
    command_body_unit_y: float,
    command_body_unit_z: float,
    var_px_m2: float,
    var_py_m2: float,
    var_pz_m2: float,
) -> float:
    def admitted(speed_m_s: float) -> bool:
        margins = _ray_margins(
            ranges_m=ranges_m,
            measured_body_x_m_s=measured_body_x_m_s,
            measured_body_y_m_s=measured_body_y_m_s,
            measured_body_z_m_s=measured_body_z_m_s,
            command_body_x_m_s=command_body_unit_x * speed_m_s,
            command_body_y_m_s=command_body_unit_y * speed_m_s,
            command_body_z_m_s=command_body_unit_z * speed_m_s,
            var_px_m2=var_px_m2,
            var_py_m2=var_py_m2,
            var_pz_m2=var_pz_m2,
        )
        return (
            not margins
            or min(margins, key=lambda item: item.margin_m).margin_m >= -1e-12
        )

    if not admitted(0.0):
        return 0.0
    if admitted(SPEED_CAP_M_S):
        return SPEED_CAP_M_S
    low, high = 0.0, SPEED_CAP_M_S
    for _ in range(60):
        midpoint = (low + high) / 2.0
        if admitted(midpoint):
            low = midpoint
        else:
            high = midpoint
    return low


def _ray_margins(
    *,
    ranges_m: dict[str, float],
    measured_body_x_m_s: float,
    measured_body_y_m_s: float,
    measured_body_z_m_s: float,
    command_body_x_m_s: float,
    command_body_y_m_s: float,
    command_body_z_m_s: float,
    var_px_m2: float,
    var_py_m2: float,
    var_pz_m2: float,
) -> tuple[RayMargin, ...]:
    closing = {
        "front": max(0.0, measured_body_x_m_s, command_body_x_m_s),
        "back": max(0.0, -measured_body_x_m_s, -command_body_x_m_s),
        "left": max(0.0, measured_body_y_m_s, command_body_y_m_s),
        "right": max(0.0, -measured_body_y_m_s, -command_body_y_m_s),
        "up": max(0.0, measured_body_z_m_s, command_body_z_m_s),
        "down": max(0.0, -measured_body_z_m_s, -command_body_z_m_s),
    }
    horizontal_variance_m2 = max(var_px_m2, var_py_m2)

    def variance_for(ray: str) -> float:
        return var_pz_m2 if ray in {"up", "down"} else horizontal_variance_m2

    return tuple(
        RayMargin(
            ray=ray,
            measured_range_m=ranges_m[ray],
            closing_speed_m_s=closing[ray],
            required_range_m=(
                required_range_m(
                    closing[ray],
                    var_px_m2=variance_for(ray),
                    var_py_m2=variance_for(ray),
                )
            ),
            margin_m=(
                ranges_m[ray]
                - required_range_m(
                    closing[ray],
                    var_px_m2=variance_for(ray),
                    var_py_m2=variance_for(ray),
                )
            ),
        )
        for ray in RAYS
        if ray in ranges_m
    )


def _command_displacement(
    command: MoveRelativeCommand | HoverCommand | TakeoffCommand,
    *,
    current_z_m: float,
) -> tuple[float, float, float]:
    if isinstance(command, MoveRelativeCommand):
        return command.x_m, command.y_m, command.z_m
    if isinstance(command, TakeoffCommand):
        return 0.0, 0.0, max(0.0, command.height_m - current_z_m)
    return 0.0, 0.0, 0.0


def _home_to_body(x_m_s: float, y_m_s: float, yaw_rad: float) -> tuple[float, float]:
    cosine, sine = math.cos(yaw_rad), math.sin(yaw_rad)
    return (
        x_m_s * cosine + y_m_s * sine,
        -x_m_s * sine + y_m_s * cosine,
    )


def _finite(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )
