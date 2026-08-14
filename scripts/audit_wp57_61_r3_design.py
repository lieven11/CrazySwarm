#!/usr/bin/env python3
"""Audit the operator-authorized WP-57 through WP-61 R3 design overlay.

R3 does not replace either frozen predecessor design. It proves that the WP-61F
promotion guard universe is independently derived from those designs and durable
requirements, then prototypes the complete expanded whole-session relation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


BASE_BEGIN = "<!-- WP57-61-DESIGN-PAYLOAD-BEGIN -->"
BASE_END = "<!-- WP57-61-DESIGN-PAYLOAD-END -->"
R2_BEGIN = "<!-- WP57-61-R2-DESIGN-PAYLOAD-BEGIN -->"
R2_END = "<!-- WP57-61-R2-DESIGN-PAYLOAD-END -->"

BASE_DESIGN_SHA256 = (
    "2096bac6a01dd437ff5f909bc63bd3b012b30927b7d270aa3f9c4644049f8c6f"
)
BASE_DESIGN_BYTES = 51_957
R2_OVERLAY_SHA256 = (
    "e1be5e88fa91c510eb5612ee1b30d35347df53008e4fd7d563f044cbd6c67b5c"
)
R2_OVERLAY_BYTES = 13_087
R2_AUDIT_SCRIPT_SHA256 = (
    "961d157e05a3293dbd9feef371167af070188c19e2a5eccf65a0499b47f8ec87"
)
R2_AUDIT_FILE_SHA256 = (
    "0237cf6d23b08dd32e0e50705fc2572aca02db896fbeb8cf99951a883b0cd810"
)
R2_AUDIT_PAYLOAD_SHA256 = (
    "229eb2a55635df03f08855be12e5bc7f487c65e5697d5556f08f2db53ce0cc2f"
)
WORKFLOW_SHA256 = (
    "b8972dfc2c74256adf268c672ae82a5bf700c43ab65d68d98a3aca88e3973183"
)

GEOMETRIES = ("straight", "curve")
REPEAT_COUNT = 3
REPEAT_NUMERIC_TOLERANCE = 1e-12

R2_GUARD_IDS = (
    "speed_compliance_fraction",
    "speed_ripple_m_s",
    "acceleration_p95_m_s2",
    "jerk_p95_m_s3",
    "angular_rate_p95_rad_s",
    "motor_spread_p95_percent",
    "tracking_rms_m",
    "path_tube_max_error_m",
    "motor_saturation_fraction",
    "duration_s",
    "terminal_secondary_peak_m_s",
    "terminal_reversal_count",
    "minimum_clearance_m",
    "collision_count",
    "supervisor_safety_gate_passed",
)

ADDITIONAL_GUARDS: dict[str, dict[str, Any]] = {
    "minimum_motor_thrust_headroom_n": {
        "relation": "MINIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.030,
        "maximum_regression_fraction": 0.05,
    },
    "electrical_energy_used_j": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 220.0,
        "maximum_regression_fraction": 0.05,
    },
    "motor_differential_sign_agreement_fraction": {
        "relation": "MINIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.95,
        "maximum_regression_fraction": 0.05,
    },
    "motor_differential_normalized_error_p95": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.10,
        "maximum_regression_fraction": 0.05,
    },
    "checkpoint_hold_conformance_fraction": {
        "relation": "MINIMUM_EXACT",
        "hard_threshold": 1.0,
    },
    "minimum_continuous_knot_speed_ratio": {
        "relation": "MINIMUM_BY_GEOMETRY_AND_MAXIMUM_REGRESSION",
        "hard_threshold_by_geometry": {"straight": 0.85, "curve": 0.95},
        "maximum_regression_fraction": 0.05,
    },
    "unintended_fly_through_stop_count": {
        "relation": "MAXIMUM_EXACT",
        "hard_threshold": 0,
    },
}

NEW_BASELINE_VALUES = {
    "straight": {
        "minimum_motor_thrust_headroom_n": 0.040,
        "electrical_energy_used_j": 150.0,
        "motor_differential_sign_agreement_fraction": 0.980,
        "motor_differential_normalized_error_p95": 0.060,
        "checkpoint_hold_conformance_fraction": 1.0,
        "minimum_continuous_knot_speed_ratio": 0.920,
        "unintended_fly_through_stop_count": 0,
    },
    "curve": {
        "minimum_motor_thrust_headroom_n": 0.038,
        "electrical_energy_used_j": 165.0,
        "motor_differential_sign_agreement_fraction": 0.975,
        "motor_differential_normalized_error_p95": 0.065,
        "checkpoint_hold_conformance_fraction": 1.0,
        "minimum_continuous_knot_speed_ratio": 0.980,
        "unintended_fly_through_stop_count": 0,
    },
}

NEW_PASS_VALUES = {
    "straight": {
        "minimum_motor_thrust_headroom_n": 0.039,
        "electrical_energy_used_j": 153.0,
        "motor_differential_sign_agreement_fraction": 0.970,
        "motor_differential_normalized_error_p95": 0.062,
        "checkpoint_hold_conformance_fraction": 1.0,
        "minimum_continuous_knot_speed_ratio": 0.900,
        "unintended_fly_through_stop_count": 0,
    },
    "curve": {
        "minimum_motor_thrust_headroom_n": 0.037,
        "electrical_energy_used_j": 168.0,
        "motor_differential_sign_agreement_fraction": 0.965,
        "motor_differential_normalized_error_p95": 0.067,
        "checkpoint_hold_conformance_fraction": 1.0,
        "minimum_continuous_knot_speed_ratio": 0.970,
        "unintended_fly_through_stop_count": 0,
    },
}

NEW_ISOLATED_FAILURES = {
    "minimum_motor_thrust_headroom_n": ("straight", 0.029),
    "electrical_energy_used_j": ("straight", 160.0),
    "motor_differential_sign_agreement_fraction": ("straight", 0.940),
    "motor_differential_normalized_error_p95": ("straight", 0.110),
    "checkpoint_hold_conformance_fraction": ("straight", 0.5),
    "minimum_continuous_knot_speed_ratio": ("curve", 0.940),
    "unintended_fly_through_stop_count": ("straight", 1),
}

# The initial metric-level fixtures above prove that each metric can reject, but eight
# of them cross both the hard and regression boundary together. These exact witnesses
# keep the hard bound passing and isolate the independently tighter regression clause.
ADDITIONAL_BINDING_CLAUSE_FAILURES = {
    "speed_ripple_m_s.straight.regression_only": (
        "speed_ripple_m_s",
        "straight",
        0.0421,
    ),
    "path_tube_max_error_m.straight.regression_only": (
        "path_tube_max_error_m",
        "straight",
        0.0421,
    ),
    "motor_saturation_fraction.straight.regression_only": (
        "motor_saturation_fraction",
        "straight",
        0.0053,
    ),
    "terminal_secondary_peak_m_s.straight.regression_only": (
        "terminal_secondary_peak_m_s",
        "straight",
        0.0106,
    ),
    "minimum_clearance_m.straight.regression_only": (
        "minimum_clearance_m",
        "straight",
        0.189,
    ),
    "minimum_motor_thrust_headroom_n.straight.regression_only": (
        "minimum_motor_thrust_headroom_n",
        "straight",
        0.0379,
    ),
    "motor_differential_normalized_error_p95.straight.regression_only": (
        "motor_differential_normalized_error_p95",
        "straight",
        0.0631,
    ),
    "minimum_continuous_knot_speed_ratio.straight.regression_only": (
        "minimum_continuous_knot_speed_ratio",
        "straight",
        0.873,
    ),
}

# Each independently binding clause under the exact canonical predecessor vector has
# one sensitive witness. Ordinary guards share one implementation relation across the
# two geometries. The continuous guard has distinct 0.85/0.95 geometry branches and
# therefore retains a separate witness for each branch.
BINDING_CLAUSE_WITNESSES = (
    ("speed_compliance_fraction", "straight", "HARD_ONLY", "metric"),
    (
        "speed_ripple_m_s",
        "straight",
        "REGRESSION_ONLY",
        "speed_ripple_m_s.straight.regression_only",
    ),
    ("acceleration_p95_m_s2", "straight", "REGRESSION_ONLY", "metric"),
    ("jerk_p95_m_s3", "straight", "REGRESSION_ONLY", "metric"),
    ("angular_rate_p95_rad_s", "straight", "REGRESSION_ONLY", "metric"),
    ("motor_spread_p95_percent", "straight", "REGRESSION_ONLY", "metric"),
    ("tracking_rms_m", "straight", "REGRESSION_ONLY", "metric"),
    (
        "path_tube_max_error_m",
        "straight",
        "REGRESSION_ONLY",
        "path_tube_max_error_m.straight.regression_only",
    ),
    (
        "motor_saturation_fraction",
        "straight",
        "REGRESSION_ONLY",
        "motor_saturation_fraction.straight.regression_only",
    ),
    ("duration_s", "straight", "REGRESSION_ONLY", "metric"),
    (
        "terminal_secondary_peak_m_s",
        "straight",
        "REGRESSION_ONLY",
        "terminal_secondary_peak_m_s.straight.regression_only",
    ),
    ("terminal_reversal_count", "straight", "EXACT_ONLY", "metric"),
    (
        "minimum_clearance_m",
        "straight",
        "REGRESSION_ONLY",
        "minimum_clearance_m.straight.regression_only",
    ),
    ("collision_count", "straight", "EXACT_ONLY", "metric"),
    ("supervisor_safety_gate_passed", "straight", "EXACT_ONLY", "metric"),
    (
        "minimum_motor_thrust_headroom_n",
        "straight",
        "REGRESSION_ONLY",
        "minimum_motor_thrust_headroom_n.straight.regression_only",
    ),
    ("electrical_energy_used_j", "straight", "REGRESSION_ONLY", "metric"),
    (
        "motor_differential_sign_agreement_fraction",
        "straight",
        "HARD_ONLY",
        "metric",
    ),
    (
        "motor_differential_normalized_error_p95",
        "straight",
        "REGRESSION_ONLY",
        "motor_differential_normalized_error_p95.straight.regression_only",
    ),
    ("checkpoint_hold_conformance_fraction", "straight", "EXACT_ONLY", "metric"),
    (
        "minimum_continuous_knot_speed_ratio",
        "straight",
        "REGRESSION_ONLY",
        "minimum_continuous_knot_speed_ratio.straight.regression_only",
    ),
    (
        "minimum_continuous_knot_speed_ratio",
        "curve",
        "HARD_ONLY",
        "metric",
    ),
    ("unintended_fly_through_stop_count", "straight", "EXACT_ONLY", "metric"),
)

SEMANTIC_GUARD_COVERAGE = {
    "speed_law_and_band_coverage": (
        "speed_compliance_fraction",
        "speed_ripple_m_s",
    ),
    "acceleration": ("acceleration_p95_m_s2",),
    "jerk": ("jerk_p95_m_s3",),
    "body_angular_activity": ("angular_rate_p95_rad_s",),
    "motor_headroom": ("minimum_motor_thrust_headroom_n",),
    "motor_spread": ("motor_spread_p95_percent",),
    "motor_saturation": ("motor_saturation_fraction",),
    "signed_motor_differential": (
        "motor_differential_sign_agreement_fraction",
        "motor_differential_normalized_error_p95",
    ),
    "energy": ("electrical_energy_used_j",),
    "path_adherence_and_deviation": (
        "tracking_rms_m",
        "path_tube_max_error_m",
    ),
    "waypoint_checkpoint_mode": ("checkpoint_hold_conformance_fraction",),
    "waypoint_continuous_mode": (
        "minimum_continuous_knot_speed_ratio",
        "unintended_fly_through_stop_count",
    ),
    "terminal_behavior": (
        "terminal_secondary_peak_m_s",
        "terminal_reversal_count",
    ),
    "duration": ("duration_s",),
    "obstacle_clearance": ("minimum_clearance_m",),
    "collision": ("collision_count",),
    "supervisor_safety": ("supervisor_safety_gate_passed",),
}

EXPECTED_SEMANTIC_CATEGORIES = tuple(SEMANTIC_GUARD_COVERAGE)

DECLARATION_PROBES = (
    {
        "source": "base_design",
        "tokens": (
            "speed compliance, speed ripple, acceleration, jerk,",
            "angular-rate shakiness, motor differential/spread, path-tube tracking, waypoint mode,",
            "terminal behavior, saturation, and duration",
        ),
        "categories": (
            "speed_law_and_band_coverage",
            "acceleration",
            "jerk",
            "body_angular_activity",
            "motor_spread",
            "path_adherence_and_deviation",
            "waypoint_checkpoint_mode",
            "waypoint_continuous_mode",
            "terminal_behavior",
            "motor_saturation",
            "duration",
        ),
    },
    {
        "source": "workflow",
        "tokens": (
            "motor headroom/spread/saturation, energy, and terminal behavior",
            "`CHECKPOINT` and `CONTINUOUS_FLY_THROUGH` are distinct reusable traversal modes",
        ),
        "categories": (
            "motor_headroom",
            "energy",
            "waypoint_checkpoint_mode",
            "waypoint_continuous_mode",
        ),
    },
    {
        "source": "workflow",
        "tokens": (
            "expected signed differential-actuation response",
            "every individual motor's requested thrust/applied PWM/thrust/current/headroom/saturation",
        ),
        "categories": (
            "signed_motor_differential",
            "motor_headroom",
            "motor_saturation",
        ),
    },
    {
        "source": "composite_design",
        "tokens": (
            "preserve the Safety Supervisor",
            "observed solids with the required clearance",
            "collision count",
        ),
        "categories": (
            "supervisor_safety",
            "obstacle_clearance",
            "collision",
        ),
    },
)

METRIC_DEFINITIONS = {
    "speed_compliance_fraction": "Fraction of unique source-sequence cruise samples inside the active target-speed band.",
    "speed_ripple_m_s": "Cruise source-sequence speed p95 minus p05 in metres per second.",
    "acceleration_p95_m_s2": "P95 norm of source-aligned world acceleration during the motion window.",
    "jerk_p95_m_s3": "P95 finite-difference acceleration derivative on unique source-sequence samples.",
    "angular_rate_p95_rad_s": "P95 norm of body angular velocity from source-aligned IMU samples.",
    "motor_spread_p95_percent": "P95 per-sample maximum minus minimum applied motor PWM percentage.",
    "tracking_rms_m": "RMS observed-position distance to the hash-bound planned trajectory at matched source time.",
    "path_tube_max_error_m": "Maximum observed-position distance outside the planned path centreline during the motion window.",
    "motor_saturation_fraction": "Fraction of motion-window samples with any motor saturation flag set.",
    "duration_s": "Source-clock elapsed time from accepted takeoff motion start through terminal motor cutoff.",
    "terminal_secondary_peak_m_s": "Largest literal last-approach secondary scalar-speed peak prominence.",
    "terminal_reversal_count": "Count of unintended velocity-component sign reversals in the literal terminal approach.",
    "minimum_clearance_m": "Minimum independent geometry distance from observed vehicle envelope to perceived solid over the executed path.",
    "collision_count": "Count of independently recomputed vehicle-envelope intersections with world solids.",
    "supervisor_safety_gate_passed": "Literal conjunction of the retained Safety Supervisor decisions for the whole session.",
    "minimum_motor_thrust_headroom_n": "Minimum over all motion samples and motors of configured maximum thrust minus applied thrust, in newtons.",
    "electrical_energy_used_j": "Trapezoidal source-time integral of measured battery voltage times current from accepted motion start through motor cutoff.",
    "motor_differential_sign_agreement_fraction": "Fraction of samples with an independently expected nonzero X-layout torque whose measured signed motor-pair differential has the expected sign.",
    "motor_differential_normalized_error_p95": "P95 absolute measured-minus-expected signed motor-pair differential divided by max(expected absolute differential, 0.005 N).",
    "checkpoint_hold_conformance_fraction": "Fraction of authored CHECKPOINT nodes captured inside their ball and held for authored dwell within plus or minus 0.02 source seconds.",
    "minimum_continuous_knot_speed_ratio": "Minimum observed-to-adjacent-target speed ratio at authored CONTINUOUS_FLY_THROUGH nodes; straight ordinary knots use 0.85 and the curve repeated crossover uses 0.95.",
    "unintended_fly_through_stop_count": "Count of undeclared stops at CONTINUOUS_FLY_THROUGH nodes using the frozen stop-speed and dwell oracle.",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _extract(text: str, begin: str, end: str) -> bytes:
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    return text[start:finish].encode()


def _guard_result(
    guard_id: str,
    contract: dict[str, Any],
    baseline_values: list[float | int | bool],
    candidate_values: list[float | int | bool],
    *,
    geometry: str | None,
) -> dict[str, Any]:
    relation = contract["relation"]
    if relation == "BOOLEAN_TRUE":
        baseline_mean: float | bool = all(value is True for value in baseline_values)
        candidate_mean: float | bool = all(value is True for value in candidate_values)
        threshold: float | bool = True
        regression = None
        passed = candidate_mean is True
    else:
        numeric_baseline = [float(value) for value in baseline_values]
        numeric_candidate = [float(value) for value in candidate_values]
        baseline_mean = _mean(numeric_baseline)
        candidate_mean = _mean(numeric_candidate)
        maximum_regression = contract.get("maximum_regression_fraction")
        if relation == "MINIMUM_BY_GEOMETRY_AND_MAXIMUM_REGRESSION":
            if geometry is None:
                raise ValueError("geometry-normalized guard requires aggregate helper")
            threshold = float(contract["hard_threshold_by_geometry"][geometry])
            regression = 1.0 - candidate_mean / baseline_mean
            passed = (
                min(numeric_candidate) >= threshold
                and regression <= float(maximum_regression)
            )
        else:
            threshold = contract["hard_threshold"]
            if relation == "MAXIMUM_EXACT":
                regression = None
                passed = max(numeric_candidate) <= float(threshold)
            elif relation == "MINIMUM_EXACT":
                regression = None
                passed = min(numeric_candidate) >= float(threshold)
            elif relation == "MAXIMUM_AND_MAXIMUM_REGRESSION":
                regression = candidate_mean / baseline_mean - 1.0
                passed = (
                    max(numeric_candidate) <= float(threshold)
                    and regression <= float(maximum_regression)
                )
            elif relation == "MINIMUM_AND_MAXIMUM_REGRESSION":
                regression = 1.0 - candidate_mean / baseline_mean
                passed = (
                    min(numeric_candidate) >= float(threshold)
                    and regression <= float(maximum_regression)
                )
            else:
                raise ValueError(f"unknown guard relation: {relation}")
    return {
        "guard_id": guard_id,
        "relation": relation,
        "geometry": geometry,
        "hard_threshold": threshold,
        "maximum_regression_fraction": contract.get(
            "maximum_regression_fraction"
        ),
        "baseline_mean": baseline_mean,
        "candidate_mean": candidate_mean,
        "regression_fraction": regression,
        "passed": passed,
    }


def _aggregate_guard_result(
    guard_id: str,
    contract: dict[str, Any],
    baseline: dict[str, dict[str, list[Any]]],
    candidate: dict[str, dict[str, list[Any]]],
) -> dict[str, Any]:
    relation = contract["relation"]
    if relation != "MINIMUM_BY_GEOMETRY_AND_MAXIMUM_REGRESSION":
        return _guard_result(
            guard_id,
            contract,
            [value for geometry in GEOMETRIES for value in baseline[geometry][guard_id]],
            [value for geometry in GEOMETRIES for value in candidate[geometry][guard_id]],
            geometry=None,
        )
    normalized_baseline = []
    normalized_candidate = []
    for geometry in GEOMETRIES:
        threshold = float(contract["hard_threshold_by_geometry"][geometry])
        normalized_baseline.extend(
            float(value) / threshold for value in baseline[geometry][guard_id]
        )
        normalized_candidate.extend(
            float(value) / threshold for value in candidate[geometry][guard_id]
        )
    baseline_mean = _mean(normalized_baseline)
    candidate_mean = _mean(normalized_candidate)
    regression = 1.0 - candidate_mean / baseline_mean
    passed = (
        min(normalized_candidate) >= 1.0
        and regression <= float(contract["maximum_regression_fraction"])
    )
    return {
        "guard_id": guard_id,
        "relation": relation,
        "geometry": None,
        "hard_threshold": 1.0,
        "hard_threshold_by_geometry": contract["hard_threshold_by_geometry"],
        "maximum_regression_fraction": contract["maximum_regression_fraction"],
        "baseline_mean_normalized_to_threshold": baseline_mean,
        "candidate_mean_normalized_to_threshold": candidate_mean,
        "minimum_candidate_normalized_to_threshold": min(normalized_candidate),
        "regression_fraction": regression,
        "passed": passed,
    }


def _guard_clause_state(
    guard_id: str,
    contract: dict[str, Any],
    scenario: dict[str, Any],
    geometry: str,
) -> dict[str, Any]:
    outputs = scenario["geometries"][geometry]
    baseline_values = outputs["baseline_repeat_outputs"][guard_id]
    candidate_values = outputs["candidate_repeat_outputs"][guard_id]
    relation = contract["relation"]
    if relation == "BOOLEAN_TRUE":
        return {
            "hard_passed": all(value is True for value in candidate_values),
            "regression_passed": None,
        }
    numeric_baseline = [float(value) for value in baseline_values]
    numeric_candidate = [float(value) for value in candidate_values]
    if relation == "MINIMUM_BY_GEOMETRY_AND_MAXIMUM_REGRESSION":
        threshold = float(contract["hard_threshold_by_geometry"][geometry])
    else:
        threshold = float(contract["hard_threshold"])
    if relation.startswith("MAXIMUM"):
        hard_passed = max(numeric_candidate) <= threshold
    else:
        hard_passed = min(numeric_candidate) >= threshold
    maximum_regression = contract.get("maximum_regression_fraction")
    if maximum_regression is None:
        regression_passed = None
    elif relation.startswith("MAXIMUM"):
        regression_passed = (
            _mean(numeric_candidate) / _mean(numeric_baseline) - 1.0
            <= float(maximum_regression)
        )
    else:
        regression_passed = (
            1.0 - _mean(numeric_candidate) / _mean(numeric_baseline)
            <= float(maximum_regression)
        )
    return {
        "hard_passed": hard_passed,
        "regression_passed": regression_passed,
    }


def _isolated_scenario_check(
    guard_id: str,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    other_guard_results = [
        result
        for result_id, result in scenario["aggregate"]["guard_results"].items()
        if result_id != guard_id
    ]
    for geometry in GEOMETRIES:
        other_guard_results.extend(
            result
            for result_id, result in scenario["geometries"][geometry][
                "guard_results"
            ].items()
            if result_id != guard_id
        )
    named_results = [scenario["aggregate"]["guard_results"][guard_id]] + [
        scenario["geometries"][geometry]["guard_results"][guard_id]
        for geometry in GEOMETRIES
    ]
    result = {
        "changed_only_named_guard": scenario["changed_guard_ids"] == [guard_id],
        "changed_no_residual": not scenario["changed_non_guard_metrics"],
        "primary_passed": scenario["aggregate"]["primary_passed"],
        "secondary_residuals_passed": scenario["aggregate"][
            "secondary_residuals_passed"
        ],
        "repeatable": scenario["aggregate"]["repeatable"],
        "named_guard_failed": not all(item["passed"] for item in named_results),
        "every_other_guard_passed": all(
            item["passed"] for item in other_guard_results
        ),
        "promotion_rejected": not scenario["promotion_oracle_passed"],
    }
    result["passed"] = all(result.values())
    return result


def _repeat_identity(outputs: dict[str, list[Any]]) -> dict[str, Any]:
    vectors = [
        {metric: values[index] for metric, values in sorted(outputs.items())}
        for index in range(REPEAT_COUNT)
    ]
    hashes = [_canonical_sha256(vector) for vector in vectors]
    spreads = {}
    for metric, values in sorted(outputs.items()):
        if all(isinstance(value, bool) for value in values):
            spreads[metric] = 0.0 if len(set(values)) == 1 else 1.0
        else:
            numeric = [float(value) for value in values]
            spreads[metric] = max(numeric) - min(numeric)
    return {
        "repeat_vectors": vectors,
        "repeat_sha256s": hashes,
        "hashes_identical": len(set(hashes)) == 1,
        "metric_spreads": spreads,
        "maximum_numeric_spread": max(spreads.values(), default=0.0),
        "numeric_tolerance": REPEAT_NUMERIC_TOLERANCE,
        "passed": (
            len(set(hashes)) == 1
            and max(spreads.values(), default=0.0) <= REPEAT_NUMERIC_TOLERANCE
        ),
    }


def _scenario(
    name: str,
    registry: dict[str, dict[str, Any]],
    baseline: dict[str, dict[str, list[Any]]],
    passing_candidate: dict[str, dict[str, list[Any]]],
    *,
    override: tuple[str, str, float | int | bool] | None = None,
) -> dict[str, Any]:
    candidate = copy.deepcopy(passing_candidate)
    if override is not None:
        guard_id, geometry, value = override
        candidate[geometry][guard_id] = [value] * REPEAT_COUNT

    per_geometry_guard_results = {
        geometry: {
            guard_id: _guard_result(
                guard_id,
                contract,
                baseline[geometry][guard_id],
                candidate[geometry][guard_id],
                geometry=geometry,
            )
            for guard_id, contract in registry.items()
        }
        for geometry in GEOMETRIES
    }
    aggregate_guard_results = {
        guard_id: _aggregate_guard_result(
            guard_id, contract, baseline, candidate
        )
        for guard_id, contract in registry.items()
    }

    position_baseline = [
        float(value)
        for geometry in GEOMETRIES
        for value in baseline[geometry]["position_rmse_m"]
    ]
    position_candidate = [
        float(value)
        for geometry in GEOMETRIES
        for value in candidate[geometry]["position_rmse_m"]
    ]
    baseline_position_mean = _mean(position_baseline)
    candidate_position_mean = _mean(position_candidate)
    absolute_improvement = baseline_position_mean - candidate_position_mean
    relative_improvement = absolute_improvement / baseline_position_mean

    residual_results = {}
    for residual in ("altitude_rmse_m", "velocity_rmse_m_s"):
        geometry_results = {}
        for geometry in GEOMETRIES:
            baseline_mean = _mean(
                [float(value) for value in baseline[geometry][residual]]
            )
            candidate_mean = _mean(
                [float(value) for value in candidate[geometry][residual]]
            )
            regression = candidate_mean / baseline_mean - 1.0
            geometry_results[geometry] = {
                "baseline_mean": baseline_mean,
                "candidate_mean": candidate_mean,
                "regression_fraction": regression,
                "passed": regression <= 0.05,
            }
        aggregate_baseline = _mean(
            [
                float(value)
                for geometry in GEOMETRIES
                for value in baseline[geometry][residual]
            ]
        )
        aggregate_candidate = _mean(
            [
                float(value)
                for geometry in GEOMETRIES
                for value in candidate[geometry][residual]
            ]
        )
        aggregate_regression = aggregate_candidate / aggregate_baseline - 1.0
        residual_results[residual] = {
            "per_geometry": geometry_results,
            "aggregate": {
                "baseline_mean": aggregate_baseline,
                "candidate_mean": aggregate_candidate,
                "regression_fraction": aggregate_regression,
                "passed": aggregate_regression <= 0.05,
            },
            "passed": (
                all(item["passed"] for item in geometry_results.values())
                and aggregate_regression <= 0.05
            ),
        }

    repeat_identity = {
        geometry: _repeat_identity(candidate[geometry]) for geometry in GEOMETRIES
    }
    changed_guard_ids = sorted(
        guard_id
        for guard_id in registry
        if any(
            candidate[geometry][guard_id]
            != passing_candidate[geometry][guard_id]
            for geometry in GEOMETRIES
        )
    )
    changed_non_guard_metrics = sorted(
        metric
        for geometry in GEOMETRIES
        for metric in candidate[geometry]
        if metric not in registry
        and candidate[geometry][metric] != passing_candidate[geometry][metric]
    )
    primary_passed = (
        absolute_improvement >= 0.005
        and relative_improvement >= 0.10
        and all(
            _mean([float(value) for value in candidate[geometry]["position_rmse_m"]])
            <= _mean([float(value) for value in baseline[geometry]["position_rmse_m"]])
            for geometry in GEOMETRIES
        )
    )
    all_guards_passed = (
        all(
            result["passed"]
            for geometry_results in per_geometry_guard_results.values()
            for result in geometry_results.values()
        )
        and all(result["passed"] for result in aggregate_guard_results.values())
    )
    all_residuals_passed = all(
        result["passed"] for result in residual_results.values()
    )
    repeatable = all(item["passed"] for item in repeat_identity.values())

    return {
        "scenario": name,
        "override": override,
        "three_whole_holdout_replays_per_geometry": REPEAT_COUNT,
        "geometries": {
            geometry: {
                "baseline_repeat_outputs": baseline[geometry],
                "candidate_repeat_outputs": candidate[geometry],
                "guard_results": per_geometry_guard_results[geometry],
                "candidate_repeat_identity": repeat_identity[geometry],
            }
            for geometry in GEOMETRIES
        },
        "aggregate": {
            "baseline_position_rmse_m": baseline_position_mean,
            "candidate_position_rmse_m": candidate_position_mean,
            "absolute_position_improvement_m": absolute_improvement,
            "relative_position_improvement_fraction": relative_improvement,
            "primary_passed": primary_passed,
            "secondary_residual_results": residual_results,
            "secondary_residuals_passed": all_residuals_passed,
            "guard_results": aggregate_guard_results,
            "all_motion_safety_guards_passed": all_guards_passed,
            "repeatable": repeatable,
        },
        "changed_guard_ids": changed_guard_ids,
        "changed_non_guard_metrics": changed_non_guard_metrics,
        "promotion_oracle_passed": (
            primary_passed
            and all_residuals_passed
            and all_guards_passed
            and repeatable
        ),
    }


def build_audit(root: Path) -> dict[str, Any]:
    active_path = root / "docs/work-packages/ACTIVE.md"
    workflow_path = root / "docs/project/WORKFLOW_AND_REQUIREMENTS.md"
    r2_script_path = root / "scripts/audit_wp57_61_r2_design.py"
    r2_audit_path = (
        root
        / "missions/campaigns/sim/qualification/"
        "wp57-61-r2-design-audit-v1.json"
    )
    active_text = active_path.read_text(encoding="utf-8")
    workflow_text = workflow_path.read_text(encoding="utf-8")
    base_payload = _extract(active_text, BASE_BEGIN, BASE_END)
    r2_overlay = _extract(active_text, R2_BEGIN, R2_END)
    r2_audit = json.loads(r2_audit_path.read_text(encoding="utf-8"))
    r2_payload = dict(r2_audit)
    retained_r2_payload_sha256 = r2_payload.pop("payload_sha256", None)

    identities = {
        "base_design": {
            "expected_sha256": BASE_DESIGN_SHA256,
            "actual_sha256": hashlib.sha256(base_payload).hexdigest(),
            "expected_bytes": BASE_DESIGN_BYTES,
            "actual_bytes": len(base_payload),
        },
        "r2_overlay": {
            "expected_sha256": R2_OVERLAY_SHA256,
            "actual_sha256": hashlib.sha256(r2_overlay).hexdigest(),
            "expected_bytes": R2_OVERLAY_BYTES,
            "actual_bytes": len(r2_overlay),
        },
        "r2_audit_script": {
            "expected_sha256": R2_AUDIT_SCRIPT_SHA256,
            "actual_sha256": _sha256(r2_script_path),
        },
        "r2_audit_file": {
            "expected_sha256": R2_AUDIT_FILE_SHA256,
            "actual_sha256": _sha256(r2_audit_path),
        },
        "r2_audit_payload": {
            "expected_sha256": R2_AUDIT_PAYLOAD_SHA256,
            "retained_sha256": retained_r2_payload_sha256,
            "recomputed_sha256": _canonical_sha256(r2_payload),
        },
        "workflow": {
            "expected_sha256": WORKFLOW_SHA256,
            "actual_sha256": _sha256(workflow_path),
        },
    }
    for name, identity in identities.items():
        if name == "r2_audit_payload":
            identity["passed"] = (
                identity["retained_sha256"]
                == identity["expected_sha256"]
                == identity["recomputed_sha256"]
            )
        else:
            identity["passed"] = (
                identity["actual_sha256"] == identity["expected_sha256"]
                and identity.get("actual_bytes", identity.get("expected_bytes"))
                == identity.get("expected_bytes", identity.get("actual_bytes"))
            )

    retained_r2_registry = r2_audit["calibration_oracle"][
        "motion_safety_guard_registry"
    ]
    registry = {
        guard_id: retained_r2_registry[guard_id] for guard_id in R2_GUARD_IDS
    }
    registry.update(ADDITIONAL_GUARDS)
    guard_ids = tuple(registry)

    pass_geometries = r2_audit["calibration_oracle"]["pass"]["geometries"]
    baseline = {
        geometry: copy.deepcopy(pass_geometries[geometry]["baseline_repeat_outputs"])
        for geometry in GEOMETRIES
    }
    passing_candidate = {
        geometry: copy.deepcopy(pass_geometries[geometry]["candidate_repeat_outputs"])
        for geometry in GEOMETRIES
    }
    for geometry in GEOMETRIES:
        for guard_id, value in NEW_BASELINE_VALUES[geometry].items():
            baseline[geometry][guard_id] = [value] * REPEAT_COUNT
        for guard_id, value in NEW_PASS_VALUES[geometry].items():
            passing_candidate[geometry][guard_id] = [value] * REPEAT_COUNT

    r2_isolated = r2_audit["calibration_oracle"][
        "isolated_motion_safety_guard_failures"
    ]
    isolated_failure_inputs: dict[str, tuple[str, float | int | bool]] = {}
    for guard_id in R2_GUARD_IDS:
        values = r2_isolated[guard_id]["geometries"]["straight"][
            "candidate_repeat_outputs"
        ][guard_id]
        if len(set(values)) != 1:
            raise ValueError(f"R2 isolated fixture is not repeatable: {guard_id}")
        isolated_failure_inputs[guard_id] = ("straight", values[0])
    isolated_failure_inputs.update(NEW_ISOLATED_FAILURES)

    pass_scenario = _scenario(
        "pass", registry, baseline, passing_candidate
    )
    isolated_failures = {
        guard_id: _scenario(
            f"fail_guard.{guard_id}",
            registry,
            baseline,
            passing_candidate,
            override=(guard_id, geometry, value),
        )
        for guard_id, (geometry, value) in isolated_failure_inputs.items()
    }
    additional_clause_failures = {
        scenario_id: _scenario(
            f"fail_clause.{scenario_id}",
            registry,
            baseline,
            passing_candidate,
            override=(guard_id, geometry, value),
        )
        for scenario_id, (
            guard_id,
            geometry,
            value,
        ) in ADDITIONAL_BINDING_CLAUSE_FAILURES.items()
    }

    declaration_rows = []
    declaration_categories: set[str] = set()
    for probe in DECLARATION_PROBES:
        if probe["source"] == "base_design":
            source_text = base_payload.decode()
        elif probe["source"] == "composite_design":
            source_text = base_payload.decode() + "\n" + r2_overlay.decode()
        else:
            source_text = workflow_text
        token_results = {token: token in source_text for token in probe["tokens"]}
        declaration_categories.update(probe["categories"])
        declaration_rows.append(
            {
                "source": probe["source"],
                "tokens": token_results,
                "categories": probe["categories"],
                "passed": all(token_results.values()),
            }
        )

    mapped_metrics = [
        metric
        for metrics in SEMANTIC_GUARD_COVERAGE.values()
        for metric in metrics
    ]
    metric_counts = Counter(mapped_metrics)
    category_guard_closure = {
        "expected_categories": EXPECTED_SEMANTIC_CATEGORIES,
        "derived_categories": tuple(
            category
            for category in EXPECTED_SEMANTIC_CATEGORIES
            if category in declaration_categories
        ),
        "declaration_probes": declaration_rows,
        "semantic_guard_coverage": SEMANTIC_GUARD_COVERAGE,
        "guard_registry_ids": guard_ids,
        "metric_definitions": METRIC_DEFINITIONS,
        "every_category_derived": declaration_categories
        == set(EXPECTED_SEMANTIC_CATEGORIES),
        "every_metric_mapped_once": (
            set(metric_counts) == set(guard_ids)
            and all(count == 1 for count in metric_counts.values())
        ),
        "definition_set_exact": set(METRIC_DEFINITIONS) == set(guard_ids),
        "r2_registry_set_exact": set(retained_r2_registry) == set(R2_GUARD_IDS),
        "new_registry_set_exact": set(ADDITIONAL_GUARDS)
        == set(NEW_BASELINE_VALUES["straight"])
        == set(NEW_BASELINE_VALUES["curve"])
        == set(NEW_PASS_VALUES["straight"])
        == set(NEW_PASS_VALUES["curve"])
        == set(NEW_ISOLATED_FAILURES),
    }
    category_guard_closure["passed"] = (
        all(row["passed"] for row in declaration_rows)
        and category_guard_closure["every_category_derived"]
        and category_guard_closure["every_metric_mapped_once"]
        and category_guard_closure["definition_set_exact"]
        and category_guard_closure["r2_registry_set_exact"]
        and category_guard_closure["new_registry_set_exact"]
    )

    isolated_checks = {
        guard_id: _isolated_scenario_check(guard_id, scenario)
        for guard_id, scenario in isolated_failures.items()
    }
    additional_clause_checks = {
        scenario_id: _isolated_scenario_check(guard_id, scenario)
        for scenario_id, scenario in additional_clause_failures.items()
        for guard_id, _, _ in [ADDITIONAL_BINDING_CLAUSE_FAILURES[scenario_id]]
    }

    binding_clause_witnesses = []
    for guard_id, geometry, expected_clause, scenario_reference in BINDING_CLAUSE_WITNESSES:
        if scenario_reference == "metric":
            scenario = isolated_failures[guard_id]
            isolation_check = isolated_checks[guard_id]
            scenario_id = f"fail_guard.{guard_id}"
        else:
            scenario = additional_clause_failures[scenario_reference]
            isolation_check = additional_clause_checks[scenario_reference]
            scenario_id = f"fail_clause.{scenario_reference}"
        clause_state = _guard_clause_state(
            guard_id, registry[guard_id], scenario, geometry
        )
        if expected_clause == "HARD_ONLY":
            clause_isolated = (
                clause_state["hard_passed"] is False
                and clause_state["regression_passed"] is True
            )
        elif expected_clause == "REGRESSION_ONLY":
            clause_isolated = (
                clause_state["hard_passed"] is True
                and clause_state["regression_passed"] is False
            )
        elif expected_clause == "EXACT_ONLY":
            clause_isolated = (
                clause_state["hard_passed"] is False
                and clause_state["regression_passed"] is None
            )
        else:  # pragma: no cover - exact frozen witness grammar
            raise ValueError(f"unknown binding clause: {expected_clause}")
        binding_clause_witnesses.append(
            {
                "guard_id": guard_id,
                "geometry": geometry,
                "expected_clause": expected_clause,
                "scenario_id": scenario_id,
                "clause_state": clause_state,
                "isolated_scenario_passed": isolation_check["passed"],
                "clause_isolated": clause_isolated,
                "passed": isolation_check["passed"] and clause_isolated,
            }
        )

    witness_counts = Counter(item["guard_id"] for item in binding_clause_witnesses)
    binding_clause_coverage = {
        "canonical_predecessor_semantics": (
            "For a conjunctive hard-plus-regression relation, the binding clause is "
            "the tighter canonical predecessor boundary. The other clause is "
            "logically dominated for this exact frozen baseline. The continuous "
            "guard has different straight and curve thresholds, so both branches "
            "are independently witnessed."
        ),
        "witnesses": binding_clause_witnesses,
        "guard_coverage_exact": set(witness_counts) == set(guard_ids),
        "one_witness_per_guard_except_two_continuous_branches": (
            witness_counts["minimum_continuous_knot_speed_ratio"] == 2
            and all(
                count == 1
                for guard_id, count in witness_counts.items()
                if guard_id != "minimum_continuous_knot_speed_ratio"
            )
        ),
        "every_witness_passed": all(
            item["passed"] for item in binding_clause_witnesses
        ),
    }
    binding_clause_coverage["passed"] = all(
        value
        for key, value in binding_clause_coverage.items()
        if key not in {"canonical_predecessor_semantics", "witnesses"}
    )

    checks = {
        "all_predecessor_and_workflow_identities_passed": all(
            item["passed"] for item in identities.values()
        ),
        "category_guard_universe_closed": category_guard_closure["passed"],
        "complete_pass_vector_accepted": pass_scenario["promotion_oracle_passed"],
        "all_22_guards_have_one_isolated_rejection": (
            len(guard_ids) == 22
            and set(isolated_failures) == set(guard_ids)
            and all(item["passed"] for item in isolated_checks.values())
        ),
        "all_8_additional_clause_scenarios_are_isolated_rejections": (
            len(additional_clause_failures) == 8
            and set(additional_clause_failures)
            == set(ADDITIONAL_BINDING_CLAUSE_FAILURES)
            and all(item["passed"] for item in additional_clause_checks.values())
        ),
        "every_independently_binding_clause_has_sensitive_witness": (
            binding_clause_coverage["passed"]
        ),
        "all_pass_vectors_have_three_repeat_outputs_for_both_geometries": all(
            len(values) == REPEAT_COUNT
            for geometry in GEOMETRIES
            for values in pass_scenario["geometries"][geometry][
                "candidate_repeat_outputs"
            ].values()
        ),
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "WP-57 through WP-61 R3 complete WP-61F guard-universe audit",
        "requirements_applied": ("REQ-WFL-046", "REQ-WFL-049"),
        "frozen_identities": identities,
        "category_guard_closure": category_guard_closure,
        "calibration_oracle": {
            "repeat_count_per_geometry": REPEAT_COUNT,
            "repeat_numeric_tolerance": REPEAT_NUMERIC_TOLERANCE,
            "guard_registry": registry,
            "pass": pass_scenario,
            "isolated_guard_failures": isolated_failures,
            "isolated_guard_checks": isolated_checks,
            "additional_binding_clause_failures": additional_clause_failures,
            "additional_binding_clause_checks": additional_clause_checks,
            "binding_clause_coverage": binding_clause_coverage,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    payload["payload_sha256"] = _canonical_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    arguments = parser.parse_args()
    audit = build_audit(arguments.root)
    rendered = json.dumps(audit, indent=2, sort_keys=True) + "\n"
    if arguments.check is not None:
        if arguments.check.read_text(encoding="utf-8") != rendered:
            raise SystemExit("retained WP-57 through WP-61 R3 design audit is stale")
    elif arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    print(
        json.dumps(
            {"passed": audit["passed"], "payload_sha256": audit["payload_sha256"]},
            sort_keys=True,
        )
    )
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
