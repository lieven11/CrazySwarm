from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from crazyswarm_app.config import AppConfig
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.engineering import ParameterService
from crazyswarm_app.fleet.coordinator import FleetCoordinator, FleetResult
from crazyswarm_app.fleet.execution import ExecutionCoordinator
from crazyswarm_app.fleet.preparation import FleetPreparation
from crazyswarm_app.missions.models import MissionRunSnapshot
from crazyswarm_app.missions.registry import MissionRegistry, default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.missions.script import MissionFileLibrary
from crazyswarm_app.observability.bridge import EvidenceBridge
from crazyswarm_app.observability.bus import TelemetryBus
from crazyswarm_app.observability.recorder import EvidenceRecorder
from crazyswarm_app.observability.replay import ReplayClock
from crazyswarm_app.observability.storage import EvidenceStore
from crazyswarm_app.planning.approval import MissionPlanApproval
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.factory import vehicles_from_scenario
from crazyswarm_app.simulation.world import ScenarioConfig, load_scenario
from crazyswarm_app.twin.coordinator import TwinCoordinator
from crazyswarm_app.vehicles.base import Vehicle
from crazyswarm_app.vehicles.providers import ProvisionedFleet

RUNTIME_TASK_SHUTDOWN_TIMEOUT_S = 5.0


@dataclass(slots=True)
class ApplicationRuntime:
    config: AppConfig
    scenario: ScenarioConfig
    vehicles: dict[str, Vehicle]
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
    fleet_preparations: dict[str, FleetPreparation] = field(default_factory=dict)
    fleet_coordinators: dict[str, FleetCoordinator] = field(default_factory=dict)
    fleet_results: dict[str, FleetResult] = field(default_factory=dict)
    fleet_tasks: dict[str, asyncio.Task[object]] = field(default_factory=dict)
    telemetry_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    replays: dict[str, ReplayClock] = field(default_factory=dict)
    executions: dict[str, ExecutionCoordinator] = field(default_factory=dict)
    execution_run_sessions: dict[str, str] = field(default_factory=dict)
    session_created_vehicle_ids: dict[str, frozenset[str]] = field(default_factory=dict)
    bootstrap_vehicle_ids: frozenset[str] = field(default_factory=frozenset)
    active_vehicle_ids: set[str] = field(default_factory=set)
    plan_approvals: dict[str, MissionPlanApproval] = field(default_factory=dict)
    run_files_backfill_task: asyncio.Task[None] | None = None

    def latest_mission_for_vehicle(self, vehicle_id: str) -> MissionRunSnapshot | None:
        runs = [run for run in self.runner.list_runs() if run.vehicle_id == vehicle_id]
        if not runs:
            return None
        return max(runs, key=lambda run: run.started_at_monotonic_s)

    async def start(self) -> None:
        self.store.open()
        if self.run_files_backfill_task is None or self.run_files_backfill_task.done():

            async def backfill_run_files() -> None:
                try:
                    await asyncio.to_thread(self.store.backfill_run_files)
                except Exception as error:  # pragma: no cover - defensive maintenance boundary
                    self.recorder.last_error = f"run-file backfill {type(error).__name__}: {error}"

            self.run_files_backfill_task = asyncio.create_task(
                backfill_run_files(),
                name="run-files-backfill",
            )
        await self.recorder.start()
        for vehicle_id, vehicle in self.vehicles.items():
            if (
                vehicle.simulation_controls is not None
                and self.supervisor.session(vehicle_id).telemetry is None
            ):
                # Fast Sim has a complete configured state before a mission starts. Seed the
                # supervisor with that snapshot so the dashboard can render the parked drone
                # immediately after an API or dashboard restart.
                self.supervisor.receive_telemetry(await vehicle.snapshot())
            task = self.telemetry_tasks.get(vehicle_id)
            if task is None or task.done():
                self.telemetry_tasks[vehicle_id] = asyncio.create_task(
                    self._consume_telemetry(vehicle),
                    name=f"telemetry-{vehicle_id}",
                )

    async def stop(self) -> None:
        for execution in self.executions.values():
            await execution.cancel()
        for coordinator in self.fleet_coordinators.values():
            await coordinator.shutdown()
        fleet_tasks = tuple(self.fleet_tasks.values())
        await self._cancel_tasks(fleet_tasks)
        self.fleet_tasks.clear()
        mission_tasks = tuple(self.mission_tasks.values())
        await self._cancel_tasks(mission_tasks)
        self.mission_tasks.clear()
        telemetry_tasks = tuple(self.telemetry_tasks.values())
        await self._cancel_tasks(telemetry_tasks)
        self.telemetry_tasks.clear()
        for session_id in tuple(self.session_created_vehicle_ids):
            await self.cleanup_session_vehicles(session_id)
        await self.recorder.stop()
        if self.run_files_backfill_task is not None:
            await self.run_files_backfill_task
            self.run_files_backfill_task = None
        self.store.close()

    @staticmethod
    async def _cancel_tasks(tasks: tuple[asyncio.Task[object], ...]) -> None:
        for task in tasks:
            if not task.done():
                task.cancel()
        if not tasks:
            return
        done, pending = await asyncio.wait(tasks, timeout=RUNTIME_TASK_SHUTDOWN_TIMEOUT_S)
        for task in done:
            if not task.cancelled():
                task.exception()
        for task in pending:
            task.cancel()

    def track_mission_task(self, run_id: str, task: asyncio.Task[object]) -> None:
        self.mission_tasks[run_id] = task

        def discard(completed: asyncio.Task[object]) -> None:
            if self.mission_tasks.get(run_id) is completed:
                self.mission_tasks.pop(run_id, None)

        task.add_done_callback(discard)

    def track_fleet_task(self, run_id: str, task: asyncio.Task[object]) -> None:
        self.fleet_tasks[run_id] = task

        def discard(completed: asyncio.Task[object]) -> None:
            if self.fleet_tasks.get(run_id) is completed:
                self.fleet_tasks.pop(run_id, None)

        task.add_done_callback(discard)

    def attach_execution_vehicles(
        self,
        session_id: str,
        provisioned: ProvisionedFleet,
    ) -> None:
        for vehicle in provisioned.vehicles:
            vehicle_id = vehicle.identity.vehicle_id
            current = self.vehicles.get(vehicle_id)
            if current is None:
                self.vehicles[vehicle_id] = vehicle
                self.supervisor.register_vehicle(vehicle)
            elif current is not vehicle:
                raise ValueError(f"vehicle identity is already attached: {vehicle_id}")
            task = self.telemetry_tasks.get(vehicle_id)
            if task is None or task.done():
                self.telemetry_tasks[vehicle_id] = asyncio.create_task(
                    self._consume_telemetry(vehicle),
                    name=f"telemetry-{vehicle_id}",
                )
        self.session_created_vehicle_ids[session_id] = provisioned.session_created_vehicle_ids
        self.active_vehicle_ids = {vehicle.identity.vehicle_id for vehicle in provisioned.vehicles}
        if self.active_vehicle_ids:
            self.selected_vehicle_id = sorted(self.active_vehicle_ids)[0]

    async def cleanup_session_vehicles(self, session_id: str) -> None:
        for vehicle_id in sorted(self.session_created_vehicle_ids.pop(session_id, frozenset())):
            task = self.telemetry_tasks.pop(vehicle_id, None)
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            session = self.supervisor.session(vehicle_id)
            if session.state.value != "DISCONNECTED":
                try:
                    await self.supervisor.disconnect(vehicle_id)
                except CrazySwarmError as error:
                    if error.code is ErrorCode.IDENTITY_MISMATCH:
                        raise
                    # A lost/stale adapter cannot provide the disarmed terminal sample
                    # required for safe unregister. Keep it quarantined until process exit
                    # instead of falsely recording a successful disconnect.
                    continue
            self.supervisor.unregister_vehicle(vehicle_id)
            self.vehicles.pop(vehicle_id, None)
            self.active_vehicle_ids.discard(vehicle_id)

    async def cleanup_completed_execution_vehicles(self) -> None:
        """Retain completed software vehicles until the application runtime stops.

        A completed mission releases command authority and disconnects its adapters, but
        the simulated pose, battery, and estimator state remain part of the operator's
        scenario.  The session-created ownership records are intentionally kept so
        ``stop()`` can still tear the adapters down at process shutdown.
        """
        return

    async def _consume_telemetry(self, vehicle: Vehicle) -> None:
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
    vehicles_override: Iterable[Vehicle] | None = None,
) -> ApplicationRuntime:
    scenario = load_scenario(scenario_path) if isinstance(scenario_path, Path) else scenario_path
    selected_vehicles = (
        tuple(vehicles_override)
        if vehicles_override is not None
        else vehicles_from_scenario(scenario)
    )
    vehicles: dict[str, Vehicle] = {item.identity.vehicle_id: item for item in selected_vehicles}
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
    run_files_directory = config.run_files.directory
    if evidence_path is not None and run_files_directory == Path("run-files"):
        run_files_directory = evidence_path.parent / "run-files"
    store = EvidenceStore(
        evidence_path or config.evidence.database_path,
        run_files_directory=run_files_directory,
        keep_latest_missions=config.run_files.keep_latest_missions,
    )
    store.update_mission_names(
        {
            **{item.mission_id: item.name for item in registry.list_metadata()},
            **{item.mission_id: item.name for item in mission_files.list_archive()},
        }
    )
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
        bootstrap_vehicle_ids=frozenset(vehicles),
        active_vehicle_ids=set(vehicles),
    )
