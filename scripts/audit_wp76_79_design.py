from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = (
    ROOT / "missions/campaigns/sim/qualification/wp76-79-design-audit-v1.json"
)
PACKETS = (
    {
        "packet_id": "WP-76",
        "title": "Region-native terminal capture and landing handoff",
        "dependencies": [],
        "minimum_value": (
            "A fresh pose already inside the admitted landing region descends from "
            "that accepted XY without a center-seeking alignment phase."
        ),
    },
    {
        "packet_id": "WP-77",
        "title": "Outcome, evidence-completeness, and motion-quality truth",
        "dependencies": ["WP-76"],
        "minimum_value": (
            "Mission completion, evidence completeness, and motion quality are "
            "reported independently and never collapsed into one success label."
        ),
    },
    {
        "packet_id": "WP-78",
        "title": "Recovery and dynamic-replanning catalog truth",
        "dependencies": ["WP-77"],
        "minimum_value": (
            "Legacy demonstrations remain immutable history while successor entries "
            "are grouped and named only for behavior they actually execute."
        ),
    },
    {
        "packet_id": "WP-79",
        "title": "Post-boundary 1D qualification and operator handoff",
        "dependencies": ["WP-76", "WP-77", "WP-78"],
        "minimum_value": (
            "A small fresh matrix proves the new implementation generation without "
            "using any Old run as baseline, prerequisite, or comparison evidence."
        ),
    },
)

CLAIMS = (
    {
        "claim_id": "region_native_landing_handoff_accelerated",
        "packet_id": "WP-76",
        "execution_boundary": "PRODUCTION_ENTRY",
        "environment": "FAST_SIM",
        "clock_evidence": "ACCELERATED",
        "trigger": (
            "POST /campaign/runs -> CampaignService.run_active -> "
            "FastSimCampaignExecutor -> FleetCoordinator -> MissionRunner -> "
            "ScriptMission -> MissionContext.capture_and_land -> "
            "SafetySupervisor.land -> LandCommand -> SimulatedVehicle._land -> "
            "MissionResult -> MissionResultPayload -> EvidenceRecorder -> "
            "EvidenceStore -> mission evaluation -> campaign analyzer/review"
        ),
        "observation": (
            "capture attempt, commanded descent target, alignment duration, "
            "source-clock telemetry, contact, and terminal region error"
        ),
        "independent_oracle": (
            "reconstruct capture-to-command XY displacement from retained mission "
            "intent/evidence and independently inspect landing-phase telemetry"
        ),
        "counterexample": (
            "rename the goal, capture exactly on the inclusive boundary, exceed the "
            "boundary by 1e-6 m, and exceed maximum capture speed by 1e-6 m/s"
        ),
    },
    {
        "claim_id": "region_native_landing_handoff_realtime",
        "packet_id": "WP-76",
        "execution_boundary": "PRODUCTION_ENTRY",
        "environment": "FAST_SIM",
        "clock_evidence": "OBSERVED_REALTIME",
        "trigger": (
            "POST /campaign/runs in OPERATOR_OBSERVED_REALTIME mode through the same "
            "API, service, executor, mission, supervisor, simulator, recorder, store, "
            "evaluation, analyzer, and review path"
        ),
        "observation": (
            "source/receive clocks, capture attempt, descent target, alignment "
            "duration, contact/disarm order, retained bundle, and review identity"
        ),
        "independent_oracle": (
            "reconstruct capture-to-command XY from the retained bundle and inspect "
            "source-time landing telemetry without using simulator control metadata"
        ),
        "counterexample": "rename the goal and reorder the selected catalog variant",
    },
    {
        "claim_id": "orthogonal_run_verdicts",
        "packet_id": "WP-77",
        "execution_boundary": "PRODUCTION_ENTRY",
        "environment": "FAST_SIM",
        "clock_evidence": "ACCELERATED",
        "trigger": "retained bundle -> campaign analyzer -> API -> Campaign Lab review",
        "observation": (
            "execution disposition, evaluator completeness, every motion-quality "
            "component, and exact failure reasons"
        ),
        "independent_oracle": (
            "recompute terminal and quality gates from exact CSV and immutable contracts"
        ),
        "counterexample": (
            "a completed mission with terminal flutter and an incomplete bundle must "
            "remain completed, quality-failed, and evidence-incomplete respectively"
        ),
    },
    {
        "claim_id": "truthful_replanning_catalog",
        "packet_id": "WP-78",
        "execution_boundary": "PRODUCTION_ENTRY",
        "environment": "NO_RUNTIME",
        "clock_evidence": "NOT_APPLICABLE",
        "trigger": "versioned curriculum grouping -> catalog service -> Campaign Lab",
        "observation": (
            "immutable case identity, execution status, behavior-driving event, "
            "runtime path, and predecessor relationship"
        ),
        "independent_oracle": (
            "semantic fingerprint plus retained runtime event/cutover/fallback evidence"
        ),
        "counterexample": (
            "rename/reorder entries and remove the event; names must not preserve "
            "dynamic or recovery qualification"
        ),
    },
    {
        "claim_id": "fresh_1d_generation_qualification_accelerated",
        "packet_id": "WP-79",
        "execution_boundary": "PRODUCTION_ENTRY",
        "environment": "FAST_SIM",
        "clock_evidence": "ACCELERATED",
        "trigger": "explicit bounded qualifier -> ordinary campaign runtime -> retained bundle",
        "observation": (
            "new run IDs, revision boundary, exact inputs, repeated terminal metrics, "
            "and Old/current eligibility"
        ),
        "independent_oracle": (
            "standalone manifest reconciliation and exact-CSV terminal reconstruction"
        ),
        "counterexample": (
            "including one superseded run, a different locked input, or an unmatched "
            "identity must fail the matrix"
        ),
    },
    {
        "claim_id": "fresh_1d_generation_qualification_realtime",
        "packet_id": "WP-79",
        "execution_boundary": "PRODUCTION_ENTRY",
        "environment": "FAST_SIM",
        "clock_evidence": "OBSERVED_REALTIME",
        "trigger": (
            "fixed realtime row in the bounded qualifier -> POST /campaign/runs -> "
            "ordinary retained campaign runtime and review bundle"
        ),
        "observation": (
            "exact fixed row identity, source/receive clocks, terminal handoff, and "
            "Old/current eligibility"
        ),
        "independent_oracle": (
            "standalone manifest reconciliation and exact-CSV source-time reconstruction"
        ),
        "counterexample": "substitute an accelerated run or one superseded run",
    },
)

NUMERIC_WITNESSES = (
    {
        "id": "accepted_offset_capture",
        "center_x_m": 1.35,
        "capture_x_m": 1.30,
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.10,
        "expected_descent_target_x_m": 1.30,
        "maximum_commanded_capture_to_descent_xy_m": 1e-9,
        "descent_authorized": True,
    },
    {
        "id": "inclusive_region_edge",
        "center_x_m": 1.35,
        "capture_x_m": 1.45,
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.10,
        "descent_authorized": True,
    },
    {
        "id": "outside_region_rejected_without_correction",
        "center_x_m": 1.35,
        "capture_x_m": 1.450001,
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.10,
        "descent_authorized": False,
    },
    {
        "id": "overspeed_capture_rejected",
        "center_x_m": 1.35,
        "capture_x_m": 1.30,
        "horizontal_tolerance_m": 0.10,
        "maximum_capture_speed_m_s": 0.10,
        "observed_speed_m_s": 0.100001,
        "descent_authorized": False,
    },
)

SAFETY_WITNESSES = (
    {
        "id": "invalid_observation",
        "observation_valid": False,
        "source_age_s": 0.0,
        "freshness_limit_s": 0.25,
        "descent_authorized": False,
    },
    {
        "id": "stale_observation",
        "observation_valid": True,
        "source_age_s": 0.250001,
        "freshness_limit_s": 0.25,
        "descent_authorized": False,
    },
    {
        "id": "wrong_landing_z",
        "goal_z_m": 0.0,
        "command_z_m": 0.000001,
        "command_valid": False,
    },
    {
        "id": "unsafe_correction_outside_flight_volume",
        "flight_max_x_m": 1.8,
        "correction_target_x_m": 1.800001,
        "correction_admitted": False,
    },
    {
        "id": "contact_before_disarm",
        "contact_source_s": 8.0,
        "disarm_source_s": 8.1,
        "order_valid": True,
    },
    {
        "id": "disarm_before_contact",
        "contact_source_s": 8.0,
        "disarm_source_s": 7.999999,
        "order_valid": False,
    },
    {
        "id": "declared_point_diversion",
        "diversion_x_m": 0.25,
        "command_x_m": 0.25,
        "command_valid": True,
    },
    {
        "id": "off_point_diversion",
        "diversion_x_m": 0.25,
        "command_x_m": 0.249999,
        "command_valid": False,
    },
)

LEGACY_LIFECYCLE = (
    ("abort_and_land_goal_fallback", "HISTORICAL_PROJECTION"),
    ("blocked_replan", "HISTORICAL_PROJECTION"),
    ("duplicate_stale_goal_update", "HISTORICAL_PROJECTION"),
    ("failure_recovery", "HISTORICAL_PROJECTION"),
    ("mid_route_goal_replacement", "HISTORICAL_PROJECTION"),
    ("online_obstacle_replan", "HISTORICAL_PROJECTION"),
    ("operator_approval_goal_replacement", "HISTORICAL_PROJECTION"),
    ("planning_budget_expiry", "HISTORICAL_PROJECTION"),
)

QUALIFICATION_ROWS = (
    ("flight-a1", "1d.takeoff_hover_land.canonical_nominal", "ACCELERATED", 1),
    ("flight-a2", "1d.takeoff_hover_land.canonical_nominal", "ACCELERATED", 2),
    ("flight-a3", "1d.takeoff_hover_land.canonical_nominal", "ACCELERATED", 3),
    ("target-a1", "1d.point_to_point_relocation.canonical_nominal", "ACCELERATED", 1),
    ("level-path-a1", "1d.continuous_waypoint_sequence.canonical_nominal", "ACCELERATED", 1),
    ("3d-path-a1", "1d.altitude_transition.canonical_nominal", "ACCELERATED", 1),
    ("shape-a1", "1d.planar_shape_loop.circle", "ACCELERATED", 1),
    ("flight-r1", "1d.takeoff_hover_land.canonical_nominal", "OBSERVED_REALTIME", 1),
)

REQUIREMENTS = (
    "REQ-EVI-003",
    "REQ-EVI-004",
    "REQ-EVI-005",
    "REQ-EVI-007",
    "REQ-EVI-011",
    "REQ-EVI-013",
    "REQ-MIS-001",
    "REQ-MIS-003",
    "REQ-MIS-009",
    "REQ-MIS-010",
    "REQ-MOT-010",
    "REQ-MOT-011",
    "REQ-RPL-006",
    "REQ-RPL-009",
    "REQ-WFL-014",
    "REQ-WFL-017",
    "REQ-WFL-018",
    "REQ-WFL-020",
    "REQ-WFL-023",
    "REQ-WFL-028",
    "REQ-WFL-029",
    "REQ-WFL-034",
    "REQ-WFL-036",
    "REQ-WFL-039",
    "REQ-WFL-042",
    "REQ-WFL-046",
    "REQ-WFL-047",
    "REQ-WFL-052",
    "REQ-WFL-053",
)

IMPLEMENT_NOW = {
    "docs/project/requirements/EVIDENCE_AND_REVIEW.md",
    "docs/reference/LANDING_GOAL_REGION_V1.md",
    "src/crazyswarm_app/domain/commands.py",
    "src/crazyswarm_app/domain/goals.py",
    "src/crazyswarm_app/missions/base.py",
    "src/crazyswarm_app/simulation/vehicle.py",
    "tests/api/test_campaign.py",
    "tests/missions/test_trajectory_execution.py",
}

PLANNED_LATER = {
    "missions/campaigns/sim/cases/failure-recovery-and-replanning/1d-cases-v1.yaml",
    "missions/campaigns/sim/curriculum/1d-major-missions-v1.yaml",
    "missions/campaigns/sim/cases/dynamic-replanning/1d-cases-v1.yaml",
    "scripts/generate_campaign_catalog.py",
    "scripts/summarize_run.py",
    "src/crazyswarm_app/campaign/analyzer.py",
    "src/crazyswarm_app/campaign/api_models.py",
    "src/crazyswarm_app/campaign/catalog.py",
    "src/crazyswarm_app/campaign/models.py",
    "src/crazyswarm_app/campaign/service.py",
    "tests/campaign/test_major_mission_curriculum.py",
    "tests/campaign/test_motion_quality_contract.py",
    "ui/app/components/CampaignLab.tsx",
    "ui/tests/campaign-lab.test.tsx",
}

PRODUCTION_TRANSIT_PATHS = {
    "src/crazyswarm_app/api/app.py",
    "src/crazyswarm_app/api/runtime.py",
    "src/crazyswarm_app/campaign/analyzer.py",
    "src/crazyswarm_app/campaign/runtime_executor.py",
    "src/crazyswarm_app/campaign/service.py",
    "src/crazyswarm_app/domain/commands.py",
    "src/crazyswarm_app/domain/goals.py",
    "src/crazyswarm_app/fleet/coordinator.py",
    "src/crazyswarm_app/missions/base.py",
    "src/crazyswarm_app/missions/models.py",
    "src/crazyswarm_app/missions/runner.py",
    "src/crazyswarm_app/missions/script.py",
    "src/crazyswarm_app/observability/bridge.py",
    "src/crazyswarm_app/observability/evaluation.py",
    "src/crazyswarm_app/observability/events.py",
    "src/crazyswarm_app/observability/recorder.py",
    "src/crazyswarm_app/observability/storage.py",
    "src/crazyswarm_app/safety/supervisor.py",
    "src/crazyswarm_app/simulation/vehicle.py",
}

LEGACY_PROJECTION_PATHS = {
    f"missions/library/one_drone/{family}/mission.py" for family, _ in LEGACY_LIFECYCLE
}

TRANSIT_TOKENS = (
    "LandingGoalRegion",
    "LandCommand",
    "capture_and_land",
    "GoalCaptureRecord",
    "all_required_behavior_oracles_passed",
    "DYNAMIC_REPLANNING",
    "FAILURE_RECOVERY_AND_REPLANNING",
    "1d-major-missions-v1",
    "superseded_at_utc",
    "MissionResultPayload",
    "EvidenceStore",
    "FastSimCampaignExecutor",
    "online_obstacle_replan",
    "failure_recovery",
    "blocked_replan",
    "planning_budget_expiry",
)

SCAN_ROOTS = (
    ROOT / "src/crazyswarm_app",
    ROOT / "tests/missions",
    ROOT / "tests/campaign",
    ROOT / "ui/app",
    ROOT / "ui/tests",
    ROOT / "missions/campaigns/sim/curriculum",
    ROOT / "missions/campaigns/sim/cases/dynamic-replanning",
    ROOT / "missions/campaigns/sim/cases/failure-recovery-and-replanning",
    ROOT / "missions/library/one_drone",
    ROOT / "scripts",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_boundaries() -> set[str]:
    discovered: set[str] = set()
    for scan_root in SCAN_ROOTS:
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".yaml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(token in text for token in TRANSIT_TOKENS):
                discovered.add(str(path.relative_to(ROOT)))
    return discovered


def classification(path: str) -> str:
    if path in IMPLEMENT_NOW:
        return "IMPLEMENTATION_OWNED"
    if path in PLANNED_LATER or path in LEGACY_PROJECTION_PATHS:
        return "PLANNED_LATER"
    return "RELIED_UPON_UNCHANGED"


def evaluate_numeric_witness(item: dict[str, object]) -> dict[str, object]:
    center_x = float(item["center_x_m"])
    capture_x = float(item["capture_x_m"])
    tolerance = float(item["horizontal_tolerance_m"])
    observed_speed = float(item["observed_speed_m_s"])
    maximum_speed = float(item["maximum_capture_speed_m_s"])
    authorized = (
        abs(capture_x - center_x) <= tolerance + 1e-12
        and observed_speed <= maximum_speed + 1e-12
    )
    return {
        "descent_authorized": authorized,
        "descent_target_x_m": capture_x if authorized else None,
        "commanded_capture_to_descent_xy_m": 0.0 if authorized else None,
    }


def evaluate_safety_witness(item: dict[str, object]) -> bool:
    witness_id = str(item["id"])
    if witness_id in {"invalid_observation", "stale_observation"}:
        return bool(item["observation_valid"]) and float(item["source_age_s"]) <= float(
            item["freshness_limit_s"]
        )
    if witness_id == "wrong_landing_z":
        return abs(float(item["goal_z_m"]) - float(item["command_z_m"])) <= 1e-9
    if witness_id == "unsafe_correction_outside_flight_volume":
        return float(item["correction_target_x_m"]) <= float(item["flight_max_x_m"])
    if witness_id in {"contact_before_disarm", "disarm_before_contact"}:
        return float(item["contact_source_s"]) <= float(item["disarm_source_s"])
    if witness_id in {"declared_point_diversion", "off_point_diversion"}:
        return abs(float(item["diversion_x_m"]) - float(item["command_x_m"])) <= 1e-9
    raise ValueError(f"unknown safety witness: {witness_id}")


def build_artifact() -> dict[str, object]:
    discovered = discover_boundaries()
    boundary_paths = sorted(
        discovered
        | IMPLEMENT_NOW
        | PLANNED_LATER
        | PRODUCTION_TRANSIT_PATHS
        | LEGACY_PROJECTION_PATHS
    )
    boundaries = []
    for relative in boundary_paths:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(relative)
        boundaries.append(
            {
                "path": relative,
                "classification": classification(relative),
                "preimage_sha256": sha256(path),
            }
        )
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "schema_version": 1,
        "batch_id": "WP-76-through-WP-79",
        "base_commit": base_commit,
        "originating_requests": [
            (
                "Analyze all 1D runs; investigate the shaky end that appears to "
                "snap into the goal; mark all analyzed 1D runs Old; and correct the "
                "misleadingly easy recovery/replanning missions, old Python files, "
                "and catalog grouping."
            ),
            "ok then what do you recommend to fix this?",
            "ok then now structure work packets for this and do one iteration on the implementation",
        ],
        "packets": PACKETS,
        "claims": CLAIMS,
        "numeric_witnesses": NUMERIC_WITNESSES,
        "numeric_witness_results": [
            {"id": item["id"], **evaluate_numeric_witness(item)}
            for item in NUMERIC_WITNESSES
        ],
        "safety_witnesses": SAFETY_WITNESSES,
        "safety_witness_results": [
            {"id": item["id"], "result": evaluate_safety_witness(item)}
            for item in SAFETY_WITNESSES
        ],
        "legacy_lifecycle_inventory": [
            {
                "family": family,
                "path": f"missions/library/one_drone/{family}/mission.py",
                "disposition": disposition,
            }
            for family, disposition in LEGACY_LIFECYCLE
        ],
        "qualification_matrix": [
            {
                "row_id": row_id,
                "case_id": case_id,
                "execution_profile_submission_id": "planner_retained_baseline",
                "planning_submission_id": "case_planning_authority",
                "clock_evidence": clock,
                "repeat_index": repeat_index,
            }
            for row_id, case_id, clock, repeat_index in QUALIFICATION_ROWS
        ],
        "qualification_guards": {
            "per_row": {
                "execution_status": "SUCCEEDED",
                "evidence_complete": True,
                "maximum_capture_to_descent_xy_m": 1e-9,
                "alignment_duration_s": 0.0,
                "minimum_terminal_region_margin_m": 0.0,
                "terminal_contact": "SIMULATED_GROUND_CONTACT",
                "contact_must_precede_disarm": True,
                "all_required_behavior_oracles_passed": True,
                "old_run_eligible": False,
            },
            "accelerated_flight_repeat_set": {
                "row_ids": ["flight-a1", "flight-a2", "flight-a3"],
                "maximum_truth_path_length_difference_m": 0.10,
                "maximum_tracking_rms_difference_m": 0.02,
                "exact_equal_fields": [
                    "case_sha256",
                    "execution_profile_submission_sha256",
                    "planning_submission_sha256",
                    "resolved_planning_package_sha256",
                ],
            },
            "aggregate": {
                "required_row_count": 8,
                "required_pass_count": 8,
                "post_result_row_selection_allowed": False,
            },
        },
        "requirements": REQUIREMENTS,
        "transit_tokens": TRANSIT_TOKENS,
        "production_transit_paths": sorted(PRODUCTION_TRANSIT_PATHS),
        "discovered_boundary_paths": sorted(discovered),
        "boundaries": boundaries,
        "iteration_scope": {
            "implement_now": ["WP-76"],
            "design_only": ["WP-77", "WP-78", "WP-79"],
        },
        "intended_new_paths": [
            "scripts/qualify_wp76_79.py",
            "missions/campaigns/sim/qualification/wp76-79-runtime-qualification-v1.json",
        ],
    }


def validate(data: dict[str, object], artifact: Path) -> list[str]:
    errors: list[str] = []
    packet_ids = tuple(item.get("packet_id") for item in data.get("packets", []))
    expected_packet_ids = tuple(item["packet_id"] for item in PACKETS)
    if packet_ids != expected_packet_ids:
        errors.append(f"packet order/set mismatch: {packet_ids!r}")
    claims = data.get("claims", [])
    claim_ids = [item.get("claim_id") for item in claims]
    if len(claim_ids) != len(set(claim_ids)) or {
        item.get("packet_id") for item in claims
    } != set(expected_packet_ids):
        errors.append("claim identity or packet coverage mismatch")
    for item in claims:
        if item.get("execution_boundary") not in {
            "MODEL_ONLY",
            "COMPONENT",
            "INTEGRATION",
            "PRODUCTION_ENTRY",
        }:
            errors.append(f"invalid execution boundary: {item.get('claim_id')}")
        if item.get("environment") not in {
            "NO_RUNTIME",
            "FAST_SIM",
            "LIVE_ISAAC",
            "HARDWARE",
        }:
            errors.append(f"invalid environment: {item.get('claim_id')}")
        if item.get("clock_evidence") not in {
            "NOT_APPLICABLE",
            "ACCELERATED",
            "OBSERVED_REALTIME",
        }:
            errors.append(f"invalid clock evidence: {item.get('claim_id')}")
    witnesses = data.get("numeric_witnesses", [])
    if len(witnesses) != len({item.get("id") for item in witnesses}):
        errors.append("numeric witness IDs are not unique")
    numeric_results = {
        item.get("id"): item for item in data.get("numeric_witness_results", [])
    }
    for item in witnesses:
        observed = evaluate_numeric_witness(item)
        retained = numeric_results.get(item.get("id"))
        if retained is None or any(retained.get(key) != value for key, value in observed.items()):
            errors.append(f"numeric witness result mismatch: {item.get('id')}")
        if retained is not None and retained.get("descent_authorized") != item.get(
            "descent_authorized"
        ):
            errors.append(f"numeric authority expectation mismatch: {item.get('id')}")
        if "expected_descent_target_x_m" in item and retained is not None:
            if retained.get("descent_target_x_m") != item.get("expected_descent_target_x_m"):
                errors.append(f"numeric descent target mismatch: {item.get('id')}")
        if "maximum_commanded_capture_to_descent_xy_m" in item and retained is not None:
            delta = retained.get("commanded_capture_to_descent_xy_m")
            if not isinstance(delta, (float, int)) or delta > float(
                item["maximum_commanded_capture_to_descent_xy_m"]
            ):
                errors.append(f"numeric no-snap witness failed: {item.get('id')}")
    safety_witnesses = data.get("safety_witnesses", [])
    safety_results = {
        item.get("id"): item.get("result")
        for item in data.get("safety_witness_results", [])
    }
    for item in safety_witnesses:
        observed = evaluate_safety_witness(item)
        retained = safety_results.get(item.get("id"))
        expected = next(
            (
                item[key]
                for key in (
                    "descent_authorized",
                    "command_valid",
                    "correction_admitted",
                    "order_valid",
                )
                if key in item
            ),
            None,
        )
        if retained != observed or observed != expected:
            errors.append(f"safety witness mismatch: {item.get('id')}")
    lifecycle = data.get("legacy_lifecycle_inventory", [])
    expected_lifecycle = {
        (family, f"missions/library/one_drone/{family}/mission.py", disposition)
        for family, disposition in LEGACY_LIFECYCLE
    }
    observed_lifecycle = {
        (item.get("family"), item.get("path"), item.get("disposition"))
        for item in lifecycle
    }
    if observed_lifecycle != expected_lifecycle or len(lifecycle) != len(expected_lifecycle):
        errors.append("legacy lifecycle inventory mismatch")
    matrix = data.get("qualification_matrix", [])
    expected_matrix = {
        (row_id, case_id, clock, repeat_index)
        for row_id, case_id, clock, repeat_index in QUALIFICATION_ROWS
    }
    observed_matrix = {
        (
            item.get("row_id"),
            item.get("case_id"),
            item.get("clock_evidence"),
            item.get("repeat_index"),
        )
        for item in matrix
    }
    if observed_matrix != expected_matrix or len(matrix) != len(expected_matrix):
        errors.append("qualification matrix mismatch")
    for item in matrix:
        if item.get("execution_profile_submission_id") != "planner_retained_baseline":
            errors.append(f"execution submission mismatch: {item.get('row_id')}")
        if item.get("planning_submission_id") != "case_planning_authority":
            errors.append(f"planning submission mismatch: {item.get('row_id')}")
    discovered = discover_boundaries()
    if set(data.get("discovered_boundary_paths", [])) != discovered:
        errors.append("transit-symbol discovery changed after the design freeze")
    boundaries = data.get("boundaries", [])
    paths = [item.get("path") for item in boundaries]
    expected_paths = (
        discovered
        | IMPLEMENT_NOW
        | PLANNED_LATER
        | PRODUCTION_TRANSIT_PATHS
        | LEGACY_PROJECTION_PATHS
    )
    if set(paths) != expected_paths or len(paths) != len(set(paths)):
        errors.append("boundary manifest is not mechanically closed")
    for item in boundaries:
        relative = item.get("path")
        path = ROOT / str(relative)
        if not path.is_file():
            errors.append(f"missing boundary: {relative}")
            continue
        if sha256(path) != item.get("preimage_sha256"):
            errors.append(f"preimage mismatch: {relative}")
        if item.get("classification") not in {
            "IMPLEMENTATION_OWNED",
            "PLANNED_LATER",
            "RELIED_UPON_UNCHANGED",
        }:
            errors.append(f"invalid classification: {relative}")
    if set(data.get("production_transit_paths", [])) != PRODUCTION_TRANSIT_PATHS:
        errors.append("production transit path inventory mismatch")
    required = set(data.get("requirements", []))
    for requirement in (
        "REQ-EVI-005",
        "REQ-EVI-007",
        "REQ-MOT-010",
        "REQ-MIS-010",
        "REQ-WFL-034",
        "REQ-WFL-047",
        "REQ-WFL-052",
    ):
        if requirement not in required:
            errors.append(f"missing required coverage: {requirement}")
    if not artifact.is_file():
        errors.append("design artifact is missing")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", nargs="?", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    artifact = args.artifact if args.artifact.is_absolute() else ROOT / args.artifact
    if args.write:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps(build_artifact(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    data = json.loads(artifact.read_text(encoding="utf-8"))
    errors = validate(data, artifact)
    result = {
        "artifact": str(artifact.relative_to(ROOT)),
        "artifact_sha256": sha256(artifact),
        "packet_count": len(data.get("packets", [])),
        "claim_count": len(data.get("claims", [])),
        "numeric_witness_count": len(data.get("numeric_witnesses", [])),
        "safety_witness_count": len(data.get("safety_witnesses", [])),
        "legacy_lifecycle_count": len(data.get("legacy_lifecycle_inventory", [])),
        "qualification_row_count": len(data.get("qualification_matrix", [])),
        "boundary_count": len(data.get("boundaries", [])),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
