from __future__ import annotations

import time
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

from crazyswarm_app.api.app import LIVE_STATE_HISTORY_LIMIT, create_app
from crazyswarm_app.api.runtime import ApplicationRuntime, create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    load_versioned_contract,
)
from crazyswarm_app.fleet.preparation import FleetPreparation
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import load_scenario
from crazyswarm_app.vehicles.mock_isaac import MockIsaacSimVehicle
from tests.api.conftest import TOKEN, approve_mission_plan, auth_headers
from tests.missions.test_package_v2 import THREE_ROLE_RESERVE_SOURCE, TWO_ROLE_SOURCE


def test_live_state_caps_history_without_removing_detail_access(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    deployment = load_versioned_contract(
        Path("config/fleet/two-drone-deployment-v1.yaml"), DeploymentManifest
    )
    binding = load_versioned_contract(
        Path("config/fleet/fast-sim-two-drone-binding-v1.yaml"), BackendBindingProfile
    )
    session_ids = [f"history-session-{index:02d}" for index in range(LIVE_STATE_HISTORY_LIMIT + 3)]
    for session_id in session_ids:
        runtime.fleet_preparations[session_id] = FleetPreparation(
            execution_session_id=session_id,
            deployment=deployment,
            binding=binding,
            supervisor=runtime.supervisor,
        )

    response = client.get("/api/v1/state", headers=auth_headers())
    response.raise_for_status()
    visible_ids = [
        item["session"]["execution_session_id"] for item in response.json()["fleet_sessions"]
    ]
    assert visible_ids == session_ids[-LIVE_STATE_HISTORY_LIMIT:]
    assert len(response.content) < 500_000

    detail = client.get(f"/api/v1/fleet/sessions/{session_ids[0]}", headers=auth_headers())
    detail.raise_for_status()
    assert detail.json()["session"]["execution_session_id"] == session_ids[0]


def test_play_derives_two_vehicle_fleet_and_runs_without_operator_assignments(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("upload-v2-fleet"),
        json={"name": "Two roles", "filename": "two_roles.py", "source": TWO_ROLE_SOURCE},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["package_schema_version"] == 2
    assert len(uploaded.json()["logical_roles"]) == 2
    preview = client.get(
        f"/api/v1/mission-files/{uploaded.json()['mission_id']}/preview",
        headers=auth_headers(),
    )
    assert preview.status_code == 200
    expected_plan_id = preview.json()["plan"]["plan_id"]
    approval = approve_mission_plan(
        client,
        uploaded.json()["mission_id"],
        "approve-v2-fleet",
    )

    started = client.post(
        f"/api/v1/mission-files/{uploaded.json()['mission_id']}/start",
        headers=auth_headers("start-v2-fleet"),
        json={"execution_mode": "SIMULATION", **approval},
    )
    assert started.status_code == 200
    assert started.json()["member_count"] == 2
    run_id = started.json()["mission_run_id"]
    session_id = started.json()["execution_session_id"]
    plan_id = started.json()["mission_plan_id"]
    assert plan_id == expected_plan_id

    for _ in range(300):
        status = client.get(f"/api/v1/mission-runs/{run_id}", headers=auth_headers()).json()
        if status.get("result") is not None:
            break
        time.sleep(0.005)
    else:
        raise AssertionError("mission-derived fleet did not finish")

    result = cast(dict[str, object], status["result"])
    assert result["status"] == "SUCCEEDED"
    child_results = cast(list[dict[str, object]], result["child_results"])
    assert {item["vehicle_id"] for item in child_results} == {
        "drone-left",
        "drone-right",
    }
    traces = {
        cast(dict[str, object], item["mission_result"])["vehicle_id"]: cast(
            dict[str, object], item["mission_result"]
        )["normalized_intent_trace"]
        for item in child_results
    }
    assert traces["drone-left"] != traces["drone-right"]
    mission_results = [cast(dict[str, object], item["mission_result"]) for item in child_results]
    assert all(result["goal_captures"] for result in mission_results)
    for mission_result in mission_results:
        capture = cast(list[dict[str, object]], mission_result["goal_captures"])[0]
        assert capture["outcome"] == "CAPTURED"
        assert capture["descent_authorized"] is True
        assert capture["terminal_state"] == "READY"
        assert capture["terminal_contact"] == "SIMULATED_GROUND_CONTACT"

    state_response = client.get("/api/v1/state", headers=auth_headers())
    state = state_response.json()
    assert state["schema_version"] == 2
    assert len(state_response.content) < 200_000
    assert {item["identity"]["vehicle_id"] for item in state["vehicles"]} == {
        "drone-left",
        "drone-right",
    }
    assert all(item["telemetry"] is not None for item in state["vehicles"])
    session = next(
        item
        for item in state["fleet_sessions"]
        if item["session"]["execution_session_id"] == session_id
    )
    assert session["fleet_run_status"] == "SUCCEEDED"
    assert "events" not in session["session"]
    assert "latest_telemetry" not in session["session"]["vehicles"][0]
    assert "preparation" not in session["execution"]
    assert set(session["execution"]) >= {
        "execution_session_id",
        "execution_run_id",
        "mission_plan_id",
        "mission_plan_sha256",
        "status",
        "reason_code",
        "message",
    }
    assert session["execution"]["schema_version"] == 2
    assert session["execution"]["mission_plan_id"] == plan_id
    detail = client.get(f"/api/v1/fleet/sessions/{session_id}", headers=auth_headers()).json()
    assert detail["execution"]["mission_plan_id"] == plan_id
    assert detail["execution"]["mission_plan"]["status"] == "APPROVED"
    events = detail["session"]["events"]
    assert {item["event_type"] for item in events} >= {
        "PLACEHOLDER_DECLARED",
        "IDENTITY_VERIFIED",
        "CONNECTION_READY",
        "TELEMETRY_STABILIZED",
        "PREFLIGHT_APPROVED",
    }
    assert runtime.fleet_tasks == {}
    assert runtime.mission_tasks == {}
    evaluation = client.get(
        f"/api/v1/run-files/{run_id}/evaluation",
        headers=auth_headers(),
    )
    assert evaluation.status_code == 200
    assert evaluation.json()["status"] == "COMPLETE"
    assert evaluation.json()["evidence"]["complete"] is True
    assert evaluation.json()["fleet"]["vehicle_count"] == 2
    assert evaluation.json()["vehicle_ids"] == ["drone-left", "drone-right"]
    assert all(
        item["landing_goal_id"] is not None
        and item["descent_authorized"] is True
        and item["terminal_goal_capture_margin_m"] >= 0.0
        and item["terminal_contact"] == "SIMULATED_GROUND_CONTACT"
        for item in evaluation.json()["vehicles"]
    )
    run_file = next(
        item
        for item in client.get("/api/v1/run-files", headers=auth_headers()).json()
        if item["mission_execution_id"] == run_id
    )
    assert run_file["evaluation"]["status"] == "COMPLETE"
    assert run_file["evaluation"]["available"] is True
    assert run_file["bundle"]["available"] is True


def test_three_role_package_keeps_reserve_prepared_and_disarmed(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("upload-reserve-package"),
        json={
            "name": "Two active plus reserve",
            "filename": "reserve.py",
            "source": THREE_ROLE_RESERVE_SOURCE,
        },
    ).json()
    approval = approve_mission_plan(
        client,
        uploaded["mission_id"],
        "approve-reserve-package",
    )
    started = client.post(
        f"/api/v1/mission-files/{uploaded['mission_id']}/start",
        headers=auth_headers("start-reserve-package"),
        json=approval,
    ).json()
    for _ in range(300):
        status = client.get(
            f"/api/v1/mission-runs/{started['mission_run_id']}",
            headers=auth_headers(),
        ).json()
        if status.get("result") is not None:
            break
        time.sleep(0.005)
    else:
        raise AssertionError("reserve mission did not finish")
    assert status["result"]["status"] == "SUCCEEDED"
    assert len(status["result"]["child_results"]) == 2
    state = client.get("/api/v1/state", headers=auth_headers()).json()
    assert len(state["vehicles"]) == 3
    session = state["fleet_sessions"][-1]["session"]
    reserve = next(item for item in session["vehicles"] if item["vehicle_id"] == "drone-reserve")
    assert reserve["mission_role"] == "RESERVE"
    assert reserve["observation"] == "COMPLETED_SNAPSHOT"
    assert not any(
        event.vehicle_id == "drone-reserve" and event.message == "arm"
        for event in runtime.supervisor.events
    )


def test_repeated_mission_preserves_dynamic_vehicle_pose_and_battery(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("upload-persistent-v2-fleet"),
        json={"name": "Persistent roles", "filename": "persistent.py", "source": TWO_ROLE_SOURCE},
    ).json()

    def start(request_id: str, *, confirm_low_battery_risk: bool = False) -> str:
        approval = approve_mission_plan(
            client,
            uploaded["mission_id"],
            f"approve-{request_id}",
        )
        response = client.post(
            f"/api/v1/mission-files/{uploaded['mission_id']}/start",
            headers=auth_headers(request_id),
            json={
                "execution_mode": "SIMULATION",
                "confirm_low_battery_risk": confirm_low_battery_risk,
                **approval,
            },
        )
        assert response.status_code == 200
        return cast(str, response.json()["mission_run_id"])

    def wait(run_id: str) -> dict[str, object]:
        for _ in range(300):
            status = client.get(f"/api/v1/mission-runs/{run_id}", headers=auth_headers()).json()
            if status.get("result") is not None:
                return cast(dict[str, object], status)
            time.sleep(0.005)
        raise AssertionError("persistent mission did not finish")

    wait(start("start-persistent-v2-first"))
    left = cast(SimulatedVehicle, runtime.vehicles["drone-left"])
    right = cast(SimulatedVehicle, runtime.vehicles["drone-right"])
    first_left_x = left.true_position_m.x
    first_right_y = right.true_position_m.y

    second_run = start("start-persistent-v2-second")
    assert runtime.vehicles["drone-left"] is left
    assert runtime.vehicles["drone-right"] is right
    second_result = wait(second_run)
    assert cast(dict[str, object], second_result["result"])["status"] == "SUCCEEDED"
    assert left.true_position_m.x < first_left_x - 0.05
    assert right.true_position_m.y > first_right_y + 0.05

    for vehicle_id in ("drone-left", "drone-right"):
        battery = client.post(
            f"/api/v1/simulation/vehicles/{vehicle_id}/clock",
            headers=auth_headers(f"set-{vehicle_id}-battery-5"),
            json={"action": "recharge", "battery_percent": 5},
        )
        assert battery.status_code == 200

    preview = client.get(
        f"/api/v1/mission-files/{uploaded['mission_id']}/preview",
        headers=auth_headers(),
    ).json()
    preview_by_vehicle = {item["vehicle_id"]: item for item in preview["vehicles"]}
    assert preview_by_vehicle["drone-left"]["existing_vehicle"] is True
    assert preview_by_vehicle["drone-right"]["existing_vehicle"] is True
    assert preview_by_vehicle["drone-left"]["backend_role"] == "FAST_SIM"
    assert preview_by_vehicle["drone-right"]["backend_role"] == "FAST_SIM"
    assert preview_by_vehicle["drone-left"]["vehicle_state"] == "DISCONNECTED"
    assert preview_by_vehicle["drone-right"]["vehicle_state"] == "DISCONNECTED"
    assert abs(preview_by_vehicle["drone-left"]["start_m"]["x"] - left.true_position_m.x) < 0.03
    assert abs(preview_by_vehicle["drone-right"]["start_m"]["y"] - right.true_position_m.y) < 0.03
    assert preview_by_vehicle["drone-left"]["battery_percent"] == 5.0
    assert preview_by_vehicle["drone-right"]["battery_percent"] == 5.0

    low_battery_run = start(
        "start-persistent-v2-low-battery",
        confirm_low_battery_risk=True,
    )
    assert runtime.vehicles["drone-left"] is left
    assert runtime.vehicles["drone-right"] is right
    assert left.battery_percent <= 5.0
    assert right.battery_percent <= 5.0
    low_battery_result = cast(dict[str, object], wait(low_battery_run)["result"])
    assert low_battery_result["reason_code"] != "PREFLIGHT_FAILED"
    assert low_battery_result["message"] != "task assignment has inadequate observed energy margin"
    assert len(cast(list[dict[str, object]], low_battery_result["child_results"])) == 2
    assert any(
        event["event_type"] == "TASK_ASSIGNED"
        and cast(dict[str, object], event["details"]).get("simulation_energy_override") is True
        for event in cast(list[dict[str, object]], low_battery_result["events"])
    )


def test_rotation_mission_settles_depleted_member_and_lands_healthy_peer(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    source_path = Path("missions/qualification/persistent_coverage_rotation.py")
    source = source_path.read_text(encoding="utf-8").replace(
        "hover(duration_s=20.0)",
        "hover(duration_s=2.0)",
    )
    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers("upload-low-battery-rotation"),
        json={
            "name": "Persistent coverage rotation",
            "filename": source_path.name,
            "source": source,
        },
    ).json()

    def start(request_id: str, *, confirm: bool = False) -> str:
        approval = approve_mission_plan(
            client,
            uploaded["mission_id"],
            f"approve-{request_id}",
        )
        response = client.post(
            f"/api/v1/mission-files/{uploaded['mission_id']}/start",
            headers=auth_headers(request_id),
            json={
                "execution_mode": "SIMULATION",
                "confirm_low_battery_risk": confirm,
                **approval,
            },
        )
        response.raise_for_status()
        return cast(str, response.json()["mission_run_id"])

    def wait(run_id: str) -> dict[str, object]:
        for _ in range(4_000):
            status = client.get(f"/api/v1/mission-runs/{run_id}", headers=auth_headers()).json()
            if status.get("result") is not None:
                return cast(dict[str, object], status)
            time.sleep(0.005)
        raise AssertionError("rotation mission did not finish")

    first_result = cast(dict[str, object], wait(start("start-rotation-baseline"))["result"])
    assert first_result["status"] == "SUCCEEDED", (
        first_result["reason_code"],
        first_result["message"],
        [
            (
                child["vehicle_id"],
                cast(dict[str, object], child["mission_result"])["status"],
                cast(dict[str, object], child["mission_result"])["reason_code"],
            )
            for child in cast(list[dict[str, object]], first_result["child_results"])
        ],
        [
            (
                event["event_type"],
                event.get("vehicle_id"),
                event.get("task_id"),
                event["details"],
            )
            for event in cast(list[dict[str, object]], first_result["events"])[-12:]
        ],
    )

    for vehicle_id, battery_percent in (
        ("coverage-a", 5.0),
        ("coverage-b", 100.0),
        ("coverage-reserve", 100.0),
    ):
        response = client.post(
            f"/api/v1/simulation/vehicles/{vehicle_id}/clock",
            headers=auth_headers(f"set-rotation-{vehicle_id}-{battery_percent}"),
            json={"action": "recharge", "battery_percent": battery_percent},
        )
        response.raise_for_status()

    result = cast(
        dict[str, object],
        wait(start("start-low-battery-rotation", confirm=True))["result"],
    )
    assert result["status"] == "DEGRADED", (
        result["reason_code"],
        result["message"],
        [
            (
                child["vehicle_id"],
                cast(dict[str, object], child["mission_result"])["status"],
                cast(dict[str, object], child["mission_result"])["reason_code"],
            )
            for child in cast(list[dict[str, object]], result["child_results"])
        ],
        [
            (
                cast(dict[str, object], task["definition"])["task_id"],
                task["owner_vehicle_id"],
            )
            for task in cast(list[dict[str, object]], result["tasks"])
        ],
    )
    children = {
        cast(str, child["vehicle_id"]): cast(dict[str, object], child["mission_result"])
        for child in cast(list[dict[str, object]], result["child_results"])
    }
    assert children["coverage-a"]["status"] == "FAILED"
    assert children["coverage-a"]["reason_code"] == "CRITICAL_BATTERY"
    assert children["coverage-b"]["status"] == "SUCCEEDED"

    depleted = cast(SimulatedVehicle, runtime.vehicles["coverage-a"])
    healthy = cast(SimulatedVehicle, runtime.vehicles["coverage-b"])
    assert depleted.true_position_m.z == 0.0
    assert healthy.true_position_m.z == 0.0
    assert runtime.supervisor.session("coverage-a").state.value == "DISCONNECTED"

    public_state = client.get("/api/v1/state", headers=auth_headers()).json()
    depleted_view = next(
        item for item in public_state["vehicles"] if item["identity"]["vehicle_id"] == "coverage-a"
    )
    assert depleted_view["observation"]["status"] == "COMPLETED_SNAPSHOT"
    assert depleted_view["telemetry"]["telemetry"]["ground_truth_position_m"]["z"] == 0.0
    assert depleted_view["telemetry"]["telemetry"]["position_m"]["z"] < 0.01


def test_same_v2_package_runs_through_mock_isaac(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    runtime = create_runtime(
        config,
        scenario,
        evidence_path=tmp_path / "evidence.sqlite3",
        vehicles_override=(MockIsaacSimVehicle("isaac01"),),
    )
    with TestClient(create_app(runtime, local_token=TOKEN)) as client:
        uploaded = client.post(
            "/api/v1/mission-files",
            headers=auth_headers("upload-v2-mock"),
            json={"name": "Mock two roles", "filename": "mock.py", "source": TWO_ROLE_SOURCE},
        ).json()
        approval = approve_mission_plan(
            client,
            uploaded["mission_id"],
            "approve-v2-mock",
        )
        started = client.post(
            f"/api/v1/mission-files/{uploaded['mission_id']}/start",
            headers=auth_headers("start-v2-mock"),
            json=approval,
        )
        assert started.status_code == 200
        run_id = started.json()["mission_run_id"]
        for _ in range(400):
            status = client.get(f"/api/v1/mission-runs/{run_id}", headers=auth_headers()).json()
            if status.get("result") is not None:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("mock Isaac fleet did not finish")
        assert status["result"]["status"] == "SUCCEEDED"
        assert {
            item["mission_result"]["backend_role"] for item in status["result"]["child_results"]
        } == {"ISAAC_SIM"}
    assert set(runtime.vehicles) == {"isaac01"}
    assert set(runtime.telemetry_tasks) == set()
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}
    assert runtime.session_created_vehicle_ids == {}
