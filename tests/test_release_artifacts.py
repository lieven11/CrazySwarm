from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, cast

from crazyswarm_app.domain.simulation import ADAPTER_CONTRACT_VERSION, canonical_sha256
from crazyswarm_app.simulation.factory import vehicles_from_scenario
from crazyswarm_app.simulation.world import load_scenario

ROOT = Path(__file__).resolve().parents[1]


def load_json(relative_path: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((ROOT / relative_path).read_text(encoding="utf-8")),
    )


def test_documentation_has_exactly_two_current_work_package_ledgers() -> None:
    ledgers = sorted(
        path.name
        for path in (ROOT / "docs/work-packages").glob("*.md")
        if "authoritative ledger" in path.read_text(encoding="utf-8")
    )
    assert ledgers == ["ACTIVE.md", "COMPLETED.md"]
    assert not (ROOT / "WorkPackets").exists()
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    assert "work-packages/ACTIVE.md" in index
    assert "work-packages/COMPLETED.md" in index
    assert "non-authoritative historical planning sources" in index
    assert (ROOT / "docs/reference/MISSION_PLAN_V1.md").is_file()
    assert (ROOT / "docs/guides/MISSION_SAFETY_GUIDE.md").is_file()
    assert (ROOT / "docs/system/PLANNING_AND_RECOVERY_PLUGINS.md").is_file()
    assert (ROOT / "docs/reference/MISSION_EXECUTION_EVALUATION_V1.md").is_file()
    assert (ROOT / "docs/qualification/MISSION_EVALUATION_WP19.md").is_file()
    assert (ROOT / "docs/reference/LANDING_GOAL_REGION_V1.md").is_file()
    assert (ROOT / "docs/qualification/GOAL_LANDING_WP21.md").is_file()
    assert (ROOT / "docs/reference/PREDICTIVE_DECONFLICTION_V1.md").is_file()
    assert (ROOT / "docs/qualification/PREDICTIVE_DECONFLICTION_WP22.md").is_file()
    assert (ROOT / "docs/reference/MISSION_CURRICULUM_V1.md").is_file()
    assert (ROOT / "docs/qualification/MISSION_CURRICULUM_WP23.md").is_file()
    assert (ROOT / "docs/reference/MULTI_DRONE_CONFLICT_PLANNING_V1.md").is_file()
    assert (ROOT / "docs/qualification/MULTI_DRONE_CONFLICT_WP24.md").is_file()
    assert (ROOT / "docs/reference/MISSION_ROBUSTNESS_MATRIX_V1.md").is_file()
    assert (ROOT / "docs/qualification/MISSION_ROBUSTNESS_WP25.md").is_file()
    assert (
        ROOT / "docs/qualification/CAMPAIGN_LAB_WP26_34_IMPLEMENTATION.md"
    ).is_file()
    assert (ROOT / "scripts/qualify_mission_robustness.py").is_file()
    assert (ROOT / "scripts/generate_campaign_catalog.py").is_file()
    active = (ROOT / "docs/work-packages/ACTIVE.md").read_text(encoding="utf-8")
    completed = (ROOT / "docs/work-packages/COMPLETED.md").read_text(encoding="utf-8")
    assert "WP-01 through WP-34 remain closed" in active
    assert "WP-35 through WP-39" in active
    assert "EXECUTION_SEMANTICS_BEFORE_CASE_COUNT" in active
    assert "Semantic truth gate and executable-case contract" in active
    assert "One-drone executable learning curriculum" in active
    assert "Two-drone executable learning curriculum" in active
    assert "Three-drone executable learning curriculum" in active
    assert "Catalog cutover, learning surface, and full qualification" in active
    assert "47 named Simulation mission families but only six distinct" in active
    assert "NVIDIA/Isaac installation" in active
    assert "not authorized by WP-35 through WP-39" in active
    assert "WP-18 — Persistent mission run files" in completed
    assert "WP-19 — Mission-execution evaluator and analysis baseline" in completed
    assert "WP-21 — Goal-region arrival and landing" in completed
    assert "WP-22 — Predictive two-drone deconfliction" in completed
    assert "WP-23 — Parameterized mission cases and curriculum" in completed
    assert "WP-24 — Scalable multi-drone conflict planning" in completed
    assert "WP-25 — Robustness qualification and higher-fidelity handoff" in completed
    assert "WP-26 — Evidence-correct analysis and timing" in completed
    assert "WP-32 — Campaign panel" in completed
    assert "WP-34 — Dynamic goals and online replanning" in completed


def test_independent_work_packet_verification_is_project_scoped_and_bounded() -> None:
    agents_text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    agents_normalized = " ".join(agents_text.split())
    assert (
        "Apply this protocol only when the user explicitly asks to create, structure, "
        "refine, implement, execute, complete, verify, qualify, or transition one or "
        "more work packets/work packages."
    ) in agents_normalized
    assert (
        "A mere mention, explanation, status question, ordinary numbered plan, or "
        "unrelated small task does not activate it."
    ) in agents_normalized
    assert (
        "If the request is design-only, stop after `DESIGN_VERIFIED`; do not "
        "implement it."
    ) in agents_normalized
    assert (
        "Do not implement a packet without a recorded `DESIGN_VERIFIED` result."
    ) in agents_normalized
    assert "Spawn a different fresh `work_packet_verifier` agent." in agents_normalized
    assert agents_normalized.count("Do not start a third automatic pass.") == 2
    assert (
        "If the independent agent, configuration, or concurrency slot is unavailable, "
        "fail closed as `REVIEW_BLOCKED` or `IMPLEMENTED_UNVERIFIED`"
    ) in agents_normalized
    assert (
        "The `work_packet_verifier` itself is exempt from triggering this protocol "
        "while reviewing and must not delegate another verifier."
    ) in agents_normalized
    assert (
        "any substantive edit invalidates the verdict."
    ) in agents_normalized
    assert "(`REQ-WFL-013` through `REQ-WFL-027`)" in agents_normalized

    verifier_path = ROOT / ".codex/agents/work-packet-verifier.toml"
    verifier = tomllib.loads(verifier_path.read_text(encoding="utf-8"))
    assert verifier["name"] == "work_packet_verifier"
    assert verifier["sandbox_mode"] == "read-only"
    assert verifier["description"]
    instructions = " ".join(verifier["developer_instructions"].split())
    for required in (
        "Do not edit files, apply fixes, mutate lifecycle state, or broaden the review "
        "scope.",
        "Do not spawn, delegate to, or request another verifier.",
        "You own finding severity and the verdict.",
        "Return exactly DESIGN_VERIFIED or BLOCKED_WITH_FINDINGS.",
        "Trace each core claim from its real trigger and production entry point through "
        "the resulting state or command change to retained observation and an "
        "independent oracle.",
        "Require an intended path and a meaningful failure/counterexample",
        "Return exactly IMPLEMENTATION_VERIFIED or BLOCKED_WITH_FINDINGS.",
    ):
        assert required in instructions

    workflow = (ROOT / "docs/project/WORKFLOW_AND_REQUIREMENTS.md").read_text(
        encoding="utf-8"
    )
    requirement_rows = {
        columns[1].strip(" `"): " ".join(columns[2].split())
        for line in workflow.splitlines()
        if line.startswith("| `REQ-WFL-")
        and len(columns := line.split("|")) >= 4
    }
    required_contracts = {
        "REQ-WFL-013": "only when the operator explicitly asks to create, structure, "
        "refine, implement, execute, complete, verify, qualify, or transition work "
        "packets/work packages",
        "REQ-WFL-014": "retain a delimited, hash-identified packet design containing "
        "the originating operator request",
        "REQ-WFL-015": "A fresh read-only verifier owns design finding severity",
        "REQ-WFL-016": "a different fresh read-only verifier must compare the exact "
        "implementation payload with the accepted design",
        "REQ-WFL-017": "trace the real trigger and production entry point through the "
        "resulting state/command change to a retained observation and an independent "
        "oracle",
        "REQ-WFL-018": "Tag claims separately by execution boundary",
        "REQ-WFL-019": "Keep the repository's canonical packet `Status` separate from "
        "`Independent verification`",
        "REQ-WFL-020": "“The dirty diff” is not an identity",
        "REQ-WFL-021": "Permit one initial review plus at most one recheck per gate",
        "REQ-WFL-022": "reviewer thread/label, date, exact design and implementation "
        "identities",
        "REQ-WFL-023": "The implementer owns the executable test plan for every work packet",
        "REQ-WFL-024": "Self-authored tests must observe behavior through the "
        "boundary being claimed",
        "REQ-WFL-025": "at least its intended path, a meaningful failure or "
        "rejected-input case, and a generalization or boundary case",
        "REQ-WFL-026": "run the smallest new test first, then affected component/integration tests",
        "REQ-WFL-027": "re-audit the implementation against each packet separately",
    }
    assert requirement_rows.keys() >= required_contracts.keys()
    for requirement_id, required_clause in required_contracts.items():
        assert required_clause in requirement_rows[requirement_id]
    assert "Independent work-packet verification protocol" in workflow
    assert "Author-driven iterative work-packet implementation loop" in workflow
    assert "Learnings from repeated work-packet reviews" in workflow

    ledgers = "\n".join(
        (ROOT / "docs/work-packages" / name).read_text(encoding="utf-8")
        for name in ("ACTIVE.md", "COMPLETED.md")
    )
    assert (
        "WP-51 — Independent work-packet verification and truthful qualification"
        in ledgers
    )
    assert "<!-- WP51-IMPLEMENTATION-EVIDENCE-BEGIN -->" in ledgers
    assert "Fresh-session discovery was not observed" in ledgers


def test_canonical_scenario_manifest_freezes_valid_configuration_hashes() -> None:
    manifest = load_json("config/qualification/canonical-scenarios-v1.json")
    assert manifest["process_repetitions"] >= 2
    assert {item["id"] for item in manifest["scenarios"]} == {
        "hover",
        "move-return",
        "failure",
        "three-vehicle",
    }
    for item in manifest["scenarios"]:
        scenario = load_scenario(ROOT / item["config"])
        assert canonical_sha256(scenario) == item["expected_scenario_sha256"]
        assert len(item["expected_outcome_sha256"]) == 64
        assert len(vehicles_from_scenario(scenario)) == (3 if item["all_vehicles"] else 1)


def test_frozen_adapter_artifact_matches_the_runtime_manifest() -> None:
    contract = load_json("config/contracts/simulator-adapter-v1.json")
    assert contract["stability"] == "FROZEN"
    assert contract["contract_version"] == ADAPTER_CONTRACT_VERSION
    scenario = load_scenario(ROOT / "config/scenarios/canonical_hover.yaml")
    runtime_manifest = vehicles_from_scenario(scenario)[0].contract_manifest.model_dump(mode="json")
    reference = contract["fast_sim_reference_manifest"]
    assert runtime_manifest["adapter_id"] == reference["adapter_id"]
    assert runtime_manifest["contract_version"] == reference["contract_version"]
    for field in ("supported_capabilities", "supported_signals", "supported_model_ids"):
        assert sorted(runtime_manifest[field]) == sorted(reference[field])


def test_release_policy_keeps_fast_sim_default_without_requiring_isaac() -> None:
    guide = (ROOT / "docs/guides/FAST_SIMULATOR.md").read_text(encoding="utf-8")
    normalized_guide = " ".join(guide.split())
    assert "default operator backend" in normalized_guide
    assert "does not require an Isaac-capable host" in normalized_guide
    limitations = (ROOT / "docs/qualification/FAST_SIMULATOR_LIMITATIONS.md").read_text(
        encoding="utf-8"
    )
    assert "CONFIGURED_UNQUALIFIED" in limitations
    assert "hardware-qualified" in limitations


def test_one_command_gate_covers_both_stacks_and_reproducibility() -> None:
    gate = (ROOT / "scripts/qualify_fast_sim.sh").read_text(encoding="utf-8")
    for required in (
        "verify_canonical_scenarios.py",
        "-m pytest -q",
        "-m ruff check .",
        "-m mypy src tests",
        "run lint",
        "run typecheck",
        "run test:unit",
        "run build",
        "audit --json",
    ):
        assert required in gate
