from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING

from crazyswarm_app.campaign.execution import compile_campaign_execution_programs
from crazyswarm_app.campaign.execution_head import CampaignExecutionHead
from crazyswarm_app.campaign.models import (
    ScenarioEventKind,
    ScenarioExpectedDisposition,
)
from crazyswarm_app.campaign.perception import PerceptionObservation
from crazyswarm_app.campaign.planner import (
    DEFAULT_STABILIZATION_S,
    DEFAULT_TAKEOFF_DURATION_S,
)
from crazyswarm_app.campaign.scenario import CampaignScenarioTrace, compile_scenario_trace
from crazyswarm_app.campaign.service import (
    CampaignExecutionRequest,
    CampaignRunMode,
    RunArtifactSet,
)
from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import OperatingMode, Vector3, VehicleCapability, VehicleState
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    BackendVehicleBinding,
    DeploymentManifest,
    DeploymentTaskDefinition,
    ExecutionBackend,
    FleetConstraints,
    FleetMemberDefinition,
    FleetSessionIdentity,
    InitialFleetRole,
    MissionArtifact,
    ZoneDefinition,
    ZoneGeometry,
)
from crazyswarm_app.fleet.coordinator import FleetCoordinator, FleetStatus
from crazyswarm_app.fleet.preparation import FleetPreparation
from crazyswarm_app.missions.base import MissionContext
from crazyswarm_app.missions.script import (
    EmptyScriptParameters,
    MissionFileRecord,
    ScriptMission,
    execute_accepted_program,
    parse_python_mission,
)
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.sensors import (
    PerceptionModelConfig,
    SimulatedPerceptionObservationSource,
)
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import (
    DynamicWorldTimeline,
    ObstacleConfig,
    WorldTruthEvent,
    WorldTruthEventKind,
    materialize_seeded_world_events,
)
from crazyswarm_app.vehicles.providers import SoftwareBackendVehicleProvider

if TYPE_CHECKING:
    from crazyswarm_app.api.runtime import ApplicationRuntime


class FastSimCampaignExecutor:
    """Execute one admitted campaign through the existing supervised Fast Sim runtime."""

    def __init__(self, runtime: ApplicationRuntime) -> None:
        self.runtime = runtime
        self._cancel_events: dict[str, asyncio.Event] = {}

    def request_cancel(self, run_id: str) -> None:
        event = self._cancel_events.get(run_id)
        if event is not None:
            event.set()

    async def __call__(self, request: CampaignExecutionRequest) -> RunArtifactSet:
        runtime = self.runtime
        if request.case.drone_count > 3:
            raise ValueError("Fast Sim campaign execution is bounded to three drones")
        scenario_trace = compile_scenario_trace(request.case)
        if not scenario_trace.all_expected_dispositions_observed:
            raise ValueError("campaign scenario disposition differs from its causal oracle")
        await runtime.cleanup_completed_execution_vehicles()
        runtime.dynamic_obstacles.clear()
        runtime.supervisor.set_mode(OperatingMode.SIM)

        record = _campaign_mission(request)
        perception_source = _perception_source(
            request,
            mission_id=record.mission_id,
            initial_obstacles=runtime.scenario.world.obstacles,
            on_release=lambda observation: _show_perceived_obstacle(runtime, observation),
        )
        execution_head = CampaignExecutionHead(
            case=request.case,
            planning_submission=request.resolved_package.planning_submission,
            execution_profile=request.resolved_package.execution_profile,
            capability_resolution=request.resolved_package.capability_resolution,
            perception_source=perception_source,
            mission_id=record.mission_id,
            run_id=request.run_id,
        )
        try:
            return await self._execute(
                request,
                scenario_trace=scenario_trace,
                record=record,
                execution_head=execution_head,
            )
        finally:
            preparation = runtime.fleet_preparations.pop(request.run_id, None)
            coordinator = runtime.fleet_coordinators.pop(request.run_id, None)
            runtime.fleet_results.pop(request.run_id, None)
            runtime.fleet_tasks.pop(request.run_id, None)
            if coordinator is not None:
                with suppress(Exception):
                    await coordinator.shutdown()
            if preparation is not None:
                with suppress(Exception):
                    await preparation.disconnect_all_safe()
            # Planner warm-up happens before mission registration.  Preserve that
            # original failure instead of masking it with the registry's wrapped
            # NOT_FOUND error during unconditional cleanup.
            with suppress(CrazySwarmError):
                runtime.missions.unregister(record.mission_id)
            for vehicle_id in tuple(runtime.active_vehicle_ids):
                vehicle = runtime.vehicles.get(vehicle_id)
                if isinstance(vehicle, SimulatedVehicle):
                    vehicle.world.dynamic_timeline = None
            runtime.dynamic_obstacles.clear()
            await execution_head.close()

    async def _execute(
        self,
        request: CampaignExecutionRequest,
        *,
        scenario_trace: CampaignScenarioTrace,
        record: MissionFileRecord,
        execution_head: CampaignExecutionHead,
    ) -> RunArtifactSet:
        runtime = self.runtime
        # Process startup/import can take longer than the in-flight freshness bound.
        # Warm the isolated dynamic planner before fleet preparation and takeoff.
        await execution_head.prepare()
        mission = _HeadAwareCampaignMission(record, execution_head)
        runtime.missions.register(mission, replace=True)
        programs = compile_campaign_execution_programs(
            case=request.case,
            plan=request.plan,
            schedule=request.schedule,
            trajectories=request.trajectories,
            mission_source_sha256=record.source_sha256,
        )
        deployment, binding, assignments = _deployment(request, record.mission_id)
        provider = SoftwareBackendVehicleProvider(
            runtime.scenario,
            dynamic_world_timeline=(
                execution_head.perception_source.timeline
                if isinstance(
                    execution_head.perception_source,
                    SimulatedPerceptionObservationSource,
                )
                else None
            ),
        )
        provisioned = provider.provision(deployment, binding, existing=runtime.vehicles)
        runtime.attach_execution_vehicles(request.run_id, provisioned)
        for vehicle in provisioned.vehicles:
            session = runtime.supervisor.session(vehicle.identity.vehicle_id)
            if session.state is not VehicleState.DISCONNECTED:
                raise RuntimeError("campaign Fast Sim vehicle is not disconnected before reset")
            controls = vehicle.simulation_controls
            if controls is None:
                raise RuntimeError("campaign executor received a non-simulation vehicle")
            controls.reset()
            if request.mode is CampaignRunMode.AUTOMATED_ACCELERATED and execution_head.enabled:
                # A paced accelerated clock gives the source-time execution head a
                # deterministic observation boundary.  An unpaced coroutine clock
                # can complete a whole route before another task observes its first
                # event, which is useful for batch simulation but invalid for an
                # in-flight reaction-horizon qualification.
                controls.clock.mode = ClockMode.REALTIME
                # Keep the dynamic regression on the same source/wall-time basis
                # as the qualifying realtime mode. Even a modest multiplier can
                # move the vehicle inside the protected obstacle envelope while
                # the isolated A* process is still certifying the earlier state,
                # creating an accelerated-only fallback rather than testing the
                # production reaction path.
                controls.clock.speed = 1.0
            else:
                controls.clock.mode = (
                    ClockMode.ACCELERATED
                    if request.mode is CampaignRunMode.AUTOMATED_ACCELERATED
                    else ClockMode.REALTIME
                )
                controls.clock.speed = 1.0

        preparation = FleetPreparation(
            execution_session_id=request.run_id,
            deployment=deployment,
            binding=binding,
            supervisor=runtime.supervisor,
        )
        # Register cleanup ownership before any connection/preflight operation can
        # fail so the outer runtime boundary can always drain this preparation.
        runtime.fleet_preparations[request.run_id] = preparation
        preparation.discover(provisioned.vehicles)
        await preparation.connect_all()
        await preparation.start_observation()
        await preparation.stabilize_observations(required_distinct_samples=1)
        preflight = await preparation.run_preflight()
        if not preflight.approved:
            raise RuntimeError("campaign fleet preparation failed preflight")

        artifact = MissionArtifact(
            mission_id=record.mission_id,
            mission_version=record.source_sha256[:12],
            source_sha256=record.source_sha256,
        )
        identity = FleetSessionIdentity.create(
            fleet_session_id=request.run_id,
            fleet_run_id=request.run_id,
            backend=ExecutionBackend.FAST_SIM,
            mission=artifact,
            deployment=deployment,
            binding=binding,
            model_id="campaign-fast-sim-v1",
            scenario_id=runtime.scenario.scenario_id,
            initial_state={
                member.vehicle_id: member.home.model_dump(mode="json")
                for member in deployment.fleet
            },
        )
        coordinator = FleetCoordinator(
            identity=identity,
            deployment=deployment,
            preparation=preparation,
            supervisor=runtime.supervisor,
            mission_runner=runtime.runner,
            accepted_plan_id=f"campaign-plan-{request.plan.plan_sha256[:20]}",
            accepted_plan_sha256=request.plan.plan_sha256,
            accepted_execution_programs={item.role_id: item for item in programs},
        )
        runtime.fleet_coordinators[request.run_id] = coordinator
        cancel_event = asyncio.Event()
        self._cancel_events[request.run_id] = cancel_event
        execution_task = asyncio.create_task(
            coordinator.run(assignments), name=f"campaign-fleet-{request.run_id}"
        )
        runtime.track_fleet_task(request.run_id, execution_task)
        cancellation_task = asyncio.create_task(
            cancel_event.wait(), name=f"campaign-cancel-{request.run_id}"
        )
        runtime.recorder.service_managed_execution_ids.add(request.run_id)
        try:
            done, _ = await asyncio.wait(
                {execution_task, cancellation_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_task in done and not execution_task.done():
                await coordinator.cancel()
            result = await execution_task
        finally:
            cancellation_task.cancel()
            with suppress(asyncio.CancelledError):
                await cancellation_task
            self._cancel_events.pop(request.run_id, None)
            await runtime.recorder.flush()
            runtime.recorder.service_managed_execution_ids.discard(request.run_id)

        dynamic_world_trace = _dynamic_world_trace(execution_head.perception_source)
        context = {
            "campaign_locked_inputs": request.locked_inputs.model_dump(mode="json"),
            "campaign_case": request.case.model_dump(mode="json"),
            "campaign_case_sha256": request.case.case_sha256,
            "campaign_plan": request.plan.model_dump(mode="json"),
            "campaign_schedule": request.schedule.model_dump(mode="json"),
            "campaign_trajectories": request.trajectories.model_dump(mode="json"),
            "campaign_scenario_trace": scenario_trace.model_dump(mode="json"),
            "campaign_execution_head_trace": execution_head.trace(),
            "campaign_dynamic_world_trace": dynamic_world_trace,
            "deployment": deployment.model_dump(mode="json"),
            "binding": binding.model_dump(mode="json"),
            "assignments": assignments,
            "fleet_result": result.model_dump(mode="json"),
            "fleet_events": tuple(item.model_dump(mode="json") for item in result.events),
            "timing_trace": (
                runtime.recorder.timing_trace.snapshot().model_dump(mode="json")
                if runtime.recorder.timing_trace is not None
                else None
            ),
        }
        await asyncio.to_thread(
            runtime.store.upsert_execution_context,
            request.run_id,
            context,
        )
        evaluation_report = await asyncio.to_thread(
            runtime.store.evaluate_mission_execution,
            request.run_id,
        )
        csv_artifact = await asyncio.to_thread(
            runtime.store.export_mission_telemetry_csv,
            request.run_id,
        )
        status = "SUCCEEDED" if result.status is FleetStatus.SUCCEEDED else result.status.value
        csv_sha256 = hashlib.sha256(csv_artifact.content).hexdigest()
        manifest = {
            "schema_version": 1,
            "artifact_kind": "CAMPAIGN_SERVICE_MANAGED_EVIDENCE",
            "mission_execution_id": request.run_id,
            "status": status,
            "evaluation_report_sha256": evaluation_report.report_sha256,
            "evaluation_evidence_complete": evaluation_report.evidence.complete,
            "dynamic_world_trace_sha256": (
                canonical_sha256(dynamic_world_trace) if dynamic_world_trace is not None else None
            ),
            "telemetry": {
                "filename": csv_artifact.filename,
                "row_count": csv_artifact.row_count,
                "size_bytes": len(csv_artifact.content),
                "sha256": csv_sha256,
            },
        }
        bundle = {
            "schema_version": 1,
            "contract": "campaign-service-managed-execution-bundle-v1",
            "mission_execution_id": request.run_id,
            "status": status,
            "context": context,
        }
        return RunArtifactSet(
            mission_execution_id=request.run_id,
            status=status,
            manifest={
                **manifest,
                "case_sha256": request.case.case_sha256,
                "plan_sha256": request.plan.plan_sha256,
                "campaign_execution_head_trace": execution_head.trace(),
                "planning_submission_id": request.locked_inputs.planning_submission_id,
                "planning_submission_sha256": (request.locked_inputs.planning_submission_sha256),
                "resolved_planning_package_sha256": (
                    request.locked_inputs.resolved_planning_package_sha256
                ),
            },
            bundle={
                **bundle,
                "case_sha256": request.case.case_sha256,
                "campaign_plan": request.plan.model_dump(mode="json"),
                "planning_submission_id": request.locked_inputs.planning_submission_id,
                "planning_submission_sha256": (request.locked_inputs.planning_submission_sha256),
                "resolved_planning_package_sha256": (
                    request.locked_inputs.resolved_planning_package_sha256
                ),
            },
            evaluation=evaluation_report.model_dump(mode="json"),
            csv_bytes_sha256=csv_sha256,
            csv_content=csv_artifact.content,
        )


class _HeadAwareCampaignMission(ScriptMission):
    def __init__(
        self,
        record: MissionFileRecord,
        execution_head: CampaignExecutionHead,
    ) -> None:
        super().__init__(record)
        self.execution_head = execution_head

    async def execute(
        self,
        context: MissionContext,
        parameters: EmptyScriptParameters,
    ) -> None:
        del parameters
        if context.accepted_execution_program is None:
            await super().execute(context, EmptyScriptParameters())
            return
        await execute_accepted_program(
            self.record,
            context,
            trajectory_executor=self.execution_head.execute,
        )


def _perception_source(
    request: CampaignExecutionRequest,
    *,
    mission_id: str,
    initial_obstacles: tuple[ObstacleConfig, ...],
    on_release: Callable[[PerceptionObservation], None] | None = None,
) -> SimulatedPerceptionObservationSource | None:
    semantics = request.case.semantics
    if semantics is None:
        return None
    accepted = tuple(
        event
        for event in semantics.scenario_events
        if event.kind in _WORLD_TRUTH_KIND_BY_SCENARIO
        and event.expected_disposition is ScenarioExpectedDisposition.ACCEPTED_UPDATE
    )
    if not accepted:
        return None
    truth_events = []
    route_start_offset_s = (
        DEFAULT_TAKEOFF_DURATION_S
        + DEFAULT_STABILIZATION_S
        + min(
            (
                item.ground_wait_s
                for item in (
                    request.plan.selected.routes if request.plan.selected is not None else ()
                )
            ),
            default=0.0,
        )
    )
    for event in accepted:
        region = event.environment_region
        solid_id = (
            event.update_identity
            if event.kind is ScenarioEventKind.OBSTACLE_REMOVED
            else region.region_id
            if region is not None
            else None
        )
        if solid_id is None or event.duration_s is None:
            raise ValueError("dynamic world scenario event has incomplete truth geometry")
        obstacle = (
            ObstacleConfig(
                obstacle_id=solid_id,
                minimum_m=region.minimum_m,
                maximum_m=region.maximum_m,
            )
            if region is not None
            else None
        )
        truth_events.append(
            WorldTruthEvent.create(
                event_id=event.event_id,
                sequence=event.sequence,
                source_timestamp_s=event.trigger_time_s + route_start_offset_s,
                effective_source_s=(event.trigger_time_s + route_start_offset_s + event.duration_s),
                kind=_WORLD_TRUTH_KIND_BY_SCENARIO[event.kind],
                solid_id=solid_id,
                obstacle=obstacle,
            )
        )
    truth_events = list(
        materialize_seeded_world_events(
            tuple(truth_events),
            seed_material=canonical_sha256((request.case.execution.seed, request.run_id)),
            volume_minimum_m=request.case.hard_constraints.flight_volume.minimum_m,
            volume_maximum_m=request.case.hard_constraints.flight_volume.maximum_m,
        )
    )
    first_vehicle_id = min(item.role_id for item in request.case.drones)
    return SimulatedPerceptionObservationSource(
        timeline=DynamicWorldTimeline(initial_obstacles, tuple(truth_events)),
        config=PerceptionModelConfig(),
        mission_id=mission_id,
        run_id=request.run_id,
        vehicle_id=first_vehicle_id,
        on_release=on_release,
    )


def _dynamic_world_trace(
    source: object,
) -> dict[str, object] | None:
    if not isinstance(source, SimulatedPerceptionObservationSource):
        return None
    timeline = source.timeline
    payload = timeline.canonical_payload()
    return {
        **payload,
        "timeline_sha256": canonical_sha256(payload),
    }


def _show_perceived_obstacle(
    runtime: ApplicationRuntime,
    observation: PerceptionObservation,
) -> None:
    if observation.region is None:
        runtime.dynamic_obstacles.pop(observation.solid_id, None)
        return
    runtime.dynamic_obstacles[observation.solid_id] = ObstacleConfig(
        obstacle_id=observation.solid_id,
        minimum_m=observation.region.minimum_m,
        maximum_m=observation.region.maximum_m,
    )


_WORLD_TRUTH_KIND_BY_SCENARIO = {
    ScenarioEventKind.OBSTACLE_ADDED: WorldTruthEventKind.SOLID_APPEARED,
    ScenarioEventKind.OBSTACLE_MOVED: WorldTruthEventKind.SOLID_MOVED,
    ScenarioEventKind.OBSTACLE_REMOVED: WorldTruthEventKind.SOLID_DISAPPEARED,
    ScenarioEventKind.PASSAGE_CLOSED: WorldTruthEventKind.PASSAGE_CLOSED,
    ScenarioEventKind.PASSAGE_OPENED: WorldTruthEventKind.PASSAGE_OPENED,
}


def _campaign_mission(request: CampaignExecutionRequest) -> MissionFileRecord:
    source = (
        f'"""Immutable campaign adapter for {request.case.case_id} '
        f'{request.case.case_sha256}."""\n\n'
        "async def mission(drone):\n"
        "    await drone.takeoff(height_m=0.3, duration_s=2.0)\n"
        "    await drone.land(duration_s=2.0)\n"
    )
    return parse_python_mission(
        filename=f"campaign_{request.case.case_id}.py",
        name=f"Campaign: {request.case.case_id}",
        source=source,
    )


def _deployment(
    request: CampaignExecutionRequest,
    mission_id: str,
) -> tuple[DeploymentManifest, BackendBindingProfile, dict[str, str]]:
    schedule_by_role = {item.role_id: item for item in request.schedule.roles}
    capabilities = frozenset(
        {
            VehicleCapability.ARMING,
            VehicleCapability.RELATIVE_POSITIONING,
            VehicleCapability.HIGH_LEVEL_COMMANDS,
            VehicleCapability.TIME_PARAMETERIZED_TRAJECTORY,
        }
    )
    members = tuple(
        FleetMemberDefinition(
            vehicle_id=drone.role_id,
            display_name=drone.role_id,
            # Authored launch regions have vertical tolerance, but a disarmed Fast
            # Sim body must start on the floor. Starting at the region centre made
            # it free-fall during preparation and falsely violate the raw 0.3 m/s
            # vertical-speed gate before takeoff authority existed.
            home=Vector3(
                x=drone.start_region.center_m.x,
                y=drone.start_region.center_m.y,
                z=drone.start_region.minimum_m.z,
            ),
            initial_role=InitialFleetRole.ACTIVE,
            required_capabilities=capabilities,
        )
        for drone in sorted(request.case.drones, key=lambda item: item.role_id)
    )
    zones = tuple(
        ZoneDefinition(
            zone_id=f"landing-{drone.role_id}",
            geometry=ZoneGeometry(
                minimum_m=drone.landing_region.minimum_m,
                maximum_m=drone.landing_region.maximum_m,
            ),
        )
        for drone in sorted(request.case.drones, key=lambda item: item.role_id)
    )
    tasks = tuple(
        DeploymentTaskDefinition(
            task_id=drone.role_id,
            task_type="CAMPAIGN_ROLE",
            zone_id=f"landing-{drone.role_id}",
            priority=drone.priority,
            mission_id=mission_id,
            required_capabilities=capabilities,
            estimated_duration_s=request.schedule.source_schedule_duration_s,
            estimated_energy_percent=max(
                0.1,
                drone.initial_battery_percent
                - schedule_by_role[drone.role_id].energy.predicted_end_battery_percent,
            ),
            energy_margin_percent=0.0,
        )
        for drone in sorted(request.case.drones, key=lambda item: item.role_id)
    )
    deployment = DeploymentManifest(
        deployment_id=f"campaign-{request.case.case_sha256[:20]}",
        fleet=members,
        zones=zones,
        tasks=tasks,
        constraints=FleetConstraints(
            warning_separation_m=request.case.hard_constraints.warning_separation_m,
            critical_separation_m=request.case.hard_constraints.critical_separation_m,
            observation_freshness_s=request.case.hard_constraints.observation_freshness_limit_s,
        ),
    )
    binding = BackendBindingProfile(
        binding_id=f"campaign-fast-sim-{request.case.case_sha256[:20]}",
        backend=ExecutionBackend.FAST_SIM,
        vehicles=tuple(
            BackendVehicleBinding(
                vehicle_id=member.vehicle_id,
                backend_identifier=f"fast-sim:{member.vehicle_id}",
                expected_vehicle_id=member.vehicle_id,
            )
            for member in members
        ),
    )
    return deployment, binding, {member.vehicle_id: member.vehicle_id for member in members}
