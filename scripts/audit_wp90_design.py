#!/usr/bin/env python3
"""Pre-freeze audit for the WP-90 D2/D3 successor design."""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ACTIVE = ROOT / "docs/work-packages/ACTIVE.md"
R1_ARTIFACT = ROOT / "missions/campaigns/real/qualification/wp89-design-audit-r1.json"
START = "<!-- WP90-R1-DESIGN-PAYLOAD-START -->"
END = "<!-- WP90-R1-DESIGN-PAYLOAD-END -->"
SCHEMA_START = "<!-- WP90-R1-BINDING-SCHEMA-START -->"
SCHEMA_END = "<!-- WP90-R1-BINDING-SCHEMA-END -->"
MISSING = "__MISSING__"
NAN = "__NAN__"


@dataclass(frozen=True)
class Metric:
    metric_id: str
    category: str
    source_id: str
    direction: str
    field: str
    mutation: Any


def metric(
    metric_id: str,
    category: str,
    source_id: str,
    direction: str,
    field: str,
    mutation: Any,
) -> Metric:
    return Metric(metric_id, category, source_id, direction, field, mutation)


def build_metrics() -> tuple[Metric, ...]:
    items = [
        metric("M_MODE_ENUM", "MODE_AUTHORITY", "SRC-OP-TOGGLE", "exact enum", "mode", "ON"),
        metric(
            "M_MONITOR_IDENTITY",
            "MODE_AUTHORITY",
            "SRC-OP-TOGGLE",
            "canonical input/output equality",
            "monitor_output.duration_s",
            2.0,
        ),
        metric(
            "M_RANGE_STATUS",
            "RANGE_VALIDITY",
            "SRC-OP-SENSOR",
            "VALID only",
            "range_status",
            "NO_HIT",
        ),
        metric(
            "M_RANGE_MAX_PRESENT",
            "RANGE_VALIDITY",
            "SRC-OP-SENSOR",
            "present",
            "range_max",
            MISSING,
        ),
        metric(
            "M_RANGE_MAX_FINITE",
            "RANGE_VALIDITY",
            "SRC-OP-SENSOR",
            "finite",
            "range_max",
            NAN,
        ),
        metric(
            "M_RANGE_MAX_POSITIVE",
            "RANGE_VALIDITY",
            "SRC-OP-SENSOR",
            "> 0",
            "range_max",
            0.0,
        ),
        metric(
            "M_RANGE_PRESENT",
            "RANGE_VALIDITY",
            "SRC-OP-SENSOR",
            "present",
            "range_value",
            MISSING,
        ),
        metric(
            "M_RANGE_FINITE",
            "RANGE_VALIDITY",
            "SRC-OP-SENSOR",
            "finite",
            "range_value",
            NAN,
        ),
        metric(
            "M_RANGE_NONNEGATIVE",
            "RANGE_VALIDITY",
            "SRC-OP-SENSOR",
            ">= 0",
            "range_value",
            -0.001,
        ),
        metric(
            "M_RANGE_BELOW_MAX",
            "RANGE_VALIDITY",
            "SRC-OP-SENSOR",
            "< max_range",
            "range_value",
            4.0,
        ),
        metric(
            "M_RANGE_TS_PRESENT",
            "RANGE_FRESHNESS",
            "SRC-OP-SENSOR",
            "present",
            "range_ts",
            MISSING,
        ),
        metric(
            "M_RANGE_TS_FINITE",
            "RANGE_FRESHNESS",
            "SRC-WP89-D1",
            "finite",
            "range_ts",
            NAN,
        ),
        metric(
            "M_RANGE_AGE_NONNEGATIVE",
            "RANGE_FRESHNESS",
            "SRC-OP-SENSOR",
            ">= 0",
            "range_ts",
            100.5,
        ),
        metric(
            "M_RANGE_AGE_MAX",
            "RANGE_FRESHNESS",
            "SRC-OP-SENSOR",
            "<= 0.4 s",
            "range_ts",
            99.9,
        ),
    ]
    for name in ("yaw", "vx", "vy"):
        upper = name.upper()
        items.extend(
            (
                metric(
                    f"M_{upper}_PRESENT",
                    "KINEMATIC_VALUE",
                    "SRC-OP-PROJECTION",
                    "present",
                    name,
                    MISSING,
                ),
                metric(
                    f"M_{upper}_FINITE",
                    "KINEMATIC_VALUE",
                    "SRC-OP-PROJECTION",
                    "finite",
                    name,
                    NAN,
                ),
                metric(
                    f"M_{upper}_TS_PRESENT",
                    "KINEMATIC_FRESHNESS",
                    "SRC-WP89-D1",
                    "present",
                    f"{name}_ts",
                    MISSING,
                ),
                metric(
                    f"M_{upper}_TS_FINITE",
                    "KINEMATIC_FRESHNESS",
                    "SRC-WP89-D1",
                    "finite",
                    f"{name}_ts",
                    NAN,
                ),
                metric(
                    f"M_{upper}_AGE_NONNEGATIVE",
                    "KINEMATIC_FRESHNESS",
                    "SRC-WP89-D1",
                    ">= 0",
                    f"{name}_ts",
                    100.5,
                ),
                metric(
                    f"M_{upper}_AGE_MAX",
                    "KINEMATIC_FRESHNESS",
                    "SRC-WP89-D1",
                    "<= 0.4 s",
                    f"{name}_ts",
                    99.9,
                ),
            )
        )
    items.extend(
        (
            metric(
                "M_COMMAND_FRAME_ENUM",
                "KINEMATIC_VALUE",
                "SRC-OP-PROJECTION",
                "BODY or HOME",
                "command_frame",
                "WORLD",
            ),
            metric(
                "M_COMMAND_VX_PRESENT",
                "KINEMATIC_VALUE",
                "SRC-OP-PROJECTION",
                "present",
                "command_vx",
                MISSING,
            ),
            metric(
                "M_COMMAND_VX_FINITE",
                "KINEMATIC_VALUE",
                "SRC-OP-PROJECTION",
                "finite",
                "command_vx",
                NAN,
            ),
            metric(
                "M_COMMAND_VY_PRESENT",
                "KINEMATIC_VALUE",
                "SRC-OP-PROJECTION",
                "present",
                "command_vy",
                MISSING,
            ),
            metric(
                "M_COMMAND_VY_FINITE",
                "KINEMATIC_VALUE",
                "SRC-OP-PROJECTION",
                "finite",
                "command_vy",
                NAN,
            ),
            metric(
                "M_EVALUATION_TIME_PRESENT",
                "KINEMATIC_FRESHNESS",
                "SRC-WP89-D1",
                "present",
                "evaluation_time",
                MISSING,
            ),
            metric(
                "M_EVALUATION_TIME_FINITE",
                "KINEMATIC_FRESHNESS",
                "SRC-WP89-D1",
                "finite",
                "evaluation_time",
                NAN,
            ),
            metric(
                "M_MAXIMUM_AGE_PRESENT",
                "RANGE_FRESHNESS",
                "SRC-WP89-D1",
                "present",
                "maximum_age",
                MISSING,
            ),
            metric(
                "M_MAXIMUM_AGE_FINITE",
                "RANGE_FRESHNESS",
                "SRC-WP89-D1",
                "finite",
                "maximum_age",
                NAN,
            ),
            metric(
                "M_MAXIMUM_AGE_NONNEGATIVE",
                "RANGE_FRESHNESS",
                "SRC-WP89-D1",
                ">= 0",
                "maximum_age",
                -0.001,
            ),
        )
    )
    for name in ("var_px", "var_py"):
        upper = name.upper()
        items.extend(
            (
                metric(
                    f"M_{upper}_PRESENT",
                    "ESTIMATOR_UNCERTAINTY",
                    "SRC-WP89-D1",
                    "present",
                    name,
                    MISSING,
                ),
                metric(
                    f"M_{upper}_FINITE",
                    "ESTIMATOR_UNCERTAINTY",
                    "SRC-WP89-D1",
                    "finite",
                    name,
                    NAN,
                ),
                metric(
                    f"M_{upper}_NONNEGATIVE",
                    "ESTIMATOR_UNCERTAINTY",
                    "SRC-OP-DISTANCE",
                    ">= 0",
                    name,
                    -0.001,
                ),
                metric(
                    f"M_{upper}_TS_PRESENT",
                    "ESTIMATOR_UNCERTAINTY",
                    "SRC-WP89-D1",
                    "present",
                    f"{name}_ts",
                    MISSING,
                ),
                metric(
                    f"M_{upper}_TS_FINITE",
                    "ESTIMATOR_UNCERTAINTY",
                    "SRC-WP89-D1",
                    "finite",
                    f"{name}_ts",
                    NAN,
                ),
                metric(
                    f"M_{upper}_AGE_NONNEGATIVE",
                    "ESTIMATOR_UNCERTAINTY",
                    "SRC-WP89-D1",
                    ">= 0",
                    f"{name}_ts",
                    100.5,
                ),
                metric(
                    f"M_{upper}_AGE_MAX",
                    "ESTIMATOR_UNCERTAINTY",
                    "SRC-WP89-D1",
                    "<= 0.4 s",
                    f"{name}_ts",
                    99.9,
                ),
            )
        )
    items.extend(
        (
            metric(
                "M_RADIUS_POSITIVE",
                "GEOMETRY",
                "SRC-OP-DISTANCE",
                "> 0",
                "vehicle_radius",
                0.0,
            ),
            metric(
                "M_SENSOR_OFFSET_BOUNDED",
                "GEOMETRY",
                "SRC-OP-DISTANCE",
                "0 <= offset < radius",
                "sensor_offset",
                0.055,
            ),
            metric(
                "M_RANGE_UNCERTAINTY_NONNEGATIVE",
                "GEOMETRY",
                "SRC-RPL-012",
                ">= 0",
                "range_uncertainty",
                -0.001,
            ),
            metric(
                "M_MARGIN_NONNEGATIVE",
                "GEOMETRY",
                "SRC-OP-DISTANCE",
                ">= 0",
                "policy_margin",
                -0.001,
            ),
        )
    )
    latency_fields = (
        ("sample_age_budget", "M_LATENCY_SAMPLE_AGE_NONNEGATIVE"),
        ("host_budget", "M_LATENCY_HOST_NONNEGATIVE"),
        ("transport_budget", "M_LATENCY_TRANSPORT_NONNEGATIVE"),
        ("commit_budget", "M_LATENCY_COMMIT_NONNEGATIVE"),
    )
    for field, metric_id in latency_fields:
        items.append(
            metric(metric_id, "LATENCY", "SRC-RPL-012", ">= 0", field, -0.001)
        )
    items.extend(
        (
            metric(
                "M_ACCELERATION_POSITIVE",
                "BRAKING",
                "SRC-OP-DISTANCE",
                "> 0",
                "maximum_acceleration",
                0.0,
            ),
            metric(
                "M_JERK_POSITIVE",
                "BRAKING",
                "SRC-RPL-012",
                "> 0",
                "maximum_jerk",
                0.0,
            ),
            metric(
                "M_SPEED_CAP_POSITIVE",
                "SPEED_LIMITING",
                "SRC-OP-LIMIT",
                "> 0",
                "speed_cap",
                0.0,
            ),
            metric(
                "M_SPEED_FLOOR_ORDER",
                "SPEED_LIMITING",
                "SRC-OP-LIMIT",
                "0 < floor <= cap",
                "speed_floor",
                0.11,
            ),
            metric(
                "M_SAFE_SPEED_MONOTONIC",
                "SPEED_LIMITING",
                "SRC-RPL-012",
                "nondecreasing with clearance",
                "candidate_safe_speeds.2",
                0.099,
            ),
            metric(
                "M_RETIME_DISPLACEMENT",
                "SPEED_LIMITING",
                "SRC-OP-LIMIT",
                "preserved",
                "retime_output.distance_m",
                0.09,
            ),
            metric(
                "M_RECOVERY_LAND_DISPATCH",
                "RECOVERY_TRACE",
                "SRC-WFL-017-024-048",
                "observed",
                "recovery_nominal.land_count",
                0,
            ),
            metric(
                "M_RECOVERY_GROUND_CONFIRM",
                "RECOVERY_TRACE",
                "SRC-WFL-017-024-048",
                "observed",
                "recovery_nominal.flying",
                True,
            ),
            metric(
                "M_RECOVERY_FAILURE_STOP_REQUIRED",
                "RECOVERY_TRACE",
                "SRC-WFL-017-024-048",
                "fail closed",
                "recovery_failure.stop_required",
                False,
            ),
        )
    )
    for field, suffix, mutation in (
        ("mode", "MODE", "ENFORCED"),
        ("decision", "DECISION", "BOGUS"),
        ("evaluation_count", "COUNT", 0),
        ("minimum_margin", "MARGIN", NAN),
        ("binding_ray", "BINDING_RAY", "diagonal"),
        ("intervention_reason", "INTERVENTION", "BOGUS"),
    ):
        items.append(
            metric(
                f"M_EVIDENCE_{suffix}",
                "RETAINED_TRUTH",
                "SRC-WFL-017-024-048",
                "retained",
                f"evidence.{field}",
                mutation,
            )
        )
    return tuple(items)


METRICS = build_metrics()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def delimited_payload() -> bytes:
    text = ACTIVE.read_text(encoding="utf-8")
    _before, found, remainder = text.partition(START)
    if not found:
        raise RuntimeError("WP-90 payload start marker is missing")
    payload, found, _after = remainder.partition(END)
    if not found:
        raise RuntimeError("WP-90 payload end marker is missing")
    return payload.strip().encode("utf-8") + b"\n"


def parse_source_categories() -> dict[str, set[str]]:
    text = delimited_payload().decode("utf-8")
    rows = re.findall(
        r"\| `(SRC-[A-Z0-9-]+)` \|[^\n]+\| ([^\n]+) \|",
        text,
    )
    parsed: dict[str, set[str]] = {}
    for source_id, category_cell in rows:
        parsed[source_id] = set(re.findall(r"`([A-Z_]+)`", category_cell))
    return parsed


def parse_binding_schema() -> dict[str, Any]:
    text = delimited_payload().decode("utf-8")
    _before, found, remainder = text.partition(SCHEMA_START)
    if not found:
        raise RuntimeError("WP-90 R1 binding schema start is missing")
    schema_block, found, _after = remainder.partition(SCHEMA_END)
    if not found:
        raise RuntimeError("WP-90 R1 binding schema end is missing")
    match = re.search(r"```json\s*(\{.*\})\s*```", schema_block, re.DOTALL)
    if match is None:
        raise RuntimeError("WP-90 R1 binding schema JSON is missing")
    parsed = json.loads(match.group(1))
    if not isinstance(parsed, dict):
        raise RuntimeError("WP-90 R1 binding schema is not an object")
    return parsed


def canonical_input(recovery: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "mode": "MONITOR_ONLY",
        "decision": "CLEAR",
        "evaluation_count": 1,
        "minimum_margin": 0.04,
        "binding_ray": "front",
        "intervention_reason": "none",
    }
    return {
        "mode": "MONITOR_ONLY",
        "monitor_input": {"distance_m": 0.10, "duration_s": 1.0, "direction": "front"},
        "monitor_output": {"distance_m": 0.10, "duration_s": 1.0, "direction": "front"},
        "range_status": "VALID",
        "range_value": 0.30,
        "range_max": 4.0,
        "range_ts": 100.1,
        "yaw": 0.0,
        "yaw_ts": 100.1,
        "vx": 0.04,
        "vx_ts": 100.1,
        "vy": 0.0,
        "vy_ts": 100.1,
        "command_frame": "BODY",
        "command_vx": 0.06,
        "command_vy": 0.0,
        "var_px": 0.0004,
        "var_px_ts": 100.1,
        "var_py": 0.0004,
        "var_py_ts": 100.1,
        "evaluation_time": 100.4,
        "maximum_age": 0.4,
        "vehicle_radius": 0.055,
        "sensor_offset": 0.012,
        "range_uncertainty": 0.02,
        "policy_margin": 0.05,
        "sample_age_budget": 0.40,
        "host_budget": 0.02,
        "transport_budget": 0.08,
        "commit_budget": 0.30,
        "maximum_acceleration": 1.0,
        "maximum_jerk": 8.0,
        "speed_cap": 0.10,
        "speed_floor": 0.02,
        "monotonic_clearances": [
            required_range(0.0),
            required_range(0.02),
            required_range(0.05),
            required_range(0.10),
        ],
        "candidate_safe_speeds": [0.0, 0.02, 0.05, 0.10],
        "retime_input": {
            "distance_m": 0.10,
            "duration_s": 1.0,
            "direction": "front",
            "clearance_m": required_range(0.05),
        },
        "retime_output": {"distance_m": 0.10, "duration_s": 2.0, "direction": "front"},
        **recovery,
        "evidence": evidence,
    }


def finite(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def check_timed_value(
    data: dict[str, Any],
    *,
    value_field: str,
    prefix: str,
    clock_valid: bool,
    maximum_age_valid: bool,
    variance: bool = False,
) -> list[str]:
    value = data.get(value_field, MISSING)
    if value == MISSING:
        return [f"M_{prefix}_PRESENT"]
    if not finite(value):
        return [f"M_{prefix}_FINITE"]
    if variance and value < 0.0:
        return [f"M_{prefix}_NONNEGATIVE"]
    timestamp_field = f"{value_field}_ts"
    timestamp = data.get(timestamp_field, MISSING)
    if timestamp == MISSING:
        return [f"M_{prefix}_TS_PRESENT"]
    if not finite(timestamp):
        return [f"M_{prefix}_TS_FINITE"]
    if not clock_valid:
        return []
    age = data["evaluation_time"] - timestamp
    if age < 0.0:
        return [f"M_{prefix}_AGE_NONNEGATIVE"]
    if maximum_age_valid and age > data["maximum_age"]:
        return [f"M_{prefix}_AGE_MAX"]
    return []


def evaluate(data: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    evaluation_time = data.get("evaluation_time", MISSING)
    if evaluation_time == MISSING:
        failures.append("M_EVALUATION_TIME_PRESENT")
        clock_valid = False
    elif not finite(evaluation_time):
        failures.append("M_EVALUATION_TIME_FINITE")
        clock_valid = False
    else:
        clock_valid = True
    maximum_age = data.get("maximum_age", MISSING)
    if maximum_age == MISSING:
        failures.append("M_MAXIMUM_AGE_PRESENT")
        maximum_age_valid = False
    elif not finite(maximum_age):
        failures.append("M_MAXIMUM_AGE_FINITE")
        maximum_age_valid = False
    elif maximum_age < 0.0:
        failures.append("M_MAXIMUM_AGE_NONNEGATIVE")
        maximum_age_valid = False
    else:
        maximum_age_valid = True
    mode_valid = data.get("mode") in {"MONITOR_ONLY", "ENFORCED"}
    if not mode_valid:
        failures.append("M_MODE_ENUM")
    if json.dumps(data.get("monitor_input"), sort_keys=True) != json.dumps(
        data.get("monitor_output"), sort_keys=True
    ):
        failures.append("M_MONITOR_IDENTITY")
    if data.get("range_status") != "VALID":
        failures.append("M_RANGE_STATUS")
    range_max = data.get("range_max", MISSING)
    if range_max == MISSING:
        failures.append("M_RANGE_MAX_PRESENT")
        range_max_valid = False
    elif not finite(range_max):
        failures.append("M_RANGE_MAX_FINITE")
        range_max_valid = False
    elif range_max <= 0.0:
        failures.append("M_RANGE_MAX_POSITIVE")
        range_max_valid = False
    else:
        range_max_valid = True
    range_value = data.get("range_value", MISSING)
    if range_value == MISSING:
        failures.append("M_RANGE_PRESENT")
    elif not finite(range_value):
        failures.append("M_RANGE_FINITE")
    elif range_value < 0.0:
        failures.append("M_RANGE_NONNEGATIVE")
    elif range_max_valid and range_value >= range_max:
        failures.append("M_RANGE_BELOW_MAX")
    range_ts = data.get("range_ts", MISSING)
    if range_ts == MISSING:
        failures.append("M_RANGE_TS_PRESENT")
    elif not finite(range_ts):
        failures.append("M_RANGE_TS_FINITE")
    elif clock_valid:
        range_age = evaluation_time - range_ts
        if range_age < 0.0:
            failures.append("M_RANGE_AGE_NONNEGATIVE")
        elif maximum_age_valid and range_age > maximum_age:
            failures.append("M_RANGE_AGE_MAX")
    for name in ("yaw", "vx", "vy"):
        failures.extend(
            check_timed_value(
                data,
                value_field=name,
                prefix=name.upper(),
                clock_valid=clock_valid,
                maximum_age_valid=maximum_age_valid,
            )
        )
    if data.get("command_frame") not in {"BODY", "HOME"}:
        failures.append("M_COMMAND_FRAME_ENUM")
    for name in ("command_vx", "command_vy"):
        value = data.get(name, MISSING)
        if value == MISSING:
            failures.append(f"M_{name.upper()}_PRESENT")
        elif not finite(value):
            failures.append(f"M_{name.upper()}_FINITE")
    for name in ("var_px", "var_py"):
        failures.extend(
            check_timed_value(
                data,
                value_field=name,
                prefix=name.upper(),
                clock_valid=clock_valid,
                maximum_age_valid=maximum_age_valid,
                variance=True,
            )
        )
    radius = data["vehicle_radius"]
    if not finite(radius) or radius <= 0.0:
        failures.append("M_RADIUS_POSITIVE")
    elif (
        not finite(data["sensor_offset"])
        or data["sensor_offset"] < 0.0
        or data["sensor_offset"] >= radius
    ):
        failures.append("M_SENSOR_OFFSET_BOUNDED")
    if not finite(data["range_uncertainty"]) or data["range_uncertainty"] < 0.0:
        failures.append("M_RANGE_UNCERTAINTY_NONNEGATIVE")
    if not finite(data["policy_margin"]) or data["policy_margin"] < 0.0:
        failures.append("M_MARGIN_NONNEGATIVE")
    for field, metric_id in (
        ("sample_age_budget", "M_LATENCY_SAMPLE_AGE_NONNEGATIVE"),
        ("host_budget", "M_LATENCY_HOST_NONNEGATIVE"),
        ("transport_budget", "M_LATENCY_TRANSPORT_NONNEGATIVE"),
        ("commit_budget", "M_LATENCY_COMMIT_NONNEGATIVE"),
    ):
        if not finite(data[field]) or data[field] < 0.0:
            failures.append(metric_id)
    if not finite(data["maximum_acceleration"]) or data["maximum_acceleration"] <= 0.0:
        failures.append("M_ACCELERATION_POSITIVE")
    if not finite(data["maximum_jerk"]) or data["maximum_jerk"] <= 0.0:
        failures.append("M_JERK_POSITIVE")
    cap = data["speed_cap"]
    if not finite(cap) or cap <= 0.0:
        failures.append("M_SPEED_CAP_POSITIVE")
    elif (
        not finite(data["speed_floor"])
        or data["speed_floor"] <= 0.0
        or data["speed_floor"] > cap
    ):
        failures.append("M_SPEED_FLOOR_ORDER")
    reported_speeds = data.get("candidate_safe_speeds", [])
    expected_speeds = [safe_speed(clearance) for clearance in data["monotonic_clearances"]]
    if not (
        len(reported_speeds) == len(expected_speeds)
        and all(
            finite(reported) and abs(reported - expected) <= 1e-9
            for reported, expected in zip(reported_speeds, expected_speeds, strict=True)
        )
        and all(
            reported_speeds[index] <= reported_speeds[index + 1]
            for index in range(len(reported_speeds) - 1)
        )
    ):
        failures.append("M_SAFE_SPEED_MONOTONIC")
    retime_input = data["retime_input"]
    retime_output = data["retime_output"]
    expected_retime_speed = safe_speed(retime_input["clearance_m"])
    expected_duration = retime_input["distance_m"] / expected_retime_speed
    if not (
        retime_output.get("distance_m") == retime_input["distance_m"]
        and retime_output.get("direction") == retime_input["direction"]
        and abs(retime_output.get("duration_s", math.nan) - expected_duration) <= 1e-9
    ):
        failures.append("M_RETIME_DISPLACEMENT")
    nominal_recovery = data["recovery_nominal"]
    failed_recovery = data["recovery_failure"]
    if nominal_recovery.get("land_count") != 1:
        failures.append("M_RECOVERY_LAND_DISPATCH")
    if not (
        nominal_recovery.get("exception_code") == "PREFLIGHT_FAILED"
        and nominal_recovery.get("trigger") == "near_floor"
        and nominal_recovery.get("flying") is False
    ):
        failures.append("M_RECOVERY_GROUND_CONFIRM")
    if not (
        failed_recovery.get("state") == "FAILED"
        and failed_recovery.get("stop_required") is True
        and failed_recovery.get("command_phase") == "OUTCOME_UNKNOWN"
    ):
        failures.append("M_RECOVERY_FAILURE_STOP_REQUIRED")
    evidence = data["evidence"]
    if mode_valid and evidence.get("mode") != data.get("mode"):
        failures.append("M_EVIDENCE_MODE")
    if evidence.get("decision") not in {
        "CLEAR",
        "LIMIT",
        "BLOCK_BEFORE_DISPATCH",
        "RECOVER_ABORT_LAND",
        "RECORD_ONLY",
    }:
        failures.append("M_EVIDENCE_DECISION")
    count = evidence.get("evaluation_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        failures.append("M_EVIDENCE_COUNT")
    if not finite(evidence.get("minimum_margin")):
        failures.append("M_EVIDENCE_MARGIN")
    if evidence.get("binding_ray") not in {"front", "back", "left", "right", None}:
        failures.append("M_EVIDENCE_BINDING_RAY")
    if evidence.get("intervention_reason") not in {
        "none",
        "insufficient_clearance",
        "invalid_binding_input",
        "unsafe_closing_speed",
    }:
        failures.append("M_EVIDENCE_INTERVENTION")
    return failures


def apply_mutation(base: dict[str, Any], item: Metric) -> dict[str, Any]:
    candidate = deepcopy(base)
    parts = item.field.split(".")
    owner: Any = candidate
    for part in parts[:-1]:
        owner = owner[int(part)] if isinstance(owner, list) else owner[part]
    key: str | int = int(parts[-1]) if isinstance(owner, list) else parts[-1]
    if item.mutation == MISSING:
        if isinstance(owner, list):
            owner.pop(key)
        else:
            owner.pop(key, None)
    elif item.mutation == NAN:
        owner[key] = float("nan")
    else:
        owner[key] = item.mutation
    return candidate


async def structured_recovery_probe() -> dict[str, Any]:
    from crazyswarm_app.api.runtime import create_runtime
    from crazyswarm_app.config import load_config
    from crazyswarm_app.domain.errors import CrazySwarmError
    from crazyswarm_app.hardware.basic_flight_lab import (
        BasicFlightLabService,
        PhysicalBasicFlightRunRequest,
    )
    from crazyswarm_app.hardware.observation_twin import PhysicalCommandTarget
    from crazyswarm_app.simulation.world import load_scenario
    from crazyswarm_app.vehicles.crazyflie import CrazyflieVehicle
    from tests.hardware.test_crazyflie_adapter import URI, FakeCrazyflieLink

    class FloorContactLink(FakeCrazyflieLink):
        def hold_position(self, duration_s: float) -> None:
            super().hold_position(duration_s)
            self.values["stateEstimate.z"] = 0.02
            self.values["range.zrange"] = 20.0

    async def sample_once(
        vehicle: CrazyflieVehicle,
        _duration_s: float,
        *,
        stability_guard: Any | None = None,
    ) -> None:
        sample = await vehicle.snapshot()
        if stability_guard is not None:
            stability_guard.observe(sample)

    target = PhysicalCommandTarget(
        selected_uri=URI,
        vehicle_label="WP-90 injected Crazyflie",
        observed_identity_sha256="a" * 64,
    )
    with tempfile.TemporaryDirectory(prefix="wp90-recovery-") as temporary:
        root = Path(temporary)
        config = load_config(ROOT / "config/app.yaml").model_copy(
            update={"cache_directory": root / "cache"}
        )
        runtime = create_runtime(
            config,
            load_scenario(ROOT / "config/worlds/one_drone.yaml"),
            evidence_path=root / "evidence.sqlite3",
        )
        nominal_link = FloorContactLink(high_level_enabled="0")
        nominal_service = BasicFlightLabService(
            runtime,
            physical_link_factory=lambda: nominal_link,
            physical_hover_duration_s=0.01,
        )
        with (
            patch(
                "crazyswarm_app.vehicles.crazyflie.AIRBORNE_GUARD_FLOOR_PERSISTENCE_S",
                0.0,
            ),
            patch.object(CrazyflieVehicle, "_wait_duration_and_refresh", sample_once),
        ):
            nominal_error: CrazySwarmError | None = None
            try:
                await nominal_service.run_physical(
                    PhysicalBasicFlightRunRequest(motion_id="commissioning-baseline"),
                    target=target,
                    operator_id="wp90-design-probe",
                )
            except CrazySwarmError as error:
                nominal_error = error
        nominal = {
            "exception_code": None if nominal_error is None else nominal_error.code.value,
            "trigger": None if nominal_error is None else nominal_error.details.get("trigger"),
            "command_kinds": [item[0] for item in nominal_link.commands],
            "land_count": [item[0] for item in nominal_link.commands].count("land"),
            "flying": bool(nominal_link.bitfield & (1 << 4)),
        }

        failure_runtime = create_runtime(
            config,
            load_scenario(ROOT / "config/worlds/one_drone.yaml"),
            evidence_path=root / "failure-evidence.sqlite3",
        )
        failure_link = FloorContactLink(high_level_enabled="0")

        def fail_land(_height_m: float, _duration_s: float) -> None:
            raise RuntimeError("injected landing acknowledgement failure")

        failure_link.land = fail_land  # type: ignore[method-assign]
        failure_service = BasicFlightLabService(
            failure_runtime,
            physical_link_factory=lambda: failure_link,
            physical_hover_duration_s=0.01,
        )
        with (
            patch(
                "crazyswarm_app.vehicles.crazyflie.AIRBORNE_GUARD_FLOOR_PERSISTENCE_S",
                0.0,
            ),
            patch.object(CrazyflieVehicle, "_wait_duration_and_refresh", sample_once),
        ):
            await failure_service.start_physical_flight(
                PhysicalBasicFlightRunRequest(motion_id="commissioning-baseline"),
                target=target,
                operator_id="wp90-design-probe",
            )
            for _ in range(200):
                terminal = await failure_service.physical_flight_status()
                if terminal.state == "FAILED":
                    break
                await asyncio.sleep(0.01)
        failure = {
            "state": terminal.state,
            "stop_required": terminal.stop_required,
            "command_phase": (
                terminal.command_evidence[-1]["phase"]
                if terminal.command_evidence
                else None
            ),
        }
    return {"recovery_nominal": nominal, "recovery_failure": failure}


def run_recovery_trace() -> dict[str, Any]:
    structured = asyncio.run(structured_recovery_probe())
    nodes = [
        "tests/hardware/test_basic_flight_lab.py::"
        "test_airborne_stability_guard_uses_existing_failure_abort_and_land_path",
        "tests/hardware/test_basic_flight_lab.py::"
        "test_recovered_observer_ground_state_clears_unconfirmed_abort",
    ]
    command = [str(ROOT / ".venv/bin/pytest"), "-q", *nodes]
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + result.stderr
    return {
        "command": [".venv/bin/pytest", "-q", *nodes],
        "node_ids": nodes,
        "exit_code": result.returncode,
        "normalized_result": (
            "2_PASSED" if result.returncode == 0 and "2 passed" in combined else "FAILED"
        ),
        "structured_observations": structured,
    }


def jerk_limited_stop(speed: float, acceleration: float, jerk: float) -> float:
    if speed <= 0.0:
        return 0.0
    ramp = acceleration / jerk
    ramp_delta = 0.5 * acceleration * ramp
    if speed <= 2.0 * ramp_delta:
        return speed * math.sqrt(speed / jerk)
    hold = (speed - 2.0 * ramp_delta) / acceleration
    first = speed * ramp - jerk * ramp**3 / 6.0
    first_end = speed - ramp_delta
    middle = first_end * hold - 0.5 * acceleration * hold**2
    final = ramp_delta * ramp - 0.5 * acceleration * ramp**2 + jerk * ramp**3 / 6.0
    return first + middle + final


def required_range(
    speed: float,
    variance: float = 0.0004,
    latency: float = 0.8,
    *,
    radius: float = 0.055,
    sensor_offset: float = 0.012,
    acceleration: float = 1.0,
    jerk: float = 8.0,
) -> float:
    uncertainty = max(0.05, 2.0 * math.sqrt(variance))
    return (
        radius
        + uncertainty
        + 0.02
        + 0.05
        + speed * latency
        + jerk_limited_stop(speed, acceleration, jerk)
        - sensor_offset
    )


def safe_speed(
    clearance: float,
    variance: float = 0.0004,
    latency: float = 0.8,
) -> float:
    if clearance < required_range(0.0, variance, latency):
        return 0.0
    if clearance >= required_range(0.1, variance, latency):
        return 0.1
    low, high = 0.0, 0.1
    for _ in range(60):
        midpoint = (low + high) / 2.0
        if required_range(midpoint, variance, latency) <= clearance:
            low = midpoint
        else:
            high = midpoint
    return low


def body_projection(
    *,
    yaw_rad: float,
    world_vx: float,
    world_vy: float,
    command_frame: str,
    command_vx: float,
    command_vy: float,
) -> dict[str, float]:
    cosine, sine = math.cos(yaw_rad), math.sin(yaw_rad)
    measured_x = world_vx * cosine + world_vy * sine
    measured_y = -world_vx * sine + world_vy * cosine
    if command_frame == "HOME":
        commanded_x = command_vx * cosine + command_vy * sine
        commanded_y = -command_vx * sine + command_vy * cosine
    else:
        commanded_x, commanded_y = command_vx, command_vy
    return {
        "front": max(0.0, measured_x, commanded_x),
        "back": max(0.0, -measured_x, -commanded_x),
        "left": max(0.0, measured_y, commanded_y),
        "right": max(0.0, -measured_y, -commanded_y),
    }


def command_decision(*, clearance: float, distance: float, duration: float) -> dict[str, Any]:
    requested_speed = distance / duration
    admitted_speed = safe_speed(clearance)
    if admitted_speed < 0.02:
        return {
            "action": "BLOCK_BEFORE_DISPATCH",
            "safe_speed_m_s": admitted_speed,
            "distance_m": distance,
            "duration_s": None,
        }
    if requested_speed <= admitted_speed + 1e-12:
        return {
            "action": "CLEAR",
            "safe_speed_m_s": admitted_speed,
            "distance_m": distance,
            "duration_s": duration,
        }
    return {
        "action": "LIMIT",
        "safe_speed_m_s": admitted_speed,
        "distance_m": distance,
        "duration_s": distance / admitted_speed,
    }


def numerical_oracle() -> dict[str, Any]:
    r02 = required_range(0.02)
    r05 = required_range(0.05)
    r10 = required_range(0.10)
    ample = command_decision(clearance=0.30, distance=0.10, duration=1.0)
    retimed = command_decision(clearance=r05, distance=0.10, duration=1.0)
    blocked = command_decision(clearance=r02 - 1e-6, distance=0.10, duration=1.0)
    monitor_input = {"distance_m": 0.10, "duration_s": 1.0, "direction": "front"}
    monitor_output = deepcopy(monitor_input)
    return {
        "required_range_m": {
            "speed_0": required_range(0.0),
            "speed_0_02": r02,
            "speed_0_05": r05,
            "speed_0_10": r10,
            "higher_latency": required_range(0.10, latency=1.0),
            "higher_variance": required_range(0.10, variance=0.01),
        },
        "boundary_safe_speed_m_s": {
            "equal": safe_speed(r10),
            "minus_1e_6": safe_speed(r10 - 1e-6),
            "plus_1e_6": safe_speed(r10 + 1e-6),
        },
        "projection": {
            "yaw_0": body_projection(
                yaw_rad=0.0,
                world_vx=0.04,
                world_vy=0.0,
                command_frame="BODY",
                command_vx=0.06,
                command_vy=0.0,
            ),
            "yaw_pi_2": body_projection(
                yaw_rad=math.pi / 2.0,
                world_vx=0.0,
                world_vy=0.04,
                command_frame="BODY",
                command_vx=0.0,
                command_vy=0.0,
            ),
            "moving_away": body_projection(
                yaw_rad=0.0,
                world_vx=-0.05,
                world_vy=0.0,
                command_frame="BODY",
                command_vx=-0.05,
                command_vy=0.0,
            ),
            "commanded_closing_only": body_projection(
                yaw_rad=0.0,
                world_vx=0.0,
                world_vy=0.0,
                command_frame="BODY",
                command_vx=0.06,
                command_vy=0.0,
            ),
        },
        "admissible_sensitivity": {
            "radius_base": required_range(0.10),
            "radius_increased": required_range(0.10, radius=0.065),
            "offset_base": required_range(0.10),
            "offset_reduced": required_range(0.10, sensor_offset=0.010),
            "acceleration_base": required_range(0.10),
            "acceleration_reduced": required_range(0.10, acceleration=0.8),
            "jerk_base": required_range(0.10),
            "jerk_reduced": required_range(0.10, jerk=6.0),
            "variance_base": required_range(0.10, variance=0.0004),
            "variance_asymmetric": required_range(0.10, variance=0.0025),
            "latency_base": required_range(0.10, latency=0.8),
            "latency_increased": required_range(0.10, latency=1.0),
        },
        "commands": {
            "ample_clearance": ample,
            "retimed_at_half_speed": retimed,
            "below_floor": blocked,
            "monitor_only": {
                "input": monitor_input,
                "output": monitor_output,
                "input_payload_sha256": sha256_bytes(
                    json.dumps(monitor_input, sort_keys=True, separators=(",", ":")).encode()
                ),
                "output_payload_sha256": sha256_bytes(
                    json.dumps(monitor_output, sort_keys=True, separators=(",", ":")).encode()
                ),
                "action": "RECORD_ONLY",
            },
            "post_dispatch_loss": {
                "command_outcome": "UNKNOWN",
                "action": "RECOVER_ABORT_LAND",
            },
        },
    }


def ast_section(path: Path, selector: str) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    parts = selector.split(".")
    nodes: list[ast.AST] = list(tree.body)
    selected: ast.AST | None = None
    for part in parts:
        selected = next(
            (
                node
                for node in nodes
                if (
                    isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
                    and node.name == part
                )
                or (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == part
                )
                or (
                    isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == part for target in node.targets)
                )
            ),
            None,
        )
        if selected is None:
            raise RuntimeError(f"AST selector not found: {path}:{selector}")
        nodes = list(getattr(selected, "body", ()))
    source = ast.get_source_segment(text, selected)
    if source is None:
        raise RuntimeError(f"AST source unavailable: {path}:{selector}")
    return {
        "selector": selector,
        "sha256": sha256_bytes((source.rstrip() + "\n").encode("utf-8")),
    }


def inherited_wp89_r1_payload() -> str:
    text = ACTIVE.read_text(encoding="utf-8")
    _before, found, remainder = text.partition("<!-- WP89-R1-DESIGN-PAYLOAD-START -->")
    if not found:
        raise RuntimeError("inherited WP-89 R1 payload start is missing")
    payload, found, _after = remainder.partition("<!-- WP89-R1-DESIGN-PAYLOAD-END -->")
    if not found:
        raise RuntimeError("inherited WP-89 R1 payload end is missing")
    return payload


def derive_boundary_paths() -> dict[str, set[str]]:
    inherited = inherited_wp89_r1_payload()
    claim_owner_paths = {
        item.rstrip(".,")
        for item in re.findall(
            r"`((?:src|ui|tests|docs|scripts)/[^`\n]+|design\.md)`",
            inherited,
        )
        if " " not in item
    }
    symbols = (
        "PhysicalBasicFlightRunRequest",
        "startPhysicalFlight",
        "start_physical_flight",
        "CrazyflieRawSample",
        "CflibCrazyflieLink",
        "TwinBasicFlightLab",
        "physical-flight/start",
    )
    transit_paths: set[str] = set()
    for root_name in (
        "src/crazyswarm_app",
        "ui/app",
        "ui/tests",
        "tests/hardware",
        "tests/api",
    ):
        root = ROOT / root_name
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            if any(symbol in source for symbol in symbols):
                transit_paths.add(path.relative_to(ROOT).as_posix())
    generate_command = json.loads((ROOT / "ui/package.json").read_text(encoding="utf-8"))[
        "scripts"
    ]["generate:api"]
    generated = {
        path
        for path in ("ui/openapi.json", "ui/app/lib/api.generated.ts")
        if path in generate_command or Path(path).name in generate_command
    }
    claims = set(re.findall(r"[|] `(WP89-C[1-4]-[A-Z_]+)` [|]", inherited))
    if claims != {
        "WP89-C1-TOGGLE_TRANSIT",
        "WP89-C2-DYNAMIC_POLICY",
        "WP89-C3-PHYSICAL_COMMAND_GUARD",
        "WP89-C4-RETAINED_TRUTH",
    }:
        raise RuntimeError(f"inherited claim universe changed: {sorted(claims)}")
    return {
        "claim_owner_paths": claim_owner_paths,
        "transit_paths": transit_paths,
        "generated_paths": generated,
    }


def current_manifest(derived: dict[str, set[str]]) -> list[dict[str, Any]]:
    paths = set().union(*derived.values())
    paths = {
        path
        for path in paths
        if not path.startswith("missions/campaigns/real/qualification/wp89-")
    }
    paths |= {
        "scripts/audit_wp90_design.py",
        "missions/campaigns/real/qualification/wp90-design-audit-r1.json",
    }
    sectioned = {
        "src/crazyswarm_app/vehicles/crazyflie_link.py": ("CrazyflieRawSample",),
        "src/crazyswarm_app/vehicles/_cflib_link.py": (
            "LOG_GROUPS",
            "CflibCrazyflieLink.__init__",
            "CflibCrazyflieLink.connect",
            "CflibCrazyflieLink.restart_observation_logs",
            "CflibCrazyflieLink._cached_sample",
            "CflibCrazyflieLink._start_logs",
            "CflibCrazyflieLink._on_log_data",
        ),
    }
    manifest: list[dict[str, Any]] = []
    for relative in sorted(paths):
        path = ROOT / relative
        if relative == "missions/campaigns/real/qualification/wp90-design-audit-r1.json":
            manifest.append(
                {"path": relative, "classification": "DESIGN_ARTIFACT", "preimage": "SELF"}
            )
        elif relative in sectioned:
            manifest.append(
                {
                    "path": relative,
                    "classification": "PRESERVE_SECTIONED",
                    "sections": [
                        ast_section(path, selector) for selector in sectioned[relative]
                    ],
                }
            )
        elif not path.exists():
            manifest.append({"path": relative, "classification": "NEW", "preimage": "ABSENT"})
        else:
            manifest.append(
                {
                    "path": relative,
                    "classification": "SCOPED_EXISTING",
                    "preimage": sha256_path(path),
                }
            )
    return manifest


def audit() -> dict[str, Any]:
    errors: list[str] = []
    parsed_sources = parse_source_categories()
    binding_schema = parse_binding_schema()

    def count_rules(value: Any) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return sum(count_rules(item) for item in value.values())
        raise RuntimeError("binding schema leaves must be rule lists")

    derived_metric_count = count_rules(binding_schema)
    if (
        derived_metric_count != 79
        or len(METRICS) != derived_metric_count
        or len({item.metric_id for item in METRICS}) != derived_metric_count
    ):
        errors.append(
            "schema/metric registry is not exactly 79 unique mechanically derived metrics"
        )
    required_categories = set().union(*parsed_sources.values()) if parsed_sources else set()
    metric_categories = {item.category for item in METRICS}
    if metric_categories != required_categories:
        errors.append("metric categories do not exactly cover independently derived categories")
    for item in METRICS:
        if item.source_id not in parsed_sources:
            errors.append(f"{item.metric_id}: unknown source")
        elif item.category not in parsed_sources[item.source_id]:
            errors.append(f"{item.metric_id}: source does not require category")
    recovery_trace = run_recovery_trace()
    base = canonical_input(recovery_trace["structured_observations"])
    whole_failures = evaluate(base)
    if whole_failures:
        errors.append(f"whole-pass input failed: {whole_failures}")
    isolated: list[dict[str, Any]] = []
    for item in METRICS:
        failures = evaluate(apply_mutation(base, item))
        isolated.append(
            {
                **asdict(item),
                "mutation": item.mutation,
                "observed_failures": failures,
                "passed": failures == [item.metric_id],
            }
        )
        if failures != [item.metric_id]:
            errors.append(f"{item.metric_id}: non-isolated failures {failures}")
    numeric = numerical_oracle()
    ranges = numeric["required_range_m"]
    boundaries = numeric["boundary_safe_speed_m_s"]
    commands = numeric["commands"]
    sensitivity = numeric["admissible_sensitivity"]
    if not (
        ranges["speed_0"] < ranges["speed_0_02"] < ranges["speed_0_05"] < ranges["speed_0_10"]
        < ranges["higher_latency"]
        and ranges["speed_0_10"] < ranges["higher_variance"]
    ):
        errors.append("numerical monotonicity failed")
    if not (
        boundaries["minus_1e_6"] < 0.1
        and abs(boundaries["equal"] - 0.1) <= 1e-9
        and boundaries["plus_1e_6"] == 0.1
    ):
        errors.append("clearance boundary sensitivity failed")
    if not (
        abs(commands["retimed_at_half_speed"]["duration_s"] - 2.0) <= 1e-9
        and commands["monitor_only"]["input_payload_sha256"]
        == commands["monitor_only"]["output_payload_sha256"]
    ):
        errors.append("command oracle failed")
    if not (
        sensitivity["radius_base"] < sensitivity["radius_increased"]
        and sensitivity["offset_base"] < sensitivity["offset_reduced"]
        and sensitivity["acceleration_base"] < sensitivity["acceleration_reduced"]
        and sensitivity["jerk_base"] < sensitivity["jerk_reduced"]
        and sensitivity["variance_base"] < sensitivity["variance_asymmetric"]
        and sensitivity["latency_base"] < sensitivity["latency_increased"]
    ):
        errors.append("admissible geometry/braking sensitivity failed")
    if recovery_trace["normalized_result"] != "2_PASSED":
        errors.append("existing recovery production trace failed")
    derived_boundaries = derive_boundary_paths()
    return {
        "schema_version": 2,
        "packet_id": "WP-90-R1",
        "base_commit": "40cd9947f87eb9bf2719d72e7c72ea867eab9977",
        "inherited_wp89_r1_payload_sha256": (
            "18a7d8186543ba688c52fdabe4a196998f5eecbf860827b804ce1317e3ff4089"
        ),
        "design_payload_sha256": sha256_bytes(delimited_payload()),
        "source_category_map_derived_from_payload": {
            key: sorted(value) for key, value in sorted(parsed_sources.items())
        },
        "required_categories": sorted(required_categories),
        "binding_schema_derived_from_payload": binding_schema,
        "binding_schema_rule_count": derived_metric_count,
        "metric_count": len(METRICS),
        "metric_registry": [asdict(item) for item in METRICS],
        "whole_pass_failures": whole_failures,
        "isolated_vectors": isolated,
        "numerical_oracle": numeric,
        "recovery_trace": recovery_trace,
        "boundary_derivation": {
            key: sorted(value) for key, value in derived_boundaries.items()
        },
        "boundary_manifest": current_manifest(derived_boundaries),
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
                raise SystemExit("retained WP-90 design audit is stale")
        else:
            output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if result["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
