from __future__ import annotations

import time

from fastapi.testclient import TestClient

from crazyswarm_app.api.runtime import ApplicationRuntime
from crazyswarm_app.domain.models import VehicleState
from tests.api.conftest import auth_headers


def test_auth_origin_health_and_generated_schema(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    unauthorized = client.get("/api/v1/health")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "LOCAL_AUTH_REQUIRED"

    health = client.get("/api/v1/health", headers=auth_headers())
    assert health.status_code == 200
    assert health.json()["local_only"] is True
    schema = client.get("/api/v1/schema", headers=auth_headers()).json()
    assert "/api/v1/vehicles/{vehicle_id}/takeoff" in schema["paths"]
    assert "/api/v1/ws/events" not in schema["paths"]

    rejected = client.get(
        "/api/v1/health",
        headers={**auth_headers(), "Origin": "https://attacker.example"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"


def test_vehicle_inspection_and_parameter_capability(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    vehicles = client.get("/api/v1/vehicles", headers=auth_headers()).json()
    assert [item["identity"]["vehicle_id"] for item in vehicles] == ["sim01"]
    assert vehicles[0]["state"] == "DISCONNECTED"
    parameters = client.get("/api/v1/vehicles/sim01/parameters", headers=auth_headers()).json()
    assert parameters["vehicle_id"] == "sim01"
    assert parameters["supported"] is True
    assert {item["name"] for item in parameters["values"]} >= {
        "sim.max_horizontal_speed_m_s",
        "sim.position_noise_std_m",
        "sim.physics.mass_kg",
        "sim.physics.battery_capacity_ah",
    }


def test_simulation_idle_snapshot_is_visible_without_mission_evidence(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    state = client.get("/api/v1/state", headers=auth_headers()).json()
    before = state["vehicles"][0]
    assert state["configured_flight_volume"]["maximum_m"]["z"] == 1.0
    assert state["safety_policy"] == {
        "minimum_takeoff_battery_percent": 30.0,
        "critical_battery_percent": 10.0,
    }
    assert before["telemetry"]["telemetry"]["position_m"] == {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
    }
    assert before["observation"]["status"] == "NOT_STARTED"
    assert before["observation"]["source_class"] == "SIMULATED_MODEL"
    assert before["observation"]["run_id"] is None
    assert before["observation"]["fidelity_manifest_id"] == "crazyflie-6dof-v2"
    assert before["observation"]["physical_radio_available"] is False
    assert before["observation"]["fields"]["position_m"]["source_class"] == ("SIMULATED_MODEL")

    # Connecting may update idle state, but it still must not manufacture mission evidence.
    assert (
        client.post(
            "/api/v1/vehicles/sim01/connect", headers=auth_headers("truth-connect")
        ).status_code
        == 200
    )
    connected = client.get("/api/v1/state", headers=auth_headers()).json()["vehicles"][0]
    assert connected["state"] == "READY"
    assert connected["telemetry"] is not None
    assert connected["observation"]["status"] == "NOT_STARTED"
    assert connected["observation"]["run_id"] is None


def test_simulation_fidelity_manifest_declares_modeled_and_omitted_outputs(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    manifest = client.get("/api/v1/simulation/fidelity", headers=auth_headers()).json()
    assert manifest["source_class"] == "SIMULATED_MODEL"
    assert "range_rays" in manifest["modeled_outputs"]
    assert "physical_radio_link_quality" in manifest["omitted_outputs"]

    contracts = client.get("/api/v1/simulation/contracts", headers=auth_headers()).json()
    assert contracts["contract_version"] == "1.0.0"
    assert len(contracts["vehicle_parameters_sha256"]) == 64
    assert {item["frame"] for item in contracts["frames"]["frames"]} == {
        "world",
        "home",
        "body",
        "sensor",
    }
    assert {item["command"] for item in contracts["commands"]} >= {
        "takeoff",
        "move_relative",
        "emergency_stop",
    }
    unsupported = next(
        item for item in contracts["signals"] if item["signal_id"] == "physical-radio-rssi"
    )
    assert unsupported["presence"] == "UNSUPPORTED"
    assert unsupported["noise_std"] is None


def test_supervised_command_lifecycle_and_duplicate_takeoff_is_idempotent(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    assert (
        client.post("/api/v1/vehicles/sim01/connect", headers=auth_headers("connect-1")).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/vehicles/sim01/control/claim", headers=auth_headers("claim-1")
        ).status_code
        == 200
    )
    preflight = client.post(
        "/api/v1/vehicles/sim01/preflight",
        headers=auth_headers("preflight-1"),
        json={"mission_id": "hover"},
    )
    assert preflight.status_code == 200
    report = preflight.json()
    assert report["approved"] is True
    assert (
        client.post(
            "/api/v1/vehicles/sim01/arm",
            headers=auth_headers("arm-1"),
            json={"report_id": report["report_id"]},
        ).status_code
        == 200
    )

    takeoff_headers = auth_headers("takeoff-1")
    first = client.post(
        "/api/v1/vehicles/sim01/takeoff",
        headers=takeoff_headers,
        json={"height_m": 0.3, "duration_s": 2.0},
    )
    duplicate = client.post(
        "/api/v1/vehicles/sim01/takeoff",
        headers=takeoff_headers,
        json={"height_m": 0.3, "duration_s": 2.0},
    )
    assert first.status_code == duplicate.status_code == 200
    assert first.json() == duplicate.json()
    sent_takeoffs = [
        event
        for event in runtime.supervisor.events
        if event.event_type == "COMMAND_SENT" and event.message == "takeoff"
    ]
    assert len(sent_takeoffs) == 1

    conflicting = client.post(
        "/api/v1/vehicles/sim01/takeoff",
        headers=auth_headers("takeoff-2"),
        json={"height_m": 0.3, "duration_s": 2.0},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "INVALID_STATE"
    assert (
        client.post(
            "/api/v1/vehicles/sim01/land",
            headers=auth_headers("land-1"),
            json={"duration_s": 2.0},
        ).status_code
        == 200
    )


def test_stale_client_cannot_renew_or_retain_control(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    client.post("/api/v1/vehicles/sim01/connect", headers=auth_headers("connect-stale"))
    client.post("/api/v1/vehicles/sim01/control/claim", headers=auth_headers("claim-stale"))
    import asyncio

    asyncio.run(runtime.supervisor.expire_control_leases(now_s=time.monotonic() + 60.0))
    renewed = client.post(
        "/api/v1/vehicles/sim01/control/renew", headers=auth_headers("renew-stale")
    )
    assert renewed.status_code == 403
    assert renewed.json()["error"]["code"] == "MODE_NOT_AUTHORIZED"
    assert runtime.supervisor.session("sim01").lease is None


def test_same_idempotency_key_cannot_be_reordered_or_reused(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    headers = auth_headers("same-key")
    assert client.post("/api/v1/vehicles/sim01/connect", headers=headers).status_code == 200
    conflict = client.post("/api/v1/vehicles/sim01/control/claim", headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_live_mode_cannot_be_enabled_for_simulated_vehicle(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    response = client.post(
        "/api/v1/mode",
        headers=auth_headers("mode-live"),
        json={"mode": "LIVE", "confirmed": True},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MODE_NOT_AUTHORIZED"
    assert runtime.supervisor.mode.value == "SIM"
    assert runtime.supervisor.session("sim01").state is VehicleState.DISCONNECTED


def test_guarded_parameter_snapshot_write_and_restore(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    snapshot = client.post(
        "/api/v1/vehicles/sim01/parameters/snapshot",
        headers=auth_headers("params-snapshot"),
    ).json()
    snapshot_id = snapshot["snapshot_id"]
    changed = client.post(
        "/api/v1/vehicles/sim01/parameters/write",
        headers=auth_headers("params-write"),
        json={"name": "sim.position_noise_std_m", "value": 0.02},
    )
    assert changed.status_code == 200
    assert changed.json()["value"] == 0.02
    diff = client.get(
        f"/api/v1/vehicles/sim01/parameters/snapshots/{snapshot_id}/diff",
        headers=auth_headers(),
    ).json()
    assert diff["changes"]["sim.position_noise_std_m"]["current"] == 0.02
    restored = client.post(
        "/api/v1/vehicles/sim01/parameters/restore",
        headers=auth_headers("params-restore"),
        json={"snapshot_id": snapshot_id},
    )
    assert restored.status_code == 200
    values = {item["name"]: item["value"] for item in restored.json()["values"]}
    assert values["sim.position_noise_std_m"] == 0.001


def test_parameter_write_is_rejected_while_armed(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    client.post("/api/v1/vehicles/sim01/connect", headers=auth_headers("p-connect"))
    client.post("/api/v1/vehicles/sim01/control/claim", headers=auth_headers("p-claim"))
    report = client.post(
        "/api/v1/vehicles/sim01/preflight",
        headers=auth_headers("p-preflight"),
        json={},
    ).json()
    client.post(
        "/api/v1/vehicles/sim01/arm",
        headers=auth_headers("p-arm"),
        json={"report_id": report["report_id"]},
    )
    rejected = client.post(
        "/api/v1/vehicles/sim01/parameters/write",
        headers=auth_headers("p-write"),
        json={"name": "sim.position_noise_std_m", "value": 0.02},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "INVALID_STATE"


def test_operator_twin_endpoint_excludes_test_streams(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    from crazyswarm_app.domain.models import CoordinateFrame, Vector3
    from crazyswarm_app.twin.models import TwinInitialState, TwinSessionConfig, TwinSourceClass

    runtime.twins.create_session(
        TwinSessionConfig(
            observed_vehicle_id="test-real",
            simulated_vehicle_id="test-sim",
            mission_id="hover",
            mission_version="1",
            observed_initial_state=TwinInitialState(
                source_class=TwinSourceClass.TEST,
                source_id="fixture",
                frame=CoordinateFrame.WORLD,
                position_m=Vector3(),
            ),
            simulated_initial_state=TwinInitialState(
                source_class=TwinSourceClass.TEST,
                source_id="fixture",
                frame=CoordinateFrame.WORLD,
                position_m=Vector3(),
            ),
            test_only=True,
        )
    )
    assert client.get("/api/v1/twins", headers=auth_headers()).json() == []
