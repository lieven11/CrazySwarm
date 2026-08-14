from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.models import (
    TwinAvailability,
    TwinIngestionBatch,
    TwinQuality,
    TwinSessionConfig,
    TwinStreamSample,
    TwinStreamSide,
)

_SCALAR_CHANNELS = {
    "battery.voltage": ("battery_voltage_v", "battery_open_circuit_voltage_v"),
    "battery.current": ("battery_current_a", None),
    **{
        f"motor.m{index}.thrust": (
            f"motor_m{index}_thrust_n",
            f"motor_m{index}_requested_thrust_n",
        )
        for index in range(1, 5)
    },
    **{
        f"motor.m{index}.pwm": (
            f"motor_m{index}_applied_pwm_percent",
            f"motor_m{index}_command_percent",
        )
        for index in range(1, 5)
    },
}
_VECTOR_CHANNELS = {
    "velocity.linear": ("velocity", "_m_s"),
    "attitude.euler": ("attitude", "_rad"),
    "imu.acceleration": ("imu_acceleration", "_m_s2"),
    "imu.angular_velocity": ("imu_angular_velocity", "_rad_s"),
}
_IDENTIFIER_CHANNELS = {
    "perception.world_revision": "perceived_world_revision",
    "command.identity": "accepted_execution_program_sha256",
    "plan.identity": "accepted_plan_sha256",
    "replan.identity": "replacement_authority_sha256",
    "safety.state": "safety_state",
}
_STATE_CHANNELS = {
    "battery.state": (
        "battery_percent",
        "battery_cutoff_active",
        "battery_cutoff_reason",
        "powertrain_current_limited",
    ),
    "estimator.health": (
        "estimator_variance_x_m2",
        "estimator_variance_y_m2",
        "estimator_variance_z_m2",
        "estimator_converged",
        "estimator_quality_metric_id",
    ),
    "flow.state": (
        "flow_velocity_x_m_s",
        "flow_velocity_y_m_s",
        "flow_velocity_z_m_s",
        "flow_ground_distance_m",
        "flow_quality_percent",
        "flow_status",
        "flow_source_timestamp_s",
    ),
    "range.state": (
        "range_max_m",
        "range_source_timestamp_s",
        *(
            f"range_{direction}_{suffix}"
            for direction in ("front", "back", "left", "right", "up", "down")
            for suffix in ("m", "status")
        ),
    ),
    **{
        f"motor.m{index}.state": (
            f"motor_m{index}_command_percent",
            f"motor_m{index}_requested_thrust_n",
            f"motor_m{index}_applied_pwm_percent",
            f"motor_m{index}_voltage_v",
            f"motor_m{index}_thrust_n",
            f"motor_m{index}_available_thrust_n",
            f"motor_m{index}_current_a",
            f"motor_m{index}_saturated",
            f"motor_m{index}_health_percent",
            f"motor_m{index}_faulted",
        )
        for index in range(1, 5)
    },
}
_CONTRACTS = {
    "pose.position": ("m", "world"),
    "velocity.linear": ("m/s", "world"),
    "attitude.euler": ("rad", "body"),
    "imu.acceleration": ("m/s^2", "body"),
    "imu.angular_velocity": ("rad/s", "body"),
    "battery.voltage": ("V", "vehicle"),
    "battery.current": ("A", "vehicle"),
    "battery.state": ("json", "vehicle"),
    "estimator.health": ("state", "vehicle"),
    "flow.state": ("json", "body"),
    "range.state": ("json", "body"),
    "perception.world_revision": ("revision", "world"),
    "command.identity": ("sha256", "authority"),
    "plan.identity": ("sha256", "authority"),
    "replan.identity": ("sha256", "authority"),
    "safety.state": ("state", "authority"),
    **{f"motor.m{index}.thrust": ("N", "body") for index in range(1, 5)},
    **{f"motor.m{index}.pwm": ("percent", "body") for index in range(1, 5)},
    **{f"motor.m{index}.state": ("json", "body") for index in range(1, 5)},
}


def telemetry_csv_twin_batches(
    *,
    session_id: str,
    config: TwinSessionConfig,
    csv_bytes: bytes,
) -> tuple[TwinIngestionBatch, ...]:
    """Translate retained run telemetry through the common twin ingestion contract.

    The observed side uses estimator/sensor values and the predicted side uses
    simulator ground truth where it exists. Every declared channel is represented;
    absence remains a hash-bound ``MISSING`` sample with no value.
    """

    rows = list(csv.DictReader(csv_bytes.decode("utf-8-sig").splitlines()))
    selected_rows = [
        row
        for row in rows
        if str(row.get("vehicle_id") or "") == config.observed_vehicle_id
    ]
    if not selected_rows:
        raise ValueError("telemetry CSV does not contain the twin observed vehicle")
    # A recorder may retain multiple event envelopes at one exact source tick.
    # The stream contract requires one state per channel and strict source-time
    # progress, so retain the highest telemetry sequence at that tick.
    by_source_time: dict[float, Mapping[str, str]] = {}
    for row in selected_rows:
        source_s = _first_float(row, "simulation_timestamp_s", "source_timestamp_s")
        prior = by_source_time.get(source_s)
        if prior is None or int(row.get("telemetry_sequence") or 0) > int(
            prior.get("telemetry_sequence") or 0
        ):
            by_source_time[source_s] = row
    selected_rows = [by_source_time[source_s] for source_s in sorted(by_source_time)]
    samples: list[TwinStreamSample] = []
    for sequence, row in enumerate(selected_rows, start=1):
        source_s = _first_float(row, "simulation_timestamp_s", "source_timestamp_s")
        received_s = _optional_float(row.get("received_timestamp_s"))
        received_s = max(source_s, received_s if received_s is not None else source_s)
        raw_hash = canonical_sha256(dict(row))
        for side, vehicle_id in (
            (TwinStreamSide.OBSERVED, config.observed_vehicle_id),
            (TwinStreamSide.PREDICTED, config.simulated_vehicle_id),
        ):
            for channel_id in _CONTRACTS:
                value = _channel_value(row, channel_id, side)
                availability = (
                    TwinAvailability.AVAILABLE
                    if value is not None
                    else TwinAvailability.MISSING
                )
                unit, frame = _CONTRACTS[channel_id]
                sample_key = {
                    "session_id": session_id,
                    "side": side,
                    "channel_id": channel_id,
                    "sequence": sequence,
                    "raw_payload_sha256": raw_hash,
                }
                samples.append(
                    TwinStreamSample.create(
                        sample_id=f"twin-sample-{canonical_sha256(sample_key)[:24]}",
                        session_id=session_id,
                        side=side,
                        vehicle_id=vehicle_id,
                        channel_id=channel_id,
                        sequence=sequence,
                        source_timestamp_s=source_s,
                        received_timestamp_s=received_s,
                        availability=availability,
                        quality=(
                            TwinQuality.GOOD
                            if availability is TwinAvailability.AVAILABLE
                            else TwinQuality.UNQUALIFIED
                        ),
                        unit=unit,
                        frame=frame,
                        value=value,
                        calibration_id=(
                            config.calibration_id
                            if side is TwinStreamSide.PREDICTED
                            else None
                        ),
                        raw_payload_sha256=raw_hash,
                    )
                )
    return tuple(
        TwinIngestionBatch(session_id=session_id, samples=tuple(samples[index : index + 512]))
        for index in range(0, len(samples), 512)
    )


def _channel_value(
    row: Mapping[str, str], channel_id: str, side: TwinStreamSide
) -> float | str | Vector3 | None:
    if channel_id == "pose.position":
        prefix = "position" if side is TwinStreamSide.OBSERVED else "ground_truth"
        return _vector(row, prefix, "_m")
    if channel_id == "attitude.euler":
        return _vector_columns(row, ("roll_rad", "pitch_rad", "yaw_rad"))
    if channel_id in _VECTOR_CHANNELS:
        if side is TwinStreamSide.PREDICTED:
            return None
        prefix, suffix = _VECTOR_CHANNELS[channel_id]
        return _vector(row, prefix, suffix)
    if channel_id in _SCALAR_CHANNELS:
        observed_column, predicted_column = _SCALAR_CHANNELS[channel_id]
        column = (
            observed_column
            if side is TwinStreamSide.OBSERVED
            else predicted_column
        )
        return _optional_float(row.get(column)) if column is not None else None
    if channel_id in _STATE_CHANNELS:
        return _state_value(row, _STATE_CHANNELS[channel_id], side)
    if side is TwinStreamSide.PREDICTED:
        return None
    value = row.get(_IDENTIFIER_CHANNELS[channel_id])
    return str(value) if value not in {None, ""} else None


def _state_value(
    row: Mapping[str, str],
    columns: tuple[str, ...],
    side: TwinStreamSide,
) -> str | None:
    selected = {
        column: row[column]
        for column in columns
        if row.get(column) not in {None, ""}
        and (
            side is TwinStreamSide.OBSERVED
            or "requested_thrust" in column
            or "command_percent" in column
        )
    }
    if not selected:
        return None
    return json.dumps(selected, sort_keys=True, separators=(",", ":"))


def _vector(row: Mapping[str, str], prefix: str, suffix: str) -> Vector3 | None:
    return _vector_columns(
        row,
        tuple(f"{prefix}_{axis}{suffix}" for axis in ("x", "y", "z")),
    )


def _vector_columns(
    row: Mapping[str, str], columns: tuple[str, str, str]
) -> Vector3 | None:
    values = tuple(_optional_float(row.get(column)) for column in columns)
    if any(value is None for value in values):
        return None
    return Vector3(x=values[0], y=values[1], z=values[2])


def _first_float(row: Mapping[str, str], *columns: str) -> float:
    for column in columns:
        value = _optional_float(row.get(column))
        if value is not None:
            return value
    raise ValueError("telemetry row has no finite source timestamp")


def _optional_float(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None
