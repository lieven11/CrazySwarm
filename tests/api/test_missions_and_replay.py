from __future__ import annotations

import time
from typing import cast

from fastapi.testclient import TestClient

from crazyswarm_app.api.runtime import ApplicationRuntime
from crazyswarm_app.domain.models import VehicleState
from crazyswarm_app.observability.events import EvidenceEvent, EvidenceKind, MissionResultPayload
from crazyswarm_app.observability.replay import ReplayClock
from tests.api.conftest import auth_headers
from tests.missions.test_runner import BlockingMission

PYTHON_MISSION = """\
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=0.1)
    await drone.land(duration_s=2.0)
"""


def wait_for_result(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        response = client.get(f"/api/v1/mission-runs/{run_id}", headers=auth_headers())
        assert response.status_code == 200
        snapshot = response.json()
        if snapshot.get("result") is not None:
            return cast(dict[str, object], snapshot)
        time.sleep(0.005)
    raise AssertionError("mission did not finish")


def wait_for_stored_events(client: TestClient, run_id: str) -> list[dict[str, object]]:
    for _ in range(100):
        response = client.get(f"/api/v1/runs/{run_id}/events", headers=auth_headers())
        assert response.status_code == 200
        events = response.json()
        if events and events[-1]["kind"] == "mission_result":
            return cast(list[dict[str, object]], events)
        time.sleep(0.005)
    raise AssertionError("mission evidence was not stored")


def test_mission_metadata_validation_start_status_and_idempotency(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    missions = client.get("/api/v1/missions", headers=auth_headers()).json()
    assert [item["mission_id"] for item in missions] == ["hover", "move-return", "square"]
    assert "parameter_schema" in missions[0]
    valid = client.post(
        "/api/v1/missions/hover/validate",
        headers=auth_headers("validate-hover"),
        json={"preset": "quick-check"},
    )
    assert valid.status_code == 200
    assert valid.json()["parameters"]["height_m"] == 0.2

    start_headers = auth_headers("start-hover")
    body = {"vehicle_id": "sim01", "preset": "quick-check"}
    first = client.post("/api/v1/missions/hover/start", headers=start_headers, json=body)
    duplicate = client.post("/api/v1/missions/hover/start", headers=start_headers, json=body)
    assert first.status_code == duplicate.status_code == 200
    assert first.json()["mission_run_id"] == duplicate.json()["mission_run_id"]
    run_id = first.json()["mission_run_id"]
    snapshot = wait_for_result(client, run_id)
    assert snapshot["result"]["status"] == "SUCCEEDED"  # type: ignore[index]
    assert len([run for run in runtime.runner.list_runs() if run.mission_run_id == run_id]) == 1
    observed = client.get("/api/v1/state", headers=auth_headers()).json()["vehicles"][0]
    assert observed["observation"]["source_class"] == "SIMULATED_MODEL"
    assert observed["observation"]["status"] == "COMPLETED_SNAPSHOT"
    assert observed["observation"]["run_id"] == run_id
    assert observed["telemetry"] is not None
    telemetry = observed["telemetry"]["telemetry"]
    assert "link_quality_percent" not in telemetry
    assert "link_latency_ms" not in telemetry
    assert "packet_loss_percent" not in telemetry
    assert telemetry["transport"]["kind"] == "modeled_transport"
    fields = observed["observation"]["fields"]
    assert fields["position_m"]["unit"] == "m"
    assert fields["position_m"]["source_class"] == "SIMULATED_MODEL"
    assert fields["position_m"]["fidelity_manifest_id"] == "crazyflie-6dof-v1"
    assert fields["motors"]["model_version"] == "1.0.0"
    assert "link_quality_percent" not in fields


def test_python_mission_upload_library_and_simulation_start(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    assert client.get("/api/v1/mission-files", headers=auth_headers()).json() == []

    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("upload-python-mission"),
        json={"name": "Hover", "filename": "hover.py", "source": PYTHON_MISSION},
    )
    assert uploaded.status_code == 200
    mission_id = uploaded.json()["mission_id"]
    assert uploaded.json()["source_kind"] == "UPLOADED_PYTHON"
    assert uploaded.json()["source_filename"] == "hover.py"
    assert len(uploaded.json()["source_sha256"]) == 64
    assert [item["action"] for item in uploaded.json()["planned_commands"]] == [
        "takeoff",
        "hover",
        "land",
    ]
    assert [
        item["mission_id"]
        for item in client.get(
            "/api/v1/mission-files",
            headers=auth_headers(),
        ).json()
    ] == [mission_id]

    twin = client.post(
        f"/api/v1/mission-files/{mission_id}/start",
        headers=auth_headers("reject-twin-without-real-adapter"),
        json={"vehicle_id": "sim01", "execution_mode": "TWIN"},
    )
    assert twin.status_code == 403
    assert twin.json()["error"]["code"] == "MODE_NOT_AUTHORIZED"

    started = client.post(
        f"/api/v1/mission-files/{mission_id}/start",
        headers=auth_headers("start-python-simulation"),
        json={"vehicle_id": "sim01", "execution_mode": "SIMULATION"},
    )
    assert started.status_code == 200
    snapshot = wait_for_result(client, started.json()["mission_run_id"])
    assert snapshot["result"]["status"] == "SUCCEEDED"  # type: ignore[index]
    result = cast(dict[str, object], snapshot["result"])
    assert result["mission_source_sha256"] == uploaded.json()["source_sha256"]
    assert result["mission_runtime_id"] == "restricted-python-dsl"
    assert result["vehicle_adapter"] == "sim"
    assert result["physics_model_id"] == "crazyflie-6dof"
    assert result["physics_model_version"] == "1.0.0"
    assert result["scenario_id"] == "one-drone-room"
    assert isinstance(result["run_identity_sha256"], str)
    assert len(result["run_identity_sha256"]) == 64

    archived = client.delete(
        f"/api/v1/mission-files/{mission_id}",
        headers=auth_headers("archive-python-mission"),
    )
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert client.get("/api/v1/mission-files", headers=auth_headers()).json() == []
    history = client.get("/api/v1/mission-files/archive", headers=auth_headers()).json()
    assert history[0]["source_sha256"] == uploaded.json()["source_sha256"]

    unsafe = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("reject-unsafe-python"),
        json={
            "name": "Unsafe",
            "filename": "unsafe.py",
            "source": "import os\nasync def mission(drone):\n    pass\n",
        },
    )
    assert unsafe.status_code == 400
    assert unsafe.json()["error"]["code"] == "INVALID_COMMAND"


def test_run_queries_diagnostic_export_and_command_free_replay(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    started = client.post(
        "/api/v1/missions/hover/start",
        headers=auth_headers("start-for-replay"),
        json={"vehicle_id": "sim01", "parameters": {"duration_s": 0.1}},
    ).json()
    run_id = started["mission_run_id"]
    wait_for_result(client, run_id)
    events = wait_for_stored_events(client, run_id)
    assert any(event["kind"] == "telemetry" for event in events)
    imu = client.get(f"/api/v1/runs/{run_id}/events?sensor=imu", headers=auth_headers()).json()
    assert imu
    runs = client.get("/api/v1/runs", headers=auth_headers()).json()
    assert any(run["run_id"] == run_id for run in runs)
    diagnostic = client.get(f"/api/v1/runs/{run_id}/diagnostic", headers=auth_headers())
    assert diagnostic.status_code == 200
    assert diagnostic.headers["content-type"] == "application/zip"

    opened = client.post(
        f"/api/v1/replay/{run_id}/open",
        headers=auth_headers("open-replay"),
    )
    assert opened.status_code == 200
    assert opened.json()["event_count"] == len(events)
    stepped = client.post(
        f"/api/v1/replay/{run_id}/control",
        headers=auth_headers("step-replay"),
        json={"action": "step"},
    )
    assert stepped.status_code == 200
    assert stepped.json()["event"] is not None
    assert stepped.json()["event"]["event_id"] == events[0]["event_id"]
    recorded = [EvidenceEvent.model_validate(event) for event in events]
    replay_clock = ReplayClock(recorded)
    replayed = []
    while (event := replay_clock.step()) is not None:
        replayed.append(event)
    assert [event.event_id for event in replayed] == [event.event_id for event in recorded]
    assert replayed[-1].kind is EvidenceKind.MISSION_RESULT
    assert isinstance(replayed[-1].payload, MissionResultPayload)
    assert replayed[-1].payload.result.status.value == "SUCCEEDED"
    schema = client.get("/api/v1/schema", headers=auth_headers()).json()
    replay_paths = [path for path in schema["paths"] if path.startswith("/api/v1/replay")]
    assert replay_paths == [
        "/api/v1/replay/{run_id}/open",
        "/api/v1/replay/{run_id}/control",
    ]


def test_simulation_world_clock_and_fault_routes(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    world = client.get("/api/v1/simulation/world", headers=auth_headers()).json()
    assert world["scenario_id"] == "one-drone-room"
    injected = client.post(
        "/api/v1/simulation/vehicles/sim01/faults",
        headers=auth_headers("fault-1"),
        json={"fault": "localization_loss", "start_s": 10.0, "end_s": 20.0},
    )
    assert injected.status_code == 200
    assert injected.json()["faults"][-1]["fault"] == "localization_loss"
    paused = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("pause-1"),
        json={"action": "pause"},
    )
    assert paused.json()["paused"] is True
    stepped = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("step-1"),
        json={"action": "step"},
    )
    assert stepped.json()["now_s"] > paused.json()["now_s"]
    resumed = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("resume-1"),
        json={"action": "resume"},
    )
    assert resumed.json()["paused"] is False
    unsafe_step = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("step-without-pause"),
        json={"action": "step"},
    )
    assert unsafe_step.status_code == 409
    assert unsafe_step.json()["error"]["message"] == (
        "simulation single-step requires a paused clock"
    )
    runtime.vehicles["sim01"].physics.state.battery_state_of_charge = 0.37
    reset = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("reset-simulation"),
        json={"action": "reset"},
    )
    assert reset.status_code == 200
    assert reset.json()["now_s"] == 0.0
    assert reset.json()["battery_percent"] == runtime.vehicles["sim01"].config.battery_start_percent
    assert reset.json()["reset_scope"] == ["clock", "pose", "battery", "model_state"]
    connected = client.post(
        "/api/v1/vehicles/sim01/connect",
        headers=auth_headers("connect-before-clock-control"),
        json={},
    )
    assert connected.status_code == 200
    unsafe_pause = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("pause-connected-vehicle"),
        json={"action": "pause"},
    )
    assert unsafe_pause.status_code == 409
    assert unsafe_pause.json()["error"]["message"] == (
        "simulation clock controls require a disconnected vehicle"
    )


def test_authenticated_operator_emergency_preempts_mission_owned_lease(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    runtime.missions.register(BlockingMission())
    started = client.post(
        "/api/v1/missions/blocking/start",
        headers=auth_headers("start-emergency-mission"),
        json={"vehicle_id": "sim01", "preset": "fast"},
    )
    assert started.status_code == 200
    run_id = started.json()["mission_run_id"]
    for _ in range(200):
        snapshot = client.get(f"/api/v1/mission-runs/{run_id}", headers=auth_headers()).json()
        if snapshot.get("phase") == "EXECUTING":
            break
        time.sleep(0.005)
    else:
        raise AssertionError("mission did not reach its execution phase")

    session = runtime.supervisor.session("sim01")
    assert session.lease is not None
    assert session.lease.owner_id == f"mission:{run_id}"
    stopped = client.post(
        "/api/v1/vehicles/sim01/emergency-stop",
        headers=auth_headers("operator-emergency-during-mission"),
        json={"reason": "operator confirmed emergency motor cutoff"},
    )
    assert stopped.status_code == 200
    assert runtime.supervisor.session("sim01").state is VehicleState.EMERGENCY
    result = wait_for_result(client, run_id)["result"]
    assert result["status"] == "ABORTED"  # type: ignore[index]
    assert result["reason_code"] == "MISSION_CANCELLED"  # type: ignore[index]
