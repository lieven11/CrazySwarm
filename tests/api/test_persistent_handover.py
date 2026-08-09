from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import ApplicationRuntime, create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.commands import (
    AbortCommand,
    ArmCommand,
    CommandEnvelope,
    FleetCommandBinding,
    LandCommand,
    MoveRelativeCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import CommandSource, OperatingMode
from crazyswarm_app.fleet.docks import DockHealth, DockManager, DockReservation
from crazyswarm_app.fleet.persistent import HandoverRecord
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.faults import FaultType, FaultWindow
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import load_scenario
from tests.api.conftest import TOKEN, approve_mission_plan, auth_headers


@dataclass
class CommandCapture:
    commands: list[CommandEnvelope] = field(default_factory=list)

    def command_sent(self, command: CommandEnvelope) -> None:
        self.commands.append(command)

    def __getattr__(self, name: str) -> Any:
        del name
        return lambda value: None


def _upload_and_start_baseline(
    client: TestClient,
) -> tuple[str, dict[str, object]]:
    source_path = Path("missions/qualification/persistent_coverage_rotation.py")
    mission_id = _upload_source(
        client,
        source_path.read_text(encoding="utf-8"),
        request_id="upload-live-persistent-handover",
        name="Live persistent coverage handover",
    )
    baseline = _start(client, mission_id, "start-live-persistent-baseline")
    baseline_result = cast(dict[str, object], baseline["result"])
    assert baseline_result["status"] == "SUCCEEDED", (
        baseline_result["reason_code"],
        baseline_result["message"],
    )
    return mission_id, baseline


def _upload_source(
    client: TestClient,
    source: str,
    *,
    request_id: str,
    name: str,
) -> str:
    uploaded = client.post(
        "/api/v1/mission-files",
        headers=auth_headers(request_id),
        json={
            "name": name,
            "filename": "persistent_coverage_rotation.py",
            "source": source,
        },
    )
    uploaded.raise_for_status()
    return cast(str, uploaded.json()["mission_id"])


def _start(
    client: TestClient,
    mission_id: str,
    request_id: str,
    *,
    confirm_low_battery_risk: bool = False,
) -> dict[str, object]:
    approval = approve_mission_plan(
        client,
        mission_id,
        f"approve-{request_id}",
    )
    started = client.post(
        f"/api/v1/mission-files/{mission_id}/start",
        headers=auth_headers(request_id),
        json={
            "execution_mode": "SIMULATION",
            "confirm_low_battery_risk": confirm_low_battery_risk,
            **approval,
        },
    )
    assert started.status_code == 200, started.json()
    run_id = cast(str, started.json()["mission_run_id"])
    return _wait_for_terminal(client, run_id)


def _wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(8_000):
        status = client.get(
            f"/api/v1/mission-runs/{run_id}",
            headers=auth_headers(),
        ).json()
        if status.get("result") is not None:
            return cast(dict[str, object], status)
        time.sleep(0.005)
    raise AssertionError(f"persistent handover did not reach a terminal state: {status}")


def _set_batteries(
    client: TestClient,
    values: dict[str, float],
) -> None:
    for vehicle_id, battery_percent in values.items():
        response = client.post(
            f"/api/v1/simulation/vehicles/{vehicle_id}/clock",
            headers=auth_headers(f"battery-{vehicle_id}-{battery_percent}"),
            json={"action": "recharge", "battery_percent": battery_percent},
        )
        response.raise_for_status()


def test_normal_play_executes_live_generation_two_reserve_handover(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    capture = CommandCapture()
    runtime.supervisor.add_audit_sink(capture)
    _set_batteries(
        client,
        {
            "coverage-a": 56.0,
            "coverage-b": 100.0,
            "coverage-reserve": 100.0,
        },
    )

    status = _start(client, mission_id, "start-live-persistent-handover")
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "SUCCEEDED", (result["reason_code"], result["message"])
    assert result["reason_code"] == "PERSISTENT_HANDOVER_COMPLETED"

    persistent = cast(dict[str, object], result["persistent_coverage"])
    assert persistent["status"] == "SUCCEEDED"
    assert cast(dict[str, str], persistent["active_owners"])["zone_a"] == ("coverage-reserve")
    handover = cast(list[dict[str, object]], persistent["handovers"])[0]
    assert handover["takeover_confirmed"] is True
    assert handover["incoming_lease_generation"] == 2

    transitions = cast(list[dict[str, object]], result["authority_transitions"])
    assert len(transitions) == 2
    assert {(item["previous_task_id"], item["current_task_id"]) for item in transitions} == {
        ("zone_a", "return-zone_a"),
        ("staging-zone_a", "zone_a"),
    }
    assert (
        next(item for item in transitions if item["current_task_id"] == "zone_a")[
            "current_task_lease_generation"
        ]
        == 2
    )

    children = cast(list[dict[str, object]], result["child_results"])
    assert {item["vehicle_id"] for item in children} == {
        "coverage-a",
        "coverage-b",
        "coverage-reserve",
    }
    assert all(
        cast(dict[str, object], item["mission_result"])["status"] == "SUCCEEDED"
        for item in children
    )
    reserve_intent = cast(
        list[dict[str, object]],
        next(
            cast(dict[str, object], item["mission_result"])
            for item in children
            if item["vehicle_id"] == "coverage-reserve"
        )["normalized_intent_trace"],
    )
    reserve_actions = [item["action"] for item in reserve_intent]
    assert reserve_actions[:3] == ["takeoff", "move_relative", "hover"]
    assert reserve_actions[-4:] == [
        "move_relative",
        "hover",
        "move_relative",
        "land",
    ]
    assert set(reserve_actions[3:-4]) <= {"hover"}

    dock = cast(list[dict[str, object]], result["dock_snapshots"])[0]
    reservation = cast(list[dict[str, object]], dock["reservations"])[0]
    assert reservation["state"] == "READY"
    assert reservation["modeled_charging_confirmed"] is True
    metrics = cast(dict[str, object], result["metrics"])
    assert len(cast(list[object], metrics["handovers"])) == 1
    assert len(cast(list[object], metrics["docks"])) == 1
    assert cast(float, metrics["coverage_gap_duration_s"]) >= 0.0
    assert cast(dict[str, float], metrics["task_assignment_latency_s"]).keys() == {
        "zone_a",
        "zone_b",
    }
    assert result["critical_violations"] == 0
    assert cast(float, result["minimum_separation_m"]) > 0.5
    fleet_events = cast(list[dict[str, object]], result["events"])
    recovery = next(
        item for item in fleet_events if item["event_type"] == "RECOVERY_PROPOSAL_EVALUATED"
    )
    recovery_details = cast(dict[str, object], recovery["details"])
    assert recovery_details["strategy_plugin_id"] == "recovery.low-battery"
    assert recovery_details["proposed_action"] == "HANDOVER"
    assert recovery_details["authorized"] is True
    assert any(
        item["event_type"] == "TAKEOVER_POSITION_CONFIRMED"
        and cast(dict[str, object], item["details"])["separation_state"] == "CLEAR"
        for item in fleet_events
    )
    public_state = client.get("/api/v1/state", headers=auth_headers()).json()
    operator_session = next(
        item
        for item in public_state["fleet_sessions"]
        if item["fleet_run_id"] == result["fleet_run_id"]
    )
    coordination = cast(dict[str, object], operator_session["coordination"])
    assert cast(dict[str, str], coordination["vehicle_states"])["coverage-reserve"] == ("ACTIVE")
    operator_handover = cast(list[dict[str, object]], coordination["handovers"])[0]
    assert operator_handover["phase"] == "COMPLETED"
    assert operator_handover["incoming_lease_generation"] == 2
    assert operator_handover["takeover_confirmed"] is True
    assert coordination["minimum_separation_m"] == result["minimum_separation_m"]
    assert coordination["authority_transition_count"] == 2
    operator_dock = cast(list[dict[str, object]], coordination["dock_snapshots"])[0]
    assert cast(list[dict[str, object]], operator_dock["reservations"])[0]["state"] == ("READY")

    outgoing_commands = [item for item in capture.commands if item.vehicle_id == "coverage-a"]
    assert any(
        item.fleet is not None
        and item.fleet.task_id == "zone_a"
        and item.fleet.task_lease_generation == 1
        for item in outgoing_commands
    )
    assert any(
        isinstance(item.payload, LandCommand)
        and item.fleet is not None
        and item.fleet.task_id == "return-zone_a"
        and item.fleet.task_lease_generation == 1
        for item in outgoing_commands
    )
    incoming_commands = [item for item in capture.commands if item.vehicle_id == "coverage-reserve"]
    assert any(
        isinstance(item.payload, MoveRelativeCommand)
        and item.fleet is not None
        and item.fleet.task_id == "staging-zone_a"
        and item.fleet.task_lease_generation == 1
        for item in incoming_commands
    )
    assert any(
        isinstance(item.payload, MoveRelativeCommand)
        and item.fleet is not None
        and item.fleet.task_id == "zone_a"
        and item.fleet.task_lease_generation == 2
        for item in incoming_commands
    )
    takeover_event_index = next(
        index
        for index, item in enumerate(fleet_events)
        if item["event_type"] == "TAKEOVER_CONFIRMED"
    )
    outgoing_landed_event_index = next(
        index
        for index, item in enumerate(fleet_events)
        if item["event_type"] == "OUTGOING_RETURNED_AND_LANDED"
    )
    assert takeover_event_index < outgoing_landed_event_index
    assert any(
        isinstance(item.payload, LandCommand)
        and item.fleet is not None
        and item.fleet.task_id == "zone_a"
        and item.fleet.task_lease_generation == 2
        for item in incoming_commands
    )

    outgoing_transition = next(item for item in transitions if item["previous_task_id"] == "zone_a")
    outgoing = cast(SimulatedVehicle, runtime.vehicles["coverage-a"])
    stale = CommandEnvelope(
        vehicle_id="coverage-a",
        command_id="stale-production-generation-one",
        mission_run_id=cast(str, outgoing_transition["mission_run_id"]),
        fleet=FleetCommandBinding(
            fleet_session_id=cast(str, outgoing_transition["fleet_session_id"]),
            fleet_run_id=cast(str, outgoing_transition["fleet_run_id"]),
            deployment_sha256=cast(str, outgoing_transition["deployment_sha256"]),
            task_id="zone_a",
            task_lease_generation=1,
            backend_namespace="fast-sim/coverage-a",
        ),
        issued_at_monotonic_s=outgoing.clock.now_s,
        source=CommandSource.MISSION,
        mode=OperatingMode.SIM,
        payload=ArmCommand(),
    )
    with pytest.raises(CrazySwarmError) as rejected:
        asyncio.run(outgoing.execute(stale))
    assert rejected.value.code is ErrorCode.IDENTITY_MISMATCH
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


def test_normal_play_retains_outgoing_authority_when_reserve_is_unserviceable(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    _set_batteries(
        client,
        {
            "coverage-a": 56.0,
            "coverage-b": 100.0,
            "coverage-reserve": 20.0,
        },
    )

    status = _start(
        client,
        mission_id,
        "start-live-persistent-no-reserve",
        confirm_low_battery_risk=True,
    )
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "DEGRADED"
    assert result["reason_code"] == "NO_SERVICEABLE_RESERVE"
    persistent = cast(dict[str, object], result["persistent_coverage"])
    handover = cast(list[dict[str, object]], persistent["handovers"])[0]
    assert handover["phase"] == "DEGRADED"
    assert handover["takeover_confirmed"] is False
    assert cast(dict[str, str], persistent["active_owners"])["zone_a"] == "coverage-a"
    assert result["authority_transitions"] == []
    assert result["dock_snapshots"] == [
        {
            "dock_id": "abstract-coverage-dock",
            "capacity": 1,
            "health": "AVAILABLE",
            "supported_charging_capability": "modeled-charge-v1",
            "occupied_vehicle_ids": [],
            "queued_vehicle_ids": [],
            "reservations": [],
        }
    ]
    assert not any(
        event.vehicle_id == "coverage-reserve" and event.message == "arm"
        for event in runtime.supervisor.events
    )


def test_normal_play_fails_closed_when_selected_reserve_command_is_dropped(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    _set_batteries(
        client,
        {
            "coverage-a": 56.0,
            "coverage-b": 100.0,
            "coverage-reserve": 100.0,
        },
    )
    reserve = cast(SimulatedVehicle, runtime.vehicles["coverage-reserve"])
    injected = client.post(
        "/api/v1/simulation/vehicles/coverage-reserve/faults",
        headers=auth_headers("drop-selected-reserve-command"),
        json={
            "fault": "command_drop",
            "start_s": reserve.clock.now_s,
            "end_s": reserve.clock.now_s + 100.0,
        },
    )
    injected.raise_for_status()

    status = _start(client, mission_id, "start-command-drop-handover")
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "FAILED"
    assert result["authority_transitions"] == []
    persistent = cast(dict[str, object], result["persistent_coverage"])
    assert persistent["status"] == "FAILED"
    handover = cast(list[dict[str, object]], persistent["handovers"])[0]
    assert handover["phase"] == "FAILED"
    assert handover["takeover_confirmed"] is False
    assert cast(dict[str, str], persistent["active_owners"])["zone_a"] == "coverage-a"
    children = cast(list[dict[str, object]], result["child_results"])
    reserve_result = next(
        cast(dict[str, object], item["mission_result"])
        for item in children
        if item["vehicle_id"] == "coverage-reserve"
    )
    assert reserve_result["status"] == "FAILED"
    assert reserve_result["reason_code"] == "COMMAND_DROPPED"
    assert cast(list[dict[str, object]], result["dock_snapshots"])[0]["reservations"] == []
    assert {
        vehicle_id: runtime.supervisor.session(vehicle_id).state.value
        for vehicle_id in ("coverage-a", "coverage-b", "coverage-reserve")
    } == {
        "coverage-a": "DISCONNECTED",
        "coverage-b": "DISCONNECTED",
        "coverage-reserve": "DISCONNECTED",
    }
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


def test_generation_two_watchdog_recovery_keeps_transferred_binding(
    api_client: tuple[TestClient, ApplicationRuntime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    capture = CommandCapture()
    runtime.supervisor.add_audit_sink(capture)
    _set_batteries(
        client,
        {
            "coverage-a": 56.0,
            "coverage-b": 100.0,
            "coverage-reserve": 100.0,
        },
    )
    original_transition = SimulatedVehicle.transition_fleet_authority

    async def inject_after_generation_two(
        vehicle: SimulatedVehicle,
        transition: Any,
    ) -> Any:
        receipt = await original_transition(vehicle, transition)
        if (
            vehicle.identity.vehicle_id == "coverage-reserve"
            and transition.next_task_id == "zone_a"
        ):
            vehicle.faults.inject(
                FaultWindow(
                    fault=FaultType.LOCALIZATION_LOSS,
                    start_s=vehicle.clock.now_s + 0.5,
                    end_s=vehicle.clock.now_s + 100.0,
                )
            )
        return receipt

    monkeypatch.setattr(
        SimulatedVehicle,
        "transition_fleet_authority",
        inject_after_generation_two,
    )

    status = _start(client, mission_id, "start-generation-two-watchdog")
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "FAILED"
    persistent = cast(dict[str, object], result["persistent_coverage"])
    assert persistent["status"] == "FAILED"
    handover = cast(list[dict[str, object]], persistent["handovers"])[0]
    assert handover["phase"] == "FAILED"
    assert handover["takeover_confirmed"] is True
    assert handover["incoming_lease_generation"] == 2
    transitions = cast(list[dict[str, object]], result["authority_transitions"])
    incoming_transition = next(item for item in transitions if item["current_task_id"] == "zone_a")
    recovery = next(
        item
        for item in capture.commands
        if item.vehicle_id == "coverage-reserve" and isinstance(item.payload, AbortCommand)
    )
    assert recovery.mission_run_id == incoming_transition["mission_run_id"]
    assert recovery.fleet is not None
    assert recovery.fleet.task_id == "zone_a"
    assert recovery.fleet.task_lease_generation == 2
    reserve_result = next(
        cast(dict[str, object], item["mission_result"])
        for item in cast(list[dict[str, object]], result["child_results"])
        if item["vehicle_id"] == "coverage-reserve"
    )
    assert reserve_result["status"] == "FAILED"
    assert reserve_result["reason_code"] == "LOCALIZATION_INVALID"
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


def test_normal_play_bounds_failed_modeled_charging_confirmation(
    api_client: tuple[TestClient, ApplicationRuntime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    original = DockManager.confirm_modeled_charging

    def reject_modeled_charging(
        manager: DockManager,
        reservation_id: str,
        *,
        confirmed: bool,
        now_s: float | None = None,
    ) -> DockReservation:
        del confirmed
        return original(manager, reservation_id, confirmed=False, now_s=now_s)

    monkeypatch.setattr(DockManager, "confirm_modeled_charging", reject_modeled_charging)
    _set_batteries(
        client,
        {
            "coverage-a": 56.0,
            "coverage-b": 100.0,
            "coverage-reserve": 100.0,
        },
    )

    status = _start(client, mission_id, "start-failed-modeled-charging")
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "PERSISTENT_HANDOVER_FAILED", (
        result["reason_code"],
        result["message"],
    )
    dock = cast(list[dict[str, object]], result["dock_snapshots"])[0]
    reservation = cast(list[dict[str, object]], dock["reservations"])[0]
    assert reservation["state"] == "FAILED"
    assert reservation["attempts"] == 2
    assert reservation["modeled_charging_confirmed"] is False
    assert reservation["terminal_reason"] == "LANDED_NOT_CHARGING"
    events = cast(list[dict[str, object]], result["events"])
    assert sum(item["event_type"] == "DOCK_CHARGING_CONFIRMATION_FAILED" for item in events) == 2
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


@pytest.mark.parametrize("dock_condition", ["occupied", "unavailable"])
def test_normal_play_reports_dock_capacity_and_availability_failures(
    api_client: tuple[TestClient, ApplicationRuntime],
    monkeypatch: pytest.MonkeyPatch,
    dock_condition: str,
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    original = DockManager.reserve_after_handover

    def inject_dock_condition(
        manager: DockManager,
        handover: HandoverRecord,
        *,
        battery_percent: float | None,
        now_s: float | None = None,
    ) -> DockReservation:
        if dock_condition == "occupied":
            manager.reserve("dock-blocker", battery_percent=100.0, now_s=now_s)
        else:
            manager.set_health(
                "abstract-coverage-dock",
                DockHealth.UNAVAILABLE,
                now_s=now_s,
            )
        return original(
            manager,
            handover,
            battery_percent=battery_percent,
            now_s=now_s,
        )

    monkeypatch.setattr(DockManager, "reserve_after_handover", inject_dock_condition)
    _set_batteries(
        client,
        {
            "coverage-a": 56.0,
            "coverage-b": 100.0,
            "coverage-reserve": 100.0,
        },
    )

    status = _start(client, mission_id, f"start-dock-{dock_condition}")
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "FAILED"
    dock = cast(list[dict[str, object]], result["dock_snapshots"])[0]
    if dock_condition == "occupied":
        reservations = cast(list[dict[str, object]], dock["reservations"])
        outgoing = next(item for item in reservations if item["vehicle_id"] == "coverage-a")
        assert outgoing["state"] == "QUEUED"
        assert "coverage-a" in cast(list[str], dock["queued_vehicle_ids"])
        assert any(
            item["event_type"] == "DOCK_WAITING_FOR_CAPACITY"
            for item in cast(list[dict[str, object]], result["events"])
        ), (result["reason_code"], result["message"])
    else:
        assert result["reason_code"] == "PREFLIGHT_FAILED"
        assert dock["health"] == "UNAVAILABLE"
        assert dock["reservations"] == []
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


def test_normal_play_active_link_loss_keeps_healthy_peer_running(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    active = cast(SimulatedVehicle, runtime.vehicles["coverage-a"])
    injected = client.post(
        "/api/v1/simulation/vehicles/coverage-a/faults",
        headers=auth_headers("lose-active-link"),
        json={
            "fault": "disconnect",
            "start_s": active.clock.now_s + 3.0,
            "end_s": active.clock.now_s + 100.0,
        },
    )
    injected.raise_for_status()

    status = _start(client, mission_id, "start-active-link-loss")
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "DEGRADED", (result["reason_code"], result["message"])
    children = {
        cast(str, item["vehicle_id"]): cast(dict[str, object], item["mission_result"])
        for item in cast(list[dict[str, object]], result["child_results"])
    }
    assert children["coverage-a"]["status"] == "FAILED"
    assert children["coverage-a"]["reason_code"] == "LINK_LOST"
    assert children["coverage-b"]["status"] == "SUCCEEDED"
    assert any(
        item["event_type"] == "PEER_POLICY_CONTINUE" and item["task_id"] == "zone_a"
        for item in cast(list[dict[str, object]], result["events"])
    )
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


def test_normal_play_selected_reserve_link_loss_fails_without_false_takeover(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    _set_batteries(
        client,
        {
            "coverage-a": 56.0,
            "coverage-b": 100.0,
            "coverage-reserve": 100.0,
        },
    )
    reserve = cast(SimulatedVehicle, runtime.vehicles["coverage-reserve"])
    injected = client.post(
        "/api/v1/simulation/vehicles/coverage-reserve/faults",
        headers=auth_headers("lose-selected-reserve-link"),
        json={
            "fault": "disconnect",
            "start_s": reserve.clock.now_s + 1.0,
            "end_s": reserve.clock.now_s + 100.0,
        },
    )
    injected.raise_for_status()

    status = _start(client, mission_id, "start-selected-reserve-link-loss")
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "FAILED"
    persistent = cast(dict[str, object], result["persistent_coverage"])
    handover = cast(list[dict[str, object]], persistent["handovers"])[0]
    assert handover["phase"] == "FAILED"
    assert handover["takeover_confirmed"] is False
    assert cast(dict[str, str], persistent["active_owners"])["zone_a"] == "coverage-a"
    reserve_result = next(
        cast(dict[str, object], item["mission_result"])
        for item in cast(list[dict[str, object]], result["child_results"])
        if item["vehicle_id"] == "coverage-reserve"
    )
    assert reserve_result["status"] == "FAILED"
    assert reserve_result["reason_code"] == "LINK_LOST", (
        reserve_result["reason_code"],
        reserve_result["message"],
        reserve_result["events"],
    )
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


def test_normal_play_stale_active_observation_keeps_healthy_peer_running(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    active = cast(SimulatedVehicle, runtime.vehicles["coverage-a"])
    injected = client.post(
        "/api/v1/simulation/vehicles/coverage-a/faults",
        headers=auth_headers("stale-active-observation"),
        json={
            "fault": "stale_telemetry",
            "start_s": active.clock.now_s + 3.0,
            "end_s": active.clock.now_s + 100.0,
        },
    )
    injected.raise_for_status()

    status = _start(client, mission_id, "start-stale-active-observation")
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "DEGRADED", (result["reason_code"], result["message"])
    children = {
        cast(str, item["vehicle_id"]): cast(dict[str, object], item["mission_result"])
        for item in cast(list[dict[str, object]], result["child_results"])
    }
    assert children["coverage-a"]["status"] == "FAILED"
    assert children["coverage-a"]["reason_code"] == "TELEMETRY_STALE"
    assert children["coverage-b"]["status"] == "SUCCEEDED"
    assert any(
        item["event_type"] == "FLEET_OBSERVATION_UNAVAILABLE"
        and cast(dict[str, object], item["details"])["reason_code"] == "TELEMETRY_STALE"
        for item in cast(list[dict[str, object]], result["events"])
    )


def test_normal_play_records_non_required_range_loss_during_handover(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    mission_id, _ = _upload_and_start_baseline(client)
    _set_batteries(
        client,
        {
            "coverage-a": 56.0,
            "coverage-b": 100.0,
            "coverage-reserve": 100.0,
        },
    )
    active = cast(SimulatedVehicle, runtime.vehicles["coverage-a"])
    injected = client.post(
        "/api/v1/simulation/vehicles/coverage-a/faults",
        headers=auth_headers("lose-active-ranges"),
        json={
            "fault": "range_unavailable",
            "start_s": active.clock.now_s,
            "end_s": active.clock.now_s + 100.0,
        },
    )
    injected.raise_for_status()

    status = _start(client, mission_id, "start-range-loss-handover")
    result = cast(dict[str, object], status["result"])
    assert result["status"] == "SUCCEEDED"
    outgoing = next(
        cast(dict[str, object], item["mission_result"])
        for item in cast(list[dict[str, object]], result["child_results"])
        if item["vehicle_id"] == "coverage-a"
    )
    observations = cast(list[dict[str, object]], outgoing["observations_read"])
    assert any(
        "RANGE_UNAVAILABLE" in cast(list[str], item["health_flags"]) for item in observations
    )
    handover = cast(
        list[dict[str, object]],
        cast(dict[str, object], result["persistent_coverage"])["handovers"],
    )[0]
    assert handover["takeover_confirmed"] is True


def test_normal_play_cancellation_stabilizes_and_releases_the_persistent_fleet(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    source = (
        Path("missions/qualification/persistent_coverage_rotation.py")
        .read_text(encoding="utf-8")
        .replace("hover(duration_s=20.0)", "hover(duration_s=60.0)")
    )
    mission_id = _upload_source(
        client,
        source,
        request_id="upload-cancellable-persistent-coverage",
        name="Cancellable persistent coverage",
    )
    approval = approve_mission_plan(
        client,
        mission_id,
        "approve-cancellable-persistent-coverage",
    )
    started = client.post(
        f"/api/v1/mission-files/{mission_id}/start",
        headers=auth_headers("start-cancellable-persistent-coverage"),
        json={"execution_mode": "SIMULATION", **approval},
    )
    started.raise_for_status()
    run_id = cast(str, started.json()["mission_run_id"])
    for _ in range(1_000):
        status = client.get(f"/api/v1/mission-runs/{run_id}", headers=auth_headers()).json()
        if status["execution"]["status"] == "RUNNING":
            break
        time.sleep(0.002)
    else:
        raise AssertionError(f"persistent execution did not start: {status}")

    cancelled = client.post(
        f"/api/v1/mission-runs/{run_id}/cancel",
        headers=auth_headers("cancel-persistent-coverage"),
    )
    cancelled.raise_for_status()
    status = _wait_for_terminal(client, run_id)
    execution = cast(dict[str, object], status["execution"])
    result = cast(dict[str, object], status["result"])
    assert execution["status"] == "ABORTED"
    assert execution["reason_code"] == "EXECUTION_CANCELLED"
    assert result["status"] == "ABORTED"
    assert any(
        cast(dict[str, object], child["mission_result"])["status"] == "ABORTED"
        for child in cast(list[dict[str, object]], result["child_results"])
    )
    for _ in range(1_000):
        if not runtime.mission_tasks and not runtime.fleet_tasks:
            break
        time.sleep(0.002)
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}
    assert all(
        runtime.supervisor.session(vehicle_id).state.value == "DISCONNECTED"
        for vehicle_id in runtime.active_vehicle_ids
    )


def test_normal_play_blocks_critical_starting_separation_before_provisioning(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    source = (
        Path("missions/qualification/persistent_coverage_rotation.py")
        .read_text(encoding="utf-8")
        .replace('"home_m": [1.2, 0.0, 0.0]', '"home_m": [-1.0, 0.0, 0.0]')
    )
    mission_id = _upload_source(
        client,
        source,
        request_id="upload-critical-start-separation",
        name="Unsafe persistent coverage separation",
    )
    preview = client.get(
        f"/api/v1/mission-files/{mission_id}/preview",
        headers=auth_headers(),
    )
    preview.raise_for_status()
    plan = cast(dict[str, object], preview.json()["plan"])
    assert plan["status"] == "BLOCKED"
    assert "STARTING_SEPARATION_CRITICAL" in {
        item["code"] for item in cast(list[dict[str, object]], plan["findings"])
    }

    started = client.post(
        f"/api/v1/mission-files/{mission_id}/start",
        headers=auth_headers("reject-critical-start-separation"),
        json={"execution_mode": "SIMULATION"},
    )
    assert started.status_code == 409
    assert started.json()["error"]["code"] == "PREFLIGHT_FAILED"
    assert runtime.executions == {}
    assert runtime.runner.list_runs() == ()
    assert set(runtime.vehicles) == {"sim01"}


def test_application_restart_cleans_active_persistent_run_and_reuses_evidence(
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
    evidence_path = tmp_path / "restart-evidence.sqlite3"
    source_path = Path("missions/qualification/persistent_coverage_rotation.py")
    source = source_path.read_text(encoding="utf-8").replace(
        "hover(duration_s=20.0)",
        "hover(duration_s=12.0)",
    )

    first_runtime = create_runtime(config, scenario, evidence_path=evidence_path)
    first_app = create_app(first_runtime, local_token=TOKEN)
    with TestClient(first_app) as first_client:
        uploaded = first_client.post(
            "/api/v1/mission-files",
            headers=auth_headers("upload-restart-persistent"),
            json={
                "name": "Restart persistent coverage",
                "filename": source_path.name,
                "source": source,
            },
        )
        uploaded.raise_for_status()
        mission_id = cast(str, uploaded.json()["mission_id"])
        approval = approve_mission_plan(
            first_client,
            mission_id,
            "approve-before-application-restart",
        )
        started = first_client.post(
            f"/api/v1/mission-files/{mission_id}/start",
            headers=auth_headers("start-before-application-restart"),
            json={"execution_mode": "SIMULATION", **approval},
        )
        started.raise_for_status()
        assert first_runtime.mission_tasks

    assert first_runtime.mission_tasks == {}
    assert first_runtime.fleet_tasks == {}
    assert first_runtime.telemetry_tasks == {}
    assert first_runtime.bus.stats.subscriber_count == 0
    assert set(first_runtime.vehicles) == {"sim01"}
    assert first_runtime.session_created_vehicle_ids == {}

    second_runtime = create_runtime(config, scenario, evidence_path=evidence_path)
    second_app = create_app(second_runtime, local_token=TOKEN)
    with TestClient(second_app) as second_client:
        restored = second_client.get("/api/v1/mission-files", headers=auth_headers()).json()
        assert mission_id in {item["mission_id"] for item in restored}
        result = cast(
            dict[str, object],
            _start(second_client, mission_id, "start-after-application-restart")["result"],
        )
        assert result["status"] == "SUCCEEDED"
        statuses: set[object] = set()
        for _ in range(200):
            history = second_client.get("/api/v1/runs", headers=auth_headers()).json()
            statuses = {item["status"] for item in history}
            if "SUCCEEDED" in statuses:
                break
            time.sleep(0.005)
        assert "ABORTED" in statuses
        assert "SUCCEEDED" in statuses
        assert second_runtime.mission_tasks == {}
        assert second_runtime.fleet_tasks == {}
