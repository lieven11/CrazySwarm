from __future__ import annotations

import json
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
    ledgers = sorted(path.name for path in (ROOT / "docs/work-packages").glob("*.md"))
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
    assert "NO_ACTIVE_SOFTWARE_PACKAGE" in active
    assert "WP-01 through WP-34 are closed" in active
    assert "Active package | None" in active
    assert "NVIDIA/Isaac installation" in active
    assert "not authorized by the WP-19-through-WP-34 software sequence" in active
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
