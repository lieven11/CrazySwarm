from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from crazyswarm_app.observability.events import EvidenceEvent, EvidenceKind, TelemetryPayload

RUN_TELEMETRY_CSV_CONTRACT = "run-telemetry-v1"

_IDENTITY_COLUMNS = (
    "csv_schema_version",
    "run_id",
    "mission_id",
    "mission_version",
    "configuration_sha256",
    "event_id",
    "event_sequence",
    "vehicle_id",
    "operating_mode",
    "source",
    "recorded_at_utc",
    "source_timestamp_s",
    "received_timestamp_s",
    "telemetry_sequence",
    "simulation_timestamp_s",
    "replay_timestamp_s",
    "source_clock_id",
    "source_clock_epoch",
    "frame",
)
_MOTION_COLUMNS = (
    "state",
    "armed",
    "flying",
    "position_is_estimate",
    "localization_source",
    "localization_quality_percent",
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
    "quaternion_w",
    "quaternion_x",
    "quaternion_y",
    "quaternion_z",
)
_POWER_TRANSPORT_COLUMNS = (
    "battery_percent",
    "battery_open_circuit_voltage_v",
    "battery_voltage_v",
    "battery_current_a",
    "battery_cutoff_active",
    "battery_cutoff_reason",
    "powertrain_current_limited",
    "transport_kind",
    "transport_source_class",
    "transport_delivery_quality_percent",
    "transport_latency_ms",
    "transport_packet_loss_percent",
)
_SENSOR_COLUMNS = (
    "imu_acceleration_x_m_s2",
    "imu_acceleration_y_m_s2",
    "imu_acceleration_z_m_s2",
    "imu_angular_velocity_x_rad_s",
    "imu_angular_velocity_y_rad_s",
    "imu_angular_velocity_z_rad_s",
    "estimator_variance_x_m2",
    "estimator_variance_y_m2",
    "estimator_variance_z_m2",
    "estimator_converged",
    "estimator_quality_metric_id",
    "flow_velocity_x_m_s",
    "flow_velocity_y_m_s",
    "flow_velocity_z_m_s",
    "flow_ground_distance_m",
    "flow_quality_percent",
    "flow_status",
    "flow_source_timestamp_s",
)
_RANGE_DIRECTIONS = ("front", "back", "left", "right", "up", "down")
_RANGE_COLUMNS = (
    "range_max_m",
    "range_source_timestamp_s",
    *(
        column
        for direction in _RANGE_DIRECTIONS
        for column in (f"range_{direction}_m", f"range_{direction}_status")
    ),
)
_MOTOR_IDS = ("m1", "m2", "m3", "m4")
_MOTOR_FIELDS = (
    "command_percent",
    "requested_thrust_n",
    "applied_pwm_percent",
    "voltage_v",
    "thrust_n",
    "available_thrust_n",
    "current_a",
    "saturated",
    "health_percent",
    "faulted",
)
_MOTOR_COLUMNS = (
    "motor_model_id",
    "motor_model_version",
    *(f"motor_{motor_id}_{field}" for motor_id in _MOTOR_IDS for field in _MOTOR_FIELDS),
)

RUN_TELEMETRY_CSV_COLUMNS = (
    *_IDENTITY_COLUMNS,
    *_MOTION_COLUMNS,
    *_POWER_TRANSPORT_COLUMNS,
    *_SENSOR_COLUMNS,
    *_RANGE_COLUMNS,
    *_MOTOR_COLUMNS,
    "faults_json",
)


@dataclass(frozen=True, slots=True)
class RunTelemetryCsvArtifact:
    filename: str
    content: bytes
    row_count: int
    sha256: str


def telemetry_csv_filename(run: dict[str, Any]) -> str:
    started_at = _parse_utc(str(run["started_at_utc"]))
    started = started_at.strftime("%Y%m%dT%H%M%SZ")
    mission_id = _filename_segment(str(run["mission_id"]))
    vehicle_id = _filename_segment(str(run["vehicle_id"]))
    run_prefix = _filename_segment(str(run["run_id"]))[:12]
    return f"{started}_{mission_id}_{vehicle_id}_{run_prefix}_telemetry-v1.csv"


def mission_telemetry_csv_filename(mission: dict[str, Any]) -> str:
    mission_name = _filename_segment(str(mission.get("mission_name") or mission["mission_id"]))
    execution_id = _filename_segment(str(mission["mission_execution_id"]))
    return f"{mission_name}_{execution_id}_telemetry-v1.csv"


def serialize_run_telemetry_csv(
    run: dict[str, Any], events: Iterable[EvidenceEvent]
) -> RunTelemetryCsvArtifact:
    telemetry_events = [event for event in events if event.kind is EvidenceKind.TELEMETRY]
    sequences = [event.sequence for event in telemetry_events]
    if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
        raise ValueError("telemetry evidence must have unique ascending event sequences")

    return _serialize_telemetry_rows(
        filename=telemetry_csv_filename(run),
        rows=((run, event) for event in telemetry_events),
    )


def serialize_mission_telemetry_csv(
    runs: Iterable[dict[str, Any]],
    events: Iterable[EvidenceEvent],
) -> RunTelemetryCsvArtifact:
    run_rows = {str(run["run_id"]): run for run in runs}
    if not run_rows:
        raise ValueError("a mission CSV requires at least one run")
    telemetry_events = [event for event in events if event.kind is EvidenceKind.TELEMETRY]
    by_run: dict[str, list[EvidenceEvent]] = {run_id: [] for run_id in run_rows}
    for event in telemetry_events:
        if event.run_id not in by_run:
            raise ValueError(f"telemetry event does not belong to the mission: {event.run_id}")
        by_run[event.run_id].append(event)
    for run_id, run_events in by_run.items():
        sequences = [event.sequence for event in run_events]
        if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
            raise ValueError(
                f"telemetry evidence must have unique ascending sequences for {run_id}"
            )
    ordered = sorted(
        telemetry_events,
        key=lambda event: (
            event.recorded_at_utc,
            event.vehicle_id,
            event.run_id,
            event.sequence,
            event.event_id,
        ),
    )
    first = min(run_rows.values(), key=lambda run: str(run["started_at_utc"]))
    return _serialize_telemetry_rows(
        filename=mission_telemetry_csv_filename(first),
        rows=((run_rows[event.run_id], event) for event in ordered),
    )


def _serialize_telemetry_rows(
    *,
    filename: str,
    rows: Iterable[tuple[dict[str, Any], EvidenceEvent]],
) -> RunTelemetryCsvArtifact:
    materialized = list(rows)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, dialect="excel", lineterminator="\r\n")
    writer.writerow(RUN_TELEMETRY_CSV_COLUMNS)
    for run, event in materialized:
        writer.writerow(_telemetry_row(run, event))
    content = stream.getvalue().encode("utf-8")
    return RunTelemetryCsvArtifact(
        filename=filename,
        content=content,
        row_count=len(materialized),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _telemetry_row(run: dict[str, Any], event: EvidenceEvent) -> list[str]:
    if not isinstance(event.payload, TelemetryPayload):
        raise TypeError("telemetry evidence must contain a TelemetryPayload")
    envelope = event.payload.telemetry
    telemetry = envelope.telemetry
    position = telemetry.position_m
    truth = telemetry.ground_truth_position_m
    velocity = telemetry.velocity_m_s
    attitude = telemetry.attitude
    quaternion = telemetry.quaternion
    transport = telemetry.transport
    imu = telemetry.imu
    estimator = telemetry.estimator
    flow = telemetry.flow
    ranges = telemetry.ranges
    motors = telemetry.motors
    readings = (
        {reading.motor_id.lower(): reading for reading in motors.readings}
        if motors is not None
        else {}
    )

    values: dict[str, Any] = {
        "csv_schema_version": 1,
        "run_id": run["run_id"],
        "mission_id": run["mission_id"],
        "mission_version": run["mission_version"],
        "configuration_sha256": run["configuration_hash"],
        "event_id": event.event_id,
        "event_sequence": event.sequence,
        "vehicle_id": event.vehicle_id,
        "operating_mode": event.mode,
        "source": event.source,
        "recorded_at_utc": event.recorded_at_utc,
        "source_timestamp_s": event.source_timestamp_s,
        "received_timestamp_s": event.received_timestamp_s,
        "telemetry_sequence": envelope.sequence,
        "simulation_timestamp_s": envelope.simulation_timestamp_s,
        "replay_timestamp_s": envelope.replay_timestamp_s,
        "source_clock_id": envelope.source_clock_id,
        "source_clock_epoch": envelope.source_clock_epoch,
        "frame": event.frame or telemetry.frame,
        "state": telemetry.state,
        "armed": telemetry.armed,
        "flying": telemetry.flying,
        "position_is_estimate": telemetry.position_is_estimate,
        "localization_source": telemetry.localization_source,
        "localization_quality_percent": telemetry.localization_quality_percent,
        "position_x_m": _component(position, "x"),
        "position_y_m": _component(position, "y"),
        "position_z_m": _component(position, "z"),
        "ground_truth_x_m": _component(truth, "x"),
        "ground_truth_y_m": _component(truth, "y"),
        "ground_truth_z_m": _component(truth, "z"),
        "velocity_x_m_s": _component(velocity, "x"),
        "velocity_y_m_s": _component(velocity, "y"),
        "velocity_z_m_s": _component(velocity, "z"),
        "roll_rad": getattr(attitude, "roll_rad", None),
        "pitch_rad": getattr(attitude, "pitch_rad", None),
        "yaw_rad": getattr(attitude, "yaw_rad", None),
        "quaternion_w": getattr(quaternion, "w", None),
        "quaternion_x": getattr(quaternion, "x", None),
        "quaternion_y": getattr(quaternion, "y", None),
        "quaternion_z": getattr(quaternion, "z", None),
        "battery_percent": telemetry.battery_percent,
        "battery_open_circuit_voltage_v": telemetry.battery_open_circuit_voltage_v,
        "battery_voltage_v": telemetry.battery_voltage_v,
        "battery_current_a": telemetry.battery_current_a,
        "battery_cutoff_active": telemetry.battery_cutoff_active,
        "battery_cutoff_reason": telemetry.battery_cutoff_reason,
        "powertrain_current_limited": telemetry.powertrain_current_limited,
        "transport_kind": getattr(transport, "kind", None),
        "transport_source_class": getattr(transport, "source_class", None),
        "transport_delivery_quality_percent": getattr(transport, "delivery_quality_percent", None),
        "transport_latency_ms": getattr(transport, "latency_ms", None),
        "transport_packet_loss_percent": getattr(transport, "packet_loss_percent", None),
        "imu_acceleration_x_m_s2": _component(getattr(imu, "acceleration_body_m_s2", None), "x"),
        "imu_acceleration_y_m_s2": _component(getattr(imu, "acceleration_body_m_s2", None), "y"),
        "imu_acceleration_z_m_s2": _component(getattr(imu, "acceleration_body_m_s2", None), "z"),
        "imu_angular_velocity_x_rad_s": _component(
            getattr(imu, "angular_velocity_body_rad_s", None), "x"
        ),
        "imu_angular_velocity_y_rad_s": _component(
            getattr(imu, "angular_velocity_body_rad_s", None), "y"
        ),
        "imu_angular_velocity_z_rad_s": _component(
            getattr(imu, "angular_velocity_body_rad_s", None), "z"
        ),
        "estimator_variance_x_m2": _component(
            getattr(estimator, "position_variance_m2", None), "x"
        ),
        "estimator_variance_y_m2": _component(
            getattr(estimator, "position_variance_m2", None), "y"
        ),
        "estimator_variance_z_m2": _component(
            getattr(estimator, "position_variance_m2", None), "z"
        ),
        "estimator_converged": getattr(estimator, "converged", None),
        "estimator_quality_metric_id": getattr(estimator, "quality_metric_id", None),
        "flow_velocity_x_m_s": _component(getattr(flow, "velocity_body_m_s", None), "x"),
        "flow_velocity_y_m_s": _component(getattr(flow, "velocity_body_m_s", None), "y"),
        "flow_velocity_z_m_s": _component(getattr(flow, "velocity_body_m_s", None), "z"),
        "flow_ground_distance_m": getattr(flow, "ground_distance_m", None),
        "flow_quality_percent": getattr(flow, "quality_percent", None),
        "flow_status": getattr(flow, "status", None),
        "flow_source_timestamp_s": getattr(flow, "source_timestamp_s", None),
        "range_max_m": getattr(ranges, "max_range_m", None),
        "range_source_timestamp_s": getattr(ranges, "source_timestamp_s", None),
        "motor_model_id": getattr(motors, "model_id", None),
        "motor_model_version": getattr(motors, "model_version", None),
        "faults_json": json.dumps(
            list(telemetry.faults), ensure_ascii=False, separators=(",", ":")
        ),
    }
    for direction in _RANGE_DIRECTIONS:
        values[f"range_{direction}_m"] = getattr(ranges, f"{direction}_m", None)
        values[f"range_{direction}_status"] = (
            ranges.statuses.get(direction) if ranges is not None else None
        )
    for motor_id in _MOTOR_IDS:
        reading = readings.get(motor_id)
        values.update(
            {
                f"motor_{motor_id}_command_percent": getattr(reading, "command_percent", None),
                f"motor_{motor_id}_requested_thrust_n": getattr(
                    reading, "requested_thrust_n", None
                ),
                f"motor_{motor_id}_applied_pwm_percent": getattr(
                    reading, "applied_pwm_percent", None
                ),
                f"motor_{motor_id}_voltage_v": getattr(reading, "motor_voltage_v", None),
                f"motor_{motor_id}_thrust_n": getattr(reading, "thrust_n", None),
                f"motor_{motor_id}_available_thrust_n": getattr(
                    reading, "available_thrust_n", None
                ),
                f"motor_{motor_id}_current_a": getattr(reading, "current_a", None),
                f"motor_{motor_id}_saturated": getattr(reading, "saturated", None),
                f"motor_{motor_id}_health_percent": getattr(reading, "health_percent", None),
                f"motor_{motor_id}_faulted": getattr(reading, "faulted", None),
            }
        )
    return [_csv_cell(values.get(column)) for column in RUN_TELEMETRY_CSV_COLUMNS]


def _component(value: object | None, name: str) -> Any:
    return getattr(value, name, None)


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return _format_utc(value)
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("CSV numeric cells must be finite")
        return repr(value)
    return str(value)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _filename_segment(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-._")
    return normalized or "unknown"
