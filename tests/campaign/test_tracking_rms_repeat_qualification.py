from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

import pytest

from crazyswarm_app.campaign.qualification import (
    TRACKING_RMS_REPEAT_IDENTITIES,
    qualify_tracking_rms_repeats,
)


def _passing() -> list[dict[str, Any]]:
    return [
        {
            "identity": {
                "packet_id": packet_id,
                "case_id": case_id,
                "mode": mode,
                "ordinal": ordinal,
            },
            "applicable": True,
            "tracking_rms_m": 0.049,
        }
        for packet_id, case_id, mode, ordinal in TRACKING_RMS_REPEAT_IDENTITIES
    ]


def test_tracking_rms_exact_repeat_universe_passes_in_any_record_order() -> None:
    passing = _passing()
    forward = qualify_tracking_rms_repeats(passing)
    reverse = qualify_tracking_rms_repeats(list(reversed(passing)))
    assert forward.passed
    assert reverse.passed
    assert forward.expected_count == reverse.expected_count == 15
    assert forward.unique_expected_observed_count == 15


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (lambda rows: [rows[0], *rows], ":DUPLICATE"),
        (lambda rows: rows[:-1], ":MISSING"),
        (
            lambda rows: _identity_update(rows, ordinal=4),
            "record-0:INVALID_IDENTITY",
        ),
        (
            lambda rows: _identity_update(rows, ordinal=True),
            "record-0:INVALID_IDENTITY",
        ),
        (
            lambda rows: _identity_update(rows, ordinal=1.0),
            "record-0:INVALID_IDENTITY",
        ),
        (
            lambda rows: _identity_update(rows, ordinal=10**9999),
            "record-0:INVALID_IDENTITY",
        ),
        (
            lambda rows: _identity_update(rows, case_id="x" * 97),
            "record-0:INVALID_IDENTITY",
        ),
        (lambda rows: _value_update(rows, None), ":MISSING_OR_NON_NUMERIC"),
        (lambda rows: _value_update(rows, True), ":MISSING_OR_NON_NUMERIC"),
        (lambda rows: _value_update(rows, -0.001), ":NEGATIVE"),
        (lambda rows: _value_update(rows, math.nan), ":NON_FINITE"),
        (lambda rows: _value_update(rows, math.inf), ":NON_FINITE"),
        (lambda rows: _value_update(rows, -math.inf), ":NON_FINITE"),
        (lambda rows: _value_update(rows, 10**9999), ":ABOVE_THRESHOLD"),
        (lambda rows: _value_update(rows, 0.051), ":ABOVE_THRESHOLD"),
        (lambda rows: _applicable_update(rows, False), ":INVALID_NOT_APPLICABLE"),
        (lambda rows: [None, *rows[1:]], "record-0:INVALID_RECORD"),
    ),
)
def test_tracking_rms_repeat_evaluator_fails_closed_without_raising(
    mutation: Any,
    reason: str,
) -> None:
    result = qualify_tracking_rms_repeats(mutation(_passing()))
    assert not result.passed
    assert any(reason in failure for failure in result.failures)


def test_tracking_rms_rejects_non_list_and_aggregate_masking() -> None:
    invalid_container = qualify_tracking_rms_repeats({"records": _passing()})
    aggregate = _passing()
    aggregate[0]["tracking_rms_m"] = 0.002
    aggregate[-1]["tracking_rms_m"] = 0.053
    masked = qualify_tracking_rms_repeats(aggregate)
    assert invalid_container.failures == ("records:INVALID_CONTAINER",)
    assert not masked.passed
    assert any(failure.endswith(":ABOVE_THRESHOLD") for failure in masked.failures)


def _identity_update(rows: list[dict[str, Any]], **updates: Any) -> list[dict[str, Any]]:
    changed = deepcopy(rows)
    changed[0]["identity"].update(updates)
    return changed


def _value_update(rows: list[dict[str, Any]], value: Any) -> list[dict[str, Any]]:
    changed = deepcopy(rows)
    changed[0]["tracking_rms_m"] = value
    return changed


def _applicable_update(rows: list[dict[str, Any]], value: Any) -> list[dict[str, Any]]:
    changed = deepcopy(rows)
    changed[0]["applicable"] = value
    return changed
