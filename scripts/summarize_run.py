#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JSON_SUFFIXES = {
    "manifest": ("-manifest.json", "_manifest.json", "manifest.json"),
    "evaluation": ("-evaluation.json", "_evaluation-v1.json", "evaluation.json"),
    "analysis": ("-analysis.json", "_analysis.json", "analysis.json"),
}
CSV_SUFFIXES = ("-telemetry.csv", "_telemetry-v1.csv", "telemetry.csv")

SIGNAL_GROUPS = {
    "position_estimate": ("position_x_m", "position_y_m", "position_z_m"),
    "ground_truth": ("ground_truth_x_m", "ground_truth_y_m", "ground_truth_z_m"),
    "velocity": ("velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"),
    "imu": ("imu_acceleration_x_m_s2", "imu_angular_velocity_x_rad_s"),
    "flow": ("flow_velocity_x_m_s", "flow_ground_distance_m", "flow_status"),
    "ranges": ("range_front_m", "range_back_m", "range_left_m", "range_right_m"),
    "motors": ("motor_m1_applied_pwm_percent", "motor_m1_command_percent"),
}

VEHICLE_EVALUATION_FIELDS = (
    "vehicle_id",
    "terminal_state",
    "elapsed_s",
    "telemetry_sample_count",
    "tracking_rms_error_m",
    "tracking_max_error_m",
    "trajectory_tracking_rms_error_m",
    "trajectory_tracking_max_error_m",
    "peak_speed_m_s",
    "peak_acceleration_m_s2",
    "peak_jerk_m_s3",
    "minimum_motor_thrust_headroom_n",
    "motor_saturation_sample_count",
    "battery_used_percent",
    "unintended_stop_count",
    "inherited_faults",
    "new_faults",
    "touchdown_target_center_error_m",
    "terminal_contact",
)

FLEET_EVALUATION_FIELDS = (
    "vehicle_count",
    "elapsed_s",
    "minimum_estimated_separation_m",
    "minimum_truth_separation_m",
    "minimum_separation_pair",
    "warning_sample_count",
    "critical_sample_count",
    "warning_separation_m",
    "critical_separation_m",
)


def finite_float(value: str | None, malformed: list[int]) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        number = float(value)
    except ValueError:
        malformed[0] += 1
        return None
    if not math.isfinite(number):
        malformed[0] += 1
        return None
    return number


def select(mapping: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    return {field: mapping[field] for field in fields if field in mapping}


@dataclass
class VehicleStats:
    sample_count: int = 0
    run_ids: set[str] = field(default_factory=set)
    clock_ids: set[str] = field(default_factory=set)
    epochs: set[int] = field(default_factory=set)
    time_windows: dict[tuple[str, int], list[float]] = field(default_factory=dict)
    signal_present: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    states: set[str] = field(default_factory=set)
    faults: set[str] = field(default_factory=set)
    speed_min: float | None = None
    speed_max: float | None = None
    altitude_min: float | None = None
    altitude_max: float | None = None
    battery_start: tuple[float, float] | None = None
    battery_end: tuple[float, float] | None = None
    voltage_min: float | None = None
    current_max: float | None = None
    range_min: float | None = None
    motor_pwm_max: float | None = None
    motor_saturation_samples: int = 0
    last_sequence: dict[tuple[str, str, int], tuple[int, float]] = field(default_factory=dict)
    nonmonotonic_samples: int = 0

    @staticmethod
    def update_min(current: float | None, value: float) -> float:
        return value if current is None else min(current, value)

    @staticmethod
    def update_max(current: float | None, value: float) -> float:
        return value if current is None else max(current, value)


def prefix_for(path: Path, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    return path.stem


def discover(target: Path) -> dict[str, Path | None]:
    if not target.exists():
        raise ValueError(f"path does not exist: {target}")
    directory = target if target.is_dir() else target.parent
    files = [path for path in directory.iterdir() if path.is_file()]

    explicit_csv = target if target.is_file() and target.name.endswith(".csv") else None
    csv_candidates = sorted(path for path in files if path.name.endswith(CSV_SUFFIXES))
    if explicit_csv is not None:
        csv_path = explicit_csv
    elif len(csv_candidates) == 1:
        csv_path = csv_candidates[0]
    elif not csv_candidates:
        csv_path = None
    else:
        names = ", ".join(path.name for path in csv_candidates[:8])
        raise ValueError(f"multiple telemetry CSVs found; specify one: {names}")

    prefix = prefix_for(csv_path, CSV_SUFFIXES) if csv_path is not None else ""
    result: dict[str, Path | None] = {"telemetry": csv_path}
    for kind, suffixes in JSON_SUFFIXES.items():
        explicit = target if target.is_file() and target.name.endswith(suffixes) else None
        exact = [
            path
            for path in files
            if prefix and any(path.name == prefix + suffix for suffix in suffixes)
        ]
        generic = [path for path in files if path.name in suffixes]
        candidates = explicit or (exact[0] if len(exact) == 1 else None)
        if candidates is None and len(generic) == 1:
            candidates = generic[0]
        if candidates is None:
            all_kind = sorted(path for path in files if path.name.endswith(suffixes))
            if len(all_kind) == 1:
                candidates = all_kind[0]
        result[kind] = candidates
    if not any(result.values()):
        raise ValueError("no manifest, evaluation, analysis, or telemetry artifact found")
    return result


def load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def parse_faults(value: str, stats: VehicleStats) -> None:
    if not value.strip():
        return
    try:
        faults = json.loads(value)
    except json.JSONDecodeError:
        stats.faults.add("<malformed faults_json>")
        return
    if isinstance(faults, list):
        stats.faults.update(str(item) for item in faults)


def summarize_csv(path: Path) -> dict[str, Any]:
    malformed = [0]
    vehicles: dict[str, VehicleStats] = defaultdict(VehicleStats)
    mission_ids: set[str] = set()
    configuration_hashes: set[str] = set()
    execution_ids: set[str] = set()
    operating_modes: set[str] = set()
    schema_versions: set[str] = set()
    event_ids: set[str] = set()
    duplicate_event_count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("telemetry CSV has no header")
        required = {"vehicle_id", "run_id", "source_timestamp_s", "source_clock_epoch"}
        missing_headers = sorted(required - set(reader.fieldnames))
        if missing_headers:
            raise ValueError(f"telemetry CSV is missing required columns: {missing_headers}")

        for row in reader:
            vehicle_id = (row.get("vehicle_id") or "<missing>").strip() or "<missing>"
            stats = vehicles[vehicle_id]
            stats.sample_count += 1
            run_id = (row.get("run_id") or "").strip()
            clock_id = (row.get("source_clock_id") or "").strip()
            epoch_value = finite_float(row.get("source_clock_epoch"), malformed)
            epoch = int(epoch_value) if epoch_value is not None else -1
            source_time = finite_float(row.get("source_timestamp_s"), malformed)
            sequence_value = finite_float(row.get("telemetry_sequence"), malformed)
            sequence = int(sequence_value) if sequence_value is not None else -1

            if run_id:
                stats.run_ids.add(run_id)
            if clock_id:
                stats.clock_ids.add(clock_id)
            if epoch >= 0:
                stats.epochs.add(epoch)
            if source_time is not None:
                window = stats.time_windows.setdefault(
                    (clock_id, epoch), [source_time, source_time]
                )
                window[0] = min(window[0], source_time)
                window[1] = max(window[1], source_time)
                ordering_key = (run_id, clock_id, epoch)
                previous = stats.last_sequence.get(ordering_key)
                if previous is not None and (sequence < previous[0] or source_time < previous[1]):
                    stats.nonmonotonic_samples += 1
                stats.last_sequence[ordering_key] = (sequence, source_time)

            for name, columns in SIGNAL_GROUPS.items():
                if any((row.get(column) or "").strip() for column in columns):
                    stats.signal_present[name] += 1

            state = (row.get("state") or "").strip()
            if state:
                stats.states.add(state)
            parse_faults(row.get("faults_json") or "", stats)

            velocity = [
                finite_float(row.get(column), malformed)
                for column in ("velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s")
            ]
            if all(value is not None for value in velocity):
                speed = math.sqrt(sum(float(value) ** 2 for value in velocity))
                stats.speed_min = stats.update_min(stats.speed_min, speed)
                stats.speed_max = stats.update_max(stats.speed_max, speed)
            altitude = finite_float(row.get("ground_truth_z_m"), malformed)
            if altitude is None:
                altitude = finite_float(row.get("position_z_m"), malformed)
            if altitude is not None:
                stats.altitude_min = stats.update_min(stats.altitude_min, altitude)
                stats.altitude_max = stats.update_max(stats.altitude_max, altitude)

            battery = finite_float(row.get("battery_percent"), malformed)
            if battery is not None:
                if stats.battery_start is None:
                    stats.battery_start = (float(stats.sample_count), battery)
                stats.battery_end = (float(stats.sample_count), battery)
            voltage = finite_float(row.get("battery_voltage_v"), malformed)
            current = finite_float(row.get("battery_current_a"), malformed)
            if voltage is not None:
                stats.voltage_min = stats.update_min(stats.voltage_min, voltage)
            if current is not None:
                stats.current_max = stats.update_max(stats.current_max, current)

            for direction in ("front", "back", "left", "right", "up", "down"):
                distance = finite_float(row.get(f"range_{direction}_m"), malformed)
                if distance is not None:
                    stats.range_min = stats.update_min(stats.range_min, distance)
            saturated = False
            for motor in ("m1", "m2", "m3", "m4"):
                pwm = finite_float(row.get(f"motor_{motor}_applied_pwm_percent"), malformed)
                if pwm is not None:
                    stats.motor_pwm_max = stats.update_max(stats.motor_pwm_max, pwm)
                saturated = (
                    saturated or (row.get(f"motor_{motor}_saturated") or "").lower() == "true"
                )
            if saturated:
                stats.motor_saturation_samples += 1

            for value, target_set in (
                (row.get("mission_id"), mission_ids),
                (row.get("configuration_sha256"), configuration_hashes),
                (row.get("mission_execution_id"), execution_ids),
                (row.get("operating_mode"), operating_modes),
                (row.get("csv_schema_version"), schema_versions),
            ):
                if value and value.strip():
                    target_set.add(value.strip())
            event_id = (row.get("event_id") or "").strip()
            if event_id:
                if event_id in event_ids:
                    duplicate_event_count += 1
                event_ids.add(event_id)

    vehicle_output: list[dict[str, Any]] = []
    for vehicle_id, stats in sorted(vehicles.items()):
        availability = {
            name: round(count / stats.sample_count, 6) if stats.sample_count else 0.0
            for name, count in sorted(stats.signal_present.items())
        }
        for name in SIGNAL_GROUPS:
            availability.setdefault(name, 0.0)
        windows = [
            {
                "source_clock_id": clock_id,
                "source_clock_epoch": epoch,
                "start_s": values[0],
                "end_s": values[1],
                "duration_s": values[1] - values[0],
            }
            for (clock_id, epoch), values in sorted(stats.time_windows.items())
        ]
        vehicle_output.append(
            {
                "vehicle_id": vehicle_id,
                "run_ids": sorted(stats.run_ids),
                "sample_count": stats.sample_count,
                "source_time_windows": windows,
                "states": sorted(stats.states),
                "faults": sorted(stats.faults),
                "signal_availability_fraction": availability,
                "speed_m_s": {"min": stats.speed_min, "max": stats.speed_max},
                "altitude_m": {"min": stats.altitude_min, "max": stats.altitude_max},
                "battery_percent": {
                    "start": stats.battery_start[1] if stats.battery_start else None,
                    "end": stats.battery_end[1] if stats.battery_end else None,
                },
                "minimum_battery_voltage_v": stats.voltage_min,
                "maximum_battery_current_a": stats.current_max,
                "minimum_recorded_range_m": stats.range_min,
                "maximum_applied_pwm_percent": stats.motor_pwm_max,
                "motor_saturation_sample_count": stats.motor_saturation_samples,
                "nonmonotonic_sample_count_within_epoch": stats.nonmonotonic_samples,
            }
        )

    anomalies: list[str] = []
    if not vehicle_output:
        anomalies.append("NO_TELEMETRY_ROWS")
    if len(mission_ids) > 1:
        anomalies.append("MIXED_MISSION_IDS")
    if len(configuration_hashes) > 1:
        anomalies.append("MIXED_CONFIGURATION_HASHES")
    if len(execution_ids) > 1:
        anomalies.append("MIXED_MISSION_EXECUTION_IDS")
    if duplicate_event_count:
        anomalies.append("DUPLICATE_EVENT_IDS")
    if malformed[0]:
        anomalies.append("MALFORMED_OR_NONFINITE_SELECTED_NUMERIC_VALUES")
    if any(item["nonmonotonic_sample_count_within_epoch"] for item in vehicle_output):
        anomalies.append("NONMONOTONIC_TELEMETRY_WITHIN_CLOCK_EPOCH")
    if any(len(item["source_time_windows"]) > 1 for item in vehicle_output):
        anomalies.append("MULTIPLE_CLOCK_EPOCHS_OR_SOURCES_ANALYZE_SEPARATELY")

    return {
        "filename": path.name,
        "row_count": sum(item["sample_count"] for item in vehicle_output),
        "csv_schema_versions": sorted(schema_versions),
        "mission_ids": sorted(mission_ids),
        "mission_execution_ids": sorted(execution_ids),
        "configuration_sha256s": sorted(configuration_hashes),
        "operating_modes": sorted(operating_modes),
        "duplicate_event_id_count": duplicate_event_count,
        "malformed_selected_numeric_cell_count": malformed[0],
        "anomalies": anomalies,
        "vehicles": vehicle_output,
    }


def summarize_evaluation(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    evidence = value.get("evidence") if isinstance(value.get("evidence"), dict) else {}
    vehicles = value.get("vehicles") if isinstance(value.get("vehicles"), list) else []
    return {
        "mission_execution_id": value.get("mission_execution_id"),
        "status": value.get("status"),
        "evidence_complete": evidence.get("complete"),
        "missing_evidence": evidence.get("missing", []),
        "summary": value.get("summary", []),
        "fleet": select(value.get("fleet"), FLEET_EVALUATION_FIELDS),
        "vehicles": [select(item, VEHICLE_EVALUATION_FIELDS) for item in vehicles],
        "report_sha256": value.get("report_sha256"),
    }


def summarize_analysis(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    motion = value.get("motion_quality") if isinstance(value.get("motion_quality"), list) else []
    motion_output = [
        {
            "vehicle_id": item.get("vehicle_id"),
            "sample_count": item.get("sample_count"),
            "failed_guards": item.get("failed_guards", []),
            "missing_guards": item.get("missing_guards", []),
            "vector": item.get("vector", {}),
        }
        for item in motion
        if isinstance(item, dict)
    ]
    return {
        "mission_execution_id": value.get("mission_execution_id"),
        "mission_outcome": value.get("mission_outcome"),
        "evidence_complete": value.get("evidence_complete"),
        "all_required_behavior_oracles_passed": value.get("all_required_behavior_oracles_passed"),
        "primary_cause": value.get("primary_cause"),
        "minimum_truth_separation_m": value.get("minimum_truth_separation_m"),
        "telemetry_row_count": value.get("telemetry_row_count"),
        "analysis_parameters": value.get("parameters"),
        "motion_quality": motion_output,
        "analysis_sha256": value.get("analysis_sha256"),
    }


def summarize_manifest(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    fields = (
        "schema_version",
        "artifact_kind",
        "mission_execution_id",
        "mission_id",
        "mission_name",
        "status",
        "case_sha256",
        "configuration_sha256",
        "plan_sha256",
        "planning_submission_id",
        "planning_submission_sha256",
        "resolved_planning_package_sha256",
        "evaluation_evidence_complete",
        "evaluation_report_sha256",
        "telemetry",
        "parameter_overrides",
    )
    return select(value, fields)


def identity_anomalies(summary: dict[str, Any]) -> list[str]:
    identities: dict[str, set[str]] = defaultdict(set)
    for source_name in ("manifest", "evaluation", "analysis"):
        source = summary.get(source_name)
        if not isinstance(source, dict):
            continue
        for identity_field in (
            "mission_execution_id",
            "plan_sha256",
            "planning_submission_sha256",
        ):
            value = source.get(identity_field)
            if value:
                identities[identity_field].add(str(value))
    csv_summary = summary.get("telemetry")
    if isinstance(csv_summary, dict):
        identities["mission_execution_id"].update(csv_summary.get("mission_execution_ids", []))
    return [f"IDENTITY_MISMATCH:{field}" for field, values in identities.items() if len(values) > 1]


def build_summary(target: Path) -> dict[str, Any]:
    artifacts = discover(target)
    manifest = load_json(artifacts["manifest"])
    evaluation = load_json(artifacts["evaluation"])
    analysis = load_json(artifacts["analysis"])
    telemetry_path = artifacts["telemetry"]
    summary: dict[str, Any] = {
        "summary_schema_version": 1,
        "source_artifacts": {
            kind: path.name if path is not None else None for kind, path in artifacts.items()
        },
        "manifest": summarize_manifest(manifest),
        "evaluation": summarize_evaluation(evaluation),
        "analysis": summarize_analysis(analysis),
        "telemetry": summarize_csv(telemetry_path) if telemetry_path is not None else None,
        "claim_boundary": (
            "Telemetry and simulator outputs retain their recorded source class; this summary "
            "does not qualify physical flight or a digital twin."
        ),
    }
    summary["cross_artifact_anomalies"] = identity_anomalies(summary)
    return summary


def markdown(summary: dict[str, Any]) -> str:
    lines = ["# Compact run summary", ""]
    manifest = summary.get("manifest") or {}
    evaluation = summary.get("evaluation") or {}
    analysis = summary.get("analysis") or {}
    execution_id = (
        manifest.get("mission_execution_id")
        or evaluation.get("mission_execution_id")
        or analysis.get("mission_execution_id")
        or "unavailable"
    )
    status = evaluation.get("status") or manifest.get("status") or "unavailable"
    outcome = analysis.get("mission_outcome") or "unavailable"
    evidence_complete = evaluation.get("evidence_complete", "unavailable")
    oracles_passed = analysis.get("all_required_behavior_oracles_passed", "unavailable")
    lines.extend(
        (
            f"- Mission execution: `{execution_id}`",
            f"- Status/outcome: `{status}` / `{outcome}`",
            f"- Evidence complete: `{evidence_complete}`",
            f"- Behavior oracles passed: `{oracles_passed}`",
            "",
        )
    )
    telemetry = summary.get("telemetry")
    if isinstance(telemetry, dict):
        lines.extend(("## Telemetry", "", f"Rows: {telemetry['row_count']}", ""))
        for vehicle in telemetry["vehicles"]:
            lines.append(
                f"- `{vehicle['vehicle_id']}`: {vehicle['sample_count']} samples; "
                f"speed max {vehicle['speed_m_s']['max']}; altitude "
                f"{vehicle['altitude_m']['min']}..{vehicle['altitude_m']['max']} m; "
                f"faults {vehicle['faults'] or 'none'}"
            )
        anomalies = telemetry.get("anomalies", []) + summary.get("cross_artifact_anomalies", [])
        lines.extend(("", f"Anomalies: {', '.join(anomalies) if anomalies else 'none'}", ""))
    if evaluation.get("summary"):
        lines.extend(("## Evaluation", ""))
        lines.extend(f"- {item}" for item in evaluation["summary"])
        lines.append("")
    if analysis.get("motion_quality"):
        lines.extend(("## Motion guards", ""))
        for item in analysis["motion_quality"]:
            lines.append(
                f"- `{item.get('vehicle_id')}`: failed={item.get('failed_guards', [])}; "
                f"missing={item.get('missing_guards', [])}"
            )
        lines.append("")
    lines.extend(("## Claim boundary", "", str(summary["claim_boundary"]), ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a compact, read-only summary of retained mission-run artifacts"
    )
    parser.add_argument("target", type=Path, help="mission folder or one telemetry artifact")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    try:
        summary = build_summary(args.target)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"summarize_run: {error}", file=sys.stderr)
        return 2
    if args.format == "markdown":
        print(markdown(summary), end="")
    else:
        print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
