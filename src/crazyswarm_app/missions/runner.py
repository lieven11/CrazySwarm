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

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import CommandSource, VehicleCapability, VehicleState
from crazyswarm_app.domain.simulation import SimulationRunIdentity
from crazyswarm_app.missions.base import (
    Mission,
    MissionCancelled,
    MissionContext,
    MissionParameters,
)
from crazyswarm_app.missions.models import (
    MissionPhase,
    MissionResult,
    MissionRunEvent,
    MissionRunSnapshot,
    MissionStatus,
)
from crazyswarm_app.missions.registry import MissionRegistry
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

    async def cancel(self, mission_run_id: str) -> MissionRunSnapshot:
        async with self._guard:
            snapshot = self.get_run(mission_run_id)
            if snapshot.result is not None:
                return snapshot
            cancel_event = self._cancel_events[mission_run_id]
            cancel_event.set()
            self._runs[mission_run_id] = snapshot.model_copy(
                update={"cancellation_requested": True}
            )
            task = self._tasks.get(mission_run_id)
            if task is not None and task is not asyncio.current_task():
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
    ) -> MissionResult:
        run_id = mission_run_id or f"run-{uuid.uuid4().hex}"
        mission = self.registry.get(mission_id)
        started_s = time.monotonic()
        started_utc = datetime.now(UTC)
        cancel_event = asyncio.Event()
        parsed: MissionParameters | None = None
        config_hash = hashlib.sha256(b"unvalidated").hexdigest()

        try:
            parsed = self.registry.validate_parameters(
                mission_id,
                parameters,
                preset=preset,
                overrides=overrides,
            )
            receipt = self._receipt_fields(mission, vehicle_id)
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
            )

        snapshot = MissionRunSnapshot(
            mission_run_id=run_id,
            mission_id=mission_id,
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

        try:
            session = self.supervisor.session(vehicle_id)
            if session.state is VehicleState.DISCONNECTED:
                self._phase(run_id, MissionPhase.CONNECTING, "connecting vehicle")
                await self.supervisor.connect(vehicle_id)
                connected_here = True
            self._phase(run_id, MissionPhase.CLAIMING_CONTROL, "claiming command authority")
            self.supervisor.claim_control(vehicle_id, owner_id)
            heartbeat = asyncio.create_task(
                self._lease_heartbeat(vehicle_id, owner_id, cancel_event)
            )

            self._phase(run_id, MissionPhase.PREFLIGHT, "running preflight checks")
            report = await self.supervisor.preflight(
                vehicle_id,
                owner_id,
                required_capabilities=mission.required_capabilities
                | frozenset({VehicleCapability.ARMING}),
            )
            if not report.approved:
                failed = [check.code for check in report.checks if not check.passed]
                raise CrazySwarmError(
                    ErrorCode.PREFLIGHT_FAILED,
                    "mission preflight failed",
                    details={"failed_checks": failed},
                )

            self._phase(run_id, MissionPhase.ARMING, "arming vehicle")
            await self.supervisor.arm(
                vehicle_id,
                owner_id,
                report.report_id,
                source=CommandSource.MISSION,
                mission_run_id=run_id,
            )
            context = MissionContext(
                mission_run_id=run_id,
                vehicle_id=vehicle_id,
                owner_id=owner_id,
                supervisor=self.supervisor,
                cancellation_requested=cancel_event.is_set,
            )
            if mission.manages_flight_path:
                self._phase(run_id, MissionPhase.EXECUTING, "executing mission file")
                await self._execute_behavior(mission, context, parsed)
                if self.supervisor.session(vehicle_id).state is not VehicleState.READY:
                    raise CrazySwarmError(
                        ErrorCode.INVALID_STATE,
                        "mission file did not finish landed and ready",
                    )
            else:
                self._phase(run_id, MissionPhase.TAKING_OFF, "taking off")
                await self.supervisor.takeoff(
                    vehicle_id,
                    owner_id,
                    height_m=mission.takeoff_height_m(parsed),
                    duration_s=mission.takeoff_duration_s(parsed),
                    source=CommandSource.MISSION,
                    mission_run_id=run_id,
                )
                self._phase(run_id, MissionPhase.EXECUTING, "executing mission behavior")
                await self._execute_behavior(mission, context, parsed)
                self._phase(run_id, MissionPhase.LANDING, "landing vehicle")
                await self.supervisor.land(
                    vehicle_id,
                    owner_id,
                    duration_s=mission.landing_duration_s(parsed),
                    source=CommandSource.MISSION,
                    mission_run_id=run_id,
                )
        except (asyncio.CancelledError, MissionCancelled):
            status = MissionStatus.ABORTED
            reason_code = "MISSION_CANCELLED"
            message = "mission was cancelled; abort-and-land recovery requested"
            await self._shielded_recovery(vehicle_id, owner_id, reason_code)
        except TimeoutError:
            status = MissionStatus.ABORTED
            reason_code = "MISSION_TIMEOUT"
            message = "mission execution timed out; abort-and-land recovery requested"
            await self._shielded_recovery(vehicle_id, owner_id, reason_code)
        except CrazySwarmError as error:
            status = MissionStatus.FAILED
            reason_code = error.code.value
            message = error.message
            await self._shielded_recovery(vehicle_id, owner_id, reason_code)
        except Exception as error:  # pragma: no cover - defensive boundary is tested by behavior
            status = MissionStatus.FAILED
            reason_code = "MISSION_EXCEPTION"
            message = f"{type(error).__name__}: {error}"
            await self._shielded_recovery(vehicle_id, owner_id, reason_code)
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
            self._phase(run_id, MissionPhase.CLEANUP, "releasing mission resources")
            await self._cleanup(vehicle_id, owner_id, connected_here)

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
            timeout=min(
                mission.execution_timeout_s(parameters),
                self.supervisor.policy.max_mission_duration_s,
            ),
        )
        context.checkpoint()

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

    async def _shielded_recovery(self, vehicle_id: str, owner_id: str, reason: str) -> None:
        async def recover() -> None:
            session = self.supervisor.session(vehicle_id)
            if session.state in {
                VehicleState.TAKING_OFF,
                VehicleState.FLYING,
                VehicleState.RETURNING,
            }:
                with suppress(Exception):
                    await self.supervisor.abort_and_land(vehicle_id, owner_id, reason=reason)

        with suppress(Exception):
            await asyncio.shield(recover())

    async def _cleanup(self, vehicle_id: str, owner_id: str, connected_here: bool) -> None:
        session = self.supervisor.session(vehicle_id)
        if (
            session.state is VehicleState.READY
            and session.telemetry is not None
            and session.telemetry.telemetry.armed
        ):
            with suppress(Exception):
                await self.supervisor.disarm(
                    vehicle_id,
                    owner_id,
                    source=CommandSource.MISSION,
                )
        if session.lease is not None and session.lease.owner_id == owner_id:
            with suppress(Exception):
                await self.supervisor.release_control(vehicle_id, owner_id)
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
            mission_id=snapshot.mission_id,
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
            parameters=snapshot.parameters,
            started_at_monotonic_s=snapshot.started_at_monotonic_s,
            finished_at_monotonic_s=time.monotonic(),
            started_at_utc=started_utc,
            events=tuple(self._events.get(snapshot.mission_run_id, ())),
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
    ) -> MissionResult:
        snapshot = MissionRunSnapshot(
            mission_run_id=run_id,
            mission_id=mission.mission_id,
            mission_version=mission.mission_version,
            vehicle_id=vehicle_id,
            mode=self.supervisor.mode,
            phase=MissionPhase.COMPLETE,
            configuration_hash=config_hash,
            **self._receipt_fields(mission, vehicle_id),
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
        }
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

    def _notify(self, method: str, value: object) -> None:
        for sink in self._audit_sinks:
            try:
                getattr(sink, method)(value)
            except Exception:
                # Evidence is required for operations, but never part of the control path.
                continue
