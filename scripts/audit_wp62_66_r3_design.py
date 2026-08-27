#!/usr/bin/env python3
"""Reproduce the narrow WP-62 through WP-66 R3 repeat-universe correction."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


THRESHOLD_M = 0.05
WP64_CASE_IDS = (
    "1d.curved_route.canonical_nominal",
    "1d.planar_shape_loop.figure_eight",
    "1d.altitude_transition.canonical_nominal",
)
WP66_CASE_ID = "1d.online_obstacle_replan.dynamic_nominal"


def _identity(
    packet_id: str,
    case_id: str,
    mode: str,
    ordinal: int,
) -> dict[str, Any]:
    return {
        "packet_id": packet_id,
        "case_id": case_id,
        "mode": mode,
        "ordinal": ordinal,
    }


def _identity_key(identity: Any) -> tuple[str, str, str, int] | None:
    if type(identity) is not dict or set(identity) != {
        "packet_id",
        "case_id",
        "mode",
        "ordinal",
    }:
        return None
    packet_id = identity["packet_id"]
    case_id = identity["case_id"]
    mode = identity["mode"]
    ordinal = identity["ordinal"]
    if (
        type(packet_id) is not str
        or type(case_id) is not str
        or type(mode) is not str
        or not packet_id
        or not case_id
        or not mode
        or type(ordinal) is not int
        or ordinal < 1
    ):
        return None
    return (packet_id, case_id, mode, ordinal)


def _expected_identities() -> list[dict[str, Any]]:
    expected: list[dict[str, Any]] = []
    for case_id in WP64_CASE_IDS:
        expected.extend(
            _identity("WP-64", case_id, "AUTOMATED_ACCELERATED", ordinal)
            for ordinal in range(1, 4)
        )
        expected.append(_identity("WP-64", case_id, "OPERATOR_OBSERVED_REALTIME", 1))
    expected.extend(
        _identity("WP-66", WP66_CASE_ID, "OPERATOR_OBSERVED_REALTIME", ordinal)
        for ordinal in range(1, 4)
    )
    return expected


def _record(identity: dict[str, Any], value: Any, *, applicable: bool = True) -> dict[str, Any]:
    return {
        "identity": identity,
        "applicable": applicable,
        "tracking_rms_m": value,
    }


def _passing_records() -> list[dict[str, Any]]:
    return [
        _record(identity, 0.047 + (index % 3) * 0.001)
        for index, identity in enumerate(_expected_identities())
    ]


def qualify(records: list[Any]) -> dict[str, Any]:
    expected = {_identity_key(identity) for identity in _expected_identities()}
    assert None not in expected
    seen: set[tuple[str, str, str, int]] = set()
    failures: list[str] = []
    for index, record in enumerate(records):
        if type(record) is not dict:
            failures.append(f"record-{index}:INVALID_RECORD")
            continue
        if set(record) != {"identity", "applicable", "tracking_rms_m"}:
            failures.append(f"record-{index}:INVALID_RECORD_FIELDS")
        identity = record.get("identity")
        key = _identity_key(identity)
        if key is None:
            failures.append(f"record-{index}:INVALID_IDENTITY")
            continue
        label = "|".join((*key[:3], str(key[3])))
        if key in seen:
            failures.append(f"{label}:DUPLICATE")
        else:
            seen.add(key)
        if key not in expected:
            failures.append(f"{label}:UNEXPECTED")
        if record.get("applicable") is not True:
            failures.append(f"{label}:INVALID_NOT_APPLICABLE")
        value = record.get("tracking_rms_m")
        if type(value) not in (int, float):
            failures.append(f"{label}:MISSING_OR_NON_NUMERIC")
        elif type(value) is float and not math.isfinite(value):
            failures.append(f"{label}:NON_FINITE")
        elif value < 0:
            failures.append(f"{label}:NEGATIVE")
        elif value > THRESHOLD_M:
            failures.append(f"{label}:ABOVE_THRESHOLD")
    for key in sorted(expected - seen):
        failures.append(f"{'|'.join((*key[:3], str(key[3])))}:MISSING")
    return {
        "passed": not failures,
        "failures": sorted(failures),
        "expected_count": len(expected),
        "observed_record_count": len(records),
        "unique_expected_observed_count": len(expected & seen),
    }


def _replace_value(
    records: list[dict[str, Any]],
    index: int,
    value: Any,
    *,
    applicable: bool = True,
) -> list[dict[str, Any]]:
    changed = [
        {"identity": dict(row["identity"]), **{k: v for k, v in row.items() if k != "identity"}}
        for row in records
    ]
    changed[index]["tracking_rms_m"] = value
    changed[index]["applicable"] = applicable
    return changed


def _serializable(value: Any) -> Any:
    if type(value) is float and not math.isfinite(value):
        return {"injected_python_float": repr(value)}
    if type(value) is dict:
        return {key: _serializable(item) for key, item in value.items()}
    if type(value) is list:
        return [_serializable(item) for item in value]
    return value


def build_payload() -> dict[str, Any]:
    passing = _passing_records()
    duplicate_overwrite = [
        _record(dict(passing[0]["identity"]), 0.20),
        *passing,
    ]
    missing_wp66_realtime_2 = [
        row
        for row in passing
        if _identity_key(row["identity"])
        != ("WP-66", WP66_CASE_ID, "OPERATOR_OBSERVED_REALTIME", 2)
    ]
    unexpected_wp66_realtime_4 = [
        *passing,
        _record(
            _identity("WP-66", WP66_CASE_ID, "OPERATOR_OBSERVED_REALTIME", 4),
            0.01,
        ),
    ]
    aggregate_cheat = _replace_value(passing, len(passing) - 1, 0.053)
    aggregate_cheat[0]["tracking_rms_m"] = 0.002
    malformed_identity_scalar = [dict(row) for row in passing]
    malformed_identity_scalar[0] = {
        **malformed_identity_scalar[0],
        "identity": "WP-64|curved|accelerated|1",
    }
    malformed_identity_missing_field = [dict(row) for row in passing]
    missing_field_identity = dict(passing[0]["identity"])
    missing_field_identity.pop("ordinal")
    malformed_identity_missing_field[0] = {
        **malformed_identity_missing_field[0],
        "identity": missing_field_identity,
    }
    malformed_identity_extra_field = [dict(row) for row in passing]
    malformed_identity_extra_field[0] = {
        **malformed_identity_extra_field[0],
        "identity": {**passing[0]["identity"], "repeat_id": "accelerated-1"},
    }
    ordinal_bool = [dict(row) for row in passing]
    ordinal_bool[0] = {
        **ordinal_bool[0],
        "identity": {**passing[0]["identity"], "ordinal": True},
    }
    ordinal_float = [dict(row) for row in passing]
    ordinal_float[0] = {
        **ordinal_float[0],
        "identity": {**passing[0]["identity"], "ordinal": 1.0},
    }
    missing_value = [dict(row) for row in passing]
    missing_value[3] = dict(missing_value[3])
    missing_value[3].pop("tracking_rms_m")
    cases = {
        "passing": passing,
        "reordered_passing": list(reversed(passing)),
        "duplicate_overwrite": duplicate_overwrite,
        "missing_wp66_realtime_2": missing_wp66_realtime_2,
        "unexpected_wp66_realtime_4": unexpected_wp66_realtime_4,
        "invalid_not_applicable": _replace_value(passing, 4, None, applicable=False),
        "malformed_identity_scalar": malformed_identity_scalar,
        "malformed_identity_missing_field": malformed_identity_missing_field,
        "malformed_identity_extra_field": malformed_identity_extra_field,
        "non_mapping_record": [None, *passing[1:]],
        "ordinal_bool": ordinal_bool,
        "ordinal_float": ordinal_float,
        "missing_value": missing_value,
        "non_numeric_value": _replace_value(passing, 5, "0.01"),
        "negative_value": _replace_value(passing, 6, -0.001),
        "oversized_integer": _replace_value(passing, 7, 10**1000),
        "single_threshold_failure": _replace_value(passing, 8, 0.051),
        "nan_failure": _replace_value(passing, 10, float("nan")),
        "positive_infinity_failure": _replace_value(passing, 11, float("inf")),
        "negative_infinity_failure": _replace_value(passing, 12, -float("inf")),
        "aggregate_cheat": aggregate_cheat,
    }
    outcomes = {case_id: qualify(records) for case_id, records in cases.items()}
    return {
        "schema_version": 1,
        "batch": "WP-62-through-WP-66-R3",
        "authorization": "ok yes i authorize",
        "base_design_sha256": (
            "52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6"
        ),
        "r2_design_sha256": (
            "4201ea8a858e1d91b3f5877bdfacbd4716b5fa59b42cac9ac9d796cf38477806"
        ),
        "metric": "tracking_rms_m",
        "comparator": "finite value <= 0.05 m on every exact repeat",
        "threshold_m": THRESHOLD_M,
        "identity_fields": ["packet_id", "case_id", "mode", "ordinal"],
        "applicability": "required; no N/A branch",
        "expected_identities": _expected_identities(),
        "expected_count": len(_expected_identities()),
        "cases": {case_id: _serializable(records) for case_id, records in cases.items()},
        "outcomes": outcomes,
        "aggregate_cheat_mean_m": sum(
            row["tracking_rms_m"] for row in aggregate_cheat
        )
        / len(aggregate_cheat),
    }


def check(payload: dict[str, Any]) -> None:
    assert payload["expected_count"] == 15
    keys = [_identity_key(identity) for identity in payload["expected_identities"]]
    assert None not in keys
    assert len(keys) == len(set(keys)) == 15
    assert payload["outcomes"]["passing"]["passed"]
    assert payload["outcomes"]["reordered_passing"] == payload["outcomes"]["passing"]
    for case_id in (
        "duplicate_overwrite",
        "missing_wp66_realtime_2",
        "unexpected_wp66_realtime_4",
        "invalid_not_applicable",
        "malformed_identity_scalar",
        "malformed_identity_missing_field",
        "malformed_identity_extra_field",
        "non_mapping_record",
        "ordinal_bool",
        "ordinal_float",
        "missing_value",
        "non_numeric_value",
        "negative_value",
        "oversized_integer",
        "single_threshold_failure",
        "nan_failure",
        "positive_infinity_failure",
        "negative_infinity_failure",
        "aggregate_cheat",
    ):
        assert not payload["outcomes"][case_id]["passed"]
    duplicate_failures = payload["outcomes"]["duplicate_overwrite"]["failures"]
    assert any(item.endswith(":DUPLICATE") for item in duplicate_failures)
    assert any(item.endswith(":ABOVE_THRESHOLD") for item in duplicate_failures)
    exact_reason_suffixes = {
        "malformed_identity_scalar": ":INVALID_IDENTITY",
        "malformed_identity_missing_field": ":INVALID_IDENTITY",
        "malformed_identity_extra_field": ":INVALID_IDENTITY",
        "non_mapping_record": ":INVALID_RECORD",
        "ordinal_bool": ":INVALID_IDENTITY",
        "ordinal_float": ":INVALID_IDENTITY",
        "missing_value": ":INVALID_RECORD_FIELDS",
        "non_numeric_value": ":MISSING_OR_NON_NUMERIC",
        "negative_value": ":NEGATIVE",
        "oversized_integer": ":ABOVE_THRESHOLD",
    }
    for case_id, suffix in exact_reason_suffixes.items():
        assert any(
            item.endswith(suffix) for item in payload["outcomes"][case_id]["failures"]
        )
    assert payload["aggregate_cheat_mean_m"] < THRESHOLD_M


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", nargs="?", type=Path)
    args = parser.parse_args()
    payload = build_payload()
    check(payload)
    if args.artifact is not None:
        assert json.loads(args.artifact.read_text()) == payload
    print(json.dumps(payload, allow_nan=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
