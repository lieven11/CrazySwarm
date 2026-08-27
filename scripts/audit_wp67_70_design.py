#!/usr/bin/env python3
"""Freeze and mechanically audit the WP-67 through WP-70 design inputs."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BOUNDARIES = {
    "design.md": "durable dynamic preparation UI rule",
    "docs/project/DESIGN.md": "Campaign workspace surface specification",
    "docs/system/README.md": "public preparation/runtime/evidence transit map",
    "missions/campaigns/sim/cases/dynamic-replanning/1d-cases-v1.yaml": (
        "immutable two-object source fixture and numerical geometry preimage"
    ),
    "src/crazyswarm_app/api/app.py": "preview, package-download, and run API transit",
    "src/crazyswarm_app/campaign/analyzer.py": "offline motion and root-cause analysis",
    "src/crazyswarm_app/campaign/api_models.py": "run request validation",
    "src/crazyswarm_app/campaign/corridor.py": "bounded A* objective and diagnostics",
    "src/crazyswarm_app/campaign/dynamic_obstacles.py": (
        "new hash-bound obstacle population and repeat-mode resolver"
    ),
    "src/crazyswarm_app/campaign/execution_head.py": (
        "reaction, fresh-state handoff, fallback, and retained event evidence"
    ),
    "src/crazyswarm_app/campaign/replanning.py": (
        "changed-world search, splice, clearance, and cutover certification"
    ),
    "src/crazyswarm_app/campaign/runtime_executor.py": (
        "production event materialization and retained source identity"
    ),
    "src/crazyswarm_app/campaign/scenario.py": "resolved event static admission",
    "src/crazyswarm_app/campaign/scheduling.py": "resolved last-event watchdog reserve",
    "src/crazyswarm_app/campaign/service.py": "resolved-package preparation and execution",
    "src/crazyswarm_app/campaign/submissions.py": (
        "operator controls, planning clearance, speed cap, and package hashes"
    ),
    "src/crazyswarm_app/campaign/trajectory.py": "planning-bound motion contract transit",
    "src/crazyswarm_app/campaign/planner.py": "planning-bound motion contract transit",
    "src/crazyswarm_app/observability/evaluation.py": (
        "dynamic completeness and unintended-stop evaluation"
    ),
    "tests/api/test_campaign.py": "public API contract and package identity tests",
    "tests/campaign/test_dynamic_perception_replanning.py": (
        "production dynamic execution and failure counterexamples"
    ),
    "tests/campaign/test_dynamic_preparation.py": (
        "new population, clearance, speed, repeat, and watchdog contract tests"
    ),
    "tests/campaign/test_goal_corridor.py": "gap and route-continuity boundary tests",
    "tests/campaign/test_motion_quality_contract.py": (
        "goal-seeking path-tube non-applicability tests"
    ),
    "tests/observability/test_evaluation.py": "stop and dynamic-evidence regressions",
    "ui/app/components/CampaignLab.tsx": "dynamic preparation controls",
    "ui/app/globals.css": "responsive dynamic preparation layout",
    "ui/app/lib/api.generated.ts": "generated request/response contract",
    "ui/app/lib/api.ts": "preview, download, and run client transit",
    "ui/app/lib/models.ts": "operator-facing dynamic preparation types",
    "ui/openapi.json": "generated public API schema",
    "ui/tests/campaign-lab.test.tsx": "rendered labels, interaction, and request tests",
}

CONTROL_SPEC = {
    "minimum_clearance_m": {
        "label": "Clearance",
        "minimum": 0.15,
        "maximum": 0.30,
        "default": 0.15,
        "step": 0.01,
        "unit": "m",
    },
    "obstacle_count": {
        "label": "Obstacles",
        "minimum": 1,
        "maximum": 4,
        "default": 3,
        "step": 1,
        "unit": "count",
    },
    "variation_mode": {
        "label": "Variation",
        "values": ["FIXED", "SEEDED_STRESS"],
        "default": "FIXED",
    },
    "speed_m_s": {
        "label": "Speed",
        "dynamic_safety_cap": 0.30,
        "unit": "m/s",
    },
}

CLAIMS = {
    "WP67_DYNAMIC_PREPARATION": {
        "required_boundaries": [
            "design.md",
            "docs/project/DESIGN.md",
            "src/crazyswarm_app/api/app.py",
            "src/crazyswarm_app/campaign/api_models.py",
            "src/crazyswarm_app/campaign/dynamic_obstacles.py",
            "src/crazyswarm_app/campaign/scheduling.py",
            "src/crazyswarm_app/campaign/service.py",
            "src/crazyswarm_app/campaign/submissions.py",
            "ui/app/components/CampaignLab.tsx",
            "ui/app/lib/api.ts",
            "ui/app/lib/models.ts",
        ],
    },
    "WP68_MOVING_REPLAN_CONTINUITY": {
        "required_boundaries": [
            "src/crazyswarm_app/campaign/corridor.py",
            "src/crazyswarm_app/campaign/execution_head.py",
            "src/crazyswarm_app/campaign/replanning.py",
            "src/crazyswarm_app/campaign/runtime_executor.py",
        ],
    },
    "WP69_EVALUATION_TRUTH": {
        "required_boundaries": [
            "src/crazyswarm_app/campaign/analyzer.py",
            "src/crazyswarm_app/observability/evaluation.py",
        ],
    },
    "WP70_REPRODUCIBLE_QUALIFICATION": {
        "required_boundaries": [
            "missions/campaigns/sim/cases/dynamic-replanning/1d-cases-v1.yaml",
            "src/crazyswarm_app/campaign/dynamic_obstacles.py",
            "src/crazyswarm_app/campaign/runtime_executor.py",
            "tests/campaign/test_dynamic_preparation.py",
            "tests/campaign/test_goal_corridor.py",
        ],
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jerk_limited_stop(speed_m_s: float) -> tuple[float, float]:
    maximum_acceleration_m_s2 = 1.0
    maximum_jerk_m_s3 = 8.0
    ramp_s = maximum_acceleration_m_s2 / maximum_jerk_m_s3
    ramp_velocity_delta = 0.5 * maximum_acceleration_m_s2 * ramp_s
    if speed_m_s <= 2.0 * ramp_velocity_delta:
        triangular_ramp_s = math.sqrt(speed_m_s / maximum_jerk_m_s3)
        return 2.0 * triangular_ramp_s, speed_m_s * triangular_ramp_s
    hold_s = (speed_m_s - 2.0 * ramp_velocity_delta) / maximum_acceleration_m_s2
    first_distance = (
        speed_m_s * ramp_s - maximum_jerk_m_s3 * ramp_s**3 / 6.0
    )
    first_end_speed = speed_m_s - ramp_velocity_delta
    hold_distance = (
        first_end_speed * hold_s
        - 0.5 * maximum_acceleration_m_s2 * hold_s**2
    )
    final_distance = (
        ramp_velocity_delta * ramp_s
        - 0.5 * maximum_acceleration_m_s2 * ramp_s**2
        + maximum_jerk_m_s3 * ramp_s**3 / 6.0
    )
    return 2.0 * ramp_s + hold_s, first_distance + hold_distance + final_distance


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_wp67_70_design.py OUTPUT.json")
    output_path = Path(sys.argv[1])
    preimages = {}
    for relative, owner in BOUNDARIES.items():
        path = ROOT / relative
        preimages[relative] = {
            "owner": owner,
            "state": "EXISTING" if path.exists() else "INTENDED_NEW",
            "sha256": sha256(path) if path.exists() else None,
        }
    missing_claim_boundaries = {
        claim: sorted(set(row["required_boundaries"]) - set(BOUNDARIES))
        for claim, row in CLAIMS.items()
    }

    vehicle_radius_m = 0.055
    uncertainty_m = 0.05
    planner_reserve_m = 0.05
    opening_witnesses = []
    for clearance_m in (0.15, 0.20, 0.30):
        opening_witnesses.append(
            {
                "minimum_clearance_m": clearance_m,
                "minimum_opening_m": round(
                    2.0
                    * (vehicle_radius_m + uncertainty_m + clearance_m + planner_reserve_m),
                    12,
                ),
            }
        )
    admission_threshold_m = opening_witnesses[0]["minimum_opening_m"]
    gap_witnesses = [
        {
            "gap_m": gap_m,
            "admitted": gap_m + 1e-9 >= admission_threshold_m,
        }
        for gap_m in (0.59, 0.61, 0.63)
    ]
    speed_witnesses = []
    for speed_m_s in (0.29, 0.30, 0.50):
        stop_time_s, stop_distance_m = jerk_limited_stop(speed_m_s)
        response_distance_m = speed_m_s * 0.74 + stop_distance_m
        speed_witnesses.append(
            {
                "requested_speed_m_s": speed_m_s,
                "resolved_speed_m_s": min(speed_m_s, 0.30),
                "jerk_limited_stop_time_s": stop_time_s,
                "jerk_limited_stop_distance_m": stop_distance_m,
                "complete_response_distance_m": response_distance_m,
                "required_center_to_surface_distance_m": (
                    vehicle_radius_m + uncertainty_m + 0.15 + response_distance_m
                ),
            }
        )
    population_witnesses = [
        {
            "obstacle_count": count,
            "event_count": count + 2,
            "maximum_simultaneous_obstacles": count,
            "event_ids": [
                "online-obstacle-appear-1",
                "online-obstacle-move-1",
                *[
                    f"online-obstacle-appear-{index}"
                    for index in range(2, count + 1)
                ],
                "online-obstacle-remove-1",
            ],
        }
        for count in range(1, 5)
    ]

    checks = {
        "all_claim_boundaries_declared": not any(missing_claim_boundaries.values()),
        "all_control_keys_unique": len(CONTROL_SPEC) == len(set(CONTROL_SPEC)),
        "opening_formula_exact": opening_witnesses
        == [
            {"minimum_clearance_m": 0.15, "minimum_opening_m": 0.61},
            {"minimum_clearance_m": 0.20, "minimum_opening_m": 0.71},
            {"minimum_clearance_m": 0.30, "minimum_opening_m": 0.91},
        ],
        "gap_boundary_sensitive": [row["admitted"] for row in gap_witnesses]
        == [False, True, True],
        "speed_cap_sensitive": [row["resolved_speed_m_s"] for row in speed_witnesses]
        == [0.29, 0.30, 0.30],
        "population_cardinality_exact": [row["event_count"] for row in population_witnesses]
        == [3, 4, 5, 6],
        "population_ids_unique": all(
            len(row["event_ids"]) == len(set(row["event_ids"]))
            for row in population_witnesses
        ),
    }
    payload = {
        "schema_version": 1,
        "audit_id": "wp67-70-design-audit-v1",
        "base_commit": "40cd9947f87eb9bf2719d72e7c72ea867eab9977",
        "control_spec": CONTROL_SPEC,
        "claims": CLAIMS,
        "boundary_preimages": preimages,
        "missing_claim_boundaries": missing_claim_boundaries,
        "numerical_witnesses": {
            "opening": opening_witnesses,
            "gap_boundary": gap_witnesses,
            "reaction_speed": speed_witnesses,
            "population": population_witnesses,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": payload["passed"], "checks": checks}, sort_keys=True))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
