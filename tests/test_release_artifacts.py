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
    guide = (ROOT / "docs/FAST_SIMULATOR.md").read_text(encoding="utf-8")
    normalized_guide = " ".join(guide.split())
    assert "default operator backend" in normalized_guide
    assert "does not require an Isaac-capable host" in normalized_guide
    limitations = (ROOT / "docs/FAST_SIMULATOR_LIMITATIONS.md").read_text(encoding="utf-8")
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
