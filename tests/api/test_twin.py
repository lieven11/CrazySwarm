from __future__ import annotations

import time

from crazyswarm_app.domain.models import CoordinateFrame, Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.models import (
    TwinAvailability,
    TwinInitialState,
    TwinQuality,
    TwinSessionConfig,
    TwinSourceClass,
    TwinStreamSample,
    TwinStreamSide,
)

from .conftest import auth_headers


def test_twin_timeline_api_round_trips_source_quality_and_hash(api_client) -> None:
    client, runtime = api_client
    observed_id = runtime.selected_vehicle_id
    record = runtime.twins.create_session(
        TwinSessionConfig(
            observed_vehicle_id=observed_id,
            simulated_vehicle_id=f"{observed_id}-model",
            mission_id="straight-1d",
            mission_version="1",
            observed_initial_state=TwinInitialState(
                source_class=TwinSourceClass.CONFIGURED,
                source_id="sim-observed",
                frame=CoordinateFrame.WORLD,
            ),
            simulated_initial_state=TwinInitialState(
                source_class=TwinSourceClass.SIMULATED_MODEL,
                source_id="model",
                frame=CoordinateFrame.WORLD,
            ),
            ground_truth_available=True,
        )
    )
    sample = TwinStreamSample.create(
        sample_id="api-sample-1",
        session_id=record.session_id,
        side=TwinStreamSide.OBSERVED,
        vehicle_id=observed_id,
        channel_id="pose.position",
        sequence=1,
        source_timestamp_s=1.0,
        received_timestamp_s=1.02,
        availability=TwinAvailability.AVAILABLE,
        quality=TwinQuality.GOOD,
        unit="m",
        frame="world",
        value=Vector3(x=0.1, z=0.4),
        raw_payload_sha256=canonical_sha256("api-row"),
    )
    response = client.post(
        f"/api/v1/twins/{record.session_id}/samples",
        headers=auth_headers("twin-sample"),
        json={"session_id": record.session_id, "samples": [sample.model_dump(mode="json")]},
    )
    assert response.status_code == 200, response.text
    timeline = client.get(
        f"/api/v1/twins/{record.session_id}/timeline",
        headers=auth_headers(),
    )
    assert timeline.status_code == 200
    body = timeline.json()
    assert body["samples"][0]["quality"] == "GOOD"
    assert body["samples"][0]["raw_payload_sha256"] == canonical_sha256("api-row")
    assert len(body["timeline_sha256"]) == 64
    sessions = client.get("/api/v1/twins", headers=auth_headers()).json()
    selected = next(item for item in sessions if item["session_id"] == record.session_id)
    assert selected["observed_source_class"] == "CONFIGURED"
    assert selected["simulated_source_class"] == "SIMULATED_MODEL"


def test_twin_curriculum_api_keeps_real_stages_not_run(api_client) -> None:
    client, _runtime = api_client
    body = client.get("/api/v1/twins/curriculum", headers=auth_headers()).json()
    real = [item for item in body["stages"] if item["environment"] == "REAL_ADAPTER"]
    assert len(real) == 8
    assert all(item["status"] == "NOT_RUN" for item in real)


def test_ready_curriculum_stage_runs_through_campaign_and_links_twin_evidence(
    api_client,
) -> None:
    client, runtime = api_client
    stage_id = "sim.startup_props_off_equivalent"
    started = client.post(
        f"/api/v1/twins/curriculum/{stage_id}/runs",
        headers=auth_headers("twin-stage-startup"),
        json={"mode": "AUTOMATED_ACCELERATED"},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]

    terminal = None
    for _ in range(400):
        curriculum = client.get("/api/v1/twins/curriculum", headers=auth_headers()).json()
        terminal = next(item for item in curriculum["stages"] if item["stage_id"] == stage_id)
        if terminal["status"] in {"PASSED", "FAILED"}:
            break
        time.sleep(0.025)
    assert terminal is not None
    assert terminal["status"] == "PASSED"
    session_id = terminal["session_id"]
    session = runtime.twins.session(session_id)
    assert session.campaign_run_id == run_id
    assert session.curriculum_stage_id == stage_id
    assert session.observed_source_class is TwinSourceClass.CONFIGURED
    assert session.simulated_source_class is TwinSourceClass.SIMULATED_MODEL
    assert runtime.twins.timeline(session_id).samples

    service = client.app.state.campaign_service
    review = next(item for item in service.state.reviews if item.run_id == run_id)
    assert review.twin_session_ids == (session_id,)
    # Re-delivery reuses the campaign-run identity and does not create a second twin.
    duplicate = client.post(
        f"/api/v1/twins/curriculum/{stage_id}/runs",
        headers=auth_headers("twin-stage-startup"),
        json={"mode": "AUTOMATED_ACCELERATED"},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["run_id"] == run_id
    matching_sessions = [
        item for item in runtime.twins.list_sessions() if item.campaign_run_id == run_id
    ]
    assert len(matching_sessions) == 1
