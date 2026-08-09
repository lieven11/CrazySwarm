from __future__ import annotations

import gc
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import ApplicationRuntime, create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.commands import AbortCommand, CommandEnvelope, StopAndHoldCommand
from crazyswarm_app.observability.evaluation import MissionExecutionEvaluation
from crazyswarm_app.planning.curriculum import (
    BorderVariant,
    MissionCaseTemplate,
    baseline_from_evaluation,
    generate_progressive_curriculum,
)
from crazyswarm_app.planning.multidrone_cases import (
    MultiDroneCaseVariant,
    generate_multi_drone_cases,
)
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import load_scenario
from tests.api.conftest import TOKEN, approve_mission_plan, auth_headers


@pytest.fixture(autouse=True)
def _collect_closed_coordination_runtime_cycles() -> Iterator[None]:
    """Keep deferred GC outside realtime mission freshness windows."""

    gc.collect()
    yield
    gc.collect()


@dataclass
class CommandCapture:
    commands: list[CommandEnvelope] = field(default_factory=list)

    def command_sent(self, command: CommandEnvelope) -> None:
        self.commands.append(command)

    def __getattr__(self, name: str) -> Any:
        del name
        return lambda value: None


def _upload(client: TestClient, filename: str, request_id: str) -> str:
    path = Path("missions/qualification") / filename
    return _upload_source(
        client,
        filename=path.name,
        source=path.read_text(encoding="utf-8"),
        request_id=request_id,
    )


def _upload_source(
    client: TestClient,
    *,
    filename: str,
    source: str,
    request_id: str,
) -> str:
    response = client.post(
        "/api/v1/mission-files",
        headers=auth_headers(request_id),
        json={
            "name": Path(filename).stem.replace("_", " ").title(),
            "filename": filename,
            "source": source,
        },
    )
    response.raise_for_status()
    return cast(str, response.json()["mission_id"])


def _play(client: TestClient, mission_id: str, request_id: str) -> dict[str, object]:
    return _wait_for_result(client, _start_play(client, mission_id, request_id))


def _start_play(client: TestClient, mission_id: str, request_id: str) -> str:
    approval = approve_mission_plan(client, mission_id, f"approve-{request_id}")
    response = client.post(
        f"/api/v1/mission-files/{mission_id}/start",
        headers=auth_headers(request_id),
        json={"execution_mode": "SIMULATION", **approval},
    )
    assert response.status_code == 200, response.json()
    return cast(str, response.json()["mission_run_id"])


def _wait_for_result(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(40_000):
        status = client.get(
            f"/api/v1/mission-runs/{run_id}",
            headers=auth_headers(),
        ).json()
        if status.get("result") is not None:
            return cast(dict[str, object], status["result"])
        time.sleep(0.002)
    raise AssertionError(f"coordination mission did not terminate: {status}")


def _wait_for_formation_flight(
    runtime: ApplicationRuntime,
    *,
    failure_message: str,
    timeout_s: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if all(
            runtime.supervisor.session(vehicle_id).state.value == "FLYING"
            for vehicle_id in ("formation-leader", "formation-follower")
        ):
            return
        time.sleep(0.002)
    raise AssertionError(failure_message)


def _inject_fault(
    client: TestClient,
    runtime: ApplicationRuntime,
    *,
    vehicle_id: str,
    fault: str,
    request_id: str,
    delay_s: float = 0.25,
) -> None:
    vehicle = cast(SimulatedVehicle, runtime.vehicles[vehicle_id])
    response = client.post(
        f"/api/v1/simulation/vehicles/{vehicle_id}/faults",
        headers=auth_headers(request_id),
        json={
            "fault": fault,
            "start_s": vehicle.clock.now_s + delay_s,
            "end_s": vehicle.clock.now_s + 100.0,
        },
    )
    response.raise_for_status()


def test_normal_play_crossing_executes_admitted_predictive_staging_strategy(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    capture = CommandCapture()
    runtime.supervisor.add_audit_sink(capture)
    mission_id = _upload(
        client,
        "crossing_route_separation.py",
        "upload-crossing-route",
    )
    preview = client.get(
        f"/api/v1/mission-files/{mission_id}/preview",
        headers=auth_headers(),
    ).json()
    deconfliction = cast(dict[str, object], preview["plan"]["deconfliction"])
    assert deconfliction["status"] == "RESOLVED"
    assert deconfliction["selected_strategy"] == "STAGING_HOLD"
    conflict = cast(dict[str, object], deconfliction["conflict"])
    assert cast(float, conflict["predicted_minimum_separation_m"]) < 0.01
    assert cast(float, conflict["ends_at_s"]) - cast(float, conflict["starts_at_s"]) < 10.0
    candidates = {
        cast(str, item["strategy"]): item
        for item in cast(list[dict[str, object]], deconfliction["candidates"])
    }
    assert candidates["STAGING_HOLD"]["feasible"] is True
    assert candidates["SPEED_RETIMING"]["feasible"] is True
    assert candidates["HORIZONTAL_DETOUR"]["feasible"] is True
    assert candidates["COMBINED_RETIMING_VERTICAL"]["feasible"] is True
    assert candidates["VERTICAL_SEPARATION"]["feasible"] is False
    assert cast(float, candidates["STAGING_HOLD"]["planned_hold_s"]) == pytest.approx(19.45)

    run_id = _start_play(client, mission_id, "play-crossing-route")
    result = _wait_for_result(client, run_id)

    assert result["status"] == "SUCCEEDED", result
    assert result["reason_code"] == "FLEET_COMPLETED"
    assert result["critical_violations"] == 0
    assert cast(float, result["minimum_separation_m"]) > 0.75
    assert result["warning_violations"] == 0
    assert result["selected_deconfliction_strategy"] == "STAGING_HOLD"
    assert result["deconfliction_plan_sha256"] == deconfliction["plan_sha256"]
    assert result["nominal_deconfliction_executed"] is True
    assert result["coordination_policy_ids"] == ["crossing-warning-hold-critical-abort-v2"]
    observations = cast(list[dict[str, object]], result["separation_observations"])
    assert observations
    assert all(item["level"] == "CLEAR" and item["action"] == "NONE" for item in observations)
    event_types = [
        cast(str, event["event_type"]) for event in cast(list[dict[str, object]], result["events"])
    ]
    assert "SEPARATION_INTERVENTION" not in event_types
    hold_commands = [
        command for command in capture.commands if isinstance(command.payload, StopAndHoldCommand)
    ]
    assert hold_commands == []
    children = cast(list[dict[str, object]], result["child_results"])
    assert {
        (item["vehicle_id"], cast(dict[str, object], item["mission_result"])["status"])
        for item in children
    } == {
        ("crossing-south", "SUCCEEDED"),
        ("crossing-west", "SUCCEEDED"),
    }
    child_by_task = {cast(str, item["task_id"]): item for item in children}
    west_result = cast(dict[str, object], child_by_task["cross_west"]["mission_result"])
    west_trace = cast(list[dict[str, object]], west_result["normalized_intent_trace"])
    assert [item["action"] for item in west_trace] == [
        "takeoff",
        "hover",
        "execute_trajectory",
        "hover",
        "land",
    ]
    assert cast(dict[str, object], west_trace[1]["arguments"])["duration_s"] == pytest.approx(20.45)
    assert all(
        cast(dict[str, object], item["mission_result"])["accepted_plan_sha256"]
        == preview["plan_sha256"]
        for item in children
    )
    assert all(
        cast(dict[str, object], item["mission_result"])["goal_captures"] for item in children
    )
    assert {
        (command.vehicle_id, command.fleet.task_id)
        for command in capture.commands
        if command.fleet is not None
    } <= {
        ("crossing-south", "cross_south"),
        ("crossing-west", "cross_west"),
    }
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}
    evaluation = client.get(
        f"/api/v1/run-files/{run_id}/evaluation",
        headers=auth_headers(),
    ).json()
    assert evaluation["status"] == "COMPLETE"
    fleet_evaluation = cast(dict[str, object], evaluation["fleet"])
    assert fleet_evaluation["deconfliction_plan_sha256"] == deconfliction["plan_sha256"]
    assert fleet_evaluation["selected_deconfliction_strategy"] == "STAGING_HOLD"
    assert fleet_evaluation["nominal_deconfliction_executed"] is True
    assert cast(float, fleet_evaluation["predicted_minimum_separation_m"]) > 0.8
    assert cast(float, fleet_evaluation["minimum_truth_separation_m"]) > 0.75
    assert fleet_evaluation["warning_sample_count"] == 0
    assert fleet_evaluation["critical_sample_count"] == 0


def test_normal_play_three_drone_conflict_executes_one_joint_schedule(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    capture = CommandCapture()
    runtime.supervisor.add_audit_sink(capture)
    mission_id = _upload(
        client,
        "three_drone_multi_conflict.py",
        "upload-three-drone-multi-conflict",
    )
    preview = client.get(
        f"/api/v1/mission-files/{mission_id}/preview",
        headers=auth_headers(),
    ).json()
    deconfliction = cast(dict[str, object], preview["plan"]["deconfliction"])
    assert deconfliction["status"] == "RESOLVED"
    assert deconfliction["selected_strategy"] == "EXACT_ENUMERATION_STAGING"
    assert len(cast(list[object], deconfliction["conflicts"])) == 3
    assert len(cast(list[object], deconfliction["candidates"])) == 6
    assert deconfliction["deadlock_detected"] is False
    selected_index = cast(int, deconfliction["selected_candidate_index"])
    selected = cast(list[dict[str, object]], deconfliction["candidates"])[selected_index]
    assert selected["precedence_order"] == ["route_alpha", "route_beta", "route_gamma"]
    assert cast(float, selected["maximum_wait_s"]) < cast(
        float, deconfliction["starvation_bound_s"]
    )
    assert cast(float, selected["predicted_minimum_separation_m"]) > 0.80

    run_id = _start_play(client, mission_id, "play-three-drone-multi-conflict")
    result = _wait_for_result(client, run_id)

    assert result["status"] == "SUCCEEDED"
    assert result["reason_code"] == "FLEET_COMPLETED"
    assert result["selected_deconfliction_strategy"] == "EXACT_ENUMERATION_STAGING"
    assert result["deconfliction_plan_sha256"] == deconfliction["plan_sha256"]
    assert result["nominal_deconfliction_executed"] is True
    assert result["warning_violations"] == 0
    assert result["critical_violations"] == 0
    assert cast(float, result["minimum_separation_m"]) > 0.75
    assert not any(isinstance(command.payload, StopAndHoldCommand) for command in capture.commands)
    children = cast(list[dict[str, object]], result["child_results"])
    assert len(children) == 3
    assert all(
        cast(dict[str, object], child["mission_result"])["status"] == "SUCCEEDED"
        for child in children
    )
    child_by_task = {cast(str, child["task_id"]): child for child in children}
    expected_holds = {
        "route_alpha": 1.0,
        "route_beta": 20.45,
        "route_gamma": 39.90,
    }
    for role_id, duration_s in expected_holds.items():
        mission_result = cast(dict[str, object], child_by_task[role_id]["mission_result"])
        trace = cast(list[dict[str, object]], mission_result["normalized_intent_trace"])
        base_actions = [
            "takeoff",
            "hover",
            "execute_trajectory",
            "hover",
            "land",
        ]
        actions = [item["action"] for item in trace]
        if actions[0] == "ground_wait":
            assert actions[1:] == base_actions
            hold = trace[0]
            expected_duration_s = max(0.0, duration_s - 1.0)
        else:
            assert actions == base_actions
            hold = trace[1]
            expected_duration_s = duration_s
        assert cast(dict[str, object], hold["arguments"])["duration_s"] == pytest.approx(
            expected_duration_s
        )
        assert mission_result["goal_captures"]
        assert mission_result["accepted_plan_sha256"] == preview["plan_sha256"]

    evaluation = client.get(
        f"/api/v1/run-files/{run_id}/evaluation",
        headers=auth_headers(),
    ).json()
    assert evaluation["status"] == "COMPLETE"
    fleet = cast(dict[str, object], evaluation["fleet"])
    assert fleet["deconfliction_plan_sha256"] == deconfliction["plan_sha256"]
    assert fleet["selected_deconfliction_strategy"] == "EXACT_ENUMERATION_STAGING"
    assert fleet["nominal_deconfliction_executed"] is True
    assert cast(float, fleet["predicted_minimum_separation_m"]) > 0.80
    assert cast(float, fleet["minimum_truth_separation_m"]) > 0.75
    assert fleet["warning_sample_count"] == 0
    assert fleet["critical_sample_count"] == 0
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


@pytest.mark.parametrize(
    "variant",
    (
        MultiDroneCaseVariant.MERGE,
        MultiDroneCaseVariant.BOTTLENECK,
        MultiDroneCaseVariant.UNEQUAL_PRIORITY,
        MultiDroneCaseVariant.CONSTRAINED_BORDER,
    ),
)
def test_declared_three_drone_variants_pass_execution_and_evaluation(
    api_client: tuple[TestClient, ApplicationRuntime],
    variant: MultiDroneCaseVariant,
) -> None:
    client, _ = api_client
    case = next(item for item in generate_multi_drone_cases() if item.variant is variant)
    mission_id = _upload_source(
        client,
        filename=case.mission_filename,
        source=case.mission_source,
        request_id=f"upload-{case.case_id}",
    )
    preview = client.get(
        f"/api/v1/mission-files/{mission_id}/preview",
        headers=auth_headers(),
    ).json()
    assert preview["plan"]["status"] == "APPROVED"
    deconfliction = cast(dict[str, object], preview["plan"]["deconfliction"])
    assert deconfliction["status"] == "RESOLVED"
    assert deconfliction["selected_strategy"] == "EXACT_ENUMERATION_STAGING"
    selected = cast(list[dict[str, object]], deconfliction["candidates"])[
        cast(int, deconfliction["selected_candidate_index"])
    ]
    assert selected["starved_role_ids"] == []
    assert cast(float, selected["maximum_wait_s"]) <= case.maximum_planned_wait_s
    assert (
        cast(float, selected["predicted_minimum_separation_m"])
        >= case.minimum_predicted_separation_m
    )

    run_id = _start_play(client, mission_id, f"play-{case.case_id}")
    result = _wait_for_result(client, run_id)

    assert result["status"] == "SUCCEEDED"
    assert result["selected_deconfliction_strategy"] == "EXACT_ENUMERATION_STAGING"
    assert result["nominal_deconfliction_executed"] is True
    assert result["warning_violations"] == 0
    assert result["critical_violations"] == 0
    assert cast(float, result["minimum_separation_m"]) > (
        case.minimum_predicted_separation_m - 0.05
    )
    assert all(
        cast(dict[str, object], child["mission_result"])["goal_captures"]
        for child in cast(list[dict[str, object]], result["child_results"])
    )
    evaluation = MissionExecutionEvaluation.model_validate(
        client.get(
            f"/api/v1/run-files/{run_id}/evaluation",
            headers=auth_headers(),
        ).json()
    )
    assert evaluation.status.value == "COMPLETE"
    assert evaluation.fleet is not None
    assert evaluation.fleet.nominal_deconfliction_executed is True
    assert evaluation.fleet.warning_sample_count == 0
    assert evaluation.fleet.critical_sample_count == 0
    assert evaluation.evidence.complete is True


def test_three_drone_joint_schedule_is_equivalent_in_realtime_fast_sim(
    tmp_path: Path,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"clock_mode": ClockMode.REALTIME, "seed": 109}
            )
        }
    )
    runtime = create_runtime(
        config,
        scenario,
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    with TestClient(create_app(runtime, local_token=TOKEN)) as client:
        mission_id = _upload(
            client,
            "three_drone_multi_conflict.py",
            "upload-realtime-three-drone-conflict",
        )
        result = _play(client, mission_id, "play-realtime-three-drone-conflict")

    assert result["status"] == "SUCCEEDED"
    assert result["selected_deconfliction_strategy"] == "EXACT_ENUMERATION_STAGING"
    assert result["nominal_deconfliction_executed"] is True
    assert result["warning_violations"] == 0
    assert result["critical_violations"] == 0
    assert cast(float, result["minimum_separation_m"]) > 0.75
    assert all(
        cast(dict[str, object], child["mission_result"])["goal_captures"]
        for child in cast(list[dict[str, object]], result["child_results"])
    )


def test_crossing_route_normalized_replay_is_stable_across_fast_sim_seeds(
    tmp_path: Path,
) -> None:
    outcomes: list[dict[str, object]] = []
    for seed in (109, 811):
        directory = tmp_path / f"seed-{seed}"
        config = load_config(Path("config/app.yaml")).model_copy(
            update={"cache_directory": directory / "cache"}
        )
        scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
        scenario = scenario.model_copy(
            update={
                "simulation": scenario.simulation.model_copy(
                    update={"clock_mode": ClockMode.ACCELERATED, "seed": seed}
                )
            }
        )
        runtime = create_runtime(
            config,
            scenario,
            evidence_path=directory / "evidence.sqlite3",
        )
        with TestClient(create_app(runtime, local_token=TOKEN)) as client:
            mission_id = _upload(
                client,
                "crossing_route_separation.py",
                f"upload-crossing-seed-{seed}",
            )
            outcomes.append(_play(client, mission_id, f"play-crossing-seed-{seed}"))

    assert all(item["status"] == "SUCCEEDED" for item in outcomes)
    assert all(item["critical_violations"] == 0 for item in outcomes)
    assert outcomes[0]["normalized_outcome_sha256"] == outcomes[1]["normalized_outcome_sha256"]


def test_predictive_crossing_strategy_is_equivalent_in_realtime_fast_sim(
    tmp_path: Path,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"clock_mode": ClockMode.REALTIME, "seed": 109}
            )
        }
    )
    runtime = create_runtime(
        config,
        scenario,
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    with TestClient(create_app(runtime, local_token=TOKEN)) as client:
        mission_id = _upload(
            client,
            "crossing_route_separation.py",
            "upload-realtime-predictive-crossing",
        )
        result = _play(client, mission_id, "play-realtime-predictive-crossing")

    assert result["status"] == "SUCCEEDED", result
    assert result["reason_code"] == "FLEET_COMPLETED"
    assert result["selected_deconfliction_strategy"] == "STAGING_HOLD"
    assert result["nominal_deconfliction_executed"] is True
    assert cast(float, result["minimum_separation_m"]) > 0.75
    assert result["warning_violations"] == 0
    assert result["critical_violations"] == 0
    assert all(
        cast(dict[str, object], item["mission_result"])["reason_code"] == "MISSION_COMPLETED"
        for item in cast(list[dict[str, object]], result["child_results"])
    )


def test_no_hover_curriculum_crossing_executes_continuous_retiming(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, _ = api_client
    case = next(
        item
        for item in generate_progressive_curriculum(
            seeds=(109,),
            border_variants=(BorderVariant.NOMINAL,),
        ).cases
        if item.template is MissionCaseTemplate.NO_HOVER_CROSSING
    )
    mission_id = _upload_source(
        client,
        filename=case.mission_filename,
        source=case.mission_source,
        request_id="upload-no-hover-curriculum-crossing",
    )
    preview = client.get(
        f"/api/v1/mission-files/{mission_id}/preview",
        headers=auth_headers(),
    ).json()
    deconfliction = cast(dict[str, object], preview["plan"]["deconfliction"])

    assert deconfliction["selected_strategy"] == "SPEED_RETIMING"
    assert all(
        item["strategy"] != "STAGING_HOLD"
        for item in cast(list[dict[str, object]], deconfliction["candidates"])
    )

    run_id = _start_play(client, mission_id, "play-no-hover-curriculum-crossing")
    result = _wait_for_result(client, run_id)

    assert result["status"] == "SUCCEEDED"
    assert result["selected_deconfliction_strategy"] == "SPEED_RETIMING"
    assert result["nominal_deconfliction_executed"] is True
    assert result["warning_violations"] == 0
    assert result["critical_violations"] == 0
    for child in cast(list[dict[str, object]], result["child_results"]):
        mission_result = cast(dict[str, object], child["mission_result"])
        trace = cast(list[dict[str, object]], mission_result["normalized_intent_trace"])
        assert [item["action"] for item in trace] == [
            "takeoff",
            "execute_trajectory",
            "land",
        ]
    evaluation = MissionExecutionEvaluation.model_validate(
        client.get(
            f"/api/v1/run-files/{run_id}/evaluation",
            headers=auth_headers(),
        ).json()
    )
    baseline = baseline_from_evaluation(case, evaluation)
    assert baseline.hard_gates_passed is True
    assert baseline.evaluator_id == "deterministic-mission-execution-evaluator"
    assert baseline.selected_deconfliction_strategy == "SPEED_RETIMING"


def test_normal_play_critical_crossing_aborts_and_lands_both_routes(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    capture = CommandCapture()
    runtime.supervisor.add_audit_sink(capture)
    source = (
        Path("missions/qualification/crossing_route_separation.py")
        .read_text(encoding="utf-8")
        .replace('"task_type": "crossing-route"', '"task_type": "crossing-route-reactive"')
        .replace("range(24)", "range(1)")
        .replace("x_m=0.1, duration_s=0.8", "x_m=2.4, duration_s=8.0")
        .replace("y_m=0.1, duration_s=0.8", "y_m=2.4, duration_s=8.0")
    )
    mission_id = _upload_source(
        client,
        filename="critical_crossing_route.py",
        source=source,
        request_id="upload-critical-crossing-route",
    )

    result = _play(client, mission_id, "play-critical-crossing-route")

    assert result["status"] == "ABORTED"
    assert cast(int, result["warning_violations"]) >= 1
    assert cast(int, result["critical_violations"]) >= 1
    assert cast(float, result["minimum_separation_m"]) <= 0.4
    observations = cast(list[dict[str, object]], result["separation_observations"])
    critical = next(
        item
        for item in observations
        if item["level"] == "CRITICAL" and cast(str, item["action"]).startswith("ABORT_PAIR_")
    )
    assert cast(float, critical["intervention_latency_s"]) <= 0.25
    children = cast(list[dict[str, object]], result["child_results"])
    assert all(
        cast(dict[str, object], child["mission_result"])["status"] == "ABORTED"
        for child in children
    )
    assert {
        command.vehicle_id
        for command in capture.commands
        if isinstance(command.payload, AbortCommand)
    } == {"crossing-south", "crossing-west"}
    assert all(
        runtime.supervisor.session(vehicle_id).state.value == "DISCONNECTED"
        for vehicle_id in ("crossing-south", "crossing-west")
    )
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


def test_normal_play_leader_follower_tracks_global_offset_with_isolated_routing(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    capture = CommandCapture()
    runtime.supervisor.add_audit_sink(capture)
    mission_id = _upload(
        client,
        "leader_follower_recovery.py",
        "upload-leader-follower",
    )

    result = _play(client, mission_id, "play-leader-follower")

    assert result["status"] == "SUCCEEDED"
    assert result["critical_violations"] == 0
    observations = cast(list[dict[str, object]], result["leader_follower_observations"])
    assert observations
    assert max(cast(float, item["tracking_error_m"]) for item in observations) <= 0.25
    assert max(cast(float, item["speed_error_m_s"]) for item in observations) <= 0.25
    assert min(cast(float, item["separation_m"]) for item in observations) > 0.8
    assert min(cast(float, item["boundary_margin_m"]) for item in observations) >= 0.0
    assert all(
        item["leader_source_clock_id"] == "fast-sim-formation-leader"
        and item["follower_source_clock_id"] == "fast-sim-formation-follower"
        for item in observations
    )
    assert set(cast(list[str], result["coordination_policy_ids"])) == {
        "leader-follower-global-offset-v1",
        "leader-loss-land-follower-v1",
        "follower-loss-land-leader-v1",
    }
    expected_routes = {
        "formation-leader": "leader",
        "formation-follower": "follower",
    }
    fleet_commands = [command for command in capture.commands if command.fleet is not None]
    assert fleet_commands
    assert all(
        command.fleet is not None
        and command.fleet.task_id == expected_routes[command.vehicle_id]
        and command.fleet.task_lease_generation == 1
        for command in fleet_commands
    )
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


def test_normal_play_coordination_cancellation_cleans_up_and_allows_restart(
    api_client: tuple[TestClient, ApplicationRuntime],
) -> None:
    client, runtime = api_client
    mission_id = _upload(
        client,
        "leader_follower_recovery.py",
        "upload-cancel-restart-leader-follower",
    )
    cancelled_run_id = _start_play(
        client,
        mission_id,
        "start-cancel-restart-leader-follower",
    )
    _wait_for_formation_flight(
        runtime,
        failure_message="coordination mission never reached cancellable flight",
    )

    cancelled = client.post(
        f"/api/v1/mission-runs/{cancelled_run_id}/cancel",
        headers=auth_headers("cancel-leader-follower"),
    )
    cancelled.raise_for_status()
    cancelled_result = _wait_for_result(client, cancelled_run_id)
    assert cancelled_result["status"] == "ABORTED"
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}

    restarted_result = _play(client, mission_id, "restart-leader-follower")
    assert restarted_result["status"] == "SUCCEEDED"
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}


@pytest.mark.parametrize(
    ("vehicle_id", "fault", "event_prefix", "peer_task_id"),
    (
        ("formation-leader", "localization_loss", "LEADER_LOSS", "follower"),
        ("formation-leader", "disconnect", "LEADER_LOSS", "follower"),
        ("formation-leader", "stale_telemetry", "LEADER_LOSS", "follower"),
        ("formation-leader", "command_drop", "LEADER_LOSS", "follower"),
        ("formation-leader", "geofence_breach", "LEADER_LOSS", "follower"),
        ("formation-follower", "disconnect", "FOLLOWER_LOSS", "leader"),
    ),
)
def test_normal_play_leader_and_follower_losses_apply_bounded_land_policy(
    api_client: tuple[TestClient, ApplicationRuntime],
    vehicle_id: str,
    fault: str,
    event_prefix: str,
    peer_task_id: str,
) -> None:
    client, runtime = api_client
    mission_id = _upload(
        client,
        "leader_follower_recovery.py",
        "upload-leader-loss-matrix",
    )
    run_id = _start_play(
        client,
        mission_id,
        f"start-coordination-{vehicle_id}-{fault}",
    )
    _wait_for_formation_flight(
        runtime,
        failure_message="leader/follower mission never reached active formation flight",
    )

    _inject_fault(
        client,
        runtime,
        vehicle_id=vehicle_id,
        fault=fault,
        request_id=f"inject-coordination-{vehicle_id}-{fault}",
    )

    result = _wait_for_result(client, run_id)

    assert result["status"] in {"ABORTED", "FAILED"}
    children = {
        cast(str, item["task_id"]): cast(dict[str, object], item["mission_result"])
        for item in cast(list[dict[str, object]], result["child_results"])
    }
    assert children[peer_task_id]["status"] == "ABORTED"
    events = cast(list[dict[str, object]], result["events"])
    detected_index = next(
        event_index
        for event_index, event in enumerate(events)
        if event["event_type"] == f"{event_prefix}_DETECTED"
    )
    applied_index = next(
        event_index
        for event_index, event in enumerate(events)
        if event["event_type"] == f"{event_prefix}_POLICY_APPLIED"
    )
    peer_terminal_index = next(
        event_index
        for event_index, event in enumerate(events)
        if event["event_type"] == "TASK_ABORTED" and event["task_id"] == peer_task_id
    )
    assert detected_index < applied_index < peer_terminal_index
    applied = cast(dict[str, object], events[applied_index]["details"])
    assert cast(float, applied["intervention_latency_s"]) <= cast(
        float, applied["intervention_bound_s"]
    )
    if event_prefix == "LEADER_LOSS":
        proposal = next(
            event for event in events if event["event_type"] == "RECOVERY_PROPOSAL_EVALUATED"
        )
        proposal_details = cast(dict[str, object], proposal["details"])
        assert proposal_details["strategy_plugin_id"] == "recovery.leader-loss"
        assert proposal_details["proposed_action"] == "LAND"
        assert proposal_details["authorized"] is True
        assert cast(float, result["leader_loss_intervention_latency_s"]) <= 0.25
    assert runtime.mission_tasks == {}
    assert runtime.fleet_tasks == {}
