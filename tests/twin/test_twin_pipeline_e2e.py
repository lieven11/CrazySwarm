import csv
import io
from pathlib import Path

import pytest

from crazyswarm_app.domain.models import CoordinateFrame
from crazyswarm_app.twin.coordinator import TwinCoordinator
from crazyswarm_app.twin.models import TwinInitialState, TwinSessionConfig, TwinSourceClass


def _csv() -> bytes:
    columns = [
        "vehicle_id",
        "source_timestamp_s",
        "received_timestamp_s",
        "telemetry_sequence",
        "position_x_m",
        "position_y_m",
        "position_z_m",
        "ground_truth_x_m",
        "ground_truth_y_m",
        "ground_truth_z_m",
        "velocity_x_m_s",
        "velocity_y_m_s",
        "velocity_z_m_s",
        "roll_rad",
        "pitch_rad",
        "yaw_rad",
        "imu_acceleration_x_m_s2",
        "imu_acceleration_y_m_s2",
        "imu_acceleration_z_m_s2",
        "imu_angular_velocity_x_rad_s",
        "imu_angular_velocity_y_rad_s",
        "imu_angular_velocity_z_rad_s",
        "battery_voltage_v",
        "battery_current_a",
        "state",
        *(f"motor_m{index}_thrust_n" for index in range(1, 5)),
        *(f"motor_m{index}_applied_pwm_percent" for index in range(1, 5)),
    ]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for sequence, source_s in enumerate((1.0, 1.02), start=1):
        row = {
            "vehicle_id": "Alpha",
            "source_timestamp_s": source_s,
            "received_timestamp_s": source_s + 0.01,
            "telemetry_sequence": sequence,
            "position_x_m": 0.1 * sequence,
            "position_y_m": 0.0,
            "position_z_m": 0.4,
            "ground_truth_x_m": 0.1 * sequence - 0.01,
            "ground_truth_y_m": 0.0,
            "ground_truth_z_m": 0.4,
            "velocity_x_m_s": 0.2,
            "velocity_y_m_s": 0.0,
            "velocity_z_m_s": 0.0,
            "roll_rad": 0.01,
            "pitch_rad": 0.02,
            "yaw_rad": 0.0,
            "imu_acceleration_x_m_s2": 0.1,
            "imu_acceleration_y_m_s2": 0.0,
            "imu_acceleration_z_m_s2": 9.81,
            "imu_angular_velocity_x_rad_s": 0.01,
            "imu_angular_velocity_y_rad_s": 0.0,
            "imu_angular_velocity_z_rad_s": 0.0,
            "battery_voltage_v": 4.0,
            "battery_current_a": 0.3,
            "state": "FLYING",
        }
        for motor in range(1, 5):
            row[f"motor_m{motor}_thrust_n"] = 0.07 + motor * 0.001
            row[f"motor_m{motor}_applied_pwm_percent"] = 45.0 + motor * 0.1
        writer.writerow(row)
    return stream.getvalue().encode()


def test_csv_pipeline_persists_observed_predicted_missing_and_residuals(
    tmp_path: Path,
) -> None:
    root = tmp_path / "twin"
    coordinator = TwinCoordinator(root)
    session = coordinator.create_session(
        TwinSessionConfig(
            observed_vehicle_id="Alpha",
            simulated_vehicle_id="Alpha-model",
            mission_id="straight-1d",
            mission_version="1",
            observed_initial_state=TwinInitialState(
                source_class=TwinSourceClass.CONFIGURED,
                source_id="fast-sim-observed",
                frame=CoordinateFrame.WORLD,
            ),
            simulated_initial_state=TwinInitialState(
                source_class=TwinSourceClass.SIMULATED_MODEL,
                source_id="physics-model",
                frame=CoordinateFrame.WORLD,
            ),
            ground_truth_available=True,
        )
    )
    receipts = coordinator.ingest_telemetry_csv(session.session_id, _csv())
    assert sum(item.accepted_count for item in receipts) == 112
    timeline = coordinator.timeline(session.session_id)
    assert len(timeline.samples) == 112
    assert len(timeline.residuals) == 56
    pose_residual = next(
        item
        for item in timeline.residuals
        if item.channel_id == "pose.position" and item.source_timestamp_s == 1.0
    )
    assert pose_residual.value is not None
    assert pose_residual.value.x == pytest.approx(0.01)
    missing = [item for item in timeline.samples if item.availability.value == "MISSING"]
    assert missing and all(item.value is None for item in missing)
    predicted_imu = next(
        item
        for item in timeline.samples
        if item.side.value == "PREDICTED" and item.channel_id == "imu.acceleration"
    )
    assert predicted_imu.availability.value == "MISSING"
    assert predicted_imu.value is None
    restarted = TwinCoordinator(root).timeline(session.session_id)
    assert restarted.timeline_sha256 == timeline.timeline_sha256
