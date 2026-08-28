from __future__ import annotations

import math
from copy import deepcopy

import pytest

from crazyswarm_app.domain.commands import MoveRelativeCommand, TakeoffCommand
from crazyswarm_app.domain.models import CoordinateFrame
from crazyswarm_app.safety.obstacle_avoidance import (
    AvoidanceDecision,
    AvoidanceMode,
    as_post_dispatch,
    evaluate_move_relative,
    evaluate_takeoff,
    required_range_m,
)
from crazyswarm_app.vehicles.crazyflie_link import CrazyflieRawSample


def sample(*, now: float = 100.0) -> CrazyflieRawSample:
    values = {
        "stabilizer.yaw": 0.0,
        "stateEstimate.vx": 0.0,
        "stateEstimate.vy": 0.0,
        "stateEstimate.vz": 0.0,
        "stateEstimate.z": 0.10,
        "kalman.varPX": 0.0004,
        "kalman.varPY": 0.0004,
        "kalman.varPZ": 0.0004,
        "range.front": 500.0,
        "range.back": 500.0,
        "range.left": 500.0,
        "range.right": 500.0,
        "range.up": 500.0,
        "range.zrange": 500.0,
    }
    return CrazyflieRawSample(
        source_timestamp_ms=10_000,
        received_at_monotonic_s=now,
        values=values,
        value_received_at_monotonic_s={name: now for name in values},
    )


def oracle_required_range_m(
    speed_m_s: float,
    *,
    var_px_m2: float = 0.0004,
    var_py_m2: float = 0.0004,
) -> float:
    uncertainty_m = max(0.05, 2.0 * math.sqrt(max(var_px_m2, var_py_m2)))
    stop_m = speed_m_s * math.sqrt(speed_m_s / 8.0) if speed_m_s > 0.0 else 0.0
    return 0.055 + uncertainty_m + 0.020 + 0.050 + speed_m_s * 0.800 + stop_m - 0.012


def test_monitor_only_never_changes_or_rejects_invalid_command() -> None:
    command = MoveRelativeCommand(x_m=0.10, duration_s=1.0)

    result = evaluate_move_relative(
        None,
        command,
        mode=AvoidanceMode.MONITOR_ONLY,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.BLOCK_BEFORE_DISPATCH
    assert result.command == command
    assert result.intervention_reason == "invalid_binding_input"


def test_minimum_margin_binds_right_not_fastest_front_ray() -> None:
    raw = sample()
    raw = deepcopy(raw)
    raw.values.update(
        {
            "range.front": 500.0,
            "range.right": 150.0,
        }
    )
    command = MoveRelativeCommand(x_m=0.06, y_m=-0.02, duration_s=1.0)

    result = evaluate_move_relative(
        raw,
        command,
        mode=AvoidanceMode.MONITOR_ONLY,
        evaluation_time_monotonic_s=100.0,
    )

    margins = {item.ray: item.margin_m for item in result.rays}
    assert margins["front"] == pytest.approx(0.2838038475772934)
    assert margins["right"] == pytest.approx(-0.03)
    assert result.binding_ray == "right"
    assert result.minimum_margin_m == pytest.approx(-0.03)
    assert result.decision is AvoidanceDecision.BLOCK_BEFORE_DISPATCH
    assert result.command == command


def test_enforced_progressively_retimes_and_preserves_displacement_and_yaw() -> None:
    raw = sample()
    raw.values["range.front"] = oracle_required_range_m(0.05) * 1_000.0
    command = MoveRelativeCommand(
        x_m=0.10,
        yaw_rad=0.30,
        duration_s=1.0,
        frame=CoordinateFrame.BODY,
    )

    result = evaluate_move_relative(
        raw,
        command,
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.LIMIT
    assert result.safe_speed_m_s == pytest.approx(0.05)
    assert result.command.duration_s == pytest.approx(2.0)
    assert result.command.x_m == command.x_m
    assert result.command.y_m == command.y_m
    assert result.command.yaw_rad == command.yaw_rad
    assert result.command.frame is command.frame


@pytest.mark.parametrize("speed_m_s", [0.0, 0.02, 0.05, 0.10])
def test_required_range_matches_independent_numerical_oracle(speed_m_s: float) -> None:
    assert required_range_m(
        speed_m_s,
        var_px_m2=0.0004,
        var_py_m2=0.0004,
    ) == pytest.approx(oracle_required_range_m(speed_m_s), abs=1e-12)


def test_required_range_uses_the_larger_estimator_variance_axis() -> None:
    expected = oracle_required_range_m(
        0.06,
        var_px_m2=0.0025,
        var_py_m2=0.0004,
    )
    assert required_range_m(
        0.06,
        var_px_m2=0.0025,
        var_py_m2=0.0004,
    ) == pytest.approx(expected)
    assert required_range_m(
        0.06,
        var_px_m2=0.0004,
        var_py_m2=0.0025,
    ) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("range.front", None),
        ("range.front", math.nan),
        ("range.front", -1.0),
        ("range.front", 4_000.0),
        ("kalman.varPX", -0.01),
        ("stateEstimate.vx", math.inf),
    ],
)
def test_enforced_invalid_binding_inputs_block_before_dispatch(
    field: str,
    value: float | None,
) -> None:
    raw = sample()
    if value is None:
        raw.values.pop(field)
    else:
        raw.values[field] = value

    result = evaluate_move_relative(
        raw,
        MoveRelativeCommand(x_m=0.10, duration_s=1.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.BLOCK_BEFORE_DISPATCH
    assert result.intervention_reason == "invalid_binding_input"
    assert field in result.invalid_fields


def test_per_variable_staleness_blocks_and_post_dispatch_requests_stop_and_hold() -> None:
    raw = sample()
    raw.value_received_at_monotonic_s["range.front"] = 99.599999

    result = evaluate_move_relative(
        raw,
        MoveRelativeCommand(x_m=0.10, duration_s=1.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )
    post_dispatch = as_post_dispatch(result)

    assert "range.front.age" in result.invalid_fields
    assert post_dispatch.decision is AvoidanceDecision.STOP_AND_HOLD
    assert post_dispatch.intervention_reason == "invalid_binding_input"


def test_exact_maximum_sample_age_is_inclusively_valid() -> None:
    raw = sample()
    for name in raw.value_received_at_monotonic_s:
        raw.value_received_at_monotonic_s[name] = 99.6

    result = evaluate_move_relative(
        raw,
        MoveRelativeCommand(x_m=0.10, duration_s=1.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.CLEAR
    assert result.invalid_fields == ()


def test_invalid_nonclosing_range_is_ignored() -> None:
    raw = sample()
    raw.values.pop("range.back")
    raw.value_received_at_monotonic_s.pop("range.back")

    result = evaluate_move_relative(
        raw,
        MoveRelativeCommand(x_m=0.10, duration_s=1.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.CLEAR
    assert result.invalid_fields == ()


def test_empty_timestamp_map_uses_whole_sample_receive_time() -> None:
    raw = sample()
    raw.value_received_at_monotonic_s.clear()

    result = evaluate_move_relative(
        raw,
        MoveRelativeCommand(x_m=0.10, duration_s=1.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.CLEAR


def test_partially_populated_timestamp_map_never_fabricates_closing_ray_time() -> None:
    raw = sample()
    raw.value_received_at_monotonic_s.pop("range.front")

    result = evaluate_move_relative(
        raw,
        MoveRelativeCommand(x_m=0.10, duration_s=1.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.BLOCK_BEFORE_DISPATCH
    assert "range.front.received_at" in result.invalid_fields


def test_home_frame_projection_at_yaw_pi_over_two_binds_right() -> None:
    raw = sample()
    raw.values["stabilizer.yaw"] = 90.0
    raw.values["range.right"] = 200.0

    result = evaluate_move_relative(
        raw,
        MoveRelativeCommand(
            x_m=0.06,
            duration_s=1.0,
            frame=CoordinateFrame.HOME,
        ),
        mode=AvoidanceMode.MONITOR_ONLY,
        evaluation_time_monotonic_s=100.0,
    )

    rays = {item.ray: item for item in result.rays}
    assert rays["right"].closing_speed_m_s == pytest.approx(0.06)
    assert rays["front"].closing_speed_m_s == pytest.approx(0.0)
    assert result.binding_ray == "right"


@pytest.mark.parametrize(
    ("z_m", "ray", "range_variable"),
    [
        (0.10, "up", "range.up"),
        (-0.10, "down", "range.zrange"),
    ],
)
def test_vertical_relative_move_binds_vertical_ray_and_retimes(
    z_m: float,
    ray: str,
    range_variable: str,
) -> None:
    raw = sample()
    raw.values[range_variable] = oracle_required_range_m(0.05) * 1_000.0

    result = evaluate_move_relative(
        raw,
        MoveRelativeCommand(z_m=z_m, duration_s=1.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.LIMIT
    assert result.binding_ray == ray
    assert result.safe_speed_m_s == pytest.approx(0.05)
    assert result.command.duration_s == pytest.approx(2.0)
    assert result.command.z_m == z_m


def test_takeoff_blocks_when_upward_clearance_is_inside_stopping_envelope() -> None:
    raw = sample()
    raw.values["range.up"] = 100.0

    result = evaluate_takeoff(
        raw,
        TakeoffCommand(height_m=0.30, duration_s=2.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.BLOCK_BEFORE_DISPATCH
    assert result.binding_ray == "up"
    assert result.command.height_m == pytest.approx(0.30)


def test_takeoff_from_floor_ignores_nonclosing_down_ray() -> None:
    raw = sample()
    raw.values.update(
        {
            "stateEstimate.z": 0.029,
            "range.up": 2_408.0,
            "range.zrange": 27.0,
        }
    )

    result = evaluate_takeoff(
        raw,
        TakeoffCommand(height_m=0.30, duration_s=2.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.LIMIT
    assert result.binding_ray == "up"
    assert result.safe_speed_m_s == pytest.approx(0.10)
    assert result.command.height_m == pytest.approx(0.30)
    assert result.command.duration_s == pytest.approx(2.71)
    assert {ray.ray for ray in result.rays} == {"up"}


def test_missing_nonclosing_vertical_range_does_not_block_horizontal_move() -> None:
    raw = sample()
    raw.values.pop("range.up")
    raw.value_received_at_monotonic_s.pop("range.up")

    result = evaluate_move_relative(
        raw,
        MoveRelativeCommand(x_m=0.10, duration_s=1.0),
        mode=AvoidanceMode.ENFORCED,
        evaluation_time_monotonic_s=100.0,
    )

    assert result.decision is AvoidanceDecision.CLEAR
    assert result.invalid_fields == ()
