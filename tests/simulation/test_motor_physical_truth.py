import csv
import io

import pytest

from crazyswarm_app.campaign.physical_truth import analyze_differential_actuation_csv
from crazyswarm_app.simulation.physics import PhysicsModelConfig


def _motor_csv(*, swapped: bool = False, saturated: bool = False) -> bytes:
    config = PhysicsModelConfig()
    thrust = (0.06, 0.06, 0.08, 0.08)
    torque_x = sum(
        position.y * value
        for position, value in zip(config.rotor_positions_body_m, thrust, strict=True)
    )
    alpha_x = torque_x / config.inertia_x_kg_m2 * (-1 if swapped else 1)
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
        for motor, value in enumerate(thrust, start=1):
            row[f"motor_m{motor}_thrust_n"] = value
            row[f"motor_m{motor}_saturated"] = str(saturated).lower()
        writer.writerow(row)
    return stream.getvalue().encode()


def _dynamic_motor_csv(*, motor_mapping_swapped: bool = False, response_shift: int = 0) -> bytes:
    config = PhysicsModelConfig()
    patterns = tuple(
        (0.055, 0.065, 0.085, 0.075)
        if index % 2
        else (0.085, 0.075, 0.055, 0.065)
        for index in range(12)
    )
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
    omega_x = 0.0
    omega_y = 0.0
    for index, physical_thrust in enumerate(patterns):
        response_index = max(0, index - response_shift)
        response_thrust = patterns[response_index]
        torque_x = sum(
            position.y * value
            for position, value in zip(
                config.rotor_positions_body_m, response_thrust, strict=True
            )
        )
        torque_y = sum(
            -position.x * value
            for position, value in zip(
                config.rotor_positions_body_m, response_thrust, strict=True
            )
        )
        if index:
            omega_x += torque_x / config.inertia_x_kg_m2 * 0.01
            omega_y += torque_y / config.inertia_y_kg_m2 * 0.01
        retained_thrust = (
            (physical_thrust[2], physical_thrust[3], physical_thrust[0], physical_thrust[1])
            if motor_mapping_swapped
            else physical_thrust
        )
        row = {
            "vehicle_id": "Alpha",
            "source_timestamp_s": index * 0.01,
            "simulation_timestamp_s": index * 0.01,
            "velocity_x_m_s": 0.0,
            "velocity_y_m_s": 0.0,
            "velocity_z_m_s": 0.0,
            "imu_angular_velocity_x_rad_s": omega_x,
            "imu_angular_velocity_y_rad_s": omega_y,
            "imu_angular_velocity_z_rad_s": 0.0,
        }
        for motor, value in enumerate(retained_thrust, start=1):
            row[f"motor_m{motor}_thrust_n"] = value
            row[f"motor_m{motor}_saturated"] = "false"
        writer.writerow(row)
    return stream.getvalue().encode()


def test_x_layout_sign_magnitude_and_saturation_are_independent() -> None:
    nominal = analyze_differential_actuation_csv(_motor_csv())
    assert nominal.passed
    assert nominal.sign_agreement_fraction == 1.0
    assert nominal.normalized_error_p95 == pytest.approx(0.0, abs=1e-12)
    reversed_response = analyze_differential_actuation_csv(_motor_csv(swapped=True))
    assert "TORQUE_IMU_SIGN" in reversed_response.failures
    saturated = analyze_differential_actuation_csv(_motor_csv(saturated=True))
    assert "SATURATED_MANEUVER" in saturated.failures


def test_swapped_motor_mapping_and_shifted_response_fail_independently() -> None:
    nominal = analyze_differential_actuation_csv(_dynamic_motor_csv())
    assert nominal.passed
    swapped = analyze_differential_actuation_csv(
        _dynamic_motor_csv(motor_mapping_swapped=True)
    )
    assert "TORQUE_IMU_SIGN" in swapped.failures
    shifted = analyze_differential_actuation_csv(
        _dynamic_motor_csv(response_shift=2)
    )
    assert "TORQUE_IMU_SIGN" in shifted.failures or (
        "TORQUE_IMU_MAGNITUDE" in shifted.failures
    )
