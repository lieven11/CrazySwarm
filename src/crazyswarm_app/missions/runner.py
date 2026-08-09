from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Protocol

from crazyswarm_app.domain.commands import FleetCommandBinding
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import CommandSource, VehicleCapability, VehicleState
from crazyswarm_app.domain.simulation import (
    FleetAuthorityTransition,
    FleetAuthorityTransitionReceipt,
    MissionRunBinding,
    SimulationRunIdentity,
)
from crazyswarm_app.domain.trajectory import AcceptedExecutionProgram, GroundWaitExecutionOperation
from crazyswarm_app.missions.authority import MissionFleetAuthority
from crazyswarm_app.missions.base import (
    Mission,
    MissionCancelled,
    MissionContext,
    MissionParameters,
)
from crazyswarm_app.missions.coordination import MissionCommandGate
from crazyswarm_app.missions.models import (
    MissionPhase,
    MissionResult,
    MissionRunEvent,
    MissionRunSnapshot,
    MissionStatus,
)
from crazyswarm_app.missions.registry import MissionRegistry
from crazyswarm_app.provenance import repository_provenance
from crazyswarm_app.safety.models import HealthAssessment
from crazyswarm_app.safety.supervisor import SafetySupervisor


class MissionAuditSink(Protocol):
    def mission_started(self, run: MissionRunSnapshot) -> None: ...

    def mission_event(self, event: MissionRunEvent) -> None: ...

    def mission_finished(self, result: MissionResult) -> None: ...


class MissionRunner:
    """Owns the generic lifecycle for every registered mission and vehicle backend."""

    def __init__(
        self,
        supervisor: SafetySupervisor,
        registry: MissionRegistry,
        *,
        audit_sinks: Iterable[MissionAuditSink] = (),
    ) -> None:
        self.supervisor = supervisor
        self.registry = registry
        self._runs: dict[str, MissionRunSnapshot] = {}
        self._events: dict[str, list[MissionRunEvent]] = {}
        self._vehicle_runs: dict[str, str] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[object]] = {}
        self._authorities: dict[str, MissionFleetAuthority] = {}
        self._authority_receipts: dict[str, tuple[FleetAuthorityTransitionReceipt, ...]] = {}
        self._guard = asyncio.Lock()
        self._audit_sinks = list(audit_sinks)

    def add_audit_sink(self, sink: MissionAuditSink) -> None:
        self._audit_sinks.append(sink)

    def list_runs(self) -> tuple[MissionRunSnapshot, ...]:
        return tuple(self._runs[key] for key in sorted(self._runs))

    def get_run(self, mission_run_id: str) -> MissionRunSnapshot:
        try:
            return self._runs[mission_run_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                f"unknown mission run: {mission_run_id}",
            ) from error

    def current_fleet_binding(
        self,
        mission_run_id: str,
    ) -> FleetCommandBinding | None:
        try:
            return self._authorities[mission_run_id].current_binding
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                f"mission run has no active command authority: {mission_run_id}",
            ) from error

    def authority_receipts(
        self,
        mission_run_id: str,
    ) -> tuple[FleetAuthorityTransitionReceipt, ...]:
        authority = self._authorities.get(mission_run_id)
        if authority is not None:
            return authority.receipts
        return self._authority_receipts.get(mission_run_id, ())

    async def transition_fleet_authority(
        self,
        mission_run_id: str,
        transition: FleetAuthorityTransition,
    ) -> FleetAuthorityTransitionReceipt:
        try:
            authority = self._authorities[mission_run_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                f"mission run has no active command authority: {mission_run_id}",
            ) from error
        receipt = await authority.transition(transition)
        self._authority_receipts[mission_run_id] = authority.receipts
        snapshot = self.get_run(mission_run_id)
        self._phase(
            mission_run_id,
            snapshot.phase,
            (
                f"fleet authority {receipt.transition_id} accepted: "
                f"{receipt.previous_task_id}@{receipt.previous_task_lease_generation} -> "
                f"{receipt.current_task_id}@{receipt.current_task_lease_generation}"
            ),
        )
        return receipt

    async def cancel(self, mission_run_id: str) -> MissionRunSnapshot:
        async with self._guard:
            snapshot = self.get_run(mission_run_id)
            if snapshot.result is not None or snapshot.cancellation_requested:
                return snapshot
            cancel_event = self._cancel_events[mission_run_id]
            cancel_event.set()
            self._runs[mission_run_id] = snapshot.model_copy(
                update={"cancellation_requested": True}
            )
            task = self._tasks.get(mission_run_id)
            if task is not None and not task.done() and task is not asyncio.current_task():
                task.cancel()
            return self._runs[mission_run_id]

    async def run(
        self,
        mission_id: str,
        vehicle_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        preset: str | None = None,
        overrides: dict[str, Any] | None = None,
        mission_run_id: str | None = None,
        fleet_binding: FleetCommandBinding | None = None,
        mission_role_id: str | None = None,
        command_gate: MissionCommandGate | None = None,
        require_prepared: bool = False,
        allow_simulation_low_battery: bool = False,
        accepted_plan_id: str | None = None,
        accepted_plan_sha256: str | None = None,
        accepted_execution_program: AcceptedExecutionProgram | None = None,
    ) -> MissionResult:
        run_id = mission_run_id or f"run-{uuid.uuid4().hex}"
        mission = self.registry.get(mission_id)
        started_s = time.monotonic()
        started_utc = datetime.now(UTC)
        cancel_event = asyncio.Event()
        parsed: MissionParameters | None = None
        config_hash = hashlib.sha256(b"unvalidated").hexdigest()
        authority_receipt = self._empty_execution_authority_fields()

        try:
            parsed = self.registry.validate_parameters(
                mission_id,
                parameters,
                preset=preset,
                overrides=overrides,
            )
            authority_receipt = self._validate_execution_authority(
                mission,
                vehicle_id,
                mission_role_id=mission_role_id,
                accepted_plan_id=accepted_plan_id,
                accepted_plan_sha256=accepted_plan_sha256,
                accepted_execution_program=accepted_execution_program,
            )
            receipt = {
                **self._receipt_fields(mission, vehicle_id),
                **authority_receipt,
            }
            config_hash = self._configuration_hash(mission, parsed, receipt)
        except CrazySwarmError as error:
            return self._validation_failure(
                run_id,
                mission,
                vehicle_id,
                started_s,
                started_utc,
                error,
                config_hash,
                mission_execution_id=(
                    fleet_binding.fleet_run_id if fleet_binding is not None else run_id
                ),
                authority_receipt=authority_receipt,
            )

        snapshot = MissionRunSnapshot(
            mission_run_id=run_id,
            mission_execution_id=(
                fleet_binding.fleet_run_id if fleet_binding is not None else run_id
            ),
            mission_id=mission_id,
            mission_name=mission.name,
            mission_version=mission.mission_version,
            vehicle_id=vehicle_id,
            mode=self.supervisor.mode,
            phase=MissionPhase.VALIDATING,
            configuration_hash=config_hash,
            **receipt,
            parameters=parsed.model_dump(mode="json"),
            started_at_monotonic_s=started_s,
        )
        async with self._guard:
            active = self._vehicle_runs.get(vehicle_id)
            if active is not None:
                result = self._result(
                    snapshot,
                    MissionStatus.FAILED,
                    "MISSION_CONFLICT",
                    f"vehicle is already owned by mission run {active}",
                    started_utc,
                )
                self._runs[run_id] = snapshot.model_copy(update={"result": result})
                self._notify("mission_started", snapshot)
                self._notify("mission_finished", result)
                return result
            self._vehicle_runs[vehicle_id] = run_id
            self._cancel_events[run_id] = cancel_event
            self._tasks[run_id] = asyncio.current_task()  # type: ignore[assignment]
            self._runs[run_id] = snapshot
            self._events[run_id] = []
        self._notify("mission_started", snapshot)

        owner_id = f"mission:{run_id}"
        connected_here = False
        status = MissionStatus.SUCCEEDED
        reason_code = "MISSION_COMPLETED"
        message = "mission completed successfully"
        heartbeat: asyncio.Task[None] | None = None
        intent_trace: list[dict[str, Any]] = []
        observations_read: list[dict[str, Any]] = []
        goal_captures: list[dict[str, Any]] = []
        session = self.supervisor.session(vehicle_id)
        authority = MissionFleetAuthority(session.vehicle, fleet_binding)
        self._authorities[run_id] = authority
        self._authority_receipts[run_id] = ()

        try:
            if session.state is VehicleState.DISCONNECTED:
                if require_prepared:
                    raise CrazySwarmError(
                        ErrorCode.PREFLIGHT_FAILED,
                        "prepared mission start requires an explicitly connected vehicle",
                    )
                self._phase(run_id, MissionPhase.CONNECTING, "connecting vehicle")
                await self.supervisor.connect(vehicle_id)
                connected_here = True
            await session.vehicle.bind_run(
                MissionRunBinding(
                    mission_run_id=run_id,
                    mission_source_sha256=snapshot.mission_source_sha256,
                    run_identity_sha256=snapshot.run_identity_sha256,
                    model_id=snapshot.physics_model_id,
                    model_version=snapshot.physics_model_version,
                    model_configuration_sha256=snapshot.physics_configuration_sha256,
                    scenario_id=snapshot.scenario_id,
                    scenario_configuration_sha256=snapshot.scenario_configuration_sha256,
                    fleet_session_id=(
                        fleet_binding.fleet_session_id if fleet_binding is not None else None
                    ),
                    fleet_run_id=(
                        fleet_binding.fleet_run_id if fleet_binding is not None else None
                    ),
                    deployment_sha256=(
                        fleet_binding.deployment_sha256 if fleet_binding is not None else None
                    ),
                    task_id=fleet_binding.task_id if fleet_binding is not None else None,
                    task_lease_generation=(
                        fleet_binding.task_lease_generation if fleet_binding is not None else None
                    ),
                    backend_namespace=(
                        fleet_binding.backend_namespace if fleet_binding is not None else None
                    ),
                    preparation_state=(
                        fleet_binding.preparation_state if fleet_binding is not None else None
                    ),
                )
            )
            self._phase(run_id, MissionPhase.CLAIMING_CONTROL, "claiming command authority")
            self.supervisor.claim_control(vehicle_id, owner_id)
            heartbeat = asyncio.create_task(
                self._lease_heartbeat(vehicle_id, owner_id, cancel_event)
            )

            context = MissionContext(
                mission_run_id=run_id,
                vehicle_id=vehicle_id,
                owner_id=owner_id,
                supervisor=self.supervisor,
                cancellation_requested=cancel_event.is_set,
                fleet_authority=authority,
                command_gate=command_gate,
                role_id=(
                    mission_role_id
                    or (fleet_binding.task_id if fleet_binding is not None else "primary")
                ),
                accepted_plan_id=accepted_plan_id,
                accepted_plan_sha256=accepted_plan_sha256,
                accepted_execution_program=accepted_execution_program,
                intent_trace=intent_trace,
                observations_read=observations_read,
                goal_captures=goal_captures,
            )
            first_operation = (
                accepted_execution_program.operations[0]
                if accepted_execution_program is not None
                else None
            )
            if isinstance(first_operation, GroundWaitExecutionOperation):
                if accepted_execution_program is None:
                    raise AssertionError("ground wait requires an accepted execution program")
                self._phase(
                    run_id,
                    MissionPhase.PREFLIGHT,
                    "waiting on ground before just-in-time preflight and arm",
                )
                await asyncio.wait_for(
                    context.ground_wait(
                        first_operation.ends_at_s - first_operation.starts_at_s
                    ),
                    timeout=accepted_execution_program.execution_timeout_s,
                )
                context.completed_ground_wait_sequences.add(first_operation.sequence)

            self._phase(run_id, MissionPhase.PREFLIGHT, "running preflight checks")
            report = await self.supervisor.preflight(
                vehicle_id,
                owner_id,
                required_capabilities=mission.required_capabilities
                | frozenset({VehicleCapability.ARMING})
                | (
                    frozenset({VehicleCapability.TIME_PARAMETERIZED_TRAJECTORY})
                    if accepted_execution_program is not None
                    else frozenset()
                ),
                allow_simulation_low_battery=allow_simulation_low_battery,
            )
            if not report.approved:
                failed = [check.code for check in report.checks if not check.passed]
                raise CrazySwarmError(
                    ErrorCode.PREFLIGHT_FAILED,
                    "mission preflight failed",
                    details={"failed_checks": failed},
                )
            current_telemetry = session.telemetry.telemetry if session.telemetry else None
            if (
                allow_simulation_low_battery
                and current_telemetry is not None
                and current_telemetry.battery_percent is not None
                and current_telemetry.battery_percent
                <= self.supervisor.policy.critical_battery_percent
            ):
                raise CrazySwarmError(
                    ErrorCode.CRITICAL_BATTERY,
                    "critical simulated battery cannot receive new mission authority",
                )

            self._phase(run_id, MissionPhase.ARMING, "arming vehicle")
            await authority.execute(
                lambda binding: self.supervisor.arm(
                    vehicle_id,
                    owner_id,
                    report.report_id,
                    source=CommandSource.MISSION,
                    mission_run_id=run_id,
                    fleet_binding=binding,
                )
            )
            await self._execute_with_health_watchdog(
                mission,
                context,
                parsed,
                run_id=run_id,
                vehicle_id=vehicle_id,
                owner_id=owner_id,
                cancel_event=cancel_event,
                authority=authority,
                allow_simulation_low_battery=allow_simulation_low_battery,
            )
        except (asyncio.CancelledError, MissionCancelled):
            if self.supervisor.session(vehicle_id).state is VehicleState.EMERGENCY:
                status = MissionStatus.ABORTED
                reason_code = ErrorCode.EMERGENCY_STOPPED.value
                message = "mission was preempted by a supervised emergency stop"
            else:
                status = MissionStatus.ABORTED
                reason_code = "MISSION_CANCELLED"
                message = "mission was cancelled; abort-and-land recovery requested"
                await self._shielded_recovery(
                    vehicle_id,
                    owner_id,
                    reason_code,
                    mission_run_id=run_id,
                    authority=authority,
                )
        except TimeoutError:
            status = MissionStatus.ABORTED
            reason_code = "MISSION_TIMEOUT"
            message = "mission execution timed out; abort-and-land recovery requested"
            await self._shielded_recovery(
                vehicle_id,
                owner_id,
                reason_code,
                mission_run_id=run_id,
                authority=authority,
            )
        except CrazySwarmError as error:
            status = MissionStatus.FAILED
            reason_code = error.code.value
            message = error.message
            await self._shielded_recovery(
                vehicle_id,
                owner_id,
                reason_code,
                mission_run_id=run_id,
                authority=authority,
            )
        except Exception as error:  # pragma: no cover - defensive boundary is tested by behavior
            status = MissionStatus.FAILED
            reason_code = "MISSION_EXCEPTION"
            message = f"{type(error).__name__}: {error}"
            await self._shielded_recovery(
                vehicle_id,
                owner_id,
                reason_code,
                mission_run_id=run_id,
                authority=authority,
            )
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError, CrazySwarmError):
                    await heartbeat
            self._phase(run_id, MissionPhase.CLEANUP, "releasing mission resources")
            await self._cleanup(
                vehicle_id,
                owner_id,
                connected_here,
                mission_run_id=run_id,
                authority=authority,
            )

        current_snapshot = self._runs[run_id]
        self._runs[run_id] = current_snapshot.model_copy(
            update={
                "normalized_intent_trace": tuple(intent_trace),
                "observations_read": tuple(observations_read),
                "goal_captures": tuple(goal_captures),
            }
        )

        self._authority_receipts[run_id] = authority.receipts
        current = self._runs[run_id]
        result = self._result(current, status, reason_code, message, started_utc)
        self._phase(run_id, MissionPhase.COMPLETE, f"mission ended {status.value}")
        current = self._runs[run_id]
        result = result.model_copy(update={"events": tuple(self._events[run_id])})
        async with self._guard:
            self._runs[run_id] = current.model_copy(update={"result": result})
            self._vehicle_runs.pop(vehicle_id, None)
            self._cancel_events.pop(run_id, None)
            self._tasks.pop(run_id, None)
            self._authorities.pop(run_id, None)
        self._notify("mission_finished", result)
        return result

    async def _execute_behavior(
        self,
        mission: Mission[Any],
        context: MissionContext,
        parameters: MissionParameters,
    ) -> None:
        await asyncio.wait_for(
            mission.execute(context, parameters),
            timeout=(
                context.accepted_execution_program.execution_timeout_s
                if context.accepted_execution_program is not None
                else min(
                    mission.execution_timeout_s(parameters),
                    self.supervisor.policy.max_mission_duration_s,
                )
            ),
        )
        context.checkpoint()

    async def _execute_with_health_watchdog(
        self,
        mission: Mission[Any],
        context: MissionContext,
        parameters: MissionParameters,
        *,
        run_id: str,
        vehicle_id: str,
        owner_id: str,
        cancel_event: asyncio.Event,
        authority: MissionFleetAuthority,
        allow_simulation_low_battery: bool,
    ) -> None:
        deferred_landing_faults: list[tuple[str, str]] = []
        flight_task = asyncio.create_task(
            self._execute_flight_path(
                mission,
                context,
                parameters,
                run_id=run_id,
                vehicle_id=vehicle_id,
                owner_id=owner_id,
                authority=authority,
            ),
            name=f"mission-flight-{run_id}",
        )
        watchdog_task = asyncio.create_task(
            self._health_watchdog(
                vehicle_id,
                owner_id,
                cancel_event,
                deferred_landing_faults,
                authority=authority,
                run_id=run_id,
                allow_simulation_low_battery=allow_simulation_low_battery,
            ),
            name=f"mission-health-{run_id}",
        )
        try:
            done, _ = await asyncio.wait(
                {flight_task, watchdog_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if watchdog_task in done:
                flight_task.cancel()
                with suppress(asyncio.CancelledError, CrazySwarmError):
                    await flight_task
                await watchdog_task
            else:
                session = self.supervisor.session(vehicle_id)
                if session.state in {VehicleState.ABORTING, VehicleState.EMERGENCY}:
                    # The active command ended because the watchdog preempted it. Let the
                    # watchdog finish the serialized recovery before surfacing the fault.
                    await watchdog_task
                else:
                    watchdog_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await watchdog_task
                    await flight_task
                    if deferred_landing_faults:
                        code, message = deferred_landing_faults[0]
                        raise CrazySwarmError(
                            ErrorCode.LOCALIZATION_INVALID,
                            message,
                            details={"health_issue": code, "recovery": "LAND_COMPLETED"},
                        )
        finally:
            for task in (flight_task, watchdog_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(flight_task, watchdog_task, return_exceptions=True)

    async def _execute_flight_path(
        self,
        mission: Mission[Any],
        context: MissionContext,
        parameters: MissionParameters,
        *,
        run_id: str,
        vehicle_id: str,
        owner_id: str,
        authority: MissionFleetAuthority,
    ) -> None:
        if mission.manages_flight_path:
            self._phase(run_id, MissionPhase.EXECUTING, "executing mission file")
            await self._execute_behavior(mission, context, parameters)
            if self.supervisor.session(vehicle_id).state is not VehicleState.READY:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "mission file did not finish landed and ready",
                )
            return
        self._phase(run_id, MissionPhase.TAKING_OFF, "taking off")
        await authority.execute(
            lambda binding: self.supervisor.takeoff(
                vehicle_id,
                owner_id,
                height_m=mission.takeoff_height_m(parameters),
                duration_s=mission.takeoff_duration_s(parameters),
                source=CommandSource.MISSION,
                mission_run_id=run_id,
                fleet_binding=binding,
            )
        )
        self._phase(run_id, MissionPhase.EXECUTING, "executing mission behavior")
        await self._execute_behavior(mission, context, parameters)
        self._phase(run_id, MissionPhase.LANDING, "landing vehicle")
        await authority.execute(
            lambda binding: self.supervisor.land(
                vehicle_id,
                owner_id,
                duration_s=mission.landing_duration_s(parameters),
                source=CommandSource.MISSION,
                mission_run_id=run_id,
                fleet_binding=binding,
            )
        )

    async def _health_watchdog(
        self,
        vehicle_id: str,
        owner_id: str,
        cancel_event: asyncio.Event,
        deferred_landing_faults: list[tuple[str, str]],
        *,
        authority: MissionFleetAuthority,
        run_id: str,
        allow_simulation_low_battery: bool,
    ) -> None:
        profile_period_s = self.supervisor.session(
            vehicle_id
        ).vehicle.backend_profile.recommended_watchdog_period_s
        period_s = min(self.supervisor.policy.health_watchdog_period_s, profile_period_s)
        while not cancel_event.is_set():
            await asyncio.sleep(period_s)
            session = self.supervisor.session(vehicle_id)
            if session.state not in {
                VehicleState.TAKING_OFF,
                VehicleState.FLYING,
                VehicleState.RETURNING,
                VehicleState.LANDING,
            }:
                continue
            if session.state is VehicleState.LANDING:

                async def assess_landing(
                    binding: FleetCommandBinding | None,
                ) -> HealthAssessment:
                    del binding
                    await self.supervisor.observe(
                        vehicle_id,
                        owner_id,
                        timeout_s=min(0.5, self.supervisor.policy.command_timeout_s),
                    )
                    return self.supervisor.evaluate_health(
                        vehicle_id,
                        allow_simulation_low_battery=allow_simulation_low_battery,
                    )

                assessment = await authority.evaluate_health(assess_landing)
                if not assessment.healthy and not deferred_landing_faults:
                    issue = assessment.issues[0]
                    deferred_landing_faults.append((issue.code, issue.message))
                continue
            assessment = await authority.evaluate_health(
                lambda binding: self.supervisor.refresh_and_enforce_health(
                    vehicle_id,
                    owner_id,
                    mission_run_id=run_id,
                    fleet_binding=binding,
                    allow_simulation_low_battery=allow_simulation_low_battery,
                )
            )
            if not assessment.healthy:
                issue = assessment.issues[0]
                raise CrazySwarmError(
                    ErrorCode.LOCALIZATION_INVALID,
                    issue.message,
                    details={"health_issue": issue.code},
                )

    async def _lease_heartbeat(
        self,
        vehicle_id: str,
        owner_id: str,
        cancel_event: asyncio.Event,
    ) -> None:
        period_s = max(0.05, self.supervisor.policy.control_lease_timeout_s / 3.0)
        while not cancel_event.is_set():
            await asyncio.sleep(period_s)
            self.supervisor.renew_control(vehicle_id, owner_id)

    async def _shielded_recovery(
        self,
        vehicle_id: str,
        owner_id: str,
        reason: str,
        *,
        mission_run_id: str,
        authority: MissionFleetAuthority,
    ) -> None:
        async def recover() -> None:
            session = self.supervisor.session(vehicle_id)
            if session.state in {
                VehicleState.TAKING_OFF,
                VehicleState.FLYING,
                VehicleState.RETURNING,
            }:
                with suppress(Exception):
                    await authority.execute(
                        lambda binding: self.supervisor.abort_and_land(
                            vehicle_id,
                            owner_id,
                            reason=reason,
                            mission_run_id=mission_run_id,
                            fleet_binding=binding,
                        )
                    )
            elif session.state in {VehicleState.LANDING, VehicleState.ABORTING}:
                with suppress(Exception):
                    await authority.execute(
                        lambda binding: self.supervisor.emergency_stop(
                            vehicle_id,
                            owner_id,
                            reason=f"interrupted landing recovery: {reason}",
                            mission_run_id=mission_run_id,
                            fleet_binding=binding,
                        )
                    )

        with suppress(Exception):
            await asyncio.shield(recover())

    async def _cleanup(
        self,
        vehicle_id: str,
        owner_id: str,
        connected_here: bool,
        *,
        mission_run_id: str,
        authority: MissionFleetAuthority,
    ) -> None:
        session = self.supervisor.session(vehicle_id)
        if (
            session.state is VehicleState.READY
            and session.telemetry is not None
            and session.telemetry.telemetry.armed
        ):
            with suppress(Exception):
                await authority.execute(
                    lambda binding: self.supervisor.disarm(
                        vehicle_id,
                        owner_id,
                        source=CommandSource.MISSION,
                        mission_run_id=mission_run_id,
                        fleet_binding=binding,
                    )
                )
        if session.lease is not None and session.lease.owner_id == owner_id:
            with suppress(Exception):
                await self.supervisor.release_control(
                    vehicle_id,
                    owner_id,
                    allow_expired_owner=True,
                )
        if connected_here and self.supervisor.session(vehicle_id).state is VehicleState.READY:
            with suppress(Exception):
                await self.supervisor.disconnect(vehicle_id)

    def _phase(self, run_id: str, phase: MissionPhase, message: str) -> None:
        snapshot = self._runs[run_id]
        event = MissionRunEvent(
            mission_run_id=run_id,
            sequence=len(self._events[run_id]) + 1,
            phase=phase,
            timestamp_monotonic_s=time.monotonic(),
            message=message,
        )
        self._events[run_id].append(event)
        self._runs[run_id] = snapshot.model_copy(update={"phase": phase})
        self._notify("mission_event", event)

    def _result(
        self,
        snapshot: MissionRunSnapshot,
        status: MissionStatus,
        reason_code: str,
        message: str,
        started_utc: datetime,
    ) -> MissionResult:
        return MissionResult(
            mission_run_id=snapshot.mission_run_id,
            mission_execution_id=snapshot.mission_execution_id,
            mission_id=snapshot.mission_id,
            mission_name=snapshot.mission_name,
            mission_version=snapshot.mission_version,
            vehicle_id=snapshot.vehicle_id,
            mode=snapshot.mode,
            status=status,
            reason_code=reason_code,
            message=message,
            configuration_hash=snapshot.configuration_hash,
            mission_source_sha256=snapshot.mission_source_sha256,
            mission_runtime_id=snapshot.mission_runtime_id,
            mission_runtime_version=snapshot.mission_runtime_version,
            vehicle_adapter=snapshot.vehicle_adapter,
            backend_role=snapshot.backend_role,
            authority_class=snapshot.authority_class,
            repository_commit=snapshot.repository_commit,
            repository_dirty=snapshot.repository_dirty,
            physics_model_id=snapshot.physics_model_id,
            physics_model_version=snapshot.physics_model_version,
            physics_configuration_sha256=snapshot.physics_configuration_sha256,
            scenario_id=snapshot.scenario_id,
            scenario_schema_version=snapshot.scenario_schema_version,
            scenario_configuration_sha256=snapshot.scenario_configuration_sha256,
            simulation_seed=snapshot.simulation_seed,
            simulation_fixed_step_s=snapshot.simulation_fixed_step_s,
            initial_state_sha256=snapshot.initial_state_sha256,
            run_identity_sha256=snapshot.run_identity_sha256,
            accepted_plan_id=snapshot.accepted_plan_id,
            accepted_plan_sha256=snapshot.accepted_plan_sha256,
            execution_program_id=snapshot.execution_program_id,
            execution_program_sha256=snapshot.execution_program_sha256,
            accepted_trajectory_sha256s=snapshot.accepted_trajectory_sha256s,
            execution_clock_policy=snapshot.execution_clock_policy,
            parameters=snapshot.parameters,
            started_at_monotonic_s=snapshot.started_at_monotonic_s,
            finished_at_monotonic_s=time.monotonic(),
            started_at_utc=started_utc,
            events=tuple(self._events.get(snapshot.mission_run_id, ())),
            normalized_intent_trace=snapshot.normalized_intent_trace,
            observations_read=snapshot.observations_read,
            fleet_authority_transitions=self._authority_receipts.get(snapshot.mission_run_id, ()),
            goal_captures=snapshot.goal_captures,
        )

    def _validation_failure(
        self,
        run_id: str,
        mission: Mission[Any],
        vehicle_id: str,
        started_s: float,
        started_utc: datetime,
        error: CrazySwarmError,
        config_hash: str,
        *,
        mission_execution_id: str,
        authority_receipt: dict[str, Any],
    ) -> MissionResult:
        snapshot = MissionRunSnapshot(
            mission_run_id=run_id,
            mission_execution_id=mission_execution_id,
            mission_id=mission.mission_id,
            mission_name=mission.name,
            mission_version=mission.mission_version,
            vehicle_id=vehicle_id,
            mode=self.supervisor.mode,
            phase=MissionPhase.COMPLETE,
            configuration_hash=config_hash,
            **{
                **self._receipt_fields(mission, vehicle_id),
                **authority_receipt,
            },
            parameters={},
            started_at_monotonic_s=started_s,
        )
        result = self._result(
            snapshot,
            MissionStatus.FAILED,
            error.code.value,
            error.message,
            started_utc,
        )
        self._runs[run_id] = snapshot.model_copy(update={"result": result})
        self._events[run_id] = []
        self._notify("mission_started", snapshot)
        self._notify("mission_finished", result)
        return result

    @staticmethod
    def _configuration_hash(
        mission: Mission[Any],
        parameters: MissionParameters,
        receipt: dict[str, Any],
    ) -> str:
        value = {
            "mission_id": mission.mission_id,
            "mission_version": mission.mission_version,
            **receipt,
            "parameters": parameters.model_dump(mode="json"),
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _receipt_fields(
        self,
        mission: Mission[Any],
        vehicle_id: str,
    ) -> dict[str, Any]:
        try:
            vehicle = self.supervisor.session(vehicle_id).vehicle
            vehicle_metadata = vehicle.execution_metadata
        except CrazySwarmError:
            vehicle_metadata = {
                "vehicle_adapter": "UNKNOWN",
                "backend_role": "UNKNOWN",
                "authority_class": "UNKNOWN",
                "physics_model_id": None,
                "physics_model_version": None,
                "physics_configuration_sha256": None,
                "scenario_id": None,
                "scenario_schema_version": None,
                "scenario_configuration_sha256": None,
                "simulation_seed": None,
                "simulation_fixed_step_s": None,
                "initial_state_sha256": None,
                "run_identity_sha256": None,
            }
        receipt = {
            "mission_source_sha256": mission.source_sha256,
            "mission_runtime_id": mission.runtime_id,
            "mission_runtime_version": mission.runtime_version,
            **vehicle_metadata,
            **repository_provenance().as_dict(),
        }
        receipt.pop("repository_provenance_available", None)
        required = (
            mission.source_sha256,
            receipt.get("physics_model_id"),
            receipt.get("physics_model_version"),
            receipt.get("physics_configuration_sha256"),
            receipt.get("scenario_id"),
            receipt.get("scenario_configuration_sha256"),
            receipt.get("initial_state_sha256"),
            receipt.get("simulation_seed"),
            receipt.get("simulation_fixed_step_s"),
        )
        if all(value is not None for value in required):
            identity = SimulationRunIdentity(
                mission_source_sha256=str(mission.source_sha256),
                model_id=str(receipt["physics_model_id"]),
                model_version=str(receipt["physics_model_version"]),
                model_configuration_sha256=str(receipt["physics_configuration_sha256"]),
                scenario_id=str(receipt["scenario_id"]),
                scenario_configuration_sha256=str(receipt["scenario_configuration_sha256"]),
                initial_state_sha256=str(receipt["initial_state_sha256"]),
                seed=int(receipt["simulation_seed"]),
                fixed_step_s=float(receipt["simulation_fixed_step_s"]),
            )
            receipt["run_identity_sha256"] = identity.sha256
        return receipt

    @staticmethod
    def _empty_execution_authority_fields() -> dict[str, Any]:
        return {
            "accepted_plan_id": None,
            "accepted_plan_sha256": None,
            "execution_program_id": None,
            "execution_program_sha256": None,
            "accepted_trajectory_sha256s": (),
            "execution_clock_policy": None,
        }

    def _validate_execution_authority(
        self,
        mission: Mission[Any],
        vehicle_id: str,
        *,
        mission_role_id: str | None,
        accepted_plan_id: str | None,
        accepted_plan_sha256: str | None,
        accepted_execution_program: AcceptedExecutionProgram | None,
    ) -> dict[str, Any]:
        if accepted_execution_program is None:
            if accepted_plan_id is not None or accepted_plan_sha256 is not None:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "accepted plan identity requires an execution program",
                )
            return self._empty_execution_authority_fields()
        if accepted_plan_id is None or accepted_plan_sha256 is None:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "accepted execution program requires its plan identity",
            )
        if len(accepted_plan_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in accepted_plan_sha256
        ):
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "accepted plan hash is invalid")
        expected_role = mission_role_id or "primary"
        if (
            accepted_execution_program.mission_source_sha256 != mission.source_sha256
            or accepted_execution_program.vehicle_id != vehicle_id
            or accepted_execution_program.role_id != expected_role
        ):
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "accepted execution authority does not match mission, role, and vehicle",
            )
        if (
            accepted_execution_program.schedule_duration_s
            > self.supervisor.policy.max_mission_duration_s
        ):
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "accepted schedule exceeds the mission duration policy",
            )
        vehicle = self.supervisor.session(vehicle_id).vehicle
        if VehicleCapability.TIME_PARAMETERIZED_TRAJECTORY not in vehicle.capabilities.features:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "selected backend does not support the accepted trajectory contract",
            )
        if (
            vehicle.backend_profile.clock_policy
            is not accepted_execution_program.clock.source_policy
        ):
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "backend clock policy contradicts the accepted execution schedule",
            )
        return {
            "accepted_plan_id": accepted_plan_id,
            "accepted_plan_sha256": accepted_plan_sha256,
            "execution_program_id": accepted_execution_program.program_id,
            "execution_program_sha256": accepted_execution_program.sha256,
            "accepted_trajectory_sha256s": (accepted_execution_program.trajectory_sha256s),
            "execution_clock_policy": (accepted_execution_program.clock.source_policy.value),
        }

    def _notify(self, method: str, value: object) -> None:
        for sink in self._audit_sinks:
            try:
                getattr(sink, method)(value)
            except Exception:
                # Evidence is required for operations, but never part of the control path.
                continue
