from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import ApplicationRuntime, create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario

TOKEN = "test-local-token-with-at-least-24-characters"


@pytest.fixture
def api_client(tmp_path: Path) -> Iterator[tuple[TestClient, ApplicationRuntime]]:
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
    app = create_app(runtime, local_token=TOKEN)
    with TestClient(app) as client:
        yield client, runtime


def auth_headers(
    request_id: str | None = None,
    *,
    client_id: str = "client-1",
) -> dict[str, str]:
    headers = {"X-Local-Token": TOKEN}
    if request_id is not None:
        headers.update({"X-Client-ID": client_id, "Idempotency-Key": request_id})
    return headers


def approve_mission_plan(
    client: TestClient,
    mission_id: str,
    request_id: str,
    *,
    vehicle_id: str | None = None,
    client_id: str = "client-1",
) -> dict[str, str]:
    preview = client.get(
        f"/api/v1/mission-files/{mission_id}/preview",
        headers=auth_headers(client_id=client_id),
    )
    preview.raise_for_status()
    preview_body = cast(dict[str, Any], preview.json())
    plan = cast(dict[str, Any], preview_body["plan"])
    acknowledgements = [
        str(finding["code"])
        for finding in cast(list[dict[str, Any]], plan["findings"])
        if finding.get("requires_confirmation") is True
    ]
    body: dict[str, Any] = {
        "expected_plan_sha256": preview_body["plan_sha256"],
        "acknowledged_finding_codes": acknowledgements,
    }
    if vehicle_id is not None:
        body["vehicle_id"] = vehicle_id
    approved = client.post(
        f"/api/v1/mission-files/{mission_id}/approve",
        headers=auth_headers(request_id, client_id=client_id),
        json=body,
    )
    approved.raise_for_status()
    approval = cast(dict[str, str], approved.json())
    return {
        "approval_id": approval["approval_id"],
        "expected_plan_sha256": approval["plan_sha256"],
    }
