from __future__ import annotations

import math
from typing import Literal

from crazyswarm_app.domain.commands import (
    BodyRateThrustCommand,
    BodyRateThrustSetpoint,
)

ACROBATICS_CLUSTER_ID = "cushioned-acrobatics"
SINGLE_ROLL_MOTION_ID = "acro-single-roll"
SINGLE_ROLL_PROFILE_ID = "cf21-cubic-roll-rate-v1"

# The reference profile is deliberately immutable. Tuning it for a particular
# airframe is a later, evidence-producing activity rather than an operator input.
SAMPLE_PERIOD_S = 0.01
BOOST_DURATION_S = 0.25
REFERENCE_ROTATION_DEG = 360.0
REFERENCE_PEAK_RATE_DEG_S = 1_400.0
REFERENCE_THRUST_PERCENT = 100.0
ACROBATICS_HOVER_HEIGHT_M = 0.50
ACROBATICS_MAX_ABS_XY_M = 0.50
ACROBATICS_TRIGGER_TIMEOUT_S = 60.0
ACROBATICS_RECOVERY_DURATION_S = 1.0


def _cubic_roll_rate_deg_s(time_s: float) -> float:
    """Continuous 0→peak→0 rate profile whose integral is one full roll.

    This is the one-flip cubic construction used by the public Crazyflie
    ``Drone_Acrobatics`` experiment, expressed here as an explicit rate command
    instead of relying on firmware mode parameters.
    """

    half_rotation_deg = REFERENCE_ROTATION_DEG / 2.0
    gamma_s = half_rotation_deg / REFERENCE_PEAK_RATE_DEG_S
    ramp_duration_s = 2.0 * gamma_s
    beta = -0.75 * gamma_s**-3 * REFERENCE_PEAK_RATE_DEG_S
    if not 0.0 <= time_s <= 2.0 * ramp_duration_s:
        raise ValueError("roll-profile time is outside the authored rotation")
    if time_s <= ramp_duration_s:
        return (
            beta / 3.0 * (time_s - gamma_s) ** 3
            - beta * gamma_s**2 * time_s
            + beta * gamma_s**3 / 3.0
        )
    remaining_s = 2.0 * ramp_duration_s - time_s
    return (
        beta / 3.0 * (remaining_s - gamma_s) ** 3
        - beta * gamma_s**2 * remaining_s
        + beta * gamma_s**3 / 3.0
    )


def single_roll_rate_thrust_command(
    *,
    direction: Literal["positive", "negative"] = "positive",
) -> BodyRateThrustCommand:
    """Build the exact finite stream consumed by the Crazyflie rate controller.

    The 25-sample collective boost is followed by a sampled cubic 360-degree roll
    rate and one zero-rate handoff sample. The sampled rates are normalized so the
    zero-order-held command integrates to exactly one authored rotation even though
    the continuous reference duration is not an integer multiple of 10 ms.
    """

    boost_samples = round(BOOST_DURATION_S / SAMPLE_PERIOD_S)
    continuous_rotation_duration_s = 2.0 * REFERENCE_ROTATION_DEG / REFERENCE_PEAK_RATE_DEG_S
    rotation_samples = math.ceil(continuous_rotation_duration_s / SAMPLE_PERIOD_S)
    continuous_sample_period_s = continuous_rotation_duration_s / rotation_samples
    raw_rates = tuple(
        _cubic_roll_rate_deg_s((index + 0.5) * continuous_sample_period_s)
        for index in range(rotation_samples)
    )
    sampled_rotation_deg = sum(raw_rates) * SAMPLE_PERIOD_S
    normalization = REFERENCE_ROTATION_DEG / sampled_rotation_deg
    sign = 1.0 if direction == "positive" else -1.0

    boost = tuple(
        BodyRateThrustSetpoint(thrust_percent=REFERENCE_THRUST_PERCENT)
        for _ in range(boost_samples)
    )
    rotation = tuple(
        BodyRateThrustSetpoint(
            roll_rate_deg_s=sign * rate_deg_s * normalization,
            thrust_percent=REFERENCE_THRUST_PERCENT,
        )
        for rate_deg_s in raw_rates
    )
    handoff = BodyRateThrustSetpoint(thrust_percent=REFERENCE_THRUST_PERCENT)
    setpoints = (*boost, *rotation, handoff)
    return BodyRateThrustCommand(
        profile_id=SINGLE_ROLL_PROFILE_ID,
        sample_period_s=SAMPLE_PERIOD_S,
        duration_s=len(setpoints) * SAMPLE_PERIOD_S,
        max_abs_xy_displacement_m=ACROBATICS_MAX_ABS_XY_M,
        setpoints=setpoints,
    )
