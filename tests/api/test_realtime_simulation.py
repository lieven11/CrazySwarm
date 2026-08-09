from __future__ import annotations

import asyncio
import time
from itertools import pairwise
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from crazyswarm_app.api.app import create_app
from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.commands import CommandEnvelope, HoverCommand
from crazyswarm_app.domain.models import CommandSource, OperatingMode, VehicleState
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.missions.models import MissionStatus
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import load_scenario

TOKEN = "realtime-test-local-token"


@pytest.mark.asyncio
async def test_runtime_exposes_intermediate_realtime_physics_to_observers(
    tmp_path: Path,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={
                    "clock_mode": ClockMode.REALTIME,
                    "speed": 20.0,
                    "fixed_step_s": 0.02,
                }
            )
        }
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    task: asyncio.Task[object] | None = None

    await runtime.start()
    await asyncio.sleep(0)
    try:
        task = asyncio.create_task(
            runtime.runner.run(
                "move-return",
                "sim01",
                parameters={"x_m": 0.2, "move_duration_s": 1.5, "dwell_s": 0.0},
                mission_run_id="run-realtime-observation",
            )
        )
        heights: list[float] = []
        x_positions: list[float] = []
        pitch_angles: list[float] = []
        active_motor_samples = 0

        while not task.done():
            telemetry = runtime.supervisor.session("sim01").telemetry
            if telemetry is not None:
                sample = telemetry.telemetry
                position = sample.ground_truth_position_m
                if position is not None:
                    heights.append(position.z)
                    x_positions.append(position.x)
                    if sample.attitude is not None:
                        pitch_angles.append(sample.attitude.pitch_rad)
                    if sample.motors is not None and any(
                        motor.command_percent > 0.0 for motor in sample.motors.readings
                    ):
                        active_motor_samples += 1
            await asyncio.sleep(0.002)

        result = await task
        assert result.status is MissionStatus.SUCCEEDED
        assert any(0.02 < height < 0.27 for height in heights)
        assert max(x_positions) > 0.15
        assert any(abs(pitch) > 0.01 for pitch in pitch_angles)
        assert active_motor_samples > 0
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_throttles_continuous_telemetry_and_accepts_clock_reset(
    tmp_path: Path,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache", "telemetry_period_s": 0.05}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"clock_mode": ClockMode.ACCELERATED, "fixed_step_s": 0.01}
            )
        }
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    vehicle = runtime.vehicles["sim01"]
    received_source_times: list[float] = []
    original_receive = runtime.supervisor.receive_telemetry

    def observe(telemetry: TelemetryEnvelope) -> None:
        received_source_times.append(telemetry.source_timestamp_s)
        original_receive(telemetry)

    runtime.supervisor.receive_telemetry = observe  # type: ignore[method-assign]
    await runtime.start()
    try:
        await runtime.supervisor.connect("sim01")
        runtime.supervisor.claim_control("sim01", "lifecycle-test")
        report = await runtime.supervisor.preflight("sim01", "lifecycle-test")
        await runtime.supervisor.arm("sim01", "lifecycle-test", report.report_id)
        await runtime.supervisor.takeoff("sim01", "lifecycle-test", height_m=0.3, duration_s=2.0)

        received_source_times.clear()
        await vehicle.execute(
            CommandEnvelope(
                vehicle_id="sim01",
                command_id="cmd-runtime-throttle",
                issued_at_monotonic_s=time.monotonic(),
                source=CommandSource.MISSION,
                mode=OperatingMode.SIM,
                payload=HoverCommand(duration_s=0.3),
            )
        )
        await asyncio.sleep(0)
        unique_times = list(dict.fromkeys(received_source_times))
        assert len(unique_times) >= 5
        assert all(
            later - earlier >= config.telemetry_period_s - 1e-9
            for earlier, later in pairwise(unique_times)
        )

        await runtime.supervisor.land("sim01", "lifecycle-test", duration_s=2.0)
        await runtime.supervisor.disconnect("sim01", "lifecycle-test")
        before_reset_s = runtime.supervisor.session("sim01").telemetry
        assert before_reset_s is not None
        previous_source_s = before_reset_s.source_timestamp_s

        received_source_times.clear()
        cast(SimulatedVehicle, vehicle).reset()
        await vehicle.connect()
        for _ in range(20):
            telemetry = runtime.supervisor.session("sim01").telemetry
            if (
                telemetry is not None
                and telemetry.source_timestamp_s < previous_source_s
                and telemetry.telemetry.state is VehicleState.READY
            ):
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("telemetry consumer did not accept the reset source clock")
        assert received_source_times
        reset_telemetry = runtime.supervisor.session("sim01").telemetry
        assert reset_telemetry is not None
        assert reset_telemetry.telemetry.state is VehicleState.READY
        await vehicle.disconnect()
    finally:
        await runtime.stop()


def test_application_runtime_survives_twenty_lifespan_cycles_without_task_leaks(
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
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    app = create_app(runtime, local_token=TOKEN)

    for cycle in range(20):
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/missions/hover/start",
                headers={
                    "X-Local-Token": TOKEN,
                    "X-Client-ID": "lifecycle-test",
                    "Idempotency-Key": f"lifecycle-{cycle}",
                },
                json={
                    "vehicle_id": "sim01",
                    "parameters": {
                        "height_m": 0.1,
                        "takeoff_duration_s": 1.0,
                        "duration_s": 0.01,
                        "landing_duration_s": 1.0,
                    },
                },
            )
            assert response.status_code == 200
            run_id = response.json()["mission_run_id"]
            for _ in range(200):
                snapshot = client.get(
                    f"/api/v1/mission-runs/{run_id}",
                    headers={"X-Local-Token": TOKEN},
                ).json()
                if snapshot.get("result") is not None:
                    assert snapshot["result"]["status"] == "SUCCEEDED"
                    break
                time.sleep(0.005)
            else:
                raise AssertionError(f"lifecycle mission {cycle} did not finish")

        assert runtime.mission_tasks == {}
        assert runtime.telemetry_tasks == {}
        assert runtime.recorder.subscription is None
        assert runtime.bus.stats.subscriber_count == 0

    assert len(runtime.runner.list_runs()) == 20
