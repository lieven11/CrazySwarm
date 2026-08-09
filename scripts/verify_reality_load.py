#!/usr/bin/env python3
"""Run the Reality WP-03 accelerated mixed-mission resource-leak gate."""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crazyswarm_app.domain.models import VehicleIdentity, VehicleState  # noqa: E402
from crazyswarm_app.missions import runner as runner_module  # noqa: E402
from crazyswarm_app.missions import script as script_module  # noqa: E402
from crazyswarm_app.missions.models import MissionStatus  # noqa: E402
from crazyswarm_app.missions.registry import MissionRegistry, default_registry  # noqa: E402
from crazyswarm_app.missions.runner import MissionRunner  # noqa: E402
from crazyswarm_app.missions.script import ScriptMission, parse_python_mission  # noqa: E402
from crazyswarm_app.provenance import repository_provenance  # noqa: E402
from crazyswarm_app.safety.supervisor import SafetySupervisor  # noqa: E402
from crazyswarm_app.simulation.faults import FaultInjector, FaultType, FaultWindow  # noqa: E402
from crazyswarm_app.simulation.models import SimulationConfig  # noqa: E402
from crazyswarm_app.simulation.vehicle import SimulatedVehicle  # noqa: E402
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig  # noqa: E402

SHORT_SCRIPT = """\
async def mission(drone):
    await drone.takeoff(height_m=0.05, duration_s=0.6)
    await drone.hover(duration_s=0.05)
    await drone.land(duration_s=0.6)
"""

RANGE_SCRIPT = """\
async def mission(drone):
    await drone.takeoff(height_m=0.05, duration_s=0.6)
    observation = await drone.observe(timeout_s=0.1, required="front_range")
    if observation.ranges.front_m > 0.6:
        await drone.hover(duration_s=0.05)
    await drone.land(duration_s=0.6)
"""


def script_registry(source: str, name: str) -> tuple[MissionRegistry, str]:
    record = parse_python_mission(filename=f"{name}.py", name=name, source=source)
    registry = MissionRegistry()
    registry.register(ScriptMission(record))
    return registry, record.mission_id


def case_for(index: int) -> tuple[str, FaultType | None]:
    faults = tuple(FaultType)
    cycle = len(faults) + 4
    selected = index % cycle
    if selected < len(faults):
        return f"fault:{faults[selected].value}", faults[selected]
    nominal = ("hover", "move-return", "square", "script")
    return f"nominal:{nominal[selected - len(faults)]}", None


async def run_case(index: int) -> tuple[str, MissionStatus, str]:
    case, fault = case_for(index)
    injector = FaultInjector(
        ()
        if fault is None
        else (
            FaultWindow(
                fault=fault,
                start_s=(
                    0.06
                    if fault
                    in {
                        FaultType.STALE_TELEMETRY,
                        FaultType.LOW_BATTERY,
                        FaultType.GEOFENCE_BREACH,
                        FaultType.COLLISION,
                        FaultType.NUMERICAL_FAILURE,
                    }
                    else 0.0
                ),
            ),
        )
    )
    vehicle = SimulatedVehicle(
        VehicleIdentity(
            vehicle_id=f"load-{index}",
            display_name=f"Load {index}",
            adapter="load-gate-arbitrary-id",
        ),
        IndoorWorld(WorldConfig()),
        config=SimulationConfig(
            seed=index,
            fixed_step_s=0.02,
            command_latency_s=0.01,
            acknowledgement_latency_s=0.0,
        ),
        faults=injector,
    )
    if fault in {FaultType.RANGE_STALE, FaultType.RANGE_UNAVAILABLE}:
        registry, mission_id = script_registry(RANGE_SCRIPT, f"range-load-{index}")
        parameters = None
    elif case == "nominal:script":
        registry, mission_id = script_registry(SHORT_SCRIPT, f"script-load-{index}")
        parameters = None
    else:
        registry = default_registry()
        mission_id = case.removeprefix("nominal:") if fault is None else "hover"
        parameters = {
            "height_m": 0.05,
            "takeoff_duration_s": 0.6,
            "landing_duration_s": 0.6,
            "duration_s": 0.05,
        }
        if mission_id == "move-return":
            parameters = {
                "height_m": 0.05,
                "takeoff_duration_s": 0.6,
                "landing_duration_s": 0.6,
                "x_m": 0.05,
                "move_duration_s": 0.6,
                "dwell_s": 0.0,
            }
        elif mission_id == "square":
            parameters = {
                "height_m": 0.05,
                "takeoff_duration_s": 0.6,
                "landing_duration_s": 0.6,
                "side_m": 0.05,
                "leg_duration_s": 0.6,
                "dwell_s": 0.0,
                "loops": 1,
            }

    supervisor = SafetySupervisor()
    supervisor.register_vehicle(vehicle)
    runner = MissionRunner(supervisor, registry)
    result = await runner.run(
        mission_id,
        vehicle.identity.vehicle_id,
        parameters=parameters,
        mission_run_id=f"load-run-{index}",
    )
    await asyncio.sleep(0)

    session = supervisor.session(vehicle.identity.vehicle_id)
    if fault is None and result.status is not MissionStatus.SUCCEEDED:
        raise AssertionError(f"nominal load case failed: {case} / {result.reason_code}")
    if fault is not None and result.status is MissionStatus.SUCCEEDED:
        raise AssertionError(f"fault load case became success: {case}")
    if runner._tasks or runner._vehicle_runs or runner._cancel_events:
        raise AssertionError(f"mission task ownership leaked: {case}")
    if session.lease is not None or session.active_execute_task is not None:
        raise AssertionError(f"safety command ownership leaked: {case}")
    if vehicle._subscribers:
        raise AssertionError(f"telemetry subscriber leaked: {case}")
    if script_module._WORKER_DIRECTORIES:
        raise AssertionError(f"mission worker directory leaked: {case}")
    if vehicle._armed or vehicle._flying:
        raise AssertionError(f"vehicle authority leaked after run: {case}")
    if fault is None and session.state is not VehicleState.DISCONNECTED:
        raise AssertionError(f"nominal vehicle did not disconnect: {case}")
    return case, result.status, result.reason_code


async def verify(runs: int) -> dict[str, object]:
    # Resolve Git once: the load gate qualifies flight/runtime cleanup, not subprocess
    # launch performance for an invariant repository identity.
    frozen_provenance = repository_provenance(ROOT)
    runner_module.repository_provenance = lambda: frozen_provenance
    baseline_tasks = {task for task in asyncio.all_tasks() if not task.done()}
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    started = time.perf_counter()
    for index in range(runs):
        case, status, reason = await run_case(index)
        counts[f"{case}:{status.value}"] += 1
        reasons[reason] += 1
    await asyncio.sleep(0)
    gc.collect()
    leaked_tasks = [
        task for task in asyncio.all_tasks() if not task.done() and task not in baseline_tasks
    ]
    if leaked_tasks:
        raise AssertionError(
            "async task leak: " + ", ".join(task.get_name() for task in leaked_tasks)
        )
    elapsed_s = time.perf_counter() - started
    return {
        "classification": "SOFTWARE_VERIFIED",
        "runs": runs,
        "elapsed_wall_s": round(elapsed_s, 6),
        "runs_per_wall_s": round(runs / elapsed_s, 3),
        "cases": dict(sorted(counts.items())),
        "reason_codes": dict(sorted(reasons.items())),
        "leaked_async_tasks": 0,
        "leaked_worker_directories": len(script_module._WORKER_DIRECTORIES),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1000)
    arguments = parser.parse_args()
    if arguments.runs < 1:
        raise SystemExit("--runs must be positive")
    print(json.dumps(asyncio.run(verify(arguments.runs)), sort_keys=True))


if __name__ == "__main__":
    main()
