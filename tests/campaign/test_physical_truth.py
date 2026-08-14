import csv
import io

from crazyswarm_app.campaign.physical_truth import analyze_differential_actuation_csv
from crazyswarm_app.simulation.physics import PhysicsModelConfig


def _csv(*, reverse_imu: bool = False, all_equal: bool = False) -> bytes:
    config = PhysicsModelConfig()
    thrusts = (0.06, 0.06, 0.08, 0.08)
    if all_equal:
        thrusts = (0.07,) * 4
    torque_x = sum(
        position.y * thrust
        for position, thrust in zip(config.rotor_positions_body_m, thrusts, strict=True)
    )
    alpha_x = torque_x / config.inertia_x_kg_m2
    if reverse_imu:
        alpha_x *= -1.0
    columns = [
        "vehicle_id",
        "source_timestamp_s",
        "simulation_timestamp_s",
        "velocity_x_m_s",
        "velocity_y_m_s",
        "velocity_z_m_s",
        "imu_angular_velocity_x_rad_s",
        "imu_angular_velocity_y_rad_s",
        "imu_angular_velocity_z_rad_s",
        *(f"motor_m{index}_thrust_n" for index in range(1, 5)),
        *(f"motor_m{index}_saturated" for index in range(1, 5)),
    ]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for index in range(8):
        row = {
            "vehicle_id": "Alpha",
            "source_timestamp_s": index * 0.01,
            "simulation_timestamp_s": index * 0.01,
            "velocity_x_m_s": index * 0.002,
            "velocity_y_m_s": 0.0,
            "velocity_z_m_s": 0.0,
            "imu_angular_velocity_x_rad_s": alpha_x * index * 0.01,
            "imu_angular_velocity_y_rad_s": 0.0,
            "imu_angular_velocity_z_rad_s": 0.0,
        }
        for motor, thrust in enumerate(thrusts, start=1):
            row[f"motor_m{motor}_thrust_n"] = thrust
            row[f"motor_m{motor}_saturated"] = "false"
        writer.writerow(row)
    return stream.getvalue().encode()


def test_x_layout_torque_matches_source_aligned_imu_response() -> None:
    analysis = analyze_differential_actuation_csv(_csv())
    assert analysis.sign_agreement_fraction == 1.0
    assert analysis.normalized_error_p95 is not None
    assert analysis.normalized_error_p95 < 1e-9
    assert analysis.passed


def test_swapped_sign_and_all_equal_moving_actuation_fail() -> None:
    reversed_response = analyze_differential_actuation_csv(_csv(reverse_imu=True))
    assert "TORQUE_IMU_SIGN" in reversed_response.failures
    equal = analyze_differential_actuation_csv(_csv(all_equal=True))
    assert "ALL_EQUAL_MOVING_ACTUATION" in equal.failures
