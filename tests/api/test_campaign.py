from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from crazyswarm_app.api.runtime import ApplicationRuntime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.service import CampaignRunStatus, CampaignService
from tests.api.conftest import auth_headers


def test_campaign_browse_validate_select_and_preview_do_not_launch(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    catalog = client.get("/api/v1/campaign/cases", headers=auth_headers())
    assert catalog.status_code == 200
    body = catalog.json()
    assert len(body["cases"]) >= 60
    assert len({item["execution_semantics_sha256"] for item in body["cases"]}) == len(body["cases"])
    assert set(body["hierarchy"]) == {"Real", "Simulation"}
    assert runtime.runner.list_runs() == ()

    qualification = client.get("/api/v1/campaign/qualification", headers=auth_headers())
    assert qualification.status_code == 200
    assert qualification.json()["case_count"] == 54
    assert qualification.json()["qualification_kind"] == "FAIL_CLOSED_STATIC_COMPILATION"

    validated = client.post(
        "/api/v1/campaign/cases/static-validate",
        headers=auth_headers("campaign-validate"),
        json={"case_id": "3d.simultaneous_center_conflict.joint_schedule_v2"},
    )
    assert validated.status_code == 200
    assert validated.json()["status"] == "READY"
    assert runtime.runner.list_runs() == ()

    selected = client.post(
        "/api/v1/campaign/active",
        headers=auth_headers("campaign-select"),
        json={
            "case_id": "3d.simultaneous_center_conflict.joint_schedule_v2",
            "reason": "API campaign contract test",
        },
    )
    assert selected.status_code == 200
    assert selected.json()["case_id"] == "3d.simultaneous_center_conflict.joint_schedule_v2"
    assert runtime.runner.list_runs() == ()

    preview = client.get(
        "/api/v1/campaign/active/preview",
        headers=auth_headers(),
    )
    assert preview.status_code == 200
    assert preview.json()["plan"]["status"] == "READY"
    assert preview.json()["schedule"]["roles"][1]["actions"][0]["kind"] == "GROUND_WAIT"
    assert runtime.runner.list_runs() == ()

    child = client.post(
        "/api/v1/campaign/active/child",
        headers=auth_headers("campaign-child"),
        json={
            "child_case_id": "3d.simultaneous_center_conflict.child-api",
            "updates": {"execution": {"seed": 99}},
        },
    )
    assert child.status_code == 200
    assert child.json()["execution"]["seed"] == 99
    assert child.json()["execution"]["backend_profile_id"] == "fast-sim-v1"
    assert child.json()["execution"]["repetitions"] == 1
    assert runtime.runner.list_runs() == ()


def test_campaign_run_returns_immediate_tracked_acknowledgement(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    client.post(
        "/api/v1/campaign/cases/static-validate",
        headers=auth_headers("campaign-async-validate"),
        json={"case_id": "1d.altitude_transition.canonical_nominal"},
    ).raise_for_status()
    client.post(
        "/api/v1/campaign/active",
        headers=auth_headers("campaign-async-select"),
        json={
            "case_id": "1d.altitude_transition.canonical_nominal",
            "reason": "verify asynchronous campaign acknowledgement",
        },
    ).raise_for_status()

    started = client.post(
        "/api/v1/campaign/runs",
        headers=auth_headers("campaign-async-run"),
        json={"mode": "AUTOMATED_ACCELERATED"},
    )

    assert started.status_code == 202
    acknowledgement = started.json()
    assert acknowledgement["accepted"] is True
    assert acknowledgement["mode"] == "AUTOMATED_ACCELERATED"
    assert acknowledgement["status"] in {"QUEUED", "RUNNING", "SUCCEEDED"}
    workspace = client.get("/api/v1/campaign/state", headers=auth_headers()).json()
    assert any(run["run_id"] == acknowledgement["run_id"] for run in workspace["runs"])


def test_altitude_submission_catalog_and_preview_are_hash_bound(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    cases = client.get("/api/v1/campaign/cases", headers=auth_headers()).json()["cases"]
    canonical = next(
        item for item in cases if item["case_id"] == "1d.altitude_transition.canonical_nominal"
    )
    submissions = {item["submission_id"]: item for item in canonical["submissions"]}
    stress = submissions["constant_path_speed.stress"]
    assert stress["case_sha256"] == canonical["case_sha256"]
    assert stress["baseline_submission_sha256"]
    assert stress["feasibility"]["maximum_path_speed_m_s"] >= 0.30
    assert submissions["constant_rotor_speed"]["status"] == "PLANNED_NOT_EXECUTABLE"

    client.post(
        "/api/v1/campaign/active",
        headers=auth_headers("campaign-submission-select"),
        json={
            "case_id": canonical["case_id"],
            "reason": "preview hash-bound execution submission",
        },
    ).raise_for_status()
    preview = client.get(
        "/api/v1/campaign/active/preview",
        params={"submission_id": stress["submission_id"]},
        headers=auth_headers(),
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["plan"]["submission_sha256"] == stress["submission_sha256"]
    assert body["trajectories"]["submission_sha256"] == stress["submission_sha256"]
    assert body["trajectories"]["profile_audits"][0]["passed"] is True
    assert runtime.runner.list_runs() == ()


def test_constraint_directed_planning_contract_preview_and_matrix_are_exposed(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    cases = client.get("/api/v1/campaign/cases", headers=auth_headers()).json()["cases"]
    merge = next(item for item in cases if item["case_id"] == "2d.merge.canonical_nominal")
    planning = {item["planning_submission_id"]: item for item in merge["planning_submissions"]}
    directed = planning["constraint_directed.merge.flexible_geometry"]
    assert directed["planning_submission_sha256"]
    assert set(directed["maneuver_dimensions"]) >= {"LATERAL", "VERTICAL"}

    client.post(
        "/api/v1/campaign/active",
        headers=auth_headers("planning-contract-select"),
        json={"case_id": merge["case_id"], "reason": "preview generalized planning authority"},
    ).raise_for_status()
    preview = client.get(
        "/api/v1/campaign/active/preview",
        params={"planning_submission_id": directed["planning_submission_id"]},
        headers=auth_headers(),
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["plan"]["planning_submission_sha256"] == directed["planning_submission_sha256"]
    assert (
        payload["schedule"]["planning_submission_sha256"] == directed["planning_submission_sha256"]
    )
    assert (
        payload["trajectories"]["planning_submission_sha256"]
        == directed["planning_submission_sha256"]
    )
    assert payload["resolved_package"]["resolved_package_sha256"]
    assert payload["plan"]["search_disposition"] == "SELECTED"
    assert payload["plan"]["feasibility_certificate"]["passed"] is True
    assert runtime.runner.list_runs() == ()

    assert len(cases) >= 54
    assert all(
        item["submission_registry"]["expected_case_sha256"] == item["case_sha256"] for item in cases
    )
    assert directed["semantic_fingerprint_sha256"]
    assert directed["experiment_axis"] == "CAPABILITY_BINDING"
    assert directed["admission"]["distinguishing_oracle"]

    downloaded = client.get(
        "/api/v1/campaign/active/package",
        params={"planning_submission_id": directed["planning_submission_id"]},
        headers=auth_headers(),
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert (
        downloaded.json()["resolved_package_sha256"]
        == payload["resolved_package"]["resolved_package_sha256"]
    )

    qualification = client.get(
        "/api/v1/campaign/qualification/constraint-directed",
        headers=auth_headers(),
    )
    assert qualification.status_code == 200
    report = qualification.json()
    assert report["passed"] is True
    assert len(report["rows"]) == 9
    assert len(report["geometry_rows"]) == 6
    assert len(report["dynamic_rows"]) == 4

    selective = client.get(
        "/api/v1/campaign/qualification/selective-submissions",
        headers=auth_headers(),
    )
    assert selective.status_code == 200
    assert selective.json()["passed"] is True
    assert selective.json()["case_count"] == 54


def test_campaign_case_can_move_to_review_manually_or_from_a_comment_then_complete(
    api_client: tuple[TestClient, ApplicationRuntime],
    tmp_path: Path,
) -> None:
    client, _ = api_client
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign-lifecycle",
    )
    case_id = "three_drone_multi_conflict"
    service.set_active(case_id, actor_id="api-test", reason="start case")
    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_run-3db45c352258411b85c44649bdef5e6b"
    )
    review = service.import_artifacts(
        case_id=case_id,
        manifest_bytes=(directory / "manifest.json").read_bytes(),
        bundle_bytes=next(directory.glob("*execution-bundle-v1.json")).read_bytes(),
        evaluation_bytes=next(directory.glob("*evaluation-v1.json")).read_bytes(),
        csv_bytes=next(directory.glob("*telemetry-v1.csv")).read_bytes(),
    )
    client.app.state.campaign_service = service

    reviewed = client.post(
        "/api/v1/campaign/cases/in-review",
        headers=auth_headers("campaign-in-review"),
        json={"case_id": case_id, "reason": "ready for operator review"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "BASELINED"

    reactivated = client.post(
        "/api/v1/campaign/active",
        headers=auth_headers("campaign-reactivated"),
        json={"case_id": case_id, "reason": "follow up on the review"},
    )
    assert reactivated.status_code == 200
    commented = client.post(
        f"/api/v1/campaign/reviews/{review.review_id}/observations",
        headers=auth_headers("campaign-commented"),
        json={"note": "The follow-up run is ready for review."},
    )
    assert commented.status_code == 200
    assert commented.json()["operator_observations"] == ["The follow-up run is ready for review."]
    state = client.get("/api/v1/campaign/state", headers=auth_headers()).json()
    assert state["lifecycle"][case_id]["state"] == "BASELINED"
    assert state["active_case_id"] is None

    completed = client.post(
        "/api/v1/campaign/cases/completed",
        headers=auth_headers("campaign-completed"),
        json={"case_id": case_id, "reason": "operator review is complete"},
    )
    assert completed.status_code == 200
    assert completed.json()["state"] == "PROMOTED"


def test_campaign_case_lifecycle_endpoint_accepts_direct_operator_changes(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    case_id = "1d.altitude_transition.canonical_nominal"

    completed = client.post(
        "/api/v1/campaign/cases/lifecycle",
        headers=auth_headers("campaign-state-override"),
        json={
            "case_id": case_id,
            "state": "PROMOTED",
            "reason": "operator marked the case complete",
        },
    )
    reopened = client.post(
        "/api/v1/campaign/cases/lifecycle",
        headers=auth_headers("campaign-state-override"),
        json={
            "case_id": case_id,
            "state": "BLOCKED",
            "reason": "operator reopened the case as blocked",
        },
    )

    assert completed.status_code == 200
    assert completed.json()["state"] == "PROMOTED"
    assert reopened.status_code == 200
    assert reopened.json()["state"] == "BLOCKED"


def test_browser_timing_channel_is_bounded_to_browser_owned_stages(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    payload = {
        "correlation_id": "sample-browser-1",
        "stage": "BROWSER_RECEIPT",
        "source_timestamp_s": 1.0,
        "source_clock_id": "fast-sim-Alpha",
        "source_clock_epoch": 1,
        "observed_monotonic_s": 2.0,
        "playback_buffer_age_s": 0.25,
        "dropped_samples": 0,
        "coalesced_samples": 0,
    }
    accepted = client.post(
        "/api/v1/campaign/timing/browser",
        headers=auth_headers("browser-timing"),
        json=payload,
    )
    assert accepted.status_code == 200
    snapshot = client.get("/api/v1/campaign/timing", headers=auth_headers()).json()
    assert snapshot["trace"]["retention_limit"] == 20_000
    assert snapshot["trace"]["stage_counts"]["BROWSER_RECEIPT"] == 1

    rejected = client.post(
        "/api/v1/campaign/timing/browser",
        headers=auth_headers("browser-timing-invalid"),
        json={**payload, "stage": "SIMULATOR_STEP"},
    )
    assert rejected.status_code == 422


def test_campaign_run_delete_removes_campaign_state_when_archive_is_already_absent(
    api_client: tuple[TestClient, ApplicationRuntime],
    tmp_path: Path,
) -> None:
    client, _ = api_client
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_run-3db45c352258411b85c44649bdef5e6b"
    )
    review = service.import_artifacts(
        case_id="three_drone_multi_conflict",
        manifest_bytes=(directory / "manifest.json").read_bytes(),
        bundle_bytes=next(directory.glob("*execution-bundle-v1.json")).read_bytes(),
        evaluation_bytes=next(directory.glob("*evaluation-v1.json")).read_bytes(),
        csv_bytes=next(directory.glob("*telemetry-v1.csv")).read_bytes(),
    )
    client.app.state.campaign_service = service

    deleted = client.delete(
        f"/api/v1/campaign/runs/{review.run_id}",
        headers=auth_headers("campaign-delete"),
    )

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["run_id"] == review.run_id
    state = client.get("/api/v1/campaign/state", headers=auth_headers()).json()
    assert state["runs"] == []
    assert state["reviews"] == []


def test_campaign_snapshot_upload_image_and_comment_contract(
    api_client: tuple[TestClient, ApplicationRuntime],
    tmp_path: Path,
) -> None:
    client, _ = api_client
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign-snapshots",
    )
    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_run-3db45c352258411b85c44649bdef5e6b"
    )
    review = service.import_artifacts(
        case_id="three_drone_multi_conflict",
        manifest_bytes=(directory / "manifest.json").read_bytes(),
        bundle_bytes=next(directory.glob("*execution-bundle-v1.json")).read_bytes(),
        evaluation_bytes=next(directory.glob("*evaluation-v1.json")).read_bytes(),
        csv_bytes=next(directory.glob("*telemetry-v1.csv")).read_bytes(),
    )
    run = service.state.runs[0]
    service._state = service.state.model_copy(
        update={
            "runs": (
                run.model_copy(
                    update={"status": CampaignRunStatus.RUNNING, "finished_at_utc": None}
                ),
            )
        }
    )
    client.app.state.campaign_service = service
    image_bytes = b"RIFF\x08\x00\x00\x00WEBPVP8 "
    review_frame = {
        "source_timestamp_s": "12.5",
        "source_clock_id": "fast-sim-Alpha",
        "source_clock_epoch": "1",
        "source_sequence": "624",
        "correlation_id": "sample-624",
        "estimate_source_timestamp_s": "12.5",
        "truth_source_timestamp_s": "12.5",
        "desired_source_timestamp_s": "12.5",
        "playback_buffer_age_s": "0.25",
        "source_rows_json": json.dumps(
            [
                {
                    "source_clock_id": "fast-sim-Alpha",
                    "source_clock_epoch": 1,
                    "source_sequence": 624,
                    "source_timestamp_s": 12.48,
                    "correlation_id": "sample-624",
                },
                {
                    "source_clock_id": "fast-sim-Alpha",
                    "source_clock_epoch": 1,
                    "source_sequence": 625,
                    "source_timestamp_s": 12.52,
                    "correlation_id": "sample-625",
                },
            ]
        ),
        "same_time_truth_estimate_error_m": "0.014",
        "buffer_induced_estimate_displacement_m": "0.031",
        "interpolation_state": "INTERPOLATED",
    }

    captured = client.post(
        f"/api/v1/campaign/runs/{review.run_id}/snapshots",
        params={"width_px": 960, "height_px": 540, **review_frame},
        headers={**auth_headers("campaign-snapshot"), "Content-Type": "image/webp"},
        content=image_bytes,
    )

    assert captured.status_code == 201
    snapshot_id = captured.json()["snapshot_id"]
    assert captured.json()["size_bytes"] == len(image_bytes)
    assert captured.json()["review_frame"]["source_sequence"] == 624
    assert [row["source_sequence"] for row in captured.json()["review_frame"]["source_rows"]] == [
        624,
        625,
    ]
    assert captured.json()["review_frame"]["captured_at_wall_utc"]
    assert captured.json()["review_frame"]["same_time_truth_estimate_error_m"] == 0.014
    assert captured.json()["review_frame"]["buffer_induced_estimate_displacement_m"] == 0.031
    assert captured.json()["case_id"] == "three_drone_multi_conflict"
    assert captured.json()["plan_sha256"] == run.plan_sha256
    image = client.get(
        f"/api/v1/campaign/snapshots/{snapshot_id}/image",
        headers=auth_headers(),
    )
    assert image.status_code == 200
    assert image.content == image_bytes
    commented = client.post(
        f"/api/v1/campaign/snapshots/{snapshot_id}/comment",
        headers=auth_headers("campaign-snapshot-comment"),
        json={"note": "  The vehicle crossed the target layer here.  "},
    )
    assert commented.status_code == 200
    assert commented.json()["operator_comment"] == (
        "  The vehicle crossed the target layer here.  "
    )
    assessed = client.post(
        f"/api/v1/campaign/snapshots/{snapshot_id}/assessment",
        headers=auth_headers("campaign-snapshot-assessment"),
        json={
            "assessment": "The comment is directionally valid at the bound source time.",
            "disposition": "PARTLY_VALID",
            "confidence": 0.85,
            "evidence_refs": ["sample-625", run.plan_sha256],
        },
    )
    assert assessed.status_code == 200
    assert assessed.json()["operator_comment"] == commented.json()["operator_comment"]
    assert assessed.json()["assessment_disposition"] == "PARTLY_VALID"
    assert assessed.json()["assessment_evidence_refs"] == sorted(["sample-625", run.plan_sha256])
