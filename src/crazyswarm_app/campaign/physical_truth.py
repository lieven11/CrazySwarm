from __future__ import annotations

import csv
import hashlib
import math
from itertools import pairwise
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.simulation.physics import PhysicsModelConfig


class DifferentialActuationAnalysis(ContractModel):
    schema_version: Literal[1] = 1
    vehicle_id: Identifier
    csv_sha256: SHA256
    physics_configuration_sha256: SHA256
    paired_sample_count: int = Field(ge=0)
    maneuver_sample_count: int = Field(ge=0)
    sign_agreement_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    normalized_error_p95: float | None = Field(default=None, ge=0.0)
    maximum_source_pairing_error_s: float | None = Field(default=None, ge=0.0)
    all_equal_moving_sample_count: int = Field(ge=0)
    saturated_maneuver_sample_count: int = Field(ge=0)
    failures: tuple[str, ...]
    passed: bool
    analysis_sha256: SHA256


def analyze_differential_actuation_csv(
    csv_bytes: bytes,
    *,
    vehicle_id: str | None = None,
    physics: PhysicsModelConfig | None = None,
    source_pairing_tolerance_s: float = 0.01,
    response_horizon_s: float = 0.05,
) -> DifferentialActuationAnalysis:
    """Independent X-layout torque/IMU oracle over literal per-motor CSV values."""

    config = physics or PhysicsModelConfig()
    rows = list(csv.DictReader(csv_bytes.decode("utf-8-sig").splitlines()))
    if not rows:
        raise ValueError("physical-truth analysis requires telemetry rows")
    selected_id = vehicle_id or str(rows[0].get("vehicle_id") or "")
    selected = sorted(
        (row for row in rows if row.get("vehicle_id") == selected_id),
        key=_source_time,
    )
    full_rigid_body_contract = any(row.get("motor_model_id") for row in selected)
    observations = []
    for before, after in pairwise(selected):
        dt = _source_time(after) - _source_time(before)
        if not 0.0 < dt <= response_horizon_s:
            continue
        thrust = tuple(_float(after.get(f"motor_m{index}_thrust_n")) for index in range(1, 5))
        if any(value is None for value in thrust):
            continue
        thrust_values = tuple(float(value) for value in thrust if value is not None)
        torque = _body_torque(config.rotor_positions_body_m, thrust_values)
        before_omega = _angular_velocity(before)
        after_omega = _angular_velocity(after)
        if before_omega is None or after_omega is None:
            continue
        observed_alpha = Vector3(
            x=(after_omega.x - before_omega.x) / dt,
            y=(after_omega.y - before_omega.y) / dt,
            z=(after_omega.z - before_omega.z) / dt,
        )
        if full_rigid_body_contract:
            inertia_x = config.total_inertia_x_kg_m2
            inertia_y = config.total_inertia_y_kg_m2
            inertia_z = config.total_inertia_z_kg_m2
            predicted_alpha = Vector3(
                x=(
                    torque.x
                    - (inertia_z - inertia_y) * before_omega.y * before_omega.z
                    - config.angular_drag_n_m_s * before_omega.x
                )
                / inertia_x,
                y=(
                    torque.y
                    - (inertia_x - inertia_z) * before_omega.z * before_omega.x
                    - config.angular_drag_n_m_s * before_omega.y
                )
                / inertia_y,
                z=(
                    torque.z
                    - (inertia_y - inertia_x) * before_omega.x * before_omega.y
                    - config.angular_drag_n_m_s * before_omega.z
                )
                / inertia_z,
            )
        else:
            # Minimal CSV fixtures and real-adapter rows that do not declare the
            # simulator's full rigid-body model can support only the geometry /
            # inertia force-torque oracle. Do not silently inject model drag.
            predicted_alpha = Vector3(
                x=torque.x / config.inertia_x_kg_m2,
                y=torque.y / config.inertia_y_kg_m2,
                z=torque.z / config.inertia_z_kg_m2,
            )
        velocity_before = _velocity(before)
        velocity_after = _velocity(after)
        horizontal_acceleration = (
            math.hypot(
                (velocity_after.x - velocity_before.x) / dt,
                (velocity_after.y - velocity_before.y) / dt,
            )
            if velocity_before is not None and velocity_after is not None
            else 0.0
        )
        expected_components = tuple(
            (float(getattr(predicted_alpha, axis)), float(getattr(observed_alpha, axis)))
            for axis in ("x", "y")
            if abs(float(getattr(predicted_alpha, axis))) >= 0.5
        )
        equal = max(thrust_values) - min(thrust_values) <= 1e-6
        saturated = any(_boolean(after.get(f"motor_m{index}_saturated")) for index in range(1, 5))
        observations.append(
            (dt, expected_components, equal and horizontal_acceleration >= 0.10, saturated)
        )
    components = [component for _dt, values, _equal, _sat in observations for component in values]
    sign_matches = [expected * observed > 0.0 for expected, observed in components]
    errors = [
        abs(observed - expected) / max(abs(expected), 0.5)
        for expected, observed in components
    ]
    all_equal_count = sum(equal for _dt, _values, equal, _sat in observations)
    longest_all_equal_run = 0
    current_all_equal_run = 0
    for _dt, _values, equal, _saturated in observations:
        current_all_equal_run = current_all_equal_run + 1 if equal else 0
        longest_all_equal_run = max(longest_all_equal_run, current_all_equal_run)
    saturated_count = sum(saturated for _dt, values, _equal, saturated in observations if values)
    # Motor and IMU values are taken from the same telemetry envelope; their
    # source-pairing error is therefore zero. ``dt`` above is the independently
    # bounded plant-response horizon, not a sensor pairing error.
    maximum_pairing = 0.0 if observations else None
    sign_agreement = sum(sign_matches) / len(sign_matches) if sign_matches else None
    p95_error = _percentile(sorted(errors), 0.95) if errors else None
    failures = []
    if not components:
        failures.append("NO_SOURCE_ALIGNED_TORQUE_RESPONSE")
    if maximum_pairing is not None and maximum_pairing > source_pairing_tolerance_s + 1e-12:
        failures.append("SOURCE_TIME_PAIRING")
    if sign_agreement is not None and sign_agreement < 0.95:
        failures.append("TORQUE_IMU_SIGN")
    if p95_error is not None and p95_error > 0.10:
        failures.append("TORQUE_IMU_MAGNITUDE")
    if longest_all_equal_run >= 3:
        failures.append("ALL_EQUAL_MOVING_ACTUATION")
    if saturated_count:
        failures.append("SATURATED_MANEUVER")
    payload = {
        "vehicle_id": selected_id,
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "physics_configuration_sha256": canonical_sha256(config),
        "paired_sample_count": len(observations),
        "maneuver_sample_count": len(components),
        "sign_agreement_fraction": sign_agreement,
        "normalized_error_p95": p95_error,
        "maximum_source_pairing_error_s": maximum_pairing,
        "all_equal_moving_sample_count": all_equal_count,
        "saturated_maneuver_sample_count": saturated_count,
        "failures": tuple(failures),
        "passed": not failures,
    }
    return DifferentialActuationAnalysis(
        **payload,
        analysis_sha256=canonical_sha256(payload),
    )


def _body_torque(
    positions: tuple[Vector3, Vector3, Vector3, Vector3],
    thrust: tuple[float, ...],
) -> Vector3:
    return Vector3(
        x=sum(position.y * value for position, value in zip(positions, thrust, strict=True)),
        y=sum(-position.x * value for position, value in zip(positions, thrust, strict=True)),
        z=0.0,
    )


def _source_time(row: dict[str, str]) -> float:
    return float(row.get("simulation_timestamp_s") or row.get("source_timestamp_s") or 0.0)


def _angular_velocity(row: dict[str, str]) -> Vector3 | None:
    return _vector(row, "imu_angular_velocity", "_rad_s")


def _velocity(row: dict[str, str]) -> Vector3 | None:
    return _vector(row, "velocity", "_m_s")


def _vector(row: dict[str, str], prefix: str, suffix: str) -> Vector3 | None:
    values = tuple(_float(row.get(f"{prefix}_{axis}{suffix}")) for axis in ("x", "y", "z"))
    if any(value is None for value in values):
        return None
    return Vector3(x=values[0], y=values[1], z=values[2])


def _float(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _boolean(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _norm(value: Vector3) -> float:
    return math.sqrt(value.x**2 + value.y**2 + value.z**2)


def _percentile(values: list[float], quantile: float) -> float:
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)
