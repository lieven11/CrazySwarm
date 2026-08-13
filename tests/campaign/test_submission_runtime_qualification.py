import importlib.util
import json
import sys
from pathlib import Path

import pytest

from crazyswarm_app.campaign.analyzer import AnalysisParameters, _count_stops

SCRIPT_PATH = Path("scripts/reconcile_wp52_56_r7_implementation.py").resolve()
SCRIPT_DIRECTORY = str(SCRIPT_PATH.parent)
SPEC = importlib.util.spec_from_file_location("wp52_56_r7_reconciliation", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - fixed repository fixture
    raise RuntimeError("R7 reconciliation script cannot be loaded")
MODULE = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, SCRIPT_DIRECTORY)
try:
    SPEC.loader.exec_module(MODULE)
finally:
    sys.path.remove(SCRIPT_DIRECTORY)

R6_ORACLE = MODULE.R6_ORACLE
build_reconciliation = MODULE.build_reconciliation
semantic_projection = MODULE.semantic_projection


def test_r7_reconciliation_is_current_and_semantically_exact() -> None:
    retained_path = Path(
        "missions/campaigns/sim/qualification/wp52-56-r7-implementation-reconciliation-v1.json"
    )
    retained = json.loads(retained_path.read_text(encoding="utf-8"))
    observed = build_reconciliation()

    assert retained == observed
    assert observed["passed"]
    assert observed["semantic_projection_equal"]
    assert observed["registry_counts"] == {
        "case_count": 54,
        "proposal_count": 111,
        "hidden_collapse_count": 28,
        "visible_relation_count": 83,
        "lifecycle_counts": {
            "SUBMISSIONS": 43,
            "BASELINE_ONLY": 9,
            "RETAIN_EXISTING_ONLY": 2,
        },
        "retained_altitude_profile_count": 5,
        "passed": True,
    }
    assert observed["seven_public_service_previews_passed"]
    assert observed["claim_boundaries"]["integration"]
    assert observed["claim_boundaries"]["production_entry_no_runtime"]


def test_r7_projection_allows_only_declared_identity_changes() -> None:
    original = {
        "metric": {"metric_id": "TM_RELEASE", "value": 4.5, "unit": "s"},
        "planning_submission_sha256": "a" * 64,
        "selected_candidate_sha256": "b" * 64,
    }
    identity_only = {
        **original,
        "planning_submission_sha256": "c" * 64,
    }
    changed_metric = {
        **identity_only,
        "metric": {"metric_id": "TM_RELEASE", "value": 4.6, "unit": "s"},
    }
    changed_winner = {
        **identity_only,
        "selected_candidate_sha256": "d" * 64,
    }

    assert semantic_projection(original) == semantic_projection(identity_only)
    assert semantic_projection(original) != semantic_projection(changed_metric)
    assert semantic_projection(original) != semantic_projection(changed_winner)


def test_r7_reconciliation_rejects_a_perturbed_frozen_oracle(tmp_path: Path) -> None:
    expected = json.loads(R6_ORACLE.read_text(encoding="utf-8"))
    expected["capacity_context_prototypes"][0]["bounded_earliest_release_oracle"][
        "minimum_release_s"
    ] += 0.01
    tampered = tmp_path / "tampered-r6-oracle.json"
    tampered.write_text(json.dumps(expected), encoding="utf-8")

    with pytest.raises(ValueError, match="internal identity"):
        build_reconciliation(tampered)


def test_runtime_stop_oracle_exempts_only_hash_bound_declared_stops() -> None:
    samples = (
        (1.00, 0.10),
        (1.10, 0.00),
        (1.20, 0.00),
        (1.31, 0.00),
        (1.40, 0.10),
        (2.00, 0.10),
    )
    parameters = AnalysisParameters(
        stop_speed_threshold_m_s=0.02,
        stop_persistence_s=0.20,
    )

    assert _count_stops(samples, parameters) == 1
    assert (
        _count_stops(
            samples,
            parameters,
            declared_stop_source_s=(1.20,),
        )
        == 0
    )
    assert (
        _count_stops(
            samples,
            parameters,
            declared_stop_source_s=(2.00,),
        )
        == 1
    )
