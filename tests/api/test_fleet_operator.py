from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import ApplicationRuntime, create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    load_versioned_contract,
)
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario
from tests.api.conftest import TOKEN, auth_headers


@pytest.fixture
def fleet_api_client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, ApplicationRuntime]]:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/two_drone_fleet.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"clock_mode": ClockMode.ACCELERATED}
            )
        }
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    app = create_app(runtime, local_token=TOKEN)
    with TestClient(app) as client:
        yield client, runtime


def test_operator_can_prepare_observe_and_run_two_drone_fleet(
    fleet_api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = fleet_api_client
    deployment = load_versioned_contract(
        Path("config/fleet/two-drone-deployment-v1.yaml"), DeploymentManifest
    )
    binding = load_versioned_contract(
        Path("config/fleet/fast-sim-two-drone-binding-v1.yaml"),
        BackendBindingProfile,
    )
    created = client.post(
        "/api/v1/fleet/sessions",
        headers=auth_headers("fleet-create"),
        json={
            "execution_session_id": "operator-session-1",
            "fleet_run_id": "operator-run-1",
            "mission_id": "hover",
            "deployment": deployment.model_dump(mode="json"),
            "binding": binding.model_dump(mode="json"),
        },
    )
    assert created.status_code == 200
    declared = created.json()["session"]
    assert declared["status"] == "DECLARED"
    assert {item["registration"] for item in declared["vehicles"]} == {"VERIFIED"}
    assert {item["connection"] for item in declared["vehicles"]} == {"DISCONNECTED"}
    assert {item["observation"] for item in declared["vehicles"]} == {"NOT_OBSERVED"}
    assert all(item["latest_telemetry"] is None for item in declared["vehicles"])

    connected = client.post(
        "/api/v1/fleet/sessions/operator-session-1/connect",
        headers=auth_headers("fleet-connect"),
    )
    assert connected.status_code == 200
    assert {item["connection"] for item in connected.json()["session"]["vehicles"]} == {"READY"}
    assert {item["observation"] for item in connected.json()["session"]["vehicles"]} == {
        "NOT_OBSERVED"
    }

    observed = client.post(
        "/api/v1/fleet/sessions/operator-session-1/observe",
        headers=auth_headers("fleet-observe"),
    )
    assert observed.status_code == 200
    assert {item["observation"] for item in observed.json()["session"]["vehicles"]} == {"CURRENT"}
    assert all(
        item["latest_telemetry"] is not None for item in observed.json()["session"]["vehicles"]
    )
    application_state = client.get("/api/v1/state", headers=auth_headers()).json()
    assert {item["observation"]["status"] for item in application_state["vehicles"]} == {"CURRENT"}
    assert all(item["telemetry"] is not None for item in application_state["vehicles"])
    assert len(application_state["fleet_sessions"]) == 1

    preflight = client.post(
        "/api/v1/fleet/sessions/operator-session-1/preflight",
        headers=auth_headers("fleet-preflight"),
    )
    assert preflight.status_code == 200
    assert preflight.json()["session"]["status"] == "READY"
    assert preflight.json()["session"]["preflight"]["approved"] is True

    # A new browser request reads server-owned preparation state without changing it.
    refreshed = client.get("/api/v1/fleet/sessions/operator-session-1", headers=auth_headers())
    assert refreshed.json()["session"]["status"] == "READY"

    started = client.post(
        "/api/v1/fleet/runs/operator-run-1/start",
        headers=auth_headers("fleet-start"),
        json={"assignments": {"inspect-a": "cf01", "inspect-b": "cf02"}},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "SCHEDULED"
    for _ in range(200):
        run = client.get("/api/v1/fleet/runs/operator-run-1", headers=auth_headers()).json()
        if run["result"] is not None:
            break
        time.sleep(0.005)
    else:
        raise AssertionError("fleet run did not complete")
    assert run["status"] == "SUCCEEDED"
    assert [item["state"] for item in run["tasks"]] == ["COMPLETED", "COMPLETED"]
    assert runtime.fleet_tasks == {}
    replay = client.get("/api/v1/fleet/runs/operator-run-1/replay", headers=auth_headers()).json()
    assert replay["command_authority"] is False
    assert replay["source_class"] == "REPLAYED"
    assert replay["event_count"] > 0
    assert replay["index"] == replay["event_count"]

    disconnected = client.post(
        "/api/v1/fleet/sessions/operator-session-1/disconnect",
        headers=auth_headers("fleet-disconnect"),
    )
    assert disconnected.status_code == 200
    assert disconnected.json()["session"]["status"] == "CLOSED"


def test_operator_can_export_bounded_software_fleet_qualification(
    fleet_api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = fleet_api_client
    response = client.get("/api/v1/fleet/qualification", headers=auth_headers())
    assert response.status_code == 200
    report = response.json()
    assert report["decision"] == "PASS_SOFTWARE_ONLY"
    assert report["equivalent_normalized_outcome"] is True
    assert report["live_isaac"] == "NOT_RUN"

    exported = client.get("/api/v1/fleet/qualification/export", headers=auth_headers())
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
