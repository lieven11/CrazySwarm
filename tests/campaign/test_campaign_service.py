from __future__ import annotations

import json
from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import LifecycleState
from crazyswarm_app.campaign.service import CampaignService, ReviewDecision


def test_startup_refreshes_changed_definition_only_identity(tmp_path: Path) -> None:
    state_directory = tmp_path / "campaign"
    catalog_path = Path("missions/campaigns/sim/cases")
    service = CampaignService(
        catalog=CampaignCatalog(catalog_path),
        state_directory=state_directory,
    )
    case_id = "1d.takeoff_hover_land.canonical_nominal"
    service.static_validate(case_id)
    state_path = state_directory / "workspace-state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["lifecycle"][case_id]["case_sha256"] = "0" * 64
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    refreshed = CampaignService(
        catalog=CampaignCatalog(catalog_path),
        state_directory=state_directory,
    )

    record = refreshed.state.lifecycle[case_id]
    assert record.case_sha256 == refreshed.catalog.get(case_id).case_sha256
    assert record.state is LifecycleState.DEFINED_NOT_RUN
    assert record.transitions == ()


def test_startup_rejects_changed_identity_with_evidence(tmp_path: Path) -> None:
    state_directory = tmp_path / "campaign"
    catalog_path = Path("missions/campaigns/sim/cases")
    CampaignService(
        catalog=CampaignCatalog(catalog_path),
        state_directory=state_directory,
    )
    case_id = "1d.takeoff_hover_land.canonical_nominal"
    state_path = state_directory / "workspace-state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["lifecycle"][case_id]["case_sha256"] = "0" * 64
    payload["lifecycle"][case_id]["run_ids"] = ["run-preserved-evidence"]
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="evidence or operator authority"):
        CampaignService(
            catalog=CampaignCatalog(catalog_path),
            state_directory=state_directory,
        )


def test_historical_intake_is_idempotent_non_executing_and_reviewable(
    tmp_path: Path,
) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    assert service.state.runs == ()
    service.static_validate("three_drone_multi_conflict")
    assert service.state.runs == ()
    service.set_active(
        "three_drone_multi_conflict",
        actor_id="campaign-service-test",
        reason="select without launching",
    )
    child = service.create_child(
        child_case_id="three_drone_multi_conflict.child-service",
        updates={"execution": {"seed": 73}},
    )
    assert child.execution.seed == 73
    assert child.execution.repetitions == 1
    assert child.execution.backend_profile_id == "fast-sim-v1"
    assert service.state.runs == ()

    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_"
        "run-3db45c352258411b85c44649bdef5e6b"
    )
    manifest = (directory / "manifest.json").read_bytes()
    bundle = next(directory.glob("*execution-bundle-v1.json")).read_bytes()
    evaluation = next(directory.glob("*evaluation-v1.json")).read_bytes()
    telemetry = next(directory.glob("*telemetry-v1.csv")).read_bytes()
    first = service.import_artifacts(
        case_id="three_drone_multi_conflict",
        manifest_bytes=manifest,
        bundle_bytes=bundle,
        evaluation_bytes=evaluation,
        csv_bytes=telemetry,
    )
    second = service.import_artifacts(
        case_id="three_drone_multi_conflict",
        manifest_bytes=manifest,
        bundle_bytes=bundle,
        evaluation_bytes=evaluation,
        csv_bytes=telemetry,
    )
    assert second.review_id == first.review_id
    assert len(service.state.runs) == 1
    assert len(service.state.reviews) == 1
    assert first.analysis.telemetry_row_count == 8_245
    assert first.analysis.minimum_truth_separation_m is not None
    assert abs(first.analysis.minimum_truth_separation_m - 0.8444) <= 0.005

    approved = service.decide_review(
        first.review_id,
        operator_id="campaign-service-test",
        decision=ReviewDecision.APPROVE,
        reason="historical evidence reproduced",
    )
    assert approved.approval is not None
    assert (
        service.state.lifecycle["three_drone_multi_conflict"].state
        is LifecycleState.BASELINED
    )
    first_recommendation = service.recommend_next()
    second_recommendation = service.recommend_next()
    assert first_recommendation.recommendation_sha256 == (
        second_recommendation.recommendation_sha256
    )
    matrix = service.materialize_wp25_matrix()
    assert matrix["matrix_id"] == "fast-sim-mission-robustness-v1"
    assert len(matrix["cells"]) == 16
