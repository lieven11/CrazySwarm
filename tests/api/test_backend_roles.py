from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.simulation.world import load_scenario
from crazyswarm_app.vehicles.mock_isaac import MockIsaacSimVehicle
from tests.api.conftest import TOKEN, approve_mission_plan, auth_headers
from tests.api.test_missions_and_replay import wait_for_result


def test_api_routes_mock_isaac_by_declared_role_not_adapter_name(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    vehicle = MockIsaacSimVehicle(vehicle_id="isaac01")
    runtime = create_runtime(
        config,
        scenario,
        evidence_path=tmp_path / "evidence.sqlite3",
        vehicles_override=(vehicle,),
    )
    app = create_app(runtime, local_token=TOKEN)
    source = (Path("missions/qualification/hover_30s.py")).read_text()
    with TestClient(app) as client:
        view = client.get("/api/v1/vehicles/isaac01", headers=auth_headers()).json()
        assert view["backend"]["role"] == "ISAAC_SIM"
        assert view["backend"]["authority"] == "SIMULATION"
        assert client.get("/api/v1/capabilities", headers=auth_headers()).json()["simulation"]

        unsupported = client.post(
            "/api/v1/simulation/vehicles/isaac01/clock",
            headers=auth_headers("mock-clock-control"),
            json={"action": "pause"},
        )
        assert unsupported.status_code == 409
        assert unsupported.json()["error"]["code"] == "CAPABILITY_MISSING"

        uploaded = client.post(
            "/api/v1/mission-files",
            headers=auth_headers("upload-mock-hover"),
            json={"name": "Mock hover", "filename": "hover_30s.py", "source": source},
        )
        assert uploaded.status_code == 200
        mission_id = uploaded.json()["mission_id"]
        approval = approve_mission_plan(
            client,
            mission_id,
            "approve-mock-hover",
            vehicle_id="isaac01",
        )
        started = client.post(
            f"/api/v1/mission-files/{mission_id}/start",
            headers=auth_headers("start-mock-hover"),
            json={
                "vehicle_id": "isaac01",
                "execution_mode": "SIMULATION",
                **approval,
            },
        )
        assert started.status_code == 200
        result = wait_for_result(client, started.json()["mission_run_id"])["result"]
        assert isinstance(result, dict)
        assert result["status"] == "SUCCEEDED"
        assert result["backend_role"] == "ISAAC_SIM"
        assert result["mission_source_sha256"] == uploaded.json()["source_sha256"]
