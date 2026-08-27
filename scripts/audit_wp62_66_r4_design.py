#!/usr/bin/env python3
"""Reproduce the narrow WP-62 through WP-66 R4 identity-bound correction."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import audit_wp62_66_r3_design as r3


THRESHOLD_M = r3.THRESHOLD_M
IDENTITY_FIELDS = frozenset({"packet_id", "case_id", "mode", "ordinal"})
RECORD_FIELDS = frozenset({"identity", "applicable", "tracking_rms_m"})
MAX_PACKET_ID_CHARS = 5
MAX_CASE_ID_CHARS = 96
MAX_MODE_CHARS = 32
MAX_ORDINAL = 3


def _identity_key(identity: Any) -> tuple[str, str, str, int] | None:
    """Return a bounded safe-to-render identity, or reject without conversion."""

    if type(identity) is not dict or frozenset(identity) != IDENTITY_FIELDS:
        return None
    packet_id = identity["packet_id"]
    case_id = identity["case_id"]
    mode = identity["mode"]
    ordinal = identity["ordinal"]
    if (
        type(packet_id) is not str
        or not 1 <= len(packet_id) <= MAX_PACKET_ID_CHARS
        or type(case_id) is not str
        or not 1 <= len(case_id) <= MAX_CASE_ID_CHARS
        or type(mode) is not str
        or not 1 <= len(mode) <= MAX_MODE_CHARS
        or type(ordinal) is not int
        or not 1 <= ordinal <= MAX_ORDINAL
    ):
        return None
    return packet_id, case_id, mode, ordinal


def _label(key: tuple[str, str, str, int]) -> str:
    # `_identity_key` bounds every component before this conversion is reachable.
    return f"{key[0]}|{key[1]}|{key[2]}|{key[3]}"


def qualify(records: Any) -> dict[str, Any]:
    expected_keys = [_identity_key(identity) for identity in r3._expected_identities()]
    assert all(key is not None for key in expected_keys)
    expected = {key for key in expected_keys if key is not None}
    failures: list[str] = []
    if type(records) is not list:
        return {
            "passed": False,
            "failures": ["records:INVALID_CONTAINER"],
            "expected_count": len(expected),
            "observed_record_count": 0,
            "unique_expected_observed_count": 0,
        }
    seen: set[tuple[str, str, str, int]] = set()
    for index, record in enumerate(records):
        if type(record) is not dict:
            failures.append(f"record-{index}:INVALID_RECORD")
            continue
        if frozenset(record) != RECORD_FIELDS:
            failures.append(f"record-{index}:INVALID_RECORD_FIELDS")
        key = _identity_key(record.get("identity"))
        if key is None:
            failures.append(f"record-{index}:INVALID_IDENTITY")
            continue
        label = _label(key)
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
        failures.append(f"{_label(key)}:MISSING")
    return {
        "passed": not failures,
        "failures": sorted(failures),
        "expected_count": len(expected),
        "observed_record_count": len(records),
        "unique_expected_observed_count": len(expected & seen),
    }


def _copy_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "identity": dict(row["identity"]),
            "applicable": row["applicable"],
            "tracking_rms_m": row["tracking_rms_m"],
        }
        for row in records
    ]


def _replace(
    passing: list[dict[str, Any]],
    index: int,
    *,
    identity: Any | None = None,
    applicable: Any = True,
    value: Any = 0.049,
) -> list[dict[str, Any]]:
    changed = _copy_records(passing)
    if identity is not None:
        changed[index]["identity"] = identity
    changed[index]["applicable"] = applicable
    changed[index]["tracking_rms_m"] = value
    return changed


def _cases() -> dict[str, Any]:
    passing = r3._passing_records()
    duplicate_overwrite = [
        r3._record(dict(passing[0]["identity"]), 0.20),
        *_copy_records(passing),
    ]
    missing = _copy_records(passing)
    missing.pop(-2)
    unexpected_identity = _replace(
        passing,
        0,
        identity={**passing[0]["identity"], "packet_id": "WP-65"},
        value=passing[0]["tracking_rms_m"],
    )
    missing_value = _copy_records(passing)
    missing_value[3].pop("tracking_rms_m")
    malformed_missing_identity_field = dict(passing[0]["identity"])
    malformed_missing_identity_field.pop("ordinal")
    malformed_extra_identity_field = {
        **passing[0]["identity"],
        "repeat_id": "accelerated-1",
    }
    aggregate_cheat = _copy_records(passing)
    aggregate_cheat[0]["tracking_rms_m"] = 0.002
    aggregate_cheat[-1]["tracking_rms_m"] = 0.053
    return {
        "passing": passing,
        "reordered_passing": list(reversed(_copy_records(passing))),
        "duplicate_overwrite": duplicate_overwrite,
        "missing": missing,
        "unexpected_identity": unexpected_identity,
        "invalid_not_applicable": _replace(passing, 4, applicable=False, value=None),
        "malformed_identity_scalar": _replace(passing, 0, identity="bad"),
        "malformed_identity_missing_field": _replace(
            passing, 0, identity=malformed_missing_identity_field
        ),
        "malformed_identity_extra_field": _replace(
            passing, 0, identity=malformed_extra_identity_field
        ),
        "non_mapping_record": [None, *_copy_records(passing[1:])],
        "ordinal_bool": _replace(
            passing, 0, identity={**passing[0]["identity"], "ordinal": True}
        ),
        "ordinal_float": _replace(
            passing, 0, identity={**passing[0]["identity"], "ordinal": 1.0}
        ),
        "ordinal_zero": _replace(
            passing, 0, identity={**passing[0]["identity"], "ordinal": 0}
        ),
        "ordinal_four": _replace(
            passing, 0, identity={**passing[0]["identity"], "ordinal": 4}
        ),
        "oversized_ordinal": _replace(
            passing, 0, identity={**passing[0]["identity"], "ordinal": 10**9999}
        ),
        "oversized_identity_string": _replace(
            passing, 0, identity={**passing[0]["identity"], "case_id": "x" * 10_000}
        ),
        "missing_value": missing_value,
        "non_numeric_value": _replace(passing, 5, value="0.01"),
        "boolean_value": _replace(passing, 5, value=True),
        "negative_value": _replace(passing, 6, value=-0.001),
        "oversized_integer_value": _replace(passing, 7, value=10**9999),
        "threshold_failure": _replace(passing, 8, value=0.051),
        "nan_failure": _replace(passing, 10, value=float("nan")),
        "positive_infinity_failure": _replace(passing, 11, value=float("inf")),
        "negative_infinity_failure": _replace(passing, 12, value=-float("inf")),
        "aggregate_cheat": aggregate_cheat,
        "invalid_container": {"records": passing},
    }


def _serializable(value: Any) -> Any:
    if type(value) is float and not math.isfinite(value):
        return {"injected_python_float": repr(value)}
    if type(value) is int and value.bit_length() > 4096:
        return {
            "injected_python_int": "10**9999",
            "bit_length": value.bit_length(),
        }
    if type(value) is str and len(value) > 256:
        return {"injected_python_string_length": len(value), "prefix": value[:16]}
    if type(value) is dict:
        return {str(key): _serializable(item) for key, item in value.items()}
    if type(value) is list:
        return [_serializable(item) for item in value]
    return value


def build_payload() -> dict[str, Any]:
    cases = _cases()
    outcomes = {case_id: qualify(records) for case_id, records in cases.items()}
    aggregate = cases["aggregate_cheat"]
    return {
        "schema_version": 1,
        "batch": "WP-62-through-WP-66-R4",
        "authorization": "ok yes i authorize",
        "base_design_sha256": (
            "52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6"
        ),
        "r2_design_sha256": (
            "4201ea8a858e1d91b3f5877bdfacbd4716b5fa59b42cac9ac9d796cf38477806"
        ),
        "r3_design_sha256": (
            "5c24eb560133232cf5fb9e7a5105a727083f78854f07cba85c86c2d5ee6c3b5d"
        ),
        "identity_bounds": {
            "packet_id_max_chars": MAX_PACKET_ID_CHARS,
            "case_id_max_chars": MAX_CASE_ID_CHARS,
            "mode_max_chars": MAX_MODE_CHARS,
            "ordinal_min": 1,
            "ordinal_max": MAX_ORDINAL,
            "validation_precedes_diagnostic_conversion": True,
        },
        "expected_identities": r3._expected_identities(),
        "cases": {case_id: _serializable(records) for case_id, records in cases.items()},
        "outcomes": outcomes,
        "aggregate_cheat_mean_m": sum(
            row["tracking_rms_m"] for row in aggregate
        )
        / len(aggregate),
    }


def check(payload: dict[str, Any]) -> None:
    assert len(payload["expected_identities"]) == 15
    assert payload["outcomes"]["passing"]["passed"]
    assert payload["outcomes"]["reordered_passing"] == payload["outcomes"]["passing"]
    for case_id, outcome in payload["outcomes"].items():
        assert outcome["passed"] is (case_id in {"passing", "reordered_passing"})
    exact_reasons = {
        "duplicate_overwrite": ":DUPLICATE",
        "missing": ":MISSING",
        "unexpected_identity": ":UNEXPECTED",
        "invalid_not_applicable": ":INVALID_NOT_APPLICABLE",
        "malformed_identity_scalar": ":INVALID_IDENTITY",
        "malformed_identity_missing_field": ":INVALID_IDENTITY",
        "malformed_identity_extra_field": ":INVALID_IDENTITY",
        "non_mapping_record": ":INVALID_RECORD",
        "ordinal_bool": ":INVALID_IDENTITY",
        "ordinal_float": ":INVALID_IDENTITY",
        "ordinal_zero": ":INVALID_IDENTITY",
        "ordinal_four": ":INVALID_IDENTITY",
        "oversized_ordinal": ":INVALID_IDENTITY",
        "oversized_identity_string": ":INVALID_IDENTITY",
        "missing_value": ":INVALID_RECORD_FIELDS",
        "non_numeric_value": ":MISSING_OR_NON_NUMERIC",
        "boolean_value": ":MISSING_OR_NON_NUMERIC",
        "negative_value": ":NEGATIVE",
        "oversized_integer_value": ":ABOVE_THRESHOLD",
        "threshold_failure": ":ABOVE_THRESHOLD",
        "nan_failure": ":NON_FINITE",
        "positive_infinity_failure": ":NON_FINITE",
        "negative_infinity_failure": ":NON_FINITE",
        "aggregate_cheat": ":ABOVE_THRESHOLD",
        "invalid_container": ":INVALID_CONTAINER",
    }
    for case_id, suffix in exact_reasons.items():
        assert any(
            failure.endswith(suffix)
            for failure in payload["outcomes"][case_id]["failures"]
        ), case_id
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
