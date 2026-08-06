from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from crazyswarm_app.config import AppConfig
from crazyswarm_app.engineering import ParameterService
from crazyswarm_app.missions.models import MissionRunSnapshot
from crazyswarm_app.missions.registry import MissionRegistry, default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.missions.script import MissionFileLibrary
from crazyswarm_app.observability.bridge import EvidenceBridge
from crazyswarm_app.observability.bus import TelemetryBus
from crazyswarm_app.observability.recorder import EvidenceRecorder
from crazyswarm_app.observability.replay import ReplayClock
from crazyswarm_app.observability.storage import EvidenceStore
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.factory import vehicles_from_scenario
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import ScenarioConfig, load_scenario
from crazyswarm_app.twin.coordinator import TwinCoordinator


@dataclass(slots=True)
class ApplicationRuntime:
    config: AppConfig
    scenario: ScenarioConfig
    vehicles: dict[str, SimulatedVehicle]
    supervisor: SafetySupervisor
    missions: MissionRegistry
    mission_files: MissionFileLibrary
    runner: MissionRunner
    bus: TelemetryBus
    bridge: EvidenceBridge
    store: EvidenceStore
    recorder: EvidenceRecorder
    selected_vehicle_id: str
    parameters: ParameterService
    twins: TwinCoordinator
    mission_tasks: dict[str, asyncio.Task[object]] = field(default_factory=dict)
    telemetry_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    replays: dict[str, ReplayClock] = field(default_factory=dict)

    def latest_mission_for_vehicle(self, vehicle_id: str) -> MissionRunSnapshot | None:
        runs = [run for run in self.runner.list_runs() if run.vehicle_id == vehicle_id]
        if not runs:
            return None
        return max(runs, key=lambda run: run.started_at_monotonic_s)

    async def start(self) -> None:
        self.store.open()
        await self.recorder.start()
        for vehicle_id, vehicle in self.vehicles.items():
            task = self.telemetry_tasks.get(vehicle_id)
            if task is None or task.done():
                self.telemetry_tasks[vehicle_id] = asyncio.create_task(
                    self._consume_telemetry(vehicle),
                    name=f"telemetry-{vehicle_id}",
                )

    async def stop(self) -> None:
        mission_tasks = tuple(self.mission_tasks.values())
        for task in mission_tasks:
            if not task.done():
                task.cancel()
        if mission_tasks:
            await asyncio.gather(*mission_tasks, return_exceptions=True)
        self.mission_tasks.clear()
        telemetry_tasks = tuple(self.telemetry_tasks.values())
        for task in telemetry_tasks:
            task.cancel()
        if telemetry_tasks:
            await asyncio.gather(*telemetry_tasks, return_exceptions=True)
        self.telemetry_tasks.clear()
        await self.recorder.stop()
        self.store.close()

    def track_mission_task(self, run_id: str, task: asyncio.Task[object]) -> None:
        self.mission_tasks[run_id] = task

        def discard(completed: asyncio.Task[object]) -> None:
            if self.mission_tasks.get(run_id) is completed:
                self.mission_tasks.pop(run_id, None)

        task.add_done_callback(discard)

    async def _consume_telemetry(self, vehicle: SimulatedVehicle) -> None:
        last_source_timestamp_s = -float("inf")
        last_state = None
        async for telemetry in vehicle.telemetry_stream():
            source_timestamp_s = telemetry.source_timestamp_s
            state = telemetry.telemetry.state
            clock_reset = source_timestamp_s < last_source_timestamp_s
            period_elapsed = (
                source_timestamp_s - last_source_timestamp_s >= self.config.telemetry_period_s
            )
            if not clock_reset and state is last_state and not period_elapsed:
                continue
            self.supervisor.receive_telemetry(telemetry)
            last_source_timestamp_s = source_timestamp_s
            last_state = state


def create_runtime(
    config: AppConfig,
    scenario_path: ScenarioConfig | Path,
    *,
    evidence_path: Path | None = None,
) -> ApplicationRuntime:
    scenario = load_scenario(scenario_path) if isinstance(scenario_path, Path) else scenario_path
    vehicles = {item.identity.vehicle_id: item for item in vehicles_from_scenario(scenario)}
    if not vehicles:
        raise ValueError("scenario must contain at least one vehicle")
    bus = TelemetryBus()
    supervisor_holder: dict[str, SafetySupervisor] = {}
    bridge = EvidenceBridge(
        bus,
        mode_provider=lambda: supervisor_holder["supervisor"].mode,
        configuration_schema_version=config.schema_version,
    )
    supervisor = SafetySupervisor(config.safety_envelope, audit_sinks=(bridge,))
    supervisor_holder["supervisor"] = supervisor
    for vehicle in vehicles.values():
        supervisor.register_vehicle(vehicle)
    registry = default_registry()
    mission_files = MissionFileLibrary(config.cache_directory / "missions", registry)
    mission_files.load()
    runner = MissionRunner(supervisor, registry, audit_sinks=(bridge,))
    store = EvidenceStore(evidence_path or config.evidence.database_path)
    recorder = EvidenceRecorder(
        bus,
        store,
        buffer_size=config.evidence.recorder_buffer_size,
    )
    return ApplicationRuntime(
        config=config,
        scenario=scenario,
        vehicles=vehicles,
        supervisor=supervisor,
        missions=registry,
        mission_files=mission_files,
        runner=runner,
        bus=bus,
        bridge=bridge,
        store=store,
        recorder=recorder,
        selected_vehicle_id=next(iter(vehicles)),
        parameters=ParameterService(vehicles),
        twins=TwinCoordinator(),
    )
