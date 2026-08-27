from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.hardware.observation_twin import ObservationTwinService
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario
from tests.api.conftest import TOKEN, auth_headers
from tests.hardware.test_observation_twin_service import URI, ObservationLink


def test_simulation_only_runtime_rejects_physical_connection(
    api_client: tuple[TestClient, object],
) -> None:
    client, _runtime = api_client

    response = client.post(
        "/api/v1/physical-twin/connect",
        headers=auth_headers("isolated-runtime-connect"),
        json={},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"
    assert "operator-owned dashboard service" in response.json()["error"]["message"]


def test_physical_twin_api_pairs_privately_and_existing_command_routes_reject_id(
    tmp_path: Path,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"clock_mode": ClockMode.ACCELERATED}
            )
        }
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    link = ObservationLink()
    service = ObservationTwinService(
        runtime,
        binding_path=tmp_path / "binding.json",
        link_factory=lambda: link,
    )
    app = create_app(
        runtime,
        local_token=TOKEN,
        observation_twin_service=service,
    )
    with TestClient(app) as client:
        initial = client.get("/api/v1/physical-twin/status", headers=auth_headers())
        assert initial.status_code == 200
        assert initial.json()["state"] == "UNCONFIGURED"

        lab_catalog = client.get("/api/v1/physical-twin/lab/catalog", headers=auth_headers())
        assert lab_catalog.status_code == 200
        assert lab_catalog.json()["cluster_id"] == "basic-flight"
        assert lab_catalog.json()["qualification_claim"] == "NONE"
        assert all(
            motion["major_mission"] != "Motor bench" for motion in lab_catalog.json()["motions"]
        )

        actuation = client.get(
            "/api/v1/physical-twin/lab/motor-actuation",
            headers=auth_headers(),
        )
        assert actuation.status_code == 200
        assert actuation.json()["state"] == "IDLE"
        assert actuation.json()["stop_required"] is False
        assert actuation.json()["measured_output_active"] is False

        physical_flight = client.get(
            "/api/v1/physical-twin/lab/physical-flight",
            headers=auth_headers(),
        )
        assert physical_flight.status_code == 200
        assert physical_flight.json()["state"] == "IDLE"
        assert physical_flight.json()["stop_required"] is False

        lab_run = client.post(
            "/api/v1/physical-twin/lab/runs",
            headers=auth_headers("basic-flight-rehearsal"),
            json={"motion_id": "commissioning-baseline"},
        )
        assert lab_run.status_code == 200
        assert lab_run.json()["execution_backend"] == "FAST_SIM"
        assert lab_run.json()["learning_sample"]["landing_contact_observed"] is True
        assert link.commands == []

        configured = client.put(
            "/api/v1/physical-twin/binding",
            headers=auth_headers("physical-configure"),
            json={
                "selected_uri": URI,
                "vehicle_label": "API Crazyflie",
                "confirm_exact_uri": True,
            },
        )
        assert configured.status_code == 200
        assert configured.json()["uri_sha256"] == hashlib.sha256(URI.encode()).hexdigest()
        assert URI not in configured.text

        paired = client.post(
            "/api/v1/physical-twin/connect",
            headers=auth_headers("physical-connect"),
            json={},
        )
        assert paired.status_code == 200
        assert paired.json()["state"] == "PAIRED"
        assert paired.json()["connection_nonce"] is None
        assert paired.json()["observed_identity_sha256"] is not None
        assert paired.json()["test_only"] is True
        assert paired.json()["provenance"] == "TEST"

        idle_flight = client.get(
            "/api/v1/physical-twin/lab/physical-flight",
            headers=auth_headers(),
        )
        assert idle_flight.status_code == 200
        assert idle_flight.json()["state"] == "IDLE"
        assert idle_flight.json()["stop_required"] is False

        # The test observation intentionally has no supervisor bitfield. Pairing
        # alone must therefore never make Play/start authoritative.
        blocked_start = client.post(
            "/api/v1/physical-twin/lab/physical-flight/start",
            headers=auth_headers("physical-start-without-supervisor"),
            json={"motion_id": "commissioning-baseline"},
        )
        assert blocked_start.status_code == 409
        assert blocked_start.json()["error"]["code"] == "PREFLIGHT_FAILED"
        assert "fresh supervisor telemetry" in blocked_start.json()["error"]["message"]
        assert link.commands == []

        binding_id = paired.json()["observed_identity_sha256"][:16]
        private_id = f"physical:{binding_id}"
        predicted_id = f"fast-sim:{binding_id}"
        counterexamples = (
            client.post(
                "/api/v1/vehicles/select",
                headers=auth_headers("private-select"),
                json={"vehicle_id": private_id},
            ),
            client.post(
                f"/api/v1/vehicles/{private_id}/connect",
                headers=auth_headers("private-connect"),
                json={},
            ),
            client.post(
                f"/api/v1/vehicles/{private_id}/control/claim",
                headers=auth_headers("private-claim"),
                json={},
            ),
            client.post(
                f"/api/v1/vehicles/{private_id}/preflight",
                headers=auth_headers("private-preflight"),
                json={},
            ),
            client.post(
                f"/api/v1/vehicles/{private_id}/arm",
                headers=auth_headers("private-arm"),
                json={"report_id": "report-impossible"},
            ),
            client.get(
                f"/api/v1/vehicles/{private_id}/parameters",
                headers=auth_headers(),
            ),
            client.post(
                "/api/v1/missions/hover/start",
                headers=auth_headers("private-mission"),
                json={"vehicle_id": private_id},
            ),
        )
        assert all(response.status_code in {400, 404} for response in counterexamples), [
            (response.status_code, response.text) for response in counterexamples
        ]
        assert link.commands == []
        assert private_id not in runtime.vehicles
        assert predicted_id not in runtime.vehicles
        private_session = runtime.twins.session(paired.json()["session_id"], include_test=True)
        assert private_session.observed_vehicle_id == private_id
        assert private_session.simulated_vehicle_id == predicted_id
        assert all(
            item["test_only"] is not True
            for item in client.get("/api/v1/twins", headers=auth_headers()).json()
        )

        disconnected = client.post(
            "/api/v1/physical-twin/disconnect",
            headers=auth_headers("physical-disconnect"),
            json={},
        )
        assert disconnected.status_code == 200
    assert disconnected.json()["state"] == "DISCONNECTED"
    assert link.commands == []


def test_physical_twin_live_stream_is_authenticated_and_compact(
    api_client: tuple[TestClient, object],
) -> None:
    client, _runtime = api_client
    unauthorized = client.get("/api/v1/physical-twin/live")
    assert unauthorized.status_code == 401

    response = client.get(
        "/api/v1/physical-twin/live",
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: physical-twin" in response.text
    payload = next(
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ")
    )
    assert '"state":"UNCONFIGURED"' in payload
    assert '"observed":null' in payload
