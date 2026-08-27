from __future__ import annotations

import pytest

from crazyswarm_app.hardware.acrobatics_lab import (
    ACROBATICS_MAX_ABS_XY_M,
    BOOST_DURATION_S,
    REFERENCE_PEAK_RATE_DEG_S,
    REFERENCE_ROTATION_DEG,
    REFERENCE_THRUST_PERCENT,
    SAMPLE_PERIOD_S,
    single_roll_rate_thrust_command,
)


def test_single_roll_stream_has_exact_sampled_rotation_and_safe_handoff() -> None:
    command = single_roll_rate_thrust_command()
    boost_samples = round(BOOST_DURATION_S / SAMPLE_PERIOD_S)

    assert command.profile_id == "cf21-cubic-roll-rate-v1"
    assert command.sample_period_s == SAMPLE_PERIOD_S
    assert command.duration_s == pytest.approx(len(command.setpoints) * SAMPLE_PERIOD_S)
    assert command.max_abs_xy_displacement_m == ACROBATICS_MAX_ABS_XY_M == 0.50
    assert all(setpoint.roll_rate_deg_s == 0.0 for setpoint in command.setpoints[:boost_samples])
    assert sum(
        setpoint.roll_rate_deg_s * command.sample_period_s for setpoint in command.setpoints
    ) == pytest.approx(REFERENCE_ROTATION_DEG, abs=1e-9)
    assert max(setpoint.roll_rate_deg_s for setpoint in command.setpoints) <= (
        REFERENCE_PEAK_RATE_DEG_S
    )
    assert all(setpoint.pitch_rate_deg_s == 0.0 for setpoint in command.setpoints)
    assert all(setpoint.yaw_rate_deg_s == 0.0 for setpoint in command.setpoints)
    assert all(
        setpoint.thrust_percent == REFERENCE_THRUST_PERCENT for setpoint in command.setpoints
    )
    terminal = command.setpoints[-1]
    assert terminal.roll_rate_deg_s == 0.0
    assert terminal.pitch_rate_deg_s == 0.0
    assert terminal.yaw_rate_deg_s == 0.0


def test_single_roll_direction_is_explicit_and_symmetric() -> None:
    positive = single_roll_rate_thrust_command(direction="positive")
    negative = single_roll_rate_thrust_command(direction="negative")

    assert len(positive.setpoints) == len(negative.setpoints)
    assert tuple(item.roll_rate_deg_s for item in negative.setpoints) == pytest.approx(
        tuple(-item.roll_rate_deg_s for item in positive.setpoints)
    )
    assert sum(
        setpoint.roll_rate_deg_s * negative.sample_period_s for setpoint in negative.setpoints
    ) == pytest.approx(-REFERENCE_ROTATION_DEG, abs=1e-9)
