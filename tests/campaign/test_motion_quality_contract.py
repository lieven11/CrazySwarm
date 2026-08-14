import csv
import io
from pathlib import Path

from crazyswarm_app.campaign.analyzer import analyze_motion_quality_csv
from crazyswarm_app.campaign.catalog import ONE_DRONE_FAMILY_ORDER, CampaignCatalog
from crazyswarm_app.campaign.models import MotionQualityContract, MotionSpeedLaw
from crazyswarm_app.domain.models import Vector3


def _csv(*, angular_spike: float = 0.0, lateral_offset_m: float = 0.0) -> bytes:
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
        row = {
            "vehicle_id": "Alpha",
            "recorded_at_utc": f"2026-01-01T00:00:0{index}Z",
            "source_timestamp_s": index * 0.1,
            "simulation_timestamp_s": index * 0.1,
            "telemetry_sequence": index + 1,
            "velocity_x_m_s": 0.3,
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


def _analyze(content: bytes):
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
    )


def test_constant_scalar_speed_does_not_hide_angular_shakiness() -> None:
    analysis = _analyze(_csv(angular_spike=1.0))
    assert analysis.vector.speed_compliance_fraction == 1.0
    assert analysis.vector.speed_ripple_m_s == 0.0
    assert "angular_rate_p95_rad_s" in analysis.failed_guards


def test_smooth_trace_outside_path_tube_fails_tracking_separately() -> None:
    analysis = _analyze(_csv(lateral_offset_m=0.08))
    assert "tracking_rms_m" in analysis.failed_guards
    assert "path_tube_max_error_m" in analysis.failed_guards
    assert "angular_rate_p95_rad_s" not in analysis.failed_guards


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
