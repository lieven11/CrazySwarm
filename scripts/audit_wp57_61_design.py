#!/usr/bin/env python3
"""Freeze the exact 1D review evidence used to design WP-57 through WP-61.

This is a pre-draft audit, not a product analyzer.  It deliberately reads the
operator-owned campaign workspace without changing lifecycle state and retains the
source artifact hashes, literal comments, snapshot-time samples, and independently
derived route/motor/IMU measurements needed by the packet design.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

PACKET_IDS = ("WP-57", "WP-58", "WP-59", "WP-60", "WP-61")

COMPARISONS = (
    {
        "comparison_id": "circle.constant_speed_vs_baseline",
        "baseline_run_ids": ("campaign-run-df75ca50ffa5c6f32a86",),
        "subject_run_id": "campaign-run-facbf746f96ae4229d25",
        "metrics": (
            "speed_90_percent_ripple_m_s",
            "imu_angular_rate_p95_rad_s",
            "motor_spread_p95_percent",
            "tracking_rms_error_m",
        ),
    },
    {
        "comparison_id": "waypoint.smoothness_vs_repeatable_baseline",
        "baseline_run_ids": ("campaign-run-ff6365da70ae904ac0cb",),
        "subject_run_id": "campaign-run-44deac41370451f16d88",
        "metrics": (
            "speed_90_percent_ripple_m_s",
            "acceleration_p95_m_s2",
            "jerk_p95_m_s3",
            "imu_angular_rate_p95_rad_s",
            "motor_spread_p95_percent",
            "tracking_rms_error_m",
        ),
    },
    {
        "comparison_id": "rounded_square.corner_transition_vs_baseline",
        "baseline_run_ids": ("campaign-run-3766abb44ed230e02072",),
        "subject_run_id": "campaign-run-e9bf520c4dc562c5453c",
        "metrics": (
            "speed_90_percent_ripple_m_s",
            "acceleration_p95_m_s2",
            "jerk_p95_m_s3",
            "tracking_rms_error_m",
        ),
    },
    {
        "comparison_id": "figure_eight.curvature_vs_repeatable_baseline",
        "baseline_run_ids": (
            "campaign-run-2687d3c2dfa5999c6908",
            "campaign-run-7e55b398244d31cb6a75",
        ),
        "subject_run_id": "campaign-run-8dbb299cb89bc20dde1d",
        "metrics": (
            "repeated_geometry_knot_speed_ratio",
            "speed_90_percent_ripple_m_s",
            "jerk_p95_m_s3",
            "tracking_rms_error_m",
        ),
    },
    {
        "comparison_id": "curve.jerk_first_vs_baseline",
        "baseline_run_ids": ("campaign-run-a074de394bffa546c79a",),
        "subject_run_id": "campaign-run-15a4993a51cd538c18d7",
        "metrics": (
            "acceleration_p95_m_s2",
            "jerk_p95_m_s3",
            "terminal_secondary_speed_peak_count",
            "tracking_rms_error_m",
        ),
    },
)

CLAIM_KEYS = (
    "WP57.complete_1d_evidence_and_motion_quality_vector",
    "WP57.foundation_mission_order",
    "WP58.whole_route_continuous_motion",
    "WP58.checkpoint_motion_remains_distinct",
    "WP58.hash_bound_in_flight_motion_contract",
    "WP59.single_drone_sensor_sourced_changed_world_replanning",
    "WP59.dynamic_obstacle_sequence_and_safe_fallback",
    "WP60.differential_actuation_and_physical_truth_evidence",
    "WP61.persistent_digital_twin_sensor_pipeline",
    "WP61.gated_hardware_curriculum_and_holdout_calibration",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _float(row: dict[str, str], key: str) -> float | None:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _percentile(values: list[float], fraction: float) -> float | None:
    ordered = sorted(value for value in values if math.isfinite(value))
    if not ordered:
        return None
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def _norm(row: dict[str, str], fields: tuple[str, str, str]) -> float | None:
    values = tuple(_float(row, field) for field in fields)
    if any(value is None for value in values):
        return None
    return math.sqrt(sum(value * value for value in values if value is not None))


def _unique_samples(path: Path) -> list[tuple[float, dict[str, str]]]:
    samples: dict[tuple[str, str, str], tuple[float, dict[str, str]]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            timestamp = _float(row, "source_timestamp_s")
            if timestamp is None or _float(row, "velocity_x_m_s") is None:
                continue
            identity = (
                row.get("vehicle_id", ""),
                row.get("source_clock_epoch", ""),
                row.get("telemetry_sequence", ""),
            )
            samples[identity] = (timestamp, row)
    return sorted(samples.values(), key=lambda item: (item[0], item[1]["telemetry_sequence"]))


def _route_from_bundle(bundle: dict[str, Any]) -> dict[str, Any] | None:
    plan = bundle.get("campaign_plan", {})
    index = plan.get("selected_candidate_index")
    candidates = plan.get("retained_candidates", [])
    if not isinstance(index, int) or not 0 <= index < len(candidates):
        return None
    routes = candidates[index].get("routes", [])
    return routes[0] if len(routes) == 1 else None


def _nearest_sample(
    samples: list[tuple[float, dict[str, str]]], timestamp_s: float
) -> dict[str, Any] | None:
    if not samples:
        return None
    timestamp, row = min(samples, key=lambda item: abs(item[0] - timestamp_s))
    motors = [
        _float(row, f"motor_m{index}_applied_pwm_percent") for index in range(1, 5)
    ]
    speed = _norm(
        row,
        ("velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"),
    )
    acceleration = _norm(
        row,
        (
            "imu_acceleration_x_m_s2",
            "imu_acceleration_y_m_s2",
            "imu_acceleration_z_m_s2",
        ),
    )
    angular_rate = _norm(
        row,
        (
            "imu_angular_velocity_x_rad_s",
            "imu_angular_velocity_y_rad_s",
            "imu_angular_velocity_z_rad_s",
        ),
    )
    valid_motors = [value for value in motors if value is not None]
    return {
        "source_timestamp_s": timestamp,
        "position_m": {
            axis: _float(row, f"ground_truth_{axis}_m") for axis in ("x", "y", "z")
        },
        "speed_m_s": speed,
        "imu_specific_force_norm_m_s2": acceleration,
        "imu_angular_rate_norm_rad_s": angular_rate,
        "motor_applied_pwm_percent": motors,
        "motor_spread_percent": (
            max(valid_motors) - min(valid_motors) if len(valid_motors) == 4 else None
        ),
    }


def _knot_measurements(
    route: dict[str, Any] | None,
    samples: list[tuple[float, dict[str, str]]],
    route_start_s: float | None,
    route_end_s: float | None,
) -> list[dict[str, Any]]:
    if route is None or route_start_s is None or route_end_s is None:
        return []
    durations = route.get("segment_durations_s", [])
    positions = route.get("points_m", [])
    timestamp = route_start_s
    output: list[dict[str, Any]] = []
    for index, duration in enumerate(durations[:-1], start=1):
        timestamp += float(duration)
        near = [
            speed
            for sample_time, row in samples
            if abs(sample_time - timestamp) <= 0.12
            and (speed := _norm(
                row,
                ("velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"),
            ))
            is not None
        ]
        adjacent = [
            speed
            for sample_time, row in samples
            if 0.35 <= abs(sample_time - timestamp) <= 0.75
            and route_start_s <= sample_time <= route_end_s
            and (speed := _norm(
                row,
                ("velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"),
            ))
            is not None
        ]
        near_median = _percentile(near, 0.5)
        adjacent_median = _percentile(adjacent, 0.5)
        position = positions[index] if index < len(positions) else None
        repeated_geometry = bool(
            position is not None
            and sum(candidate == position for candidate in positions) > 1
        )
        output.append(
            {
                "knot_index": index,
                "elapsed_route_s": timestamp - route_start_s,
                "position_m": position,
                "repeated_geometry": repeated_geometry,
                "near_speed_median_m_s": near_median,
                "adjacent_speed_median_m_s": adjacent_median,
                "near_to_adjacent_speed_ratio": (
                    near_median / adjacent_median
                    if near_median is not None
                    and adjacent_median is not None
                    and adjacent_median > 0.0
                    else None
                ),
            }
        )
    return output


def _terminal_speed_metrics(
    route: dict[str, Any] | None,
    samples: list[tuple[float, dict[str, str]]],
    route_start_s: float | None,
    route_end_s: float | None,
) -> dict[str, Any]:
    """Measure literal late-route reacceleration without filtering it away.

    The terminal-approach window is the final authored route segment. Speeds are
    reduced to fixed 0.10 s source-clock medians so duplicate recorder rows cannot
    create a peak. A secondary peak exists when a later bucket rises more than the
    frozen 0.02 m/s prominence above the lowest earlier bucket before route handoff.
    """

    prominence_m_s = 0.02
    if route is None or route_start_s is None or route_end_s is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "route or source-time boundary unavailable",
            "prominence_threshold_m_s": prominence_m_s,
        }
    durations = tuple(float(value) for value in route.get("segment_durations_s", ()))
    if not durations:
        return {
            "status": "UNAVAILABLE",
            "reason": "route has no authored segment durations",
            "prominence_threshold_m_s": prominence_m_s,
        }
    window_start_s = route_start_s + sum(durations[:-1])
    bucket_values: dict[int, list[float]] = {}
    for timestamp, row in samples:
        if timestamp < window_start_s or timestamp > route_end_s:
            continue
        speed = _norm(row, ("velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"))
        if speed is None:
            continue
        bucket = min(
            max(0, int((timestamp - window_start_s) / 0.10)),
            max(0, int((route_end_s - window_start_s) / 0.10)),
        )
        bucket_values.setdefault(bucket, []).append(speed)
    bucket_medians = [
        {
            "elapsed_terminal_s": round(bucket * 0.10, 9),
            "speed_m_s": _percentile(values, 0.5),
        }
        for bucket, values in sorted(bucket_values.items())
    ]
    running_min = float("inf")
    peaks: list[dict[str, Any]] = []
    speeds = [float(item["speed_m_s"]) for item in bucket_medians]
    for index, speed in enumerate(speeds):
        if speed < running_min:
            running_min = speed
        next_speed = speeds[index + 1] if index + 1 < len(speeds) else -float("inf")
        prominence = speed - running_min
        if speed >= next_speed and prominence > prominence_m_s:
            peaks.append(
                {
                    "elapsed_terminal_s": bucket_medians[index]["elapsed_terminal_s"],
                    "speed_m_s": speed,
                    "prior_minimum_speed_m_s": running_min,
                    "prominence_m_s": prominence,
                }
            )
            running_min = speed
    return {
        "status": "AVAILABLE",
        "window_start_source_s": window_start_s,
        "window_end_source_s": route_end_s,
        "bucket_width_s": 0.10,
        "prominence_threshold_m_s": prominence_m_s,
        "bucket_medians": bucket_medians,
        "terminal_secondary_speed_peak_count": len(peaks),
        "secondary_peaks": peaks,
    }


def _artifact_linkage(
    *,
    run_id: str,
    telemetry_path: Path,
    bundle_path: Path,
    manifest_path: Path,
    analysis: dict[str, Any],
    evaluation: dict[str, Any],
    bundle: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    locked = bundle.get("context", {}).get("campaign_locked_inputs", {})
    checks = {
        "run_identity": all(
            value == run_id
            for value in (
                analysis.get("mission_execution_id"),
                evaluation.get("mission_execution_id"),
                bundle.get("mission_execution_id"),
                manifest.get("mission_execution_id"),
            )
        ),
        "telemetry_file_hash": (
            _sha256(telemetry_path)
            == analysis.get("csv_sha256")
            == manifest.get("artifact", {}).get("sha256")
        ),
        "manifest_file_hash": _sha256(manifest_path) == analysis.get("manifest_sha256"),
        "bundle_file_hash": _sha256(bundle_path) == analysis.get("bundle_sha256"),
        "bundle_content_hash": (
            bundle.get("bundle_sha256")
            == manifest.get("bundle", {}).get("bundle_sha256")
        ),
        "evaluation_report_hash": (
            evaluation.get("report_sha256")
            == bundle.get("evaluation", {}).get("report_sha256")
            == manifest.get("evaluation", {}).get("report_sha256")
        ),
        "case_identity": (
            analysis.get("case_sha256")
            == bundle.get("case_sha256")
            == locked.get("case_sha256")
            == manifest.get("case_sha256")
        ),
        "plan_identity": (
            analysis.get("plan_sha256")
            == bundle.get("campaign_plan", {}).get("plan_sha256")
            == manifest.get("plan_sha256")
        ),
        "planning_submission_identity": (
            analysis.get("planning_submission_sha256")
            == bundle.get("planning_submission_sha256")
            == locked.get("planning_submission_sha256")
            == manifest.get("planning_submission_sha256")
        ),
        "resolved_package_identity": (
            analysis.get("resolved_planning_package_sha256")
            == bundle.get("resolved_planning_package_sha256")
            == locked.get("resolved_planning_package_sha256")
            == manifest.get("resolved_planning_package_sha256")
        ),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "failed_checks": tuple(name for name, passed in checks.items() if not passed),
    }


def _run_record(
    workspace: Path,
    run: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    run_id = run["run_id"]
    evidence_dir = workspace / "evidence" / run_id
    telemetry_path = evidence_dir / "telemetry.csv"
    analysis_path = evidence_dir / "analysis.json"
    evaluation_path = evidence_dir / "evaluation.json"
    bundle_path = evidence_dir / "execution-bundle.json"
    manifest_path = evidence_dir / "manifest.json"
    required = (
        telemetry_path,
        analysis_path,
        evaluation_path,
        bundle_path,
        manifest_path,
    )
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        return {
            "run_id": run_id,
            "case_id": review["case_id"],
            "status": run.get("status"),
            "operator_observations": review.get("operator_observations", []),
            "evidence_complete_for_audit": False,
            "missing_files": missing,
        }

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    vehicle = analysis["vehicles"][0]
    evaluation_vehicle = evaluation["vehicles"][0]
    timeline = vehicle["timeline"]
    route_start = timeline.get("route_start_source_s")
    route_end = timeline.get("landing_start_source_s")
    samples = _unique_samples(telemetry_path)
    route_samples = [
        row
        for timestamp, row in samples
        if route_start is not None
        and route_end is not None
        and route_start <= timestamp <= route_end
    ]
    speeds = [
        value
        for row in route_samples
        if (value := _norm(
            row,
            ("velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"),
        ))
        is not None
    ]
    acceleration_norms = [
        value
        for row in route_samples
        if (value := _norm(
            row,
            (
                "imu_acceleration_x_m_s2",
                "imu_acceleration_y_m_s2",
                "imu_acceleration_z_m_s2",
            ),
        ))
        is not None
    ]
    acceleration_median = _percentile(acceleration_norms, 0.5)
    specific_force_ripple = (
        [abs(value - acceleration_median) for value in acceleration_norms]
        if acceleration_median is not None
        else []
    )
    angular_rates = [
        value
        for row in route_samples
        if (value := _norm(
            row,
            (
                "imu_angular_velocity_x_rad_s",
                "imu_angular_velocity_y_rad_s",
                "imu_angular_velocity_z_rad_s",
            ),
        ))
        is not None
    ]
    motor_spreads: list[float] = []
    moving_motor_samples = 0
    moving_unequal_motor_samples = 0
    for row, speed in zip(route_samples, speeds, strict=False):
        motors = [
            _float(row, f"motor_m{index}_applied_pwm_percent")
            for index in range(1, 5)
        ]
        if any(value is None for value in motors):
            continue
        present = [value for value in motors if value is not None]
        if not present or max(present) <= 0.0:
            continue
        spread = max(present) - min(present)
        motor_spreads.append(spread)
        if speed > 0.05:
            moving_motor_samples += 1
            if spread > 1e-4:
                moving_unequal_motor_samples += 1

    p05 = _percentile(speeds, 0.05)
    p95 = _percentile(speeds, 0.95)
    route = _route_from_bundle(bundle)
    knot_measurements = _knot_measurements(route, samples, route_start, route_end)
    repeated_knot_ratios = [
        float(item["near_to_adjacent_speed_ratio"])
        for item in knot_measurements
        if item["repeated_geometry"] and item["near_to_adjacent_speed_ratio"] is not None
    ]
    terminal_metrics = _terminal_speed_metrics(route, samples, route_start, route_end)
    return {
        "run_id": run_id,
        "case_id": review["case_id"],
        "status": run.get("status"),
        "mode": run.get("mode"),
        "started_at_utc": run.get("started_at_utc"),
        "finished_at_utc": run.get("finished_at_utc"),
        "submission_id": run["locked_inputs"].get("submission_id"),
        "planning_submission_id": run["locked_inputs"].get(
            "planning_submission_id"
        ),
        "operator_observations": review.get("operator_observations", []),
        "evidence_complete_for_audit": True,
        "source_hashes": {
            path.name: _sha256(path) for path in required
        },
        "artifact_linkage": _artifact_linkage(
            run_id=run_id,
            telemetry_path=telemetry_path,
            bundle_path=bundle_path,
            manifest_path=manifest_path,
            analysis=analysis,
            evaluation=evaluation,
            bundle=bundle,
            manifest=manifest,
        ),
        "retained_analysis": {
            "mission_outcome": analysis.get("mission_outcome"),
            "all_required_behavior_oracles_passed": analysis.get(
                "all_required_behavior_oracles_passed"
            ),
            "tracking_rms_error_m": vehicle.get("tracking_rms_error_m"),
            "tracking_max_error_m": vehicle.get("tracking_max_error_m"),
            "unintended_stop_count": vehicle.get("unintended_stop_count"),
            "acceleration_p95_m_s2": vehicle.get("acceleration_m_s2", {}).get("p95"),
            "acceleration_peak_m_s2": vehicle.get("acceleration_m_s2", {}).get("peak"),
            "jerk_p95_m_s3": vehicle.get("jerk_m_s3", {}).get("p95"),
            "jerk_peak_m_s3": vehicle.get("jerk_m_s3", {}).get("peak"),
            "terminal_state": vehicle.get("terminal_state"),
            "terminal_raw_vertical_speed_peak_m_s": vehicle.get(
                "kinematics_gate_reconciliation", {}
            ).get("raw_vertical_speed_peak_m_s"),
        },
        "retained_evaluation": {
            "profile_kind": evaluation_vehicle.get("profile_kind"),
            "profile_steady_speed_p05_m_s": evaluation_vehicle.get(
                "profile_steady_speed_p05_m_s"
            ),
            "profile_steady_speed_p95_m_s": evaluation_vehicle.get(
                "profile_steady_speed_p95_m_s"
            ),
            "profile_steady_speed_ripple_m_s": evaluation_vehicle.get(
                "profile_steady_speed_ripple_m_s"
            ),
            "trajectory_speed_rms_error_m_s": evaluation_vehicle.get(
                "trajectory_speed_rms_error_m_s"
            ),
            "minimum_motor_thrust_headroom_n": evaluation_vehicle.get(
                "minimum_motor_thrust_headroom_n"
            ),
            "motor_saturation_sample_count": evaluation_vehicle.get(
                "motor_saturation_sample_count"
            ),
        },
        "independent_route_metrics": {
            "sample_count": len(route_samples),
            "speed_p05_m_s": p05,
            "speed_p50_m_s": _percentile(speeds, 0.5),
            "speed_p95_m_s": p95,
            "speed_90_percent_ripple_m_s": (
                p95 - p05 if p05 is not None and p95 is not None else None
            ),
            "imu_specific_force_ripple_p95_m_s2": _percentile(
                specific_force_ripple, 0.95
            ),
            "imu_angular_rate_p95_rad_s": _percentile(angular_rates, 0.95),
            "motor_spread_p95_percent": _percentile(motor_spreads, 0.95),
            "motor_spread_max_percent": max(motor_spreads) if motor_spreads else None,
            "moving_unequal_motor_fraction": (
                moving_unequal_motor_samples / moving_motor_samples
                if moving_motor_samples
                else None
            ),
            "repeated_geometry_knot_speed_ratio": (
                min(repeated_knot_ratios) if repeated_knot_ratios else None
            ),
            "knot_measurements": knot_measurements,
            "terminal_speed": terminal_metrics,
            "terminal_secondary_speed_peak_count": terminal_metrics.get(
                "terminal_secondary_speed_peak_count"
            ),
        },
    }


def _comparison_metric_value(record: dict[str, Any], metric: str) -> float | int | None:
    analysis_metrics = record.get("retained_analysis", {})
    independent_metrics = record.get("independent_route_metrics", {})
    if metric in analysis_metrics:
        value = analysis_metrics[metric]
    else:
        value = independent_metrics.get(metric)
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def _relative_improvement(baseline: float, candidate: float) -> float:
    return (baseline - candidate) / baseline if baseline > 0.0 else 0.0


def _oracle_prototypes() -> dict[str, Any]:
    """Retain exact independent witnesses for every newly frozen numerical gate."""

    arm_projection_m = 0.046 / math.sqrt(2.0)
    pitch_thrusts_n = (0.065, 0.075, 0.075, 0.065)
    pitch_torque_n_m = arm_projection_m * (
        pitch_thrusts_n[1]
        + pitch_thrusts_n[2]
        - pitch_thrusts_n[0]
        - pitch_thrusts_n[3]
    )
    pitch_angular_acceleration_rad_s2 = pitch_torque_n_m / 1.43e-5
    constant_speed_pass = [0.30] * 95 + [0.34] + [0.36] * 4
    constant_speed_fail = [0.30] * 94 + [0.36] * 6

    def speed_vector(values: list[float]) -> dict[str, Any]:
        inside = [value for value in values if abs(value - 0.30) <= 0.05]
        p05 = _percentile(values, 0.05)
        p95 = _percentile(values, 0.95)
        return {
            "sample_count": len(values),
            "inside_target_band_count": len(inside),
            "inside_target_band_fraction": len(inside) / len(values),
            "p05_m_s": p05,
            "p95_m_s": p95,
            "p95_minus_p05_m_s": (
                p95 - p05 if p05 is not None and p95 is not None else None
            ),
        }

    terminal_pass = (0.30, 0.24, 0.18, 0.199, 0.14, 0.08, 0.02)
    terminal_fail = (0.30, 0.24, 0.18, 0.201, 0.14, 0.08, 0.02)

    def terminal_prominence(values: tuple[float, ...]) -> float:
        minimum = values[0]
        maximum_rise = 0.0
        for value in values[1:]:
            maximum_rise = max(maximum_rise, value - minimum)
            minimum = min(minimum, value)
        return maximum_rise

    return {
        "prototype_command": (
            "python scripts/audit_wp57_61_design.py --output "
            "missions/campaigns/sim/qualification/wp57-61-predraft-1d-evidence-v1.json"
        ),
        "WP57_terminal_peak": {
            "sampling": "0.10 s source-clock bucket medians over final authored route segment",
            "comparison": "strictly greater than 0.02 m/s prominence fails",
            "pass_input_m_s": terminal_pass,
            "pass_maximum_rise_m_s": terminal_prominence(terminal_pass),
            "pass_verdict": terminal_prominence(terminal_pass) <= 0.02,
            "fail_input_m_s": terminal_fail,
            "fail_maximum_rise_m_s": terminal_prominence(terminal_fail),
            "fail_verdict": terminal_prominence(terminal_fail) <= 0.02,
        },
        "WP58_motion_gates": {
            "fly_through_knot": {
                "threshold": 0.85,
                "pass": {"knot_m_s": 0.27, "adjacent_m_s": 0.30, "ratio": 0.90},
                "fail": {"knot_m_s": 0.24, "adjacent_m_s": 0.30, "ratio": 0.80},
            },
            "repeated_crossover": {
                "threshold": 0.95,
                "pass": {"knot_m_s": 0.291, "adjacent_m_s": 0.30, "ratio": 0.97},
                "fail": {"knot_m_s": 0.282, "adjacent_m_s": 0.30, "ratio": 0.94},
            },
            "constant_speed": {
                "target_m_s": 0.30,
                "band_m_s": 0.05,
                "minimum_coverage": 0.95,
                "maximum_p95_minus_p05_m_s": 0.05,
                "pass": speed_vector(constant_speed_pass),
                "fail": speed_vector(constant_speed_fail),
            },
            "integrated_squared_jerk": {
                "minimum_relative_improvement": 0.20,
                "baseline": 10.0,
                "pass_candidate": 7.5,
                "pass_improvement": _relative_improvement(10.0, 7.5),
                "fail_candidate": 8.1,
                "fail_improvement": _relative_improvement(10.0, 8.1),
            },
            "angular_and_motor_nonregression": {
                "maximum_relative_regression": 0.10,
                "angular": {"baseline": 0.20, "pass": 0.218, "fail": 0.222},
                "motor_spread": {"baseline": 0.40, "pass": 0.436, "fail": 0.444},
            },
            "tracking": {
                "maximum_absolute_regression_m": 0.01,
                "tube_m": 0.05,
                "baseline_m": 0.02,
                "pass_candidate_m": 0.029,
                "fail_candidate_m": 0.031,
            },
            "duration": {
                "maximum_ratio": 1.75,
                "baseline_s": 10.0,
                "pass_candidate_s": 17.0,
                "fail_candidate_s": 17.6,
            },
            "route_equivalence": {
                "maximum_sample_difference_m": 1e-6,
                "pass_difference_m": 5e-7,
                "fail_difference_m": 1.1e-6,
                "sample_step_m": 0.01,
            },
        },
        "WP60_force_torque_alignment": {
            "rotor_positions_m": (
                (arm_projection_m, -arm_projection_m, 0.0),
                (-arm_projection_m, -arm_projection_m, 0.0),
                (-arm_projection_m, arm_projection_m, 0.0),
                (arm_projection_m, arm_projection_m, 0.0),
            ),
            "pitch_witness_thrusts_n": pitch_thrusts_n,
            "expected_pitch_torque_n_m": pitch_torque_n_m,
            "inertia_y_kg_m2": 1.43e-5,
            "expected_pitch_angular_acceleration_rad_s2": (
                pitch_angular_acceleration_rad_s2
            ),
            "force_torque_absolute_tolerance": 1e-9,
            "maximum_source_alignment_s": 0.01,
            "pass_source_shift_s": 0.01,
            "fail_source_shift_s": 0.02,
            "response_sign_window_s": 0.05,
        },
        "WP61_ingestion_and_calibration": {
            "ingestion": {
                "maximum_batch_records": 512,
                "maximum_request_bytes": 1_048_576,
                "maximum_channels_per_session": 32,
                "maximum_channel_rate_hz": 500.0,
                "maximum_buffered_records": 4096,
                "maximum_records_per_session": 1_000_000,
                "maximum_session_bytes": 4_294_967_296,
                "overflow_disposition": "REJECT_WHOLE_BATCH_RETRYABLE_NO_DROP",
                "duplicate_disposition": "IDEMPOTENT_ONLY_IF_HASH_EQUAL",
                "retention": "operator-owned; no automatic deletion in this batch",
            },
            "calibration_parameter_family": {
                "mass_scale": (0.85, 1.15),
                "linear_drag_scale": (0.50, 1.50),
                "motor_time_constant_scale": (0.75, 1.25),
                "thrust_scale": (0.85, 1.15),
            },
            "split": {
                "minimum_sessions": 6,
                "minimum_geometries": 2,
                "training_sessions_per_geometry": 2,
                "holdout_sessions_per_geometry": 1,
                "unit": "whole session; no segment crosses split",
                "assignment": "per-geometry canonical session hash rank before fitting",
            },
            "promotion": {
                "primary_metric": "holdout_position_rmse_m",
                "minimum_relative_improvement": 0.10,
                "minimum_absolute_improvement_m": 0.005,
                "maximum_altitude_velocity_rmse_regression": 0.05,
                "deterministic_replay_repeats": 3,
                "baseline_holdout_rmse_m": (0.080, 0.070),
                "pass_candidate_holdout_rmse_m": (0.068, 0.060),
                "fail_candidate_holdout_rmse_m": (0.074, 0.066),
                "pass_mean_relative_improvement": _relative_improvement(0.075, 0.064),
                "pass_mean_absolute_improvement_m": 0.011,
                "fail_mean_relative_improvement": _relative_improvement(0.075, 0.070),
                "fail_mean_absolute_improvement_m": 0.005,
            },
        },
    }


def build_audit(workspace: Path) -> dict[str, Any]:
    state_path = workspace / "workspace-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    run_by_id = {run["run_id"]: run for run in state["runs"]}
    reviews = [
        review for review in state["reviews"] if review["case_id"].startswith("1d.")
    ]
    records = [
        _run_record(workspace, run_by_id[review["run_id"]], review)
        for review in reviews
    ]
    snapshots = []
    for snapshot in state["snapshots"]:
        if not snapshot["case_id"].startswith("1d."):
            continue
        image_path = workspace / "snapshots" / snapshot["run_id"] / snapshot["filename"]
        samples = _unique_samples(
            workspace / "evidence" / snapshot["run_id"] / "telemetry.csv"
        )
        snapshots.append(
            {
                "snapshot_id": snapshot["snapshot_id"],
                "run_id": snapshot["run_id"],
                "case_id": snapshot["case_id"],
                "filename": snapshot["filename"],
                "sha256": _sha256(image_path),
                "recorded_sha256": snapshot["sha256"],
                "source_timestamp_s": snapshot["review_frame"]["source_timestamp_s"],
                "operator_comment": snapshot.get("operator_comment"),
                "neutral_assessment": snapshot.get("neutral_assessment"),
                "exact_time_sample": _nearest_sample(
                    samples, snapshot["review_frame"]["source_timestamp_s"]
                ),
            }
        )

    reviewed_run_ids = {record["run_id"] for record in records}
    failed_without_review = [
        {
            "run_id": run["run_id"],
            "case_id": run["locked_inputs"]["case_id"],
            "status": run["status"],
            "failure_reason": run.get("failure_reason"),
            "finished_at_utc": run.get("finished_at_utc"),
        }
        for run in state["runs"]
        if run["locked_inputs"]["case_id"].startswith("1d.")
        and run["run_id"] not in reviewed_run_ids
        and run["status"] == "FAILED"
    ]
    lifecycle = {
        case_id: entry
        for case_id, entry in state["lifecycle"].items()
        if case_id.startswith("1d.")
    }
    record_by_id = {record["run_id"]: record for record in records}
    comparison_audit = []
    for comparison in COMPARISONS:
        run_ids = (*comparison["baseline_run_ids"], comparison["subject_run_id"])
        missing = sorted(set(run_ids) - set(record_by_id))
        case_ids = sorted(
            {record_by_id[run_id]["case_id"] for run_id in run_ids if run_id in record_by_id}
        )
        modes = sorted(
            {record_by_id[run_id]["mode"] for run_id in run_ids if run_id in record_by_id}
        )
        metric_values_by_run_id = {
            run_id: {
                metric: _comparison_metric_value(record_by_id[run_id], metric)
                for metric in comparison["metrics"]
            }
            for run_id in run_ids
            if run_id in record_by_id
        }
        missing_metrics_by_run_id = {
            run_id: tuple(
                metric for metric, value in values.items() if value is None
            )
            for run_id, values in metric_values_by_run_id.items()
            if any(value is None for value in values.values())
        }
        linkage_failures = {
            run_id: record_by_id[run_id]["artifact_linkage"]["failed_checks"]
            for run_id in run_ids
            if run_id in record_by_id
            and not record_by_id[run_id]["artifact_linkage"]["passed"]
        }
        metric_dispositions = {
            metric: (
                "OPEN_CURRENT_BASELINE_AND_SUBJECT_NONZERO"
                if metric == "terminal_secondary_speed_peak_count"
                and all(
                    (values.get(metric) or 0) > 0
                    for values in metric_values_by_run_id.values()
                )
                else "AVAILABLE_FOR_DESIGN_NOT_A_QUALIFICATION_VERDICT"
            )
            for metric in comparison["metrics"]
        }
        passed = (
            not missing
            and len(case_ids) == 1
            and len(modes) == 1
            and not missing_metrics_by_run_id
            and not linkage_failures
        )
        comparison_audit.append(
            {
                **comparison,
                "missing_run_ids": missing,
                "case_ids": case_ids,
                "modes": modes,
                "same_case": len(case_ids) == 1,
                "same_clock_mode": len(modes) == 1,
                "metric_values_by_run_id": metric_values_by_run_id,
                "missing_metrics_by_run_id": missing_metrics_by_run_id,
                "artifact_linkage_failures_by_run_id": linkage_failures,
                "metric_dispositions": metric_dispositions,
                "passed": passed,
            }
        )
    summary = {
        "reviewed_1d_run_count": len(records),
        "reviewed_1d_case_count": len({record["case_id"] for record in records}),
        "complete_review_evidence_count": sum(
            bool(record["evidence_complete_for_audit"]) for record in records
        ),
        "commented_review_count": sum(
            bool(record["operator_observations"]) for record in records
        ),
        "snapshot_count": len(snapshots),
        "failed_unreviewed_run_count": len(failed_without_review),
        "lifecycle_counts": dict(
            sorted(Counter(entry["state"] for entry in lifecycle.values()).items())
        ),
        "moving_runs_with_differential_motor_evidence": sum(
            (
                record.get("independent_route_metrics", {}).get(
                    "moving_unequal_motor_fraction"
                )
                or 0.0
            )
            > 0.95
            for record in records
        ),
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "WP-57 through WP-61 pre-draft 1D review evidence audit",
        "source_workspace_state_sha256": _sha256(state_path),
        "summary": summary,
        "lifecycle": lifecycle,
        "reviewed_runs": records,
        "snapshots": snapshots,
        "failed_unreviewed_runs": failed_without_review,
        "oracle_prototypes": _oracle_prototypes(),
        "design_set_audit": {
            "packet_ids": PACKET_IDS,
            "packet_ids_unique": len(set(PACKET_IDS)) == len(PACKET_IDS),
            "claim_keys": CLAIM_KEYS,
            "claim_keys_unique": len(set(CLAIM_KEYS)) == len(CLAIM_KEYS),
            "comparisons": comparison_audit,
            "all_comparisons_passed": all(
                comparison["passed"] for comparison in comparison_audit
            ),
            "all_reviewed_runs_have_one_record": len(record_by_id) == len(records),
            "all_review_evidence_complete": all(
                record["evidence_complete_for_audit"] for record in records
            ),
            "all_artifact_linkage_passed": all(
                record["artifact_linkage"]["passed"] for record in records
            ),
        },
        "metric_definitions": {
            "route_window": "retained analyzer route_start_source_s through landing_start_source_s",
            "speed_90_percent_ripple_m_s": "independent source-time velocity-norm p95 minus p05",
            "imu_specific_force_ripple_p95_m_s2": (
                "p95 absolute deviation of body IMU force norm from its "
                "route-window median"
            ),
            "imu_angular_rate_p95_rad_s": "p95 body angular-velocity vector norm",
            "motor_spread_percent": (
                "maximum minus minimum recorded applied PWM across motors M1..M4"
            ),
            "knot_speed_ratio": (
                "median speed within 0.12 s of the knot divided by median speed "
                "0.35..0.75 s from it"
            ),
            "terminal_secondary_speed_peak_count": (
                "count of final-segment 0.10 s source-clock median-speed peaks whose "
                "rise above an earlier minimum is strictly greater than 0.02 m/s"
            ),
        },
    }
    payload["payload_sha256"] = _canonical_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(".cache/crazyswarm/campaign"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    arguments = parser.parse_args()
    audit = build_audit(arguments.workspace)
    rendered = json.dumps(audit, indent=2, sort_keys=True) + "\n"
    if arguments.check is not None:
        if arguments.check.read_text(encoding="utf-8") != rendered:
            raise SystemExit("retained WP-57 through WP-61 design audit is stale")
    elif arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    print(json.dumps(audit["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
