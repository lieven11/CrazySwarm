from __future__ import annotations

import time

from fastapi.testclient import TestClient

from crazyswarm_app.api.runtime import ApplicationRuntime
from tests.api.conftest import TOKEN, auth_headers
from tests.api.test_missions_and_replay import wait_for_result


def test_websocket_auth_rate_contract_and_disconnect_is_not_a_safety_dependency(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    with client.websocket_connect(
        f"/api/v1/ws/events?token={TOKEN}&client_id=ui-1&rate_hz=10"
    ) as socket:
        connected = socket.receive_json()
        assert connected == {
            "type": "connected",
            "client_id": "ui-1",
            "rate_hz": 10.0,
            "mode": "SIM",
        }
        runtime.bridge.operator_action(
            vehicle_id="sim01",
            client_id="ui-1",
            request_id="ws-action",
            action="inspect",
        )
        event = socket.receive_json()
        assert event["type"] == "event"
        assert event["data"]["kind"] == "operator_action"

    # Only the independent recorder subscription remains after the UI goes away.
    for _ in range(20):
        if runtime.bus.stats.subscriber_count == 1:
            break
        time.sleep(0.005)
    assert runtime.bus.stats.subscriber_count == 1

    started = client.post(
        "/api/v1/missions/hover/start",
        headers=auth_headers("mission-after-ws"),
        json={"vehicle_id": "sim01", "parameters": {"duration_s": 0.1}},
    )
    result = wait_for_result(client, started.json()["mission_run_id"])
    assert result["result"]["status"] == "SUCCEEDED"  # type: ignore[index]
