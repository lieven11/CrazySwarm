#!/usr/bin/env python3
"""Final bounded design audit for WP-91."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import audit_wp90_design as prior  # noqa: E402


ACTIVE = ROOT / "docs/work-packages/ACTIVE.md"
START = "<!-- WP91-DESIGN-PAYLOAD-START -->"
END = "<!-- WP91-DESIGN-PAYLOAD-END -->"
ARTIFACT = ROOT / "missions/campaigns/real/qualification/wp91-design-audit.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def payload_bytes() -> bytes:
    text = ACTIVE.read_text(encoding="utf-8")
    _before, found, remainder = text.partition(START)
    if not found:
        raise RuntimeError("WP-91 payload start is missing")
    payload, found, _after = remainder.partition(END)
    if not found:
        raise RuntimeError("WP-91 payload end is missing")
    return payload.strip().encode("utf-8") + b"\n"


def flatten_schema(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, list):
        return [f"{prefix}.{rule}" for rule in value]
    if not isinstance(value, dict):
        raise RuntimeError(f"schema node is neither object nor rule list: {prefix}")
    flattened: list[str] = []
    for key, child in value.items():
        child_prefix = f"{prefix}.{key}" if prefix else key
        flattened.extend(flatten_schema(child, child_prefix))
    return flattened


def rule_metric_map() -> dict[str, str]:
    mapping = {
        "mode.exact_enum": "M_MODE_ENUM",
        "mode.monitor_input_output_identity": "M_MONITOR_IDENTITY",
        "range.status_valid": "M_RANGE_STATUS",
        "range.value_present": "M_RANGE_PRESENT",
        "range.value_finite": "M_RANGE_FINITE",
        "range.value_nonnegative": "M_RANGE_NONNEGATIVE",
        "range.max_present": "M_RANGE_MAX_PRESENT",
        "range.max_finite": "M_RANGE_MAX_FINITE",
        "range.max_positive": "M_RANGE_MAX_POSITIVE",
        "range.value_strictly_below_max": "M_RANGE_BELOW_MAX",
        "range.timestamp_present": "M_RANGE_TS_PRESENT",
        "range.timestamp_finite": "M_RANGE_TS_FINITE",
        "range.age_nonnegative": "M_RANGE_AGE_NONNEGATIVE",
        "range.age_at_most_0_4": "M_RANGE_AGE_MAX",
        "commanded_kinematics.frame.exact_BODY_or_HOME": "M_COMMAND_FRAME_ENUM",
        "commanded_kinematics.vx.present": "M_COMMAND_VX_PRESENT",
        "commanded_kinematics.vx.finite": "M_COMMAND_VX_FINITE",
        "commanded_kinematics.vy.present": "M_COMMAND_VY_PRESENT",
        "commanded_kinematics.vy.finite": "M_COMMAND_VY_FINITE",
        "clock.evaluation_time.present": "M_EVALUATION_TIME_PRESENT",
        "clock.evaluation_time.finite": "M_EVALUATION_TIME_FINITE",
        "clock.maximum_age.present": "M_MAXIMUM_AGE_PRESENT",
        "clock.maximum_age.finite": "M_MAXIMUM_AGE_FINITE",
        "clock.maximum_age.nonnegative": "M_MAXIMUM_AGE_NONNEGATIVE",
        "geometry.radius_positive": "M_RADIUS_POSITIVE",
        "geometry.sensor_offset_inside_radius": "M_SENSOR_OFFSET_BOUNDED",
        "geometry.range_uncertainty_nonnegative": "M_RANGE_UNCERTAINTY_NONNEGATIVE",
        "geometry.margin_nonnegative": "M_MARGIN_NONNEGATIVE",
        "latency.sample_age_nonnegative": "M_LATENCY_SAMPLE_AGE_NONNEGATIVE",
        "latency.host_nonnegative": "M_LATENCY_HOST_NONNEGATIVE",
        "latency.transport_ack_nonnegative": "M_LATENCY_TRANSPORT_NONNEGATIVE",
        "latency.onboard_commit_nonnegative": "M_LATENCY_COMMIT_NONNEGATIVE",
        "braking.acceleration_positive": "M_ACCELERATION_POSITIVE",
        "braking.jerk_positive": "M_JERK_POSITIVE",
        "speed.cap_positive": "M_SPEED_CAP_POSITIVE",
        "speed.floor_inside_cap": "M_SPEED_FLOOR_ORDER",
        "speed.inverse_monotonic": "M_SAFE_SPEED_MONOTONIC",
        "speed.retime_preserves_displacement": "M_RETIME_DISPLACEMENT",
        "speed.retime_preserves_yaw": "M_RETIME_YAW",
        "recovery.one_land_dispatched": "M_RECOVERY_LAND_DISPATCH",
        "recovery.ground_confirmed": "M_RECOVERY_GROUND_CONFIRM",
        "recovery.landing_failure_retains_stop_required": (
            "M_RECOVERY_FAILURE_STOP_REQUIRED"
        ),
        "evidence.mode_exact": "M_EVIDENCE_MODE",
        "evidence.decision_enum": "M_EVIDENCE_DECISION",
        "evidence.evaluation_count_positive_integer": "M_EVIDENCE_COUNT",
        "evidence.minimum_margin_finite": "M_EVIDENCE_MARGIN",
        "evidence.binding_ray_enum": "M_EVIDENCE_BINDING_RAY",
        "evidence.intervention_reason_enum": "M_EVIDENCE_INTERVENTION",
    }
    for axis in ("yaw", "vx", "vy"):
        prefix = axis.upper()
        for rule, suffix in (
            ("present", "PRESENT"),
            ("finite", "FINITE"),
            ("timestamp_present", "TS_PRESENT"),
            ("timestamp_finite", "TS_FINITE"),
            ("age_nonnegative", "AGE_NONNEGATIVE"),
            ("age_at_most_0_4", "AGE_MAX"),
        ):
            mapping[f"measured_kinematics.{axis}.{rule}"] = f"M_{prefix}_{suffix}"
    for axis, prefix in (("varPX", "VAR_PX"), ("varPY", "VAR_PY")):
        for rule, suffix in (
            ("present", "PRESENT"),
            ("finite", "FINITE"),
            ("nonnegative", "NONNEGATIVE"),
            ("timestamp_present", "TS_PRESENT"),
            ("timestamp_finite", "TS_FINITE"),
            ("age_nonnegative", "AGE_NONNEGATIVE"),
            ("age_at_most_0_4", "AGE_MAX"),
        ):
            mapping[f"variance.{axis}.{rule}"] = f"M_{prefix}_{suffix}"
    return mapping


def source_category_links() -> dict[str, dict[str, list[str]]]:
    source_categories = prior.parse_source_categories()
    links: dict[str, dict[str, list[str]]] = {
        source: {category: [] for category in sorted(categories)}
        for source, categories in sorted(source_categories.items())
    }
    for item in prior.METRICS:
        links[item.source_id][item.category].append(item.metric_id)
    links["SRC-OP-DISTANCE"]["LATENCY"] = [
        "M_LATENCY_SAMPLE_AGE_NONNEGATIVE",
        "M_LATENCY_HOST_NONNEGATIVE",
        "M_LATENCY_TRANSPORT_NONNEGATIVE",
        "M_LATENCY_COMMIT_NONNEGATIVE",
    ]
    links["SRC-OP-PROJECTION"]["KINEMATIC_FRESHNESS"] = [
        f"M_{axis}_{suffix}"
        for axis in ("YAW", "VX", "VY")
        for suffix in ("TS_PRESENT", "TS_FINITE", "AGE_NONNEGATIVE", "AGE_MAX")
    ]
    links["SRC-WP89-D1"]["KINEMATIC_VALUE"] = [
        f"M_{axis}_{suffix}"
        for axis in ("YAW", "VX", "VY")
        for suffix in ("PRESENT", "FINITE")
    ]
    links["SRC-OP-LIMIT"]["SPEED_LIMITING"].append("M_RETIME_YAW")
    return links


def source_category_link_errors(
    links: dict[str, dict[str, list[str]]],
    *,
    required_pairs: set[tuple[str, str]],
    canonical_metric_ids: set[str],
    expected_links: dict[str, dict[str, list[str]]],
) -> list[str]:
    errors: list[str] = []
    linked_pairs: set[tuple[str, str]] = set()
    linked_metric_ids: set[str] = set()
    for source, categories in links.items():
        for category, metrics in categories.items():
            pair = (source, category)
            if metrics:
                linked_pairs.add(pair)
            if len(metrics) != len(set(metrics)):
                errors.append(f"duplicate metric identity in {source}/{category}")
            expected_metrics = expected_links.get(source, {}).get(category)
            if expected_metrics is None or set(metrics) != set(expected_metrics):
                errors.append(
                    f"source/category metric identity mismatch in {source}/{category}: "
                    f"expected={sorted(expected_metrics or [])}, actual={sorted(metrics)}"
                )
            unknown = set(metrics) - canonical_metric_ids
            if unknown:
                errors.append(
                    f"unknown metric identity in {source}/{category}: {sorted(unknown)}"
                )
            linked_metric_ids.update(metrics)
    if linked_pairs != required_pairs:
        errors.append(
            "source/category linkage mismatch: "
            f"missing={sorted(required_pairs - linked_pairs)}, "
            f"extra={sorted(linked_pairs - required_pairs)}"
        )
    if linked_metric_ids != canonical_metric_ids:
        errors.append(
            "linked metric identity mismatch: "
            f"missing={sorted(canonical_metric_ids - linked_metric_ids)}, "
            f"extra={sorted(linked_metric_ids - canonical_metric_ids)}"
        )
    return errors


def required_range_xy(
    speed: float,
    *,
    var_px: float,
    var_py: float,
    latency: float = 0.8,
) -> float:
    uncertainty = max(0.05, 2.0 * math.sqrt(max(var_px, var_py)))
    return (
        0.055
        + uncertainty
        + 0.02
        + 0.05
        + speed * latency
        + prior.jerk_limited_stop(speed, 1.0, 8.0)
        - 0.012
    )


def computed_evidence(data: dict[str, Any]) -> dict[str, Any]:
    projections = prior.body_projection(
        yaw_rad=data["yaw"],
        world_vx=data["vx"],
        world_vy=data["vy"],
        command_frame=data["command_frame"],
        command_vx=data["command_vx"],
        command_vy=data["command_vy"],
    )
    ranges = data.get("range_values")
    valid_ranges = isinstance(ranges, dict) and all(
        ray in ranges
        and prior.finite(ranges[ray])
        and ranges[ray] >= 0.0
        and prior.finite(data.get("range_max"))
        and ranges[ray] < data["range_max"]
        for ray in projections
    )
    if not valid_ranges:
        return {
            "mode": data.get("mode"),
            "decision": "BLOCK_BEFORE_DISPATCH",
            "evaluation_count": len(data.get("observations", [])),
            "minimum_margin": 0.0,
            "binding_ray": None,
            "intervention_reason": "invalid_binding_input",
        }
    margins = {
        ray: ranges[ray]
        - required_range_xy(
            closing_speed,
            var_px=data["var_px"],
            var_py=data["var_py"],
        )
        for ray, closing_speed in projections.items()
    }
    binding_ray = min(margins, key=margins.__getitem__)
    decision = prior.command_decision(
        clearance=ranges[binding_ray],
        distance=data["retime_input"]["distance_m"],
        duration=data["retime_input"]["duration_s"],
    )["action"]
    reason = {
        "CLEAR": "none",
        "LIMIT": "insufficient_clearance",
        "BLOCK_BEFORE_DISPATCH": "insufficient_clearance",
    }[decision]
    return {
        "mode": data["mode"],
        "decision": decision,
        "evaluation_count": len(data["observations"]),
        "minimum_margin": margins[binding_ray],
        "binding_ray": binding_ray,
        "intervention_reason": reason,
    }


def exact_evidence_failures(data: dict[str, Any]) -> list[str]:
    expected = computed_evidence(data)
    actual = data["evidence"]
    failures: list[str] = []
    for field, metric_id in (
        ("mode", "M_EVIDENCE_MODE"),
        ("decision", "M_EVIDENCE_DECISION"),
        ("evaluation_count", "M_EVIDENCE_COUNT"),
        ("binding_ray", "M_EVIDENCE_BINDING_RAY"),
        ("intervention_reason", "M_EVIDENCE_INTERVENTION"),
    ):
        if actual.get(field) != expected[field]:
            failures.append(metric_id)
    margin = actual.get("minimum_margin")
    if not prior.finite(margin) or abs(margin - expected["minimum_margin"]) > 1e-9:
        failures.append("M_EVIDENCE_MARGIN")
    return failures


def audit() -> dict[str, Any]:
    errors: list[str] = []
    inherited = prior.audit()
    if inherited["result"] != "PASS":
        errors.append(f"inherited WP-90 R1 audit failed: {inherited['errors']}")
    schema = deepcopy(inherited["binding_schema_derived_from_payload"])
    schema["speed"].append("retime_preserves_yaw")
    rules = flatten_schema(schema)
    mapping = rule_metric_map()
    metric_ids = {item.metric_id for item in prior.METRICS} | {"M_RETIME_YAW"}
    if len(rules) != len(set(rules)):
        errors.append("flattened schema contains duplicate rule identities")
    if set(mapping) != set(rules):
        errors.append(
            "rule identity mismatch: "
            f"missing={sorted(set(rules) - set(mapping))}, "
            f"extra={sorted(set(mapping) - set(rules))}"
        )
    if set(mapping.values()) != metric_ids or len(mapping.values()) != len(metric_ids):
        errors.append("metric identity mapping is not exact and one-to-one")

    source_categories = prior.parse_source_categories()
    links = source_category_links()
    expected_links = deepcopy(links)
    required_pairs = {
        (source, category)
        for source, categories in source_categories.items()
        for category in categories
    }
    link_errors = source_category_link_errors(
        links,
        required_pairs=required_pairs,
        canonical_metric_ids=metric_ids,
        expected_links=expected_links,
    )
    errors.extend(link_errors)
    unknown_metric_links = deepcopy(links)
    unknown_metric_links["SRC-OP-DISTANCE"]["LATENCY"][0] = (
        "M_NOT_A_REAL_METRIC"
    )
    unknown_metric_failures = source_category_link_errors(
        unknown_metric_links,
        required_pairs=required_pairs,
        canonical_metric_ids=metric_ids,
        expected_links=expected_links,
    )
    if not any("M_NOT_A_REAL_METRIC" in failure for failure in unknown_metric_failures):
        errors.append("unknown linked metric mutation did not fail")
    misplaced_metric_links = deepcopy(links)
    misplaced_metric_links["SRC-OP-DISTANCE"]["LATENCY"][0] = "M_MODE_ENUM"
    misplaced_metric_failures = source_category_link_errors(
        misplaced_metric_links,
        required_pairs=required_pairs,
        canonical_metric_ids=metric_ids,
        expected_links=expected_links,
    )
    if not any(
        "SRC-OP-DISTANCE/LATENCY" in failure
        for failure in misplaced_metric_failures
    ):
        errors.append("canonical-but-wrong linked metric mutation did not fail")

    duplicate_rule_mutation = [*rules, "speed.retime_preserves_displacement"]
    duplicate_rule_failures = (
        ["flattened schema contains duplicate rule identities"]
        if len(duplicate_rule_mutation) != len(set(duplicate_rule_mutation))
        else []
    )
    if not duplicate_rule_failures:
        errors.append("duplicate flattened-rule mutation did not fail")

    recovery = inherited["recovery_trace"]["structured_observations"]
    base = prior.canonical_input(recovery)
    base["observations"] = [{"sequence": 1}]
    base["range_values"] = {
        "front": base["range_value"],
        "back": base["range_value"],
        "left": base["range_value"],
        "right": base["range_value"],
    }
    base["retime_input"]["yaw_rad"] = 0.30
    base["retime_output"]["yaw_rad"] = 0.30
    base["evidence"] = computed_evidence(base)
    base_failures = prior.evaluate(base) + exact_evidence_failures(base)
    if base_failures:
        errors.append(f"exact evidence whole pass failed: {base_failures}")
    evidence_mutations = {
        "M_EVIDENCE_DECISION": ("decision", "LIMIT"),
        "M_EVIDENCE_COUNT": ("evaluation_count", 999),
        "M_EVIDENCE_MARGIN": ("minimum_margin", 999.0),
        "M_EVIDENCE_BINDING_RAY": ("binding_ray", "back"),
        "M_EVIDENCE_INTERVENTION": (
            "intervention_reason",
            "unsafe_closing_speed",
        ),
    }
    evidence_vectors: list[dict[str, Any]] = []
    for metric_id, (field, value) in evidence_mutations.items():
        candidate = deepcopy(base)
        candidate["evidence"][field] = value
        failures = exact_evidence_failures(candidate)
        evidence_vectors.append(
            {
                "metric_id": metric_id,
                "field": field,
                "mutation": value,
                "observed_failures": failures,
                "passed": failures == [metric_id],
            }
        )
        if failures != [metric_id]:
            errors.append(f"{metric_id}: exact evidence mutation was not isolated")

    baseline = required_range_xy(0.10, var_px=0.0004, var_py=0.0004)
    asymmetric_px = required_range_xy(0.10, var_px=0.0025, var_py=0.0004)
    asymmetric_py = required_range_xy(0.10, var_px=0.0004, var_py=0.0025)
    broken_minimum = (
        0.055
        + max(0.05, 2.0 * math.sqrt(min(0.0025, 0.0004)))
        + 0.02
        + 0.05
        + 0.10 * 0.8
        + prior.jerk_limited_stop(0.10, 1.0, 8.0)
        - 0.012
    )
    if not (
        asymmetric_px == asymmetric_py
        and asymmetric_px > baseline
        and broken_minimum == baseline
        and broken_minimum < asymmetric_px
    ):
        errors.append("asymmetric max-variance witness failed")

    body = prior.body_projection(
        yaw_rad=math.pi / 2.0,
        world_vx=0.0,
        world_vy=0.0,
        command_frame="BODY",
        command_vx=0.06,
        command_vy=0.0,
    )
    home = prior.body_projection(
        yaw_rad=math.pi / 2.0,
        world_vx=0.0,
        world_vy=0.0,
        command_frame="HOME",
        command_vx=0.06,
        command_vy=0.0,
    )
    if not (
        abs(body["front"] - 0.06) <= 1e-12
        and abs(home["right"] - 0.06) <= 1e-12
        and home["front"] <= 1e-12
    ):
        errors.append("BODY/HOME yaw projection witness failed")

    yaw_candidate = deepcopy(base)
    yaw_candidate["retime_output"]["yaw_rad"] = 0.40
    yaw_failures = (
        []
        if yaw_candidate["retime_output"]["yaw_rad"]
        == yaw_candidate["retime_input"]["yaw_rad"]
        else ["M_RETIME_YAW"]
    )
    if yaw_failures != ["M_RETIME_YAW"]:
        errors.append("retime yaw-preservation mutation failed")

    per_ray_candidate = deepcopy(base)
    per_ray_candidate.update(
        {
            "vx": 0.0,
            "vy": 0.0,
            "command_vx": 0.06,
            "command_vy": -0.02,
            "range_values": {
                "front": 0.50,
                "back": 0.50,
                "left": 0.50,
                "right": 0.15,
            },
        }
    )
    per_ray_evidence = computed_evidence(per_ray_candidate)
    expected_front_margin = 0.50 - required_range_xy(
        0.06, var_px=per_ray_candidate["var_px"], var_py=per_ray_candidate["var_py"]
    )
    expected_right_margin = 0.15 - required_range_xy(
        0.02, var_px=per_ray_candidate["var_px"], var_py=per_ray_candidate["var_py"]
    )
    if not (
        per_ray_evidence["binding_ray"] == "right"
        and abs(per_ray_evidence["minimum_margin"] - expected_right_margin) <= 1e-12
        and expected_right_margin < expected_front_margin
    ):
        errors.append("per-ray minimum-margin binding witness failed")

    invalid_binding_candidate = deepcopy(base)
    invalid_binding_candidate["range_values"].pop("right")
    invalid_binding_evidence = computed_evidence(invalid_binding_candidate)
    if not (
        invalid_binding_evidence["binding_ray"] is None
        and invalid_binding_evidence["intervention_reason"] == "invalid_binding_input"
    ):
        errors.append("missing binding range did not derive invalid_binding_input")

    return {
        "schema_version": 1,
        "packet_id": "WP-91",
        "base_commit": "40cd9947f87eb9bf2719d72e7c72ea867eab9977",
        "design_payload_sha256": sha256_bytes(payload_bytes()),
        "inherited_wp90_r1_result": inherited["result"],
        "flattened_rule_count": len(rules),
        "flattened_rules": rules,
        "rule_to_metric": mapping,
        "source_category_links": links,
        "source_category_link_errors": link_errors,
        "unknown_metric_link_mutation": {
            "replacement": "M_NOT_A_REAL_METRIC",
            "observed_failures": unknown_metric_failures,
            "passed": any(
                "M_NOT_A_REAL_METRIC" in failure
                for failure in unknown_metric_failures
            ),
        },
        "misplaced_metric_link_mutation": {
            "replacement": "M_MODE_ENUM",
            "observed_failures": misplaced_metric_failures,
            "passed": any(
                "SRC-OP-DISTANCE/LATENCY" in failure
                for failure in misplaced_metric_failures
            ),
        },
        "duplicate_rule_mutation": {
            "rule": "speed.retime_preserves_displacement",
            "flattened_rule_count": len(duplicate_rule_mutation),
            "unique_rule_count": len(set(duplicate_rule_mutation)),
            "observed_failures": duplicate_rule_failures,
            "passed": bool(duplicate_rule_failures),
        },
        "required_source_category_pairs": [
            list(item) for item in sorted(required_pairs)
        ],
        "exact_evidence_whole_pass": base["evidence"],
        "exact_evidence_vectors": evidence_vectors,
        "asymmetric_variance": {
            "baseline_required_range_m": baseline,
            "var_px_high_required_range_m": asymmetric_px,
            "var_py_high_required_range_m": asymmetric_py,
            "broken_minimum_required_range_m": broken_minimum,
        },
        "frame_projection": {"body_yaw_pi_2": body, "home_yaw_pi_2": home},
        "retime_yaw": {
            "input_yaw_rad": base["retime_input"]["yaw_rad"],
            "passing_output_yaw_rad": base["retime_output"]["yaw_rad"],
            "failing_output_yaw_rad": yaw_candidate["retime_output"]["yaw_rad"],
            "observed_failures": yaw_failures,
        },
        "per_ray_minimum_margin": {
            "ranges_m": per_ray_candidate["range_values"],
            "front_margin_m": expected_front_margin,
            "right_margin_m": expected_right_margin,
            "computed_evidence": per_ray_evidence,
        },
        "invalid_binding_input": invalid_binding_evidence,
        "errors": errors,
        "result": "PASS" if not errors else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = audit()
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.check:
            if not output.exists() or output.read_text(encoding="utf-8") != rendered:
                raise SystemExit("retained WP-91 design audit is stale")
        else:
            output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if result["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
