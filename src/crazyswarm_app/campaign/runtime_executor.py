from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from typing import TYPE_CHECKING

from crazyswarm_app.campaign.execution import compile_campaign_execution_programs
from crazyswarm_app.campaign.service import (
    CampaignExecutionRequest,
    CampaignRunMode,
    RunArtifactSet,
)
from crazyswarm_app.domain.models import OperatingMode, VehicleCapability, VehicleState
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
from crazyswarm_app.missions.script import MissionFileRecord, ScriptMission, parse_python_mission
from crazyswarm_app.simulation.clock import ClockMode
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
        await runtime.cleanup_completed_execution_vehicles()
        runtime.supervisor.set_mode(OperatingMode.SIM)

        record = _campaign_mission(request)
        mission = ScriptMission(record)
        runtime.missions.register(mission, replace=True)
        programs = compile_campaign_execution_programs(
            case=request.case,
            plan=request.plan,
            schedule=request.schedule,
            trajectories=request.trajectories,
            mission_source_sha256=record.source_sha256,
        )
        deployment, binding, assignments = _deployment(request, record.mission_id)
        provider = SoftwareBackendVehicleProvider(runtime.scenario)
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
        runtime.fleet_preparations[request.run_id] = preparation
        runtime.fleet_coordinators[request.run_id] = coordinator
        cancel_event = asyncio.Event()
        self._cancel_events[request.run_id] = cancel_event
        execution_task = asyncio.create_task(
            coordinator.run(assignments), name=f"campaign-fleet-{request.run_id}"
        )
        cancellation_task = asyncio.create_task(
            cancel_event.wait(), name=f"campaign-cancel-{request.run_id}"
        )
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
            with suppress(Exception):
                await preparation.disconnect_all_safe()
            with suppress(KeyError):
                runtime.missions.unregister(record.mission_id)

        context = {
            "campaign_case": request.case.model_dump(mode="json"),
            "campaign_case_sha256": request.case.case_sha256,
            "campaign_plan": request.plan.model_dump(mode="json"),
            "campaign_schedule": request.schedule.model_dump(mode="json"),
            "campaign_trajectories": request.trajectories.model_dump(mode="json"),
            "deployment": deployment.model_dump(mode="json"),
            "binding": binding.model_dump(mode="json"),
            "assignments": assignments,
            "fleet_result": result.model_dump(mode="json"),
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
        manifest = await asyncio.to_thread(
            runtime.store.materialize_mission_execution,
            request.run_id,
        )
        bundle_reference = await asyncio.to_thread(
            runtime.store.get_persisted_execution_bundle,
            request.run_id,
        )
        evaluation_reference = await asyncio.to_thread(
            runtime.store.get_persisted_execution_evaluation,
            request.run_id,
        )
        bundle = json.loads(bundle_reference["path"].read_bytes())
        evaluation = json.loads(evaluation_reference["path"].read_bytes())
        csv_artifact = await asyncio.to_thread(
            runtime.store.export_mission_telemetry_csv,
            request.run_id,
        )
        status = "SUCCEEDED" if result.status is FleetStatus.SUCCEEDED else result.status.value
        return RunArtifactSet(
            mission_execution_id=request.run_id,
            status=status,
            manifest={
                **manifest,
                "case_sha256": request.case.case_sha256,
                "plan_sha256": request.plan.plan_sha256,
            },
            bundle={
                **bundle,
                "case_sha256": request.case.case_sha256,
                "campaign_plan": request.plan.model_dump(mode="json"),
            },
            evaluation=evaluation,
            csv_bytes_sha256=hashlib.sha256(csv_artifact.content).hexdigest(),
            csv_content=csv_artifact.content,
        )


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
            home=drone.start_region.center_m,
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
            observation_freshness_s=max(
                1.0, request.case.hard_constraints.observation_freshness_limit_s
            ),
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
