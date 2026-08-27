#!/usr/bin/env python3
"""Freeze and audit the corrected WP-89 avoidance design before implementation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "docs/work-packages/ACTIVE.md"
START = "<!-- WP89-R1-DESIGN-PAYLOAD-START -->"
END = "<!-- WP89-R1-DESIGN-PAYLOAD-END -->"

EXPECTED_CLAIMS = {
    "WP89-C1-TOGGLE_TRANSIT",
    "WP89-C2-DYNAMIC_POLICY",
    "WP89-C3-PHYSICAL_COMMAND_GUARD",
    "WP89-C4-RETAINED_TRUTH",
}
INTENDED_NEW = {
    "src/crazyswarm_app/safety/avoidance.py",
    "tests/safety/test_avoidance.py",
}
GENERATED = {"ui/openapi.json", "ui/app/lib/api.generated.ts"}
DISCOVERY_SYMBOLS = (
    "PhysicalBasicFlightRunRequest",
    "startPhysicalFlight",
    "start_physical_flight",
    "CrazyflieRawSample",
    "CflibCrazyflieLink",
    "TwinBasicFlightLab",
    "physical-flight/start",
)
DISCOVERY_ROOTS = (
    "src/crazyswarm_app",
    "ui/app",
    "ui/tests",
    "tests/hardware",
    "tests/api",
)

CONSTANTS = {
    "vehicle_radius_m": 0.055,
    "sensor_origin_offset_m": 0.012,
    "minimum_position_uncertainty_m": 0.05,
    "estimator_sigma_multiplier": 2.0,
    "range_uncertainty_m": 0.02,
    "policy_margin_m": 0.05,
    "maximum_state_age_s": 0.4,
    "maximum_acceleration_m_s2": 1.0,
    "maximum_jerk_m_s3": 8.0,
    "minimum_controllable_speed_m_s": 0.02,
    "maximum_command_speed_m_s": 0.10,
}
LATENCY_BUDGET_S = {
    "accepted_sample_age": 0.40,
    "host_evaluation_and_poll": 0.02,
    "command_transport_and_acknowledgement": 0.08,
    "onboard_commit_and_braking_onset": 0.30,
}
GUARD_CATEGORIES = {
    "mode_authority": "typed mode and monitor-only command identity",
    "range_validity": "finite VALID in-range closing-direction measurement",
    "range_freshness": "per-variable host receive age",
    "kinematic_freshness": "yaw, vx, and vy per-variable host receive age",
    "estimator_uncertainty": "fresh 2-sigma estimator variance with a conservative floor",
    "geometry": "vehicle radius and sensor-origin offset",
    "reaction_latency": "complete accepted-age through onboard-commit budget",
    "braking_authority": "jerk-limited stop distance",
    "speed_boundary": "0.10 cap and 0.02 controllable floor",
    "recovery": "post-dispatch adverse sample selects existing abort/land",
    "retained_truth": "mode, decision, counts, margin, and intervention identity",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def payload_bytes() -> bytes:
    text = ACTIVE.read_text(encoding="utf-8")
    _before, found, remainder = text.partition(START)
    if not found:
        raise RuntimeError("WP-89 R1 payload start marker is missing")
    payload, found, _after = remainder.partition(END)
    if not found:
        raise RuntimeError("WP-89 R1 payload end marker is missing")
    return payload.strip().encode("utf-8") + b"\n"


def payload_text() -> str:
    return payload_bytes().decode("utf-8")


def jerk_limited_stop(speed: float, acceleration: float, jerk: float) -> tuple[float, float]:
    if speed <= 0.0:
        return 0.0, 0.0
    ramp = acceleration / jerk
    ramp_delta = 0.5 * acceleration * ramp
    if speed <= 2.0 * ramp_delta:
        triangular = math.sqrt(speed / jerk)
        return 2.0 * triangular, speed * triangular
    hold = (speed - 2.0 * ramp_delta) / acceleration
    first = speed * ramp - jerk * ramp**3 / 6.0
    first_end_speed = speed - ramp_delta
    middle = first_end_speed * hold - 0.5 * acceleration * hold**2
    final = ramp_delta * ramp - 0.5 * acceleration * ramp**2 + jerk * ramp**3 / 6.0
    return 2.0 * ramp + hold, first + middle + final


def position_uncertainty(variance_m2: float) -> float:
    return max(
        CONSTANTS["minimum_position_uncertainty_m"],
        CONSTANTS["estimator_sigma_multiplier"] * math.sqrt(variance_m2),
    )


def required_sensor_range(speed: float, variance_m2: float = 0.0004) -> dict[str, float]:
    stop_time, stop_distance = jerk_limited_stop(
        speed,
        CONSTANTS["maximum_acceleration_m_s2"],
        CONSTANTS["maximum_jerk_m_s3"],
    )
    latency = sum(LATENCY_BUDGET_S.values())
    uncertainty = position_uncertainty(variance_m2)
    center_required = (
        CONSTANTS["vehicle_radius_m"]
        + uncertainty
        + CONSTANTS["range_uncertainty_m"]
        + CONSTANTS["policy_margin_m"]
        + speed * latency
        + stop_distance
    )
    return {
        "speed_m_s": speed,
        "position_uncertainty_m": uncertainty,
        "stop_time_s": stop_time,
        "stop_distance_m": stop_distance,
        "complete_latency_s": latency,
        "required_center_distance_m": center_required,
        "required_sensor_range_m": center_required - CONSTANTS["sensor_origin_offset_m"],
    }


def maximum_safe_speed(clearance_m: float, variance_m2: float = 0.0004) -> float:
    if clearance_m < required_sensor_range(0.0, variance_m2)["required_sensor_range_m"]:
        return 0.0
    cap = CONSTANTS["maximum_command_speed_m_s"]
    if clearance_m >= required_sensor_range(cap, variance_m2)["required_sensor_range_m"]:
        return cap
    low, high = 0.0, cap
    for _ in range(40):
        midpoint = (low + high) / 2.0
        if required_sensor_range(midpoint, variance_m2)["required_sensor_range_m"] <= clearance_m:
            low = midpoint
        else:
            high = midpoint
    return low


def numerical_vectors() -> dict[str, object]:
    maximum = required_sensor_range(0.10)
    half = required_sensor_range(0.05)
    minimum = required_sensor_range(0.02)
    equality = maximum["required_sensor_range_m"]
    high_variance = required_sensor_range(0.10, variance_m2=0.01)
    return {
        "clock_contract": {
            "world_or_firmware_source_time_s": 10.0,
            "host_variable_received_monotonic_s": 100.0,
            "effective_evaluation_monotonic_s": 100.4,
            "accepted_age_s": 0.4,
            "just_stale_effective_time_s": 100.400001,
            "budgets_s": LATENCY_BUDGET_S,
            "complete_latency_s": sum(LATENCY_BUDGET_S.values()),
        },
        "primary_relation": {
            "zero_speed": required_sensor_range(0.0),
            "minimum_speed": minimum,
            "half_speed": half,
            "maximum_speed": maximum,
            "equality_safe_speed_m_s": maximum_safe_speed(equality),
            "just_below_safe_speed_m_s": maximum_safe_speed(equality - 0.000001),
            "just_above_safe_speed_m_s": maximum_safe_speed(equality + 0.000001),
            "high_variance": high_variance,
            "increased_latency_required_sensor_range_m": (
                maximum["required_sensor_range_m"] + 0.1 * 0.20
            ),
        },
        "projection_vectors": [
            {
                "id": "yaw-zero-front-closing",
                "yaw_rad": 0.0,
                "world_velocity_m_s": [0.04, 0.0],
                "body_command_m_s": [0.06, 0.0],
                "expected_front_closing_m_s": 0.06,
            },
            {
                "id": "yaw-90-front-closing",
                "yaw_rad": math.pi / 2.0,
                "world_velocity_m_s": [0.0, 0.04],
                "body_command_m_s": [0.0, 0.0],
                "expected_front_closing_m_s": 0.04,
            },
            {
                "id": "front-moving-away",
                "yaw_rad": 0.0,
                "world_velocity_m_s": [-0.05, 0.0],
                "body_command_m_s": [-0.05, 0.0],
                "expected_front_closing_m_s": 0.0,
            },
        ],
        "command_vectors": [
            {
                "id": "nominal-full-speed",
                "mode": "ENFORCED",
                "front_range_m": 0.30,
                "requested_displacement_m": 0.10,
                "requested_duration_s": 1.0,
                "expected_action": "CLEAR",
                "expected_duration_s": 1.0,
            },
            {
                "id": "progressive-retime",
                "mode": "ENFORCED",
                "front_range_m": half["required_sensor_range_m"],
                "requested_displacement_m": 0.10,
                "requested_duration_s": 1.0,
                "expected_action": "LIMIT",
                "expected_safe_speed_m_s": 0.05,
                "expected_duration_s": 2.0,
            },
            {
                "id": "below-controllable-floor",
                "mode": "ENFORCED",
                "front_range_m": minimum["required_sensor_range_m"] - 0.000001,
                "expected_action": "BLOCK_BEFORE_DISPATCH",
            },
            {
                "id": "monitor-command-identity",
                "mode": "MONITOR_ONLY",
                "front_range_m": 0.05,
                "requested_displacement_m": 0.10,
                "requested_duration_s": 1.0,
                "expected_action": "RECORD_ONLY",
                "expected_duration_s": 1.0,
            },
            {
                "id": "mid-command-clearance-loss",
                "mode": "ENFORCED",
                "initial_front_range_m": 0.30,
                "later_front_range_m": 0.05,
                "expected_action": "RECOVER_ABORT_LAND",
                "dispatched_outcome": "UNKNOWN",
            },
        ],
        "invalid_and_isolated_guard_vectors": [
            {"id": "stale-range", "binding": True, "range_age_s": 0.400001, "expected": "REJECT"},
            {"id": "missing-range", "binding": True, "distance": None, "expected": "REJECT"},
            {"id": "no-hit", "binding": True, "status": "NO_HIT", "expected": "REJECT"},
            {"id": "clipped", "binding": True, "status": "CLIPPED", "expected": "REJECT"},
            {"id": "out-of-range", "binding": True, "distance": 4.0, "expected": "REJECT"},
            {"id": "stale-yaw", "yaw_age_s": 0.400001, "expected": "REJECT"},
            {"id": "stale-vx", "vx_age_s": 0.400001, "expected": "REJECT"},
            {"id": "stale-vy", "vy_age_s": 0.400001, "expected": "REJECT"},
            {"id": "stale-variance", "variance_age_s": 0.400001, "expected": "REJECT"},
            {"id": "missing-variance", "variance": None, "expected": "REJECT"},
            {
                "id": "invalid-nonclosing-front",
                "binding": False,
                "status": "UNAVAILABLE",
                "body_velocity_m_s": [-0.05, 0.0],
                "body_command_m_s": [-0.05, 0.0],
                "expected": "IGNORE_DIRECTION",
            },
            {
                "id": "hover-stale-kinematics",
                "command_speed_m_s": 0.0,
                "yaw_age_s": 0.400001,
                "expected": "RECOVER_ABORT_LAND",
            },
        ],
    }


def extract_payload_paths(text: str) -> set[str]:
    candidates = set(re.findall(r"`((?:src|ui|tests|docs|scripts|missions)/[^`\n]+|design\.md)`", text))
    return {candidate.rstrip(".,") for candidate in candidates if " " not in candidate}


def discover_transit_paths() -> set[str]:
    found: set[str] = set()
    for root_name in DISCOVERY_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(symbol in text for symbol in DISCOVERY_SYMBOLS):
                found.add(path.relative_to(ROOT).as_posix())
    return found


def boundary_manifest(paths: set[str]) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    for relative in sorted(paths):
        if relative == "missions/campaigns/real/qualification/wp89-design-audit-r1.json":
            manifest.append(
                {"path": relative, "classification": "DESIGN_ARTIFACT", "preimage": "SELF"}
            )
            continue
        path = ROOT / relative
        if relative in INTENDED_NEW:
            if path.exists():
                raise RuntimeError(f"intended-new path already exists: {relative}")
            manifest.append({"path": relative, "classification": "NEW", "preimage": "ABSENT"})
            continue
        if not path.exists():
            raise RuntimeError(f"existing boundary is absent: {relative}")
        classification = "GENERATED" if relative in GENERATED else "SCOPED_EXISTING"
        manifest.append(
            {"path": relative, "classification": classification, "preimage": sha256_path(path)}
        )
    return manifest


def audit() -> dict[str, object]:
    text = payload_text()
    payload_paths = extract_payload_paths(text)
    discovered_transit = discover_transit_paths()
    package_script = json.loads((ROOT / "ui/package.json").read_text(encoding="utf-8"))["scripts"]
    generate_command = package_script["generate:api"]
    generated = {
        path for path in GENERATED if path in generate_command or Path(path).name in generate_command
    }
    manifest_paths = payload_paths | generated
    claims = set(re.findall(r"\| `(WP89-C[1-4]-[A-Z_]+)` \|", text))
    vectors = numerical_vectors()
    errors: list[str] = []
    if claims != EXPECTED_CLAIMS:
        errors.append(f"claim universe mismatch: {sorted(claims)}")
    if generated != GENERATED:
        errors.append("generated API boundary pair was not derived exactly")
    if not discovered_transit <= manifest_paths:
        errors.append("a discovered production/test transit is absent from the manifest")
    if not INTENDED_NEW <= manifest_paths:
        errors.append("an intended-new implementation boundary is absent")
    primary = vectors["primary_relation"]
    assert isinstance(primary, dict)
    maximum = primary["maximum_speed"]
    half = primary["half_speed"]
    high_variance = primary["high_variance"]
    assert isinstance(maximum, dict) and isinstance(half, dict) and isinstance(high_variance, dict)
    if abs(sum(LATENCY_BUDGET_S.values()) - 0.8) > 1e-12:
        errors.append("latency budget does not sum to 0.8 seconds")
    if not (
        half["required_sensor_range_m"] < maximum["required_sensor_range_m"]
        < primary["increased_latency_required_sensor_range_m"]
    ):
        errors.append("speed/latency monotonic witness failed")
    if not maximum["required_sensor_range_m"] < high_variance["required_sensor_range_m"]:
        errors.append("measured-uncertainty monotonic witness failed")
    if abs(primary["equality_safe_speed_m_s"] - 0.10) > 1e-9:
        errors.append("safe-speed equality witness failed")
    if not (
        primary["just_below_safe_speed_m_s"] < 0.10
        and primary["just_above_safe_speed_m_s"] == 0.10
    ):
        errors.append("safe-speed boundary perturbation failed")
    isolated_ids = {
        item["id"] for item in vectors["invalid_and_isolated_guard_vectors"]
    }
    required_isolated = {
        "stale-range",
        "missing-range",
        "no-hit",
        "clipped",
        "out-of-range",
        "stale-yaw",
        "stale-vx",
        "stale-vy",
        "stale-variance",
        "missing-variance",
        "invalid-nonclosing-front",
        "hover-stale-kinematics",
    }
    if isolated_ids != required_isolated:
        errors.append("isolated guard vector universe mismatch")
    return {
        "schema_version": 2,
        "packet_id": "WP-89-R1",
        "base_commit": "40cd9947f87eb9bf2719d72e7c72ea867eab9977",
        "design_payload_sha256": sha256_bytes(payload_bytes()),
        "claims_derived_from_payload": sorted(claims),
        "guard_categories_derived_from_request_and_contract": GUARD_CATEGORIES,
        "constants": CONSTANTS,
        "latency_budget_s": LATENCY_BUDGET_S,
        "numerical_vectors": vectors,
        "typed_modes": {
            "accepted": ["MONITOR_ONLY", "ENFORCED"],
            "rejected": [True, False, 0, 1, 1.0, "ON", "OFF", None],
        },
        "generated_outputs_derived_from_ui_command": sorted(generated),
        "transit_paths_derived_from_production_symbols": sorted(discovered_transit),
        "payload_paths": sorted(payload_paths),
        "boundary_manifest": boundary_manifest(manifest_paths),
        "errors": errors,
        "result": "PASS" if not errors else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = audit()
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.check:
            if not output.exists() or output.read_text(encoding="utf-8") != rendered:
                raise SystemExit("retained WP-89 R1 audit is stale")
        else:
            output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if result["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
