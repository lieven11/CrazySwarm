from __future__ import annotations

import csv
import hashlib
import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from crazyswarm_app.api.runtime import ApplicationRuntime
from crazyswarm_app.domain.errors import ErrorCode
from crazyswarm_app.domain.models import Vector3, VehicleIdentity, VehicleState
from crazyswarm_app.missions.models import MissionResult, MissionRunSnapshot, MissionStatus
from crazyswarm_app.observability.events import EvidenceEvent, EvidenceKind, MissionResultPayload
from crazyswarm_app.observability.replay import ReplayClock
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from tests.api.conftest import approve_mission_plan, auth_headers
from tests.missions.test_package_v2 import TWO_ROLE_SOURCE
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


def test_idle_simulator_is_visible_at_home_before_first_mission(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client

    response = client.get("/api/v1/state", headers=auth_headers())

    assert response.status_code == 200
    vehicle = response.json()["vehicles"][0]
    assert runtime.runner.list_runs() == ()
    assert vehicle["state"] == "DISCONNECTED"
    assert vehicle["observation"]["status"] == "NOT_STARTED"
    assert vehicle["observation"]["source_class"] == "SIMULATED_MODEL"
    assert vehicle["observation"]["run_id"] is None
    assert vehicle["telemetry"]["telemetry"]["position_m"] == {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
    }
    assert vehicle["telemetry"]["telemetry"]["ground_truth_position_m"] == {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
    }
    assert vehicle["telemetry"]["telemetry"]["battery_percent"] == 100.0


def test_selectable_mission_preview_stages_declared_roles_without_running(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("upload-preview-roles"),
        json={"name": "Two role preview", "filename": "preview.py", "source": TWO_ROLE_SOURCE},
    ).json()

    response = client.get(
        f"/api/v1/mission-files/{uploaded['mission_id']}/preview",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    preview = response.json()
    assert [(item["vehicle_id"], item["home_m"]) for item in preview["vehicles"]] == [
        ("drone-left", {"x": -0.8, "y": 0.0, "z": 0.0}),
        ("drone-right", {"x": 0.8, "y": 0.0, "z": 0.0}),
    ]
    assert [item["start_m"] for item in preview["vehicles"]] == [
        {"x": -0.8, "y": 0.0, "z": 0.0},
        {"x": 0.8, "y": 0.0, "z": 0.0},
    ]
    assert all(item["existing_vehicle"] is False for item in preview["vehicles"])
    assert all(item["backend_role"] == "FAST_SIM" for item in preview["vehicles"])
    assert all(item["vehicle_state"] is None for item in preview["vehicles"])
    assert preview["vehicles"][0]["planned_commands"][1]["arguments"]["x_m"] == -0.1
    assert preview["vehicles"][1]["planned_commands"][1]["arguments"]["y_m"] == 0.1
    assert all(item["preview_fidelity"] == "EXACT_ROLE" for item in preview["vehicles"])
    assert all(item["minimum_battery_percent"] == 11.0 for item in preview["vehicles"])
    assert preview["plan"]["status"] == "APPROVED"
    assert preview["plan"]["plan_id"].startswith("mission-plan-")
    assert preview["plan"]["planning"]["plugin_selections"]
    assert preview["plan"]["planning"]["route_plans"]
    assert preview["plan"]["planning"]["execution_graph"]["graph_sha256"]
    assert preview["plan"]["planning"]["safety_case"]["safety_case_sha256"]
    assert preview["plan_sha256"]
    assert runtime.runner.list_runs() == ()
    assert set(runtime.vehicles) == {"sim01"}


def test_play_requires_exact_current_operator_approval(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("upload-approval-required"),
        json={
            "name": "Approval required",
            "filename": "approval.py",
            "source": PYTHON_MISSION,
        },
    ).json()
    mission_id = cast(str, uploaded["mission_id"])

    missing = client.post(
        f"/api/v1/mission-files/{mission_id}/start",
        headers=auth_headers("start-without-plan-approval"),
        json={"execution_mode": "SIMULATION"},
    )

    assert missing.status_code == 409
    assert "exact current mission plan" in missing.json()["error"]["message"]
    assert runtime.executions == {}

    approval = approve_mission_plan(
        client,
        mission_id,
        "approve-before-plan-change",
    )
    changed = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("change-battery-after-approval"),
        json={"action": "recharge", "battery_percent": 75},
    )
    assert changed.status_code == 200
    stale = client.post(
        f"/api/v1/mission-files/{mission_id}/start",
        headers=auth_headers("start-stale-plan-approval"),
        json={"execution_mode": "SIMULATION", **approval},
    )

    assert stale.status_code == 409
    assert "stale" in stale.json()["error"]["message"]
    assert runtime.executions == {}


def test_mission_plan_blocks_unsafe_route_before_execution_provisioning(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    source = """\
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.move_relative(x_m=3.0, duration_s=10.0, frame="home")
    await drone.land(duration_s=2.0)
"""
    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("upload-unsafe-planned-route"),
        json={"name": "Unsafe planned route", "filename": "unsafe.py", "source": source},
    ).json()

    preview = client.get(
        f"/api/v1/mission-files/{uploaded['mission_id']}/preview",
        headers=auth_headers(),
    )
    started = client.post(
        f"/api/v1/mission-files/{uploaded['mission_id']}/start",
        headers=auth_headers("reject-unsafe-planned-route"),
        json={"execution_mode": "SIMULATION"},
    )

    assert preview.status_code == 200
    assert preview.json()["plan"]["status"] == "BLOCKED"
    assert started.status_code == 409
    error = started.json()["error"]
    assert error["code"] == ErrorCode.PREFLIGHT_FAILED.value
    assert "TARGET_OUTSIDE_FLIGHT_VOLUME" in {item["code"] for item in error["details"]["findings"]}
    assert runtime.executions == {}
    assert runtime.runner.list_runs() == ()
    assert set(runtime.vehicles) == {"sim01"}


def test_confirmed_low_battery_uploaded_mission_reaches_simulation_execution(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    battery = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("set-critical-scenario-battery"),
        json={"action": "recharge", "battery_percent": 5},
    )
    assert battery.status_code == 200

    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("upload-critical-scenario"),
        json={
            "name": "Critical battery scenario",
            "filename": "critical_battery.py",
            "source": PYTHON_MISSION,
        },
    ).json()
    approval = approve_mission_plan(
        client,
        uploaded["mission_id"],
        "approve-critical-scenario",
    )
    started = client.post(
        f"/api/v1/mission-files/{uploaded['mission_id']}/start",
        headers=auth_headers("start-critical-scenario"),
        json={
            "execution_mode": "SIMULATION",
            "confirm_low_battery_risk": True,
            **approval,
        },
    )
    assert started.status_code == 200

    snapshot = wait_for_result(client, started.json()["mission_run_id"])
    result = cast(dict[str, object], snapshot["result"])
    assert result["reason_code"] != ErrorCode.PREFLIGHT_FAILED.value
    assert any(
        event.event_type == "PREFLIGHT_COMPLETED"
        and event.details.get("simulation_low_battery_override") is True
        for event in runtime.supervisor.events
    )


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
    assert fields["position_m"]["fidelity_manifest_id"] == "crazyflie-6dof-v2"
    assert fields["motors"]["model_version"] == "2.0.0"
    assert "link_quality_percent" not in fields


def test_repeated_and_completed_mission_cancellation_is_idempotent(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    started = client.post(
        "/api/v1/missions/hover/start",
        headers=auth_headers("start-cancel-idempotency"),
        json={"vehicle_id": "sim01", "parameters": {"duration_s": 30.0}},
    )
    assert started.status_code == 200
    run_id = started.json()["mission_run_id"]

    for _ in range(100):
        snapshot = client.get(f"/api/v1/mission-runs/{run_id}", headers=auth_headers()).json()
        if snapshot.get("phase") == "EXECUTING":
            break
        time.sleep(0.005)
    else:
        raise AssertionError("mission did not start executing")

    first = client.post(
        f"/api/v1/mission-runs/{run_id}/cancel",
        headers=auth_headers("cancel-idempotency-1"),
    )
    second = client.post(
        f"/api/v1/mission-runs/{run_id}/cancel",
        headers=auth_headers("cancel-idempotency-2"),
    )
    assert first.status_code == second.status_code == 200
    snapshot = wait_for_result(client, run_id)
    assert snapshot["phase"] == "COMPLETE"
    assert snapshot["result"]["status"] == "ABORTED"  # type: ignore[index]

    completed = client.post(
        f"/api/v1/mission-runs/{run_id}/cancel",
        headers=auth_headers("cancel-idempotency-complete"),
    )
    assert completed.status_code == 200
    assert completed.json()["result"]["status"] == "ABORTED"
    assert run_id not in runtime.mission_tasks


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

    approval = approve_mission_plan(
        client,
        mission_id,
        "approve-python-simulation",
        vehicle_id="sim01",
    )
    started = client.post(
        f"/api/v1/mission-files/{mission_id}/start",
        headers=auth_headers("start-python-simulation"),
        json={
            "vehicle_id": "sim01",
            "execution_mode": "SIMULATION",
            **approval,
        },
    )
    assert started.status_code == 200
    snapshot = wait_for_result(client, started.json()["mission_run_id"])
    assert snapshot["result"]["status"] == "SUCCEEDED"  # type: ignore[index]
    result = cast(dict[str, object], snapshot["result"])
    assert result["mission_source_sha256"] == uploaded.json()["source_sha256"]
    assert result["mission_runtime_id"] == "restricted-python-online"
    assert result["vehicle_adapter"] == "sim"
    assert result["physics_model_id"] == "crazyflie-6dof"
    assert result["physics_model_version"] == "2.0.0"
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
    client, runtime = api_client
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
    run = next(run for run in runs if run["run_id"] == run_id)
    artifact = run["artifacts"][0]
    assert artifact == {
        "kind": "TELEMETRY_CSV",
        "filename": artifact["filename"],
        "media_type": "text/csv",
        "schema_version": "run-telemetry-v1",
        "download_url": f"/api/v1/run-files/{run_id}/telemetry.csv",
        "available": True,
        "unavailable_reason": None,
        "row_count": len([event for event in events if event["kind"] == "telemetry"]),
    }
    assert artifact["filename"].endswith(f"_{run_id}_telemetry-v1.csv")
    assert client.get(artifact["download_url"]).status_code == 401
    telemetry_csv = client.get(artifact["download_url"], headers=auth_headers())
    assert telemetry_csv.status_code == 200
    assert telemetry_csv.headers["content-type"] == "text/csv; charset=utf-8"
    assert telemetry_csv.headers["content-disposition"] == (
        f'attachment; filename="{artifact["filename"]}"'
    )
    assert telemetry_csv.headers["x-crazyswarm-csv-schema"] == "run-telemetry-v1"
    assert int(telemetry_csv.headers["x-crazyswarm-row-count"]) == artifact["row_count"]
    csv_sha256 = hashlib.sha256(telemetry_csv.content).hexdigest()
    assert telemetry_csv.headers["x-crazyswarm-content-sha256"] == csv_sha256
    assert telemetry_csv.headers["etag"] == f'"{csv_sha256}"'
    csv_rows = list(csv.DictReader(io.StringIO(telemetry_csv.text, newline="")))
    assert len(csv_rows) == artifact["row_count"]
    assert {row["run_id"] for row in csv_rows} == {run_id}
    assert [int(row["event_sequence"]) for row in csv_rows] == sorted(
        int(row["event_sequence"]) for row in csv_rows
    )
    repeated_csv = client.get(artifact["download_url"], headers=auth_headers())
    assert repeated_csv.content == telemetry_csv.content
    assert repeated_csv.headers["etag"] == telemetry_csv.headers["etag"]
    mission_files = client.get("/api/v1/run-files", headers=auth_headers())
    assert mission_files.status_code == 200
    mission_file = next(
        item for item in mission_files.json() if item["mission_execution_id"] == run_id
    )
    assert mission_file["mission_name"] == "Take off, hover, and land"
    assert mission_file["status"] == "SUCCEEDED"
    persisted_artifact = mission_file["artifact"]
    assert persisted_artifact["run_ids"] == [run_id]
    assert persisted_artifact["vehicle_ids"] == ["sim01"]
    assert persisted_artifact["telemetry_row_count"] == artifact["row_count"]
    assert persisted_artifact["size_bytes"] == len(telemetry_csv.content)
    assert persisted_artifact["sha256"] == csv_sha256
    assert persisted_artifact["download_url"] == (f"/api/v1/run-files/{run_id}/telemetry.csv")
    persisted_csv = client.get(
        persisted_artifact["download_url"],
        headers=auth_headers(),
    )
    assert persisted_csv.status_code == 200
    assert persisted_csv.content == telemetry_csv.content
    persisted = runtime.store.get_persisted_mission_file(run_id)
    assert persisted["path"].is_file()
    evaluation_view = client.get(
        f"/api/v1/run-files/{run_id}/evaluation",
        headers=auth_headers(),
    )
    assert evaluation_view.status_code == 200
    assert evaluation_view.json()["mission_execution_id"] == run_id
    assert evaluation_view.json()["status"] == "INCOMPLETE"
    assert "accepted_plan" in evaluation_view.json()["evidence"]["missing"]
    evaluation_artifact = mission_file["evaluation"]
    assert evaluation_artifact["available"] is True
    evaluation_download = client.get(
        evaluation_artifact["download_url"],
        headers=auth_headers(),
    )
    assert evaluation_download.status_code == 200
    assert evaluation_download.json()["report_sha256"] == (evaluation_artifact["report_sha256"])
    bundle_artifact = mission_file["bundle"]
    assert bundle_artifact["available"] is True
    bundle_download = client.get(
        bundle_artifact["download_url"],
        headers=auth_headers(),
    )
    assert bundle_download.status_code == 200
    assert bundle_download.json()["mission_execution_id"] == run_id
    annotated = client.post(
        f"/api/v1/run-files/{run_id}/annotations",
        headers=auth_headers("annotate-run"),
        json={"note": "landing looked early"},
    )
    assert annotated.status_code == 200
    assert annotated.json()["annotation"]["note"] == "landing looked early"
    assert annotated.json()["evaluation"]["annotations"][0]["author_id"] == "client-1"
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
    deleted = client.delete(
        f"/api/v1/run-files/{run_id}",
        headers=auth_headers("delete-run-files"),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted_run_ids"] == [run_id]
    assert not any(
        item["mission_execution_id"] == run_id
        for item in client.get("/api/v1/run-files", headers=auth_headers()).json()
    )
    assert not any(
        item["run_id"] == run_id
        for item in client.get("/api/v1/runs", headers=auth_headers()).json()
    )
    schema = client.get("/api/v1/schema", headers=auth_headers()).json()
    replay_paths = [path for path in schema["paths"] if path.startswith("/api/v1/replay")]
    assert replay_paths == [
        "/api/v1/replay/{run_id}/open",
        "/api/v1/replay/{run_id}/control",
    ]


def test_telemetry_csv_rejects_unknown_and_incomplete_but_exports_aborted_run(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    started = client.post(
        "/api/v1/missions/hover/start",
        headers=auth_headers("start-for-csv-states"),
        json={"vehicle_id": "sim01", "parameters": {"duration_s": 0.1}},
    ).json()
    source_run_id = started["mission_run_id"]
    wait_for_result(client, source_run_id)
    source = runtime.store.get_run(source_run_id)
    snapshot = MissionRunSnapshot.model_validate_json(source["snapshot_json"])
    result = MissionResult.model_validate_json(source["result_json"])

    incomplete_id = "run-api-incomplete-csv"
    runtime.store.begin_run(
        snapshot.model_copy(
            update={
                "mission_run_id": incomplete_id,
                "mission_execution_id": incomplete_id,
            }
        )
    )
    incomplete = client.get(f"/api/v1/runs/{incomplete_id}/telemetry.csv", headers=auth_headers())
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "RUN_INCOMPLETE"
    deleting_incomplete = client.delete(
        f"/api/v1/run-files/{incomplete_id}",
        headers=auth_headers("delete-incomplete-run-files"),
    )
    assert deleting_incomplete.status_code == 409
    assert deleting_incomplete.json()["error"]["code"] == "INVALID_STATE"

    aborted_id = "run-api-aborted-csv"
    runtime.store.begin_run(
        snapshot.model_copy(
            update={
                "mission_run_id": aborted_id,
                "mission_execution_id": aborted_id,
            }
        )
    )
    runtime.store.complete_run(
        result.model_copy(
            update={
                "mission_run_id": aborted_id,
                "mission_execution_id": aborted_id,
                "status": MissionStatus.ABORTED,
                "reason_code": "OPERATOR_CANCELLED",
            }
        )
    )
    aborted = client.get(f"/api/v1/runs/{aborted_id}/telemetry.csv", headers=auth_headers())
    assert aborted.status_code == 200
    assert aborted.headers["x-crazyswarm-row-count"] == "0"
    assert len(list(csv.reader(io.StringIO(aborted.text, newline="")))) == 1

    missing = client.get("/api/v1/runs/missing/telemetry.csv", headers=auth_headers())
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"


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
    simulated_vehicle = cast(SimulatedVehicle, runtime.vehicles["sim01"])
    simulated_vehicle.physics.state.battery_state_of_charge = 0.37
    simulated_vehicle.physics.state.position_m = Vector3(x=0.4, y=-0.2, z=0.3)
    before_pose_reset_s = simulated_vehicle.clock.now_s
    pose_reset = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("reset-simulation-pose"),
        json={"action": "reset_pose"},
    )
    assert pose_reset.status_code == 200
    assert pose_reset.json()["now_s"] == before_pose_reset_s
    assert pose_reset.json()["position_m"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert pose_reset.json()["reset_scope"] == ["pose", "motion", "estimator_state"]
    assert simulated_vehicle.battery_percent == 37.0
    pose_telemetry = runtime.supervisor.session("sim01").telemetry
    assert pose_telemetry is not None
    assert pose_telemetry.telemetry.ground_truth_position_m == Vector3()

    simulated_vehicle.physics.state.position_m = Vector3(x=-0.3, y=0.2, z=0.1)
    simulated_vehicle.physics.state.battery_state_of_charge = 0.22
    recharge = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("recharge-simulation"),
        json={"action": "recharge", "battery_percent": 18.5},
    )
    assert recharge.status_code == 200
    assert recharge.json()["battery_percent"] == 18.5
    assert recharge.json()["reset_scope"] == ["battery"]
    assert simulated_vehicle.true_position_m == Vector3(x=-0.3, y=0.2, z=0.1)
    battery_telemetry = runtime.supervisor.session("sim01").telemetry
    assert battery_telemetry is not None
    assert battery_telemetry.telemetry.battery_percent == 18.5

    simulated_vehicle.physics.state.position_m = Vector3(x=-0.2, y=0.1, z=0.0)
    # A modeled cutoff can finish adapter-side as FAULT while the supervisor is
    # still reconciling the serialized ABORTING lifecycle state.
    simulated_vehicle._state = VehicleState.FAULT
    simulated_vehicle._armed = False
    simulated_vehicle._flying = False
    runtime.supervisor.session("sim01").state = VehicleState.ABORTING
    recovered = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("recharge-aborted-simulation"),
        json={"action": "recharge", "battery_percent": 100},
    )
    assert recovered.status_code == 200
    assert recovered.json()["battery_percent"] == 100.0
    assert runtime.supervisor.session("sim01").state is VehicleState.DISCONNECTED
    assert simulated_vehicle.true_position_m == Vector3(x=-0.2, y=0.1, z=0.0)

    simulated_vehicle.physics.state.battery_state_of_charge = 0.37
    reset = client.post(
        "/api/v1/simulation/vehicles/sim01/clock",
        headers=auth_headers("reset-simulation"),
        json={"action": "reset"},
    )
    assert reset.status_code == 200
    assert reset.json()["now_s"] == 0.0
    assert reset.json()["battery_percent"] == simulated_vehicle.config.battery_start_percent
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


def test_simulation_fleet_reset_replaces_the_previous_visible_roster(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    primary = cast(SimulatedVehicle, runtime.vehicles["sim01"])
    stale = SimulatedVehicle(
        VehicleIdentity(
            vehicle_id="stale-from-previous-mission",
            display_name="Stale previous mission drone",
            adapter="sim",
        ),
        primary.world,
        config=primary.config,
        initial_position_m=Vector3(x=0.7, y=0.3, z=0.0),
    )
    runtime.vehicles[stale.identity.vehicle_id] = stale
    runtime.supervisor.register_vehicle(stale)
    runtime.active_vehicle_ids = {"sim01", stale.identity.vehicle_id}
    connected = client.post(
        "/api/v1/vehicles/sim01/connect",
        headers=auth_headers("connect-before-fleet-reset"),
        json={},
    )
    assert connected.status_code == 200
    assert runtime.supervisor.session("sim01").state is VehicleState.READY

    before = client.get("/api/v1/state", headers=auth_headers()).json()
    assert {item["identity"]["vehicle_id"] for item in before["vehicles"]} == {
        "sim01",
        "stale-from-previous-mission",
    }

    reset = client.post(
        "/api/v1/simulation/fleet/reset-poses",
        headers=auth_headers("reset-selected-simulation-fleet"),
        json={"vehicle_ids": ["sim01"]},
    )

    assert reset.status_code == 200
    assert reset.json()["vehicle_ids"] == ["sim01"]
    assert reset.json()["reset_scope"] == [
        "active_fleet",
        "pose",
        "motion",
        "estimator_state",
    ]
    assert runtime.supervisor.session("sim01").state is VehicleState.DISCONNECTED
    after = client.get("/api/v1/state", headers=auth_headers()).json()
    assert [item["identity"]["vehicle_id"] for item in after["vehicles"]] == ["sim01"]


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
    assert result["reason_code"] == "EMERGENCY_STOPPED"  # type: ignore[index]


def test_slow_run_history_read_does_not_block_state_or_health(
    api_client: tuple[TestClient, ApplicationRuntime],
    monkeypatch: MonkeyPatch,
) -> None:
    client, runtime = api_client
    original = runtime.store.list_runs
    query_started = threading.Event()
    release_query = threading.Event()

    def slow_list_runs(*, vehicle_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query_started.set()
        assert release_query.wait(2.0)
        return original(vehicle_id=vehicle_id, limit=limit)

    monkeypatch.setattr(runtime.store, "list_runs", slow_list_runs)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                client.get,
                "/api/v1/runs?limit=20",
                headers=auth_headers(),
            )
            assert query_started.wait(1.0)
            started = time.perf_counter()
            health = client.get("/api/v1/health", headers=auth_headers())
            state = client.get("/api/v1/state", headers=auth_headers())
            elapsed = time.perf_counter() - started
            release_query.set()
            runs = future.result(timeout=2.0)
    finally:
        release_query.set()

    assert runs.status_code == 200
    assert health.status_code == 200
    assert state.status_code == 200
    assert elapsed < 0.5
