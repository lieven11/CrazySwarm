from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from crazyswarm_app.domain.commands import FleetCommandBinding
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256
from crazyswarm_app.fleet.artifacts import BackendBindingProfile, DeploymentManifest
from crazyswarm_app.fleet.coordinator import FleetCoordinator, FleetResult, FleetStatus
from crazyswarm_app.fleet.preparation import FleetPreparation
from crazyswarm_app.missions.models import MissionResult, MissionStatus
from crazyswarm_app.missions.planning import MissionPlanReceipt, MissionPlanStatus
from crazyswarm_app.missions.runner import MissionRunner


class ExecutionStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    PREPARING = "PREPARING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


class ExecutionRecord(ContractModel):
    schema_version: Literal[2] = 2
    execution_session_id: Identifier
    execution_run_id: Identifier
    mission_id: Identifier
    mission_source_sha256: SHA256
    deployment_id: Identifier
    deployment_sha256: SHA256
    binding_sha256: SHA256
    mission_plan_id: Identifier
    mission_plan_sha256: SHA256
    status: ExecutionStatus
    member_count: int = Field(ge=1)
    active_task_count: int = Field(ge=1)
    created_at_monotonic_s: float = Field(ge=0.0)
    updated_at_monotonic_s: float = Field(ge=0.0)
    preparation: dict[str, Any]
    mission_plan: dict[str, Any]
    result: dict[str, Any] | None = None
    reason_code: str | None = None
    message: str = ""


class ExecutionCoordinator:
    """One owner for automatic preparation and one/multi-vehicle mission execution."""

    def __init__(
        self,
        *,
        execution_session_id: str,
        execution_run_id: str,
        mission_id: str,
        mission_source_sha256: str,
        deployment: DeploymentManifest,
        binding: BackendBindingProfile,
        mission_plan: MissionPlanReceipt,
        assignments: dict[str, str],
        preparation: FleetPreparation,
        mission_runner: MissionRunner,
        fleet_coordinator: FleetCoordinator | None,
        allow_simulation_low_battery: bool = False,
    ) -> None:
        if not assignments:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "execution has no active mission task")
        self.execution_session_id = execution_session_id
        self.execution_run_id = execution_run_id
        self.mission_id = mission_id
        self.mission_source_sha256 = mission_source_sha256
        self.deployment = deployment
        self.binding = binding
        if mission_plan.mission_source_sha256 != mission_source_sha256:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "mission plan source mismatch")
        if mission_plan.deployment_sha256 != deployment.sha256:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "mission plan deployment mismatch")
        if mission_plan.status is MissionPlanStatus.BLOCKED:
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "blocked mission plan cannot execute")
        if (
            mission_plan.status is MissionPlanStatus.REQUIRES_CONFIRMATION
            and not allow_simulation_low_battery
        ):
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "mission plan confirmation is required before execution",
            )
        graph_roles = {
            role_id
            for node in mission_plan.planning.execution_graph.nodes
            for role_id in node.role_ids
        }
        route_roles = {route.role_id for route in mission_plan.planning.route_plans}
        assignment_roles = set(assignments)
        if graph_roles != assignment_roles or route_roles != assignment_roles:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "execution assignments are absent from the accepted execution graph",
                details={
                    "assignment_roles": sorted(assignment_roles),
                    "graph_roles": sorted(graph_roles),
                    "route_roles": sorted(route_roles),
                },
            )
        self.mission_plan = mission_plan
        self.assignments = dict(sorted(assignments.items()))
        self.preparation = preparation
        self.mission_runner = mission_runner
        self.fleet_coordinator = fleet_coordinator
        self.allow_simulation_low_battery = allow_simulation_low_battery
        self._status = ExecutionStatus.SCHEDULED
        self._created_at = time.monotonic()
        self._updated_at = self._created_at
        self._result: MissionResult | FleetResult | None = None
        self._reason_code: str | None = None
        self._message = "mission deployment scheduled"
        self._cancel_requested = asyncio.Event()
        self._cleanup_complete = False

    @property
    def record(self) -> ExecutionRecord:
        return ExecutionRecord(
            execution_session_id=self.execution_session_id,
            execution_run_id=self.execution_run_id,
            mission_id=self.mission_id,
            mission_source_sha256=self.mission_source_sha256,
            deployment_id=self.deployment.deployment_id,
            deployment_sha256=self.deployment.sha256,
            binding_sha256=self.binding.sha256,
            mission_plan_id=self.mission_plan.plan_id,
            mission_plan_sha256=self.mission_plan.sha256,
            status=self._status,
            member_count=len(self.deployment.fleet),
            active_task_count=len(self.assignments),
            created_at_monotonic_s=self._created_at,
            updated_at_monotonic_s=self._updated_at,
            preparation=self.preparation.record.model_dump(mode="json"),
            mission_plan=self.mission_plan.model_dump(mode="json"),
            result=(
                self._result.model_dump(mode="json")
                if self._result is not None and self._cleanup_complete
                else None
            ),
            reason_code=self._reason_code,
            message=self._message,
        )

    @property
    def state_summary(self) -> dict[str, Any]:
        """Bounded execution state for the high-frequency operator snapshot."""
        return {
            "schema_version": 2,
            "execution_session_id": self.execution_session_id,
            "execution_run_id": self.execution_run_id,
            "mission_id": self.mission_id,
            "mission_source_sha256": self.mission_source_sha256,
            "mission_plan_id": self.mission_plan.plan_id,
            "mission_plan_sha256": self.mission_plan.sha256,
            "deployment_id": self.deployment.deployment_id,
            "deployment_sha256": self.deployment.sha256,
            "binding_sha256": self.binding.sha256,
            "execution_graph_sha256": (self.mission_plan.planning.execution_graph.graph_sha256),
            "safety_case_sha256": self.mission_plan.planning.safety_case.safety_case_sha256,
            "status": self._status.value,
            "member_count": len(self.deployment.fleet),
            "active_task_count": len(self.assignments),
            "created_at_monotonic_s": self._created_at,
            "updated_at_monotonic_s": self._updated_at,
            "reason_code": self._reason_code,
            "message": self._message,
        }

    @property
    def evidence_context(self) -> dict[str, Any]:
        fleet_result = self._result if isinstance(self._result, FleetResult) else None
        return {
            "execution_session_id": self.execution_session_id,
            "mission_execution_id": self.execution_run_id,
            "mission_id": self.mission_id,
            "mission_source_sha256": self.mission_source_sha256,
            "mission_plan_id": self.mission_plan.plan_id,
            "mission_plan_sha256": self.mission_plan.sha256,
            "deployment": self.deployment.model_dump(mode="json"),
            "binding": self.binding.model_dump(mode="json"),
            "assignments": self.assignments,
            "mission_plan": self.mission_plan.model_dump(mode="json"),
            "fleet_events": (
                [item.model_dump(mode="json") for item in fleet_result.events]
                if fleet_result is not None
                else []
            ),
            "execution_result": (
                self.record.model_dump(mode="json")
                if self.terminal and self._cleanup_complete
                else {}
            ),
        }

    @property
    def terminal(self) -> bool:
        return self._status in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.DEGRADED,
            ExecutionStatus.ABORTED,
            ExecutionStatus.FAILED,
        }

    @property
    def fleet_result(self) -> FleetResult | None:
        return self._result if isinstance(self._result, FleetResult) else None

    async def run(self) -> ExecutionRecord:
        try:
            self._set(ExecutionStatus.PREPARING, "initializing and verifying mission deployment")
            await self.preparation.connect_all()
            await self.preparation.start_observation()
            await self.preparation.stabilize_observations()
            await self.preparation.run_preflight(
                allow_simulation_low_battery=self.allow_simulation_low_battery
            )
            # A multi-member preflight can legitimately consume most of a short
            # observation-freshness window. Re-observe every identity-checked source
            # before admission so readiness reflects current telemetry, not the age of
            # the sample taken before the preflight sequence began.
            await self.preparation.refresh_observations()
            self.preparation.require_ready()
            self._set(ExecutionStatus.READY, "required fleet is ready")
            if self._cancel_requested.is_set():
                self._set_terminal(
                    ExecutionStatus.ABORTED,
                    "EXECUTION_CANCELLED",
                    "execution was cancelled before mission start",
                )
                return self.record
            self._set(ExecutionStatus.RUNNING, "starting verified mission roles")
            if self.fleet_coordinator is not None:
                self._result = await self.fleet_coordinator.run(
                    self.assignments,
                    allow_simulation_low_battery=self.allow_simulation_low_battery,
                )
                if self._cancel_requested.is_set():
                    self._set_terminal(
                        ExecutionStatus.ABORTED,
                        "EXECUTION_CANCELLED",
                        "execution cancellation completed with bounded fleet cleanup",
                    )
                else:
                    self._apply_fleet_result(self._result)
            else:
                self._result = await self._run_single()
                if self._cancel_requested.is_set():
                    self._set_terminal(
                        ExecutionStatus.ABORTED,
                        "EXECUTION_CANCELLED",
                        "execution cancellation completed with bounded mission cleanup",
                    )
                else:
                    self._apply_mission_result(self._result)
        except asyncio.CancelledError:
            self._cancel_requested.set()
            await self._cancel_active()
            self._set_terminal(
                ExecutionStatus.ABORTED,
                "EXECUTION_CANCELLED",
                "execution task was cancelled",
            )
        except CrazySwarmError as error:
            await self._cancel_active()
            self._set_terminal(ExecutionStatus.FAILED, error.code.value, error.message)
        except Exception as error:  # pragma: no cover - defensive owner boundary
            await self._cancel_active()
            self._set_terminal(
                ExecutionStatus.FAILED,
                "EXECUTION_EXCEPTION",
                f"{type(error).__name__}: {error}",
            )
        finally:
            with suppress(CrazySwarmError, TimeoutError):
                await asyncio.wait_for(
                    self.preparation.disconnect_all_safe(),
                    timeout=max(
                        1.0,
                        len(self.deployment.fleet)
                        * self.mission_runner.supervisor.policy.command_timeout_s,
                    ),
                )
            self._cleanup_complete = True
            self._updated_at = time.monotonic()
        return self.record

    async def cancel(self) -> ExecutionRecord:
        if self.terminal and self._cleanup_complete:
            return self.record
        self._cancel_requested.set()
        await self._cancel_active()
        if not self.terminal:
            self._set_terminal(
                ExecutionStatus.ABORTED,
                "EXECUTION_CANCELLED",
                "execution cancellation requested",
            )
        return self.record

    async def abort_vehicle(self, vehicle_id: str, *, reason: str) -> ExecutionRecord:
        if self.fleet_coordinator is None:
            if vehicle_id not in self.assignments.values():
                raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "vehicle is not active")
            with suppress(CrazySwarmError):
                await self.mission_runner.cancel(self.execution_run_id)
        else:
            await self.fleet_coordinator.abort_vehicle(vehicle_id, reason=reason)
        return self.record

    async def _run_single(self) -> MissionResult:
        task_id, vehicle_id = next(iter(self.assignments.items()))
        accepted_program = next(
            (
                program
                for program in self.mission_plan.execution_programs
                if program.role_id == task_id and program.vehicle_id == vehicle_id
            ),
            None,
        )
        fleet_binding = FleetCommandBinding(
            fleet_session_id=self.execution_session_id,
            fleet_run_id=self.execution_run_id,
            deployment_sha256=self.deployment.sha256,
            task_id=task_id,
            task_lease_generation=1,
            backend_namespace=self.binding.binding(vehicle_id).backend_identifier,
        )
        return await self.mission_runner.run(
            self.mission_id,
            vehicle_id,
            mission_run_id=self.execution_run_id,
            fleet_binding=fleet_binding,
            mission_role_id=task_id,
            require_prepared=True,
            allow_simulation_low_battery=self.allow_simulation_low_battery,
            accepted_plan_id=(self.mission_plan.plan_id if accepted_program is not None else None),
            accepted_plan_sha256=(
                self.mission_plan.sha256 if accepted_program is not None else None
            ),
            accepted_execution_program=accepted_program,
        )

    async def _cancel_active(self) -> None:
        if self.fleet_coordinator is not None:
            await self.fleet_coordinator.shutdown(reason="top-level execution cancelled")
            return
        with suppress(CrazySwarmError):
            await self.mission_runner.cancel(self.execution_run_id)

    def _apply_mission_result(self, result: MissionResult) -> None:
        status = {
            MissionStatus.SUCCEEDED: ExecutionStatus.SUCCEEDED,
            MissionStatus.ABORTED: ExecutionStatus.ABORTED,
            MissionStatus.FAILED: ExecutionStatus.FAILED,
        }[result.status]
        self._set_terminal(status, result.reason_code, result.message)

    def _apply_fleet_result(self, result: FleetResult) -> None:
        status = {
            FleetStatus.SUCCEEDED: ExecutionStatus.SUCCEEDED,
            FleetStatus.DEGRADED: ExecutionStatus.DEGRADED,
            FleetStatus.ABORTED: ExecutionStatus.ABORTED,
            FleetStatus.FAILED: ExecutionStatus.FAILED,
        }[result.status]
        self._set_terminal(status, result.reason_code, result.message)

    def _set(self, status: ExecutionStatus, message: str) -> None:
        self._status = status
        self._message = message
        self._updated_at = time.monotonic()

    def _set_terminal(self, status: ExecutionStatus, reason_code: str, message: str) -> None:
        self._reason_code = reason_code
        self._set(status, message)
