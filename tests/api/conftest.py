from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

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
