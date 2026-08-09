from __future__ import annotations

from fastapi.testclient import TestClient

from crazyswarm_app.api.runtime import ApplicationRuntime
from tests.api.conftest import auth_headers


def test_campaign_browse_validate_select_and_preview_do_not_launch(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    catalog = client.get("/api/v1/campaign/cases", headers=auth_headers())
    assert catalog.status_code == 200
    body = catalog.json()
    assert len(body["cases"]) >= 150
    assert set(body["hierarchy"]) == {"Real", "Simulation"}
    assert runtime.runner.list_runs() == ()

    validated = client.post(
        "/api/v1/campaign/cases/static-validate",
        headers=auth_headers("campaign-validate"),
        json={"case_id": "three_drone_multi_conflict"},
    )
    assert validated.status_code == 200
    assert validated.json()["status"] == "READY"
    assert runtime.runner.list_runs() == ()

    selected = client.post(
        "/api/v1/campaign/active",
        headers=auth_headers("campaign-select"),
        json={
            "case_id": "three_drone_multi_conflict",
            "reason": "API campaign contract test",
        },
    )
    assert selected.status_code == 200
    assert selected.json()["case_id"] == "three_drone_multi_conflict"
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
            "child_case_id": "three_drone_multi_conflict.child-api",
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
