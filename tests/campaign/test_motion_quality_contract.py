import csv
import io
import math
from pathlib import Path

from crazyswarm_app.campaign.analyzer import (
    _accepted_trajectory_horizontal_turn,
    _distance_to_polyline,
    _independent_trajectory_position,
    _nominal_route_path_errors,
    _retained_trajectory_authority_start,
    _Sample,
    analyze_motion_quality_csv,
)
from crazyswarm_app.campaign.catalog import ONE_DRONE_FAMILY_ORDER, CampaignCatalog
from crazyswarm_app.campaign.models import MotionQualityContract, MotionSpeedLaw
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256


def _csv(
    *,
    angular_spike: float = 0.0,
    lateral_offset_m: float = 0.0,
    speeds_m_s: tuple[float, ...] | None = None,
) -> bytes:
    columns = [
        "vehicle_id",
        "recorded_at_utc",
        "source_timestamp_s",
        "simulation_timestamp_s",
        "telemetry_sequence",
        "velocity_x_m_s",
        "velocity_y_m_s",
        "velocity_z_m_s",
        "ground_truth_x_m",
        "ground_truth_y_m",
        "ground_truth_z_m",
        "imu_angular_velocity_x_rad_s",
        "imu_angular_velocity_y_rad_s",
        "imu_angular_velocity_z_rad_s",
        "battery_voltage_v",
        "battery_current_a",
        *(
            column
            for index in range(1, 5)
            for column in (
                f"motor_m{index}_applied_pwm_percent",
                f"motor_m{index}_thrust_n",
                f"motor_m{index}_available_thrust_n",
                f"motor_m{index}_saturated",
            )
        ),
    ]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for index in range(8):
        speed_m_s = speeds_m_s[index] if speeds_m_s is not None else 0.3
        row = {
            "vehicle_id": "Alpha",
            "recorded_at_utc": f"2026-01-01T00:00:0{index}Z",
            "source_timestamp_s": index * 0.1,
            "simulation_timestamp_s": index * 0.1,
            "telemetry_sequence": index + 1,
            "velocity_x_m_s": speed_m_s,
            "velocity_y_m_s": 0.0,
            "velocity_z_m_s": 0.0,
            "ground_truth_x_m": index * 0.03,
            "ground_truth_y_m": lateral_offset_m,
            "ground_truth_z_m": 0.4,
            "imu_angular_velocity_x_rad_s": angular_spike if index == 4 else 0.0,
            "imu_angular_velocity_y_rad_s": 0.0,
            "imu_angular_velocity_z_rad_s": 0.0,
            "battery_voltage_v": 4.0,
            "battery_current_a": 0.5,
        }
        for motor in range(1, 5):
            row[f"motor_m{motor}_applied_pwm_percent"] = 45.0 + motor * 0.05
            row[f"motor_m{motor}_thrust_n"] = 0.07
            row[f"motor_m{motor}_available_thrust_n"] = 0.12
            row[f"motor_m{motor}_saturated"] = "false"
        writer.writerow(row)
    return stream.getvalue().encode()


def _analyze(content: bytes, *, tracking_error_m: float = 0.0):
    return analyze_motion_quality_csv(
        content,
        MotionQualityContract(
            speed_law=MotionSpeedLaw.CONSTANT,
            target_speed_m_s=0.3,
        ),
        planned_route_m=(Vector3(z=0.4), Vector3(x=0.3, z=0.4)),
        minimum_clearance_m=0.3,
        collision_count=0,
        checkpoint_hold_conformance_fraction=1.0,
        minimum_continuous_knot_speed_ratio=1.0,
        unintended_fly_through_stop_count=0,
        motor_differential_sign_agreement_fraction=1.0,
        motor_differential_normalized_error_p95=0.01,
        supervisor_safety_gate_passed=True,
        reference_tracking_errors_m=(tracking_error_m,) * 8,
    )


def test_constant_scalar_speed_does_not_hide_angular_shakiness() -> None:
    analysis = _analyze(_csv(angular_spike=1.0))
    assert analysis.vector.speed_compliance_fraction == 1.0
    assert analysis.vector.speed_ripple_m_s == 0.0
    assert "angular_rate_p95_rad_s" in analysis.failed_guards


def test_smooth_trace_outside_path_tube_fails_tracking_separately() -> None:
    analysis = _analyze(_csv(lateral_offset_m=0.08), tracking_error_m=0.08)
    assert "tracking_rms_m" in analysis.failed_guards
    assert "path_tube_max_error_m" in analysis.failed_guards
    assert "angular_rate_p95_rad_s" not in analysis.failed_guards


def test_temporal_tracking_and_geometric_path_errors_are_independent() -> None:
    analysis = analyze_motion_quality_csv(
        _csv(),
        MotionQualityContract(
            speed_law=MotionSpeedLaw.CONSTANT,
            target_speed_m_s=0.3,
        ),
        planned_route_m=(Vector3(z=0.4), Vector3(x=0.3, z=0.4)),
        minimum_clearance_m=0.3,
        collision_count=0,
        checkpoint_hold_conformance_fraction=1.0,
        minimum_continuous_knot_speed_ratio=1.0,
        unintended_fly_through_stop_count=0,
        motor_differential_sign_agreement_fraction=1.0,
        motor_differential_normalized_error_p95=0.01,
        supervisor_safety_gate_passed=True,
        reference_tracking_errors_m=(0.04, 0.04),
        reference_path_errors_m=(0.01, 0.02),
    )

    assert analysis.vector.tracking_rms_m == 0.04
    assert analysis.vector.path_tube_max_error_m == 0.02


def test_nominal_path_oracle_measures_truth_to_authored_polyline() -> None:
    rows = csv.DictReader(io.StringIO(_csv(lateral_offset_m=0.08).decode()))
    samples = tuple(_Sample(row) for row in rows)

    errors = _nominal_route_path_errors(
        samples=samples,
        nominal_route=(Vector3(z=0.4), Vector3(x=0.3, z=0.4)),
        route_start_source_s=0.2,
        landing_start_source_s=0.6,
    )

    assert errors is not None
    assert len(errors) == 4
    assert all(abs(value - 0.08) <= 1e-12 for value in errors)


def test_curvature_oracle_uses_accepted_trajectory_geometry() -> None:
    def point(timestamp_s: float, x: float, y: float) -> dict[str, object]:
        return {
            "time_from_start_s": timestamp_s,
            "position_m": {"x": x, "y": y, "z": 0.4},
            "velocity_m_s": {"x": 0.0, "y": 0.0, "z": 0.0},
            "acceleration_m_s2": {"x": 0.0, "y": 0.0, "z": 0.0},
        }

    straight = {"points": (point(0.0, 0.0, 0.0), point(2.0, 1.0, 0.0))}
    bent = {
        "points": (
            point(0.0, 0.0, 0.0),
            point(1.0, 1.0, 0.0),
            point(2.0, 1.0, 1.0),
        )
    }

    assert _accepted_trajectory_horizontal_turn(straight) <= 1e-12
    assert abs(_accepted_trajectory_horizontal_turn(bent) - math.pi / 2.0) <= 1e-9


def test_independent_temporal_oracle_detects_same_polyline_time_lag() -> None:
    trajectory = {
        "points": (
            {
                "time_from_start_s": 0.0,
                "position_m": {"x": 0.0, "y": 0.0, "z": 0.4},
                "velocity_m_s": {"x": 1.0, "y": 0.0, "z": 0.0},
                "acceleration_m_s2": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
            {
                "time_from_start_s": 1.0,
                "position_m": {"x": 1.0, "y": 0.0, "z": 0.4},
                "velocity_m_s": {"x": 1.0, "y": 0.0, "z": 0.0},
                "acceleration_m_s2": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
        )
    }
    lagged_truth = Vector3(x=0.4, y=0.0, z=0.4)
    reference = _independent_trajectory_position(trajectory, 0.5)

    assert abs(reference.x - 0.5) <= 1e-12
    assert _distance_to_polyline(
        lagged_truth,
        (Vector3(z=0.4), Vector3(x=1.0, z=0.4)),
    ) == 0.0
    assert abs(abs(reference.x - lagged_truth.x) - 0.1) <= 1e-12


def test_temporal_oracle_uses_hash_bound_command_source_receipt() -> None:
    trajectory = {
        "points": (
            {
                "time_from_start_s": 0.0,
                "position_m": {"x": 0.0, "y": 0.0, "z": 0.4},
                "velocity_m_s": {"x": 0.0, "y": 0.0, "z": 0.0},
                "acceleration_m_s2": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
            {
                "time_from_start_s": 1.0,
                "position_m": {"x": 1.0, "y": 0.0, "z": 0.4},
                "velocity_m_s": {"x": 0.0, "y": 0.0, "z": 0.0},
                "acceleration_m_s2": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
        )
    }
    trajectory_sha256 = canonical_sha256(trajectory)
    context = {
        "fleet_result": {
            "child_results": (
                {
                    "task_id": "Alpha",
                    "mission_result": {
                        "normalized_intent_trace": (
                            {
                                "action": "execute_trajectory",
                                "arguments": {
                                    "trajectory_sha256": trajectory_sha256,
                                    "command_received_at_source_s": 3.125,
                                    "command_source_clock_id": "fast-sim-Alpha",
                                    "command_source_clock_epoch": 2,
                                },
                            },
                        )
                    },
                },
            )
        }
    }

    assert _retained_trajectory_authority_start(context, "Alpha", trajectory) == (
        3.125,
        "fast-sim-Alpha",
        2,
    )
    context["fleet_result"]["child_results"][0]["mission_result"][
        "normalized_intent_trace"
    ][0]["arguments"]["trajectory_sha256"] = "f" * 64
    assert _retained_trajectory_authority_start(context, "Alpha", trajectory) is None


def test_temporal_oracle_uses_pre_dispatch_authority_when_cutover_cancels_ack() -> None:
    trajectory = {
        "points": (
            {
                "time_from_start_s": 0.0,
                "position_m": {"x": 0.0, "y": 0.0, "z": 0.4},
                "velocity_m_s": {"x": 0.0, "y": 0.0, "z": 0.0},
                "acceleration_m_s2": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
            {
                "time_from_start_s": 1.0,
                "position_m": {"x": 1.0, "y": 0.0, "z": 0.4},
                "velocity_m_s": {"x": 0.0, "y": 0.0, "z": 0.0},
                "acceleration_m_s2": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
        )
    }
    trajectory_sha256 = canonical_sha256(trajectory)
    arguments = {
        "trajectory_sha256": trajectory_sha256,
        "command_authority_at_source_s": 4.25,
        "command_authority_source_clock_id": "fast-sim-Alpha",
        "command_authority_source_clock_epoch": 3,
    }
    context = {
        "fleet_result": {
            "child_results": (
                {
                    "task_id": "Alpha",
                    "mission_result": {
                        "normalized_intent_trace": (
                            {
                                "action": "execute_trajectory",
                                "arguments": arguments,
                            },
                        )
                    },
                },
            )
        }
    }

    assert _retained_trajectory_authority_start(context, "Alpha", trajectory) == (
        4.25,
        "fast-sim-Alpha",
        3,
    )
    arguments["command_received_at_source_s"] = 4.30
    arguments["command_source_clock_id"] = "fast-sim-Alpha"
    arguments["command_source_clock_epoch"] = 3
    assert _retained_trajectory_authority_start(context, "Alpha", trajectory) == (
        4.30,
        "fast-sim-Alpha",
        3,
    )
    del arguments["command_source_clock_epoch"]
    assert _retained_trajectory_authority_start(context, "Alpha", trajectory) is None


def test_speed_ripple_is_bounded_per_declared_steady_window() -> None:
    analysis = analyze_motion_quality_csv(
        _csv(speeds_m_s=(0.2, 0.2, 0.2, 0.2, 0.3, 0.3, 0.3, 0.3)),
        MotionQualityContract(),
        planned_route_m=(Vector3(z=0.4), Vector3(x=0.3, z=0.4)),
        minimum_clearance_m=0.3,
        collision_count=0,
        checkpoint_hold_conformance_fraction=1.0,
        minimum_continuous_knot_speed_ratio=1.0,
        unintended_fly_through_stop_count=0,
        motor_differential_sign_agreement_fraction=1.0,
        motor_differential_normalized_error_p95=0.01,
        supervisor_safety_gate_passed=True,
        steady_windows_source_s=((0.0, 0.3), (0.4, 0.7)),
    )

    assert analysis.vector.speed_ripple_m_s == 0.0


def test_one_drone_operator_progression_is_not_eligibility_order() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    one_drone_families = []
    for case in catalog.cases():
        if case.drone_count == 1 and case.family not in one_drone_families:
            one_drone_families.append(case.family)
    assert tuple(one_drone_families[: len(ONE_DRONE_FAMILY_ORDER)]) == ONE_DRONE_FAMILY_ORDER
    takeoff = catalog.get("1d.takeoff_hover_land.canonical_nominal")
    edited = takeoff.model_copy(update={"purpose": takeoff.purpose + " Display prose."})
    assert edited.execution_semantics_sha256 == takeoff.execution_semantics_sha256
