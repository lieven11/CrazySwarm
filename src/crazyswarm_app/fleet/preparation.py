from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    ContractModel,
    Identifier,
    Vector3,
    VehicleCapability,
    VehicleState,
)
from crazyswarm_app.domain.simulation import SHA256
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    ExecutionBackend,
    InitialFleetRole,
)
from crazyswarm_app.fleet.backends import BackendVehicleFactory
from crazyswarm_app.safety.models import PreflightReport
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.vehicles.base import Vehicle


class RegistrationState(StrEnum):
    DECLARED = "DECLARED"
    DISCOVERED = "DISCOVERED"
    IDENTITY_BOUND = "IDENTITY_BOUND"
    VERIFIED = "VERIFIED"


class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    FAULT = "FAULT"


class MissionRoleState(StrEnum):
    UNASSIGNED = "UNASSIGNED"
    ACTIVE = "ACTIVE"
    RESERVE = "RESERVE"
    HANDOVER = "HANDOVER"
    RETURNING = "RETURNING"
    DOCKED = "DOCKED"
    CHARGING = "CHARGING"


class ObservationState(StrEnum):
    NOT_OBSERVED = "NOT_OBSERVED"
    CURRENT = "CURRENT"
    STALE = "STALE"
    COMPLETED_SNAPSHOT = "COMPLETED_SNAPSHOT"


class ExecutionSessionStatus(StrEnum):
    DECLARED = "DECLARED"
    PREPARING = "PREPARING"
    OBSERVING = "OBSERVING"
    READY = "READY"
    FAULT = "FAULT"
    CLOSED = "CLOSED"


class FleetVehicleLifecycle(ContractModel):
    vehicle_id: Identifier
    configured_home: Vector3
    registration: RegistrationState = RegistrationState.DECLARED
    connection: ConnectionState = ConnectionState.DISCONNECTED
    mission_role: MissionRoleState = MissionRoleState.UNASSIGNED
    observation: ObservationState = ObservationState.NOT_OBSERVED
    latest_telemetry: TelemetryEnvelope | None = None
    observed_at_monotonic_s: float | None = Field(default=None, ge=0.0)
    preflight_approved: bool = False
    readiness_samples: int = Field(default=0, ge=0)
    readiness_reason: str = "WAITING_FOR_CONNECTION"
    fault_reason: str | None = None


class PreparationEvent(ContractModel):
    schema_version: Literal[1] = 1
    execution_session_id: Identifier
    deployment_sha256: SHA256
    binding_sha256: SHA256
    sequence: int = Field(ge=1)
    vehicle_id: Identifier
    event_type: Identifier
    timestamp_monotonic_s: float = Field(ge=0.0)
    registration: RegistrationState
    connection: ConnectionState
    mission_role: MissionRoleState
    observation: ObservationState
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class FleetPreflightReport(ContractModel):
    execution_session_id: Identifier
    approved: bool
    required_vehicle_ids: frozenset[Identifier]
    reports: tuple[PreflightReport, ...]
    failed_vehicle_ids: tuple[Identifier, ...] = ()


class ExecutionSessionRecord(ContractModel):
    schema_version: Literal[1] = 1
    execution_session_id: Identifier
    deployment_id: Identifier
    deployment_sha256: SHA256
    binding_sha256: SHA256
    backend: ExecutionBackend
    status: ExecutionSessionStatus
    created_at_monotonic_s: float = Field(ge=0.0)
    observation_started_at_monotonic_s: float | None = Field(default=None, ge=0.0)
    vehicles: tuple[FleetVehicleLifecycle, ...]
    preflight: FleetPreflightReport | None = None
    events: tuple[PreparationEvent, ...] = ()


class FleetPreparation:
    """Explicit pre-mission discovery, connection, observation, and readiness workflow."""

    def __init__(
        self,
        *,
        execution_session_id: str,
        deployment: DeploymentManifest,
        binding: BackendBindingProfile,
        supervisor: SafetySupervisor,
    ) -> None:
        binding.validate_for(deployment)
        self.deployment = deployment
        self.binding = binding
        self.supervisor = supervisor
        self.execution_session_id = execution_session_id
        self._vehicles: dict[str, Vehicle] = {}
        self._records = {
            member.vehicle_id: FleetVehicleLifecycle(
                vehicle_id=member.vehicle_id,
                configured_home=member.home,
                mission_role=_mission_role(member.initial_role),
            )
            for member in deployment.fleet
        }
        self._events: list[PreparationEvent] = []
        self._status = ExecutionSessionStatus.DECLARED
        self._created_at = time.monotonic()
        self._observation_started_at: float | None = None
        self._preflight: FleetPreflightReport | None = None
        for vehicle_id in sorted(self._records):
            self._emit(vehicle_id, "PLACEHOLDER_DECLARED")

    @property
    def record(self) -> ExecutionSessionRecord:
        return ExecutionSessionRecord(
            execution_session_id=self.execution_session_id,
            deployment_id=self.deployment.deployment_id,
            deployment_sha256=self.deployment.sha256,
            binding_sha256=self.binding.sha256,
            backend=self.binding.backend,
            status=self._status,
            created_at_monotonic_s=self._created_at,
            observation_started_at_monotonic_s=self._observation_started_at,
            vehicles=tuple(self._records[key] for key in sorted(self._records)),
            preflight=self._preflight,
            events=tuple(self._events),
        )

    @property
    def created_at_monotonic_s(self) -> float:
        return self._created_at

    @property
    def state_summary(self) -> dict[str, Any]:
        """Bounded preparation state without telemetry or lifecycle event histories."""
        return {
            "schema_version": 1,
            "execution_session_id": self.execution_session_id,
            "deployment_id": self.deployment.deployment_id,
            "deployment_sha256": self.deployment.sha256,
            "binding_sha256": self.binding.sha256,
            "backend": self.binding.backend.value,
            "status": self._status.value,
            "created_at_monotonic_s": self._created_at,
            "observation_started_at_monotonic_s": self._observation_started_at,
            "vehicles": [
                {
                    "vehicle_id": vehicle.vehicle_id,
                    "registration": vehicle.registration.value,
                    "connection": vehicle.connection.value,
                    "mission_role": vehicle.mission_role.value,
                    "observation": vehicle.observation.value,
                    "preflight_approved": vehicle.preflight_approved,
                    "readiness_samples": vehicle.readiness_samples,
                    "readiness_reason": vehicle.readiness_reason,
                    "fault_reason": vehicle.fault_reason,
                }
                for vehicle in (self._records[key] for key in sorted(self._records))
            ],
            "preflight": (
                {
                    "approved": self._preflight.approved,
                    "failed_vehicle_ids": list(self._preflight.failed_vehicle_ids),
                }
                if self._preflight is not None
                else None
            ),
        }

    def vehicle(self, vehicle_id: str) -> FleetVehicleLifecycle:
        try:
            return self._records[vehicle_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH, f"vehicle is not declared: {vehicle_id}"
            ) from error

    def initialize_backend(self, factory: BackendVehicleFactory) -> ExecutionSessionRecord:
        if self._status is not ExecutionSessionStatus.DECLARED:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "backend is already initialized")
        self._status = ExecutionSessionStatus.PREPARING
        self.discover(factory.build(self.deployment, self.binding))
        return self.record

    def discover(self, vehicles: tuple[Vehicle, ...]) -> ExecutionSessionRecord:
        observed_ids = [vehicle.identity.vehicle_id for vehicle in vehicles]
        duplicate_ids = sorted(
            vehicle_id for vehicle_id in set(observed_ids) if observed_ids.count(vehicle_id) > 1
        )
        declared_ids = set(self._records)
        unexpected = sorted(set(observed_ids) - declared_ids)
        missing = sorted(self.deployment.required_vehicle_ids - set(observed_ids))
        if duplicate_ids or unexpected or missing:
            for vehicle_id in missing:
                self._emit(
                    vehicle_id,
                    "IDENTITY_VERIFICATION_FAILED",
                    details={"reason": "MISSING"},
                )
            for vehicle_id in unexpected or duplicate_ids:
                self._emit_external_failure(vehicle_id)
            self._status = ExecutionSessionStatus.FAULT
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "discovered fleet does not match declared identities",
                details={
                    "missing": missing,
                    "unexpected": unexpected,
                    "duplicate": duplicate_ids,
                },
            )
        for vehicle in sorted(vehicles, key=lambda item: item.identity.vehicle_id):
            vehicle_id = vehicle.identity.vehicle_id
            selected = self.binding.binding(vehicle_id)
            record = self.vehicle(vehicle_id)
            record = record.model_copy(update={"registration": RegistrationState.DISCOVERED})
            self._records[vehicle_id] = record
            self._emit(vehicle_id, "VEHICLE_DISCOVERED")
            if selected.expected_vehicle_id != vehicle_id:
                self._status = ExecutionSessionStatus.FAULT
                self._emit(
                    vehicle_id,
                    "IDENTITY_VERIFICATION_FAILED",
                    details={"reason": "CROSS_BOUND"},
                )
                raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "cross-bound vehicle identity")
            self._records[vehicle_id] = record.model_copy(
                update={"registration": RegistrationState.IDENTITY_BOUND}
            )
            self._emit(vehicle_id, "IDENTITY_BOUND")
            try:
                self._validate_backend_role(vehicle)
            except CrazySwarmError:
                self._status = ExecutionSessionStatus.FAULT
                self._emit(
                    vehicle_id,
                    "IDENTITY_VERIFICATION_FAILED",
                    details={"reason": "BACKEND_ROLE_MISMATCH"},
                )
                raise
            try:
                registered = self.supervisor.session(vehicle_id).vehicle
            except CrazySwarmError:
                self.supervisor.register_vehicle(vehicle)
            else:
                if registered is not vehicle:
                    self._status = ExecutionSessionStatus.FAULT
                    self._emit(
                        vehicle_id,
                        "IDENTITY_VERIFICATION_FAILED",
                        details={"reason": "DUPLICATE_REGISTERED_IDENTITY"},
                    )
                    raise CrazySwarmError(
                        ErrorCode.IDENTITY_MISMATCH,
                        "a different adapter already owns the logical vehicle identity",
                    )
            self._vehicles[vehicle_id] = vehicle
            self._records[vehicle_id] = self._records[vehicle_id].model_copy(
                update={"registration": RegistrationState.VERIFIED}
            )
            self._emit(vehicle_id, "IDENTITY_VERIFIED")
        return self.record

    async def connect_all(self, *, allow_partial: bool = False) -> ExecutionSessionRecord:
        failures: dict[str, str] = {}
        for vehicle_id in sorted(self._vehicles):
            lifecycle = self.vehicle(vehicle_id)
            if lifecycle.registration is not RegistrationState.VERIFIED:
                continue
            self._records[vehicle_id] = lifecycle.model_copy(
                update={"connection": ConnectionState.CONNECTING, "fault_reason": None}
            )
            self._emit(vehicle_id, "CONNECTION_STARTED")
            try:
                telemetry = await self.supervisor.connect(vehicle_id)
            except Exception as error:
                failures[vehicle_id] = f"{type(error).__name__}: {error}"
                self._records[vehicle_id] = self.vehicle(vehicle_id).model_copy(
                    update={
                        "connection": ConnectionState.FAULT,
                        "fault_reason": failures[vehicle_id],
                    }
                )
                self._emit(vehicle_id, "CONNECTION_FAILED")
                if not allow_partial:
                    break
            else:
                self._records[vehicle_id] = self.vehicle(vehicle_id).model_copy(
                    update={
                        "connection": ConnectionState.READY,
                        "latest_telemetry": telemetry,
                        "readiness_reason": "WAITING_FOR_FRESH_TELEMETRY",
                    }
                )
                self._emit(vehicle_id, "CONNECTION_READY")
        failed_required = self.deployment.required_vehicle_ids & failures.keys()
        if failed_required:
            self._status = ExecutionSessionStatus.FAULT
            if not allow_partial:
                raise CrazySwarmError(
                    ErrorCode.PREFLIGHT_FAILED,
                    "required fleet connection failed",
                    details={"failures": failures},
                )
        return self.record

    async def start_observation(self) -> ExecutionSessionRecord:
        if self._observation_started_at is not None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "observation session already started")
        self._observation_started_at = time.monotonic()
        self._status = ExecutionSessionStatus.OBSERVING
        await self.refresh_observations()
        return self.record

    async def refresh_observations(self) -> ExecutionSessionRecord:
        if self._observation_started_at is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "observation session has not started")
        for vehicle_id in sorted(self._vehicles):
            lifecycle = self.vehicle(vehicle_id)
            if lifecycle.connection is not ConnectionState.READY:
                continue
            try:
                telemetry = await self._vehicles[vehicle_id].snapshot()
                if telemetry.vehicle_id != vehicle_id:
                    raise CrazySwarmError(
                        ErrorCode.IDENTITY_MISMATCH, "observation identity mismatch"
                    )
                self.supervisor.receive_telemetry(telemetry)
            except Exception as error:
                self._records[vehicle_id] = lifecycle.model_copy(
                    update={
                        "observation": ObservationState.STALE,
                        "readiness_reason": "TELEMETRY_SOURCE_FAILED",
                        "fault_reason": f"{type(error).__name__}: {error}",
                    }
                )
                self._emit(vehicle_id, "OBSERVATION_FAILED")
            else:
                self._records[vehicle_id] = lifecycle.model_copy(
                    update={
                        "observation": ObservationState.CURRENT,
                        "latest_telemetry": telemetry,
                        "observed_at_monotonic_s": time.monotonic(),
                        "readiness_reason": "STABILIZING_TELEMETRY",
                        "fault_reason": None,
                    }
                )
                self._emit(vehicle_id, "TELEMETRY_OBSERVED")
        return self.record

    async def stabilize_observations(
        self,
        *,
        required_distinct_samples: int = 1,
        maximum_attempts: int = 4,
    ) -> ExecutionSessionRecord:
        """Require distinct, identity-correct and operational source samples before preflight."""

        if required_distinct_samples < 1 or maximum_attempts < required_distinct_samples:
            raise ValueError("invalid observation readiness window")
        markers: dict[str, set[tuple[str, int, float]]] = {
            vehicle_id: set() for vehicle_id in self._vehicles
        }
        for _ in range(maximum_attempts):
            await self.refresh_observations()
            for vehicle_id in sorted(self._vehicles):
                lifecycle = self.vehicle(vehicle_id)
                telemetry = lifecycle.latest_telemetry
                if lifecycle.connection is not ConnectionState.READY or telemetry is None:
                    continue
                sample = telemetry.telemetry
                valid = (
                    telemetry.vehicle_id == vehicle_id
                    and sample.state is VehicleState.READY
                    and sample.position_m is not None
                    and sample.battery_percent is not None
                    and sample.localization_quality_percent is not None
                )
                if not valid:
                    self._records[vehicle_id] = lifecycle.model_copy(
                        update={"readiness_reason": "WAITING_FOR_VALID_OPERATIONAL_FIELDS"}
                    )
                    continue
                markers[vehicle_id].add(
                    (
                        telemetry.source_clock_id,
                        telemetry.source_clock_epoch,
                        telemetry.source_timestamp_s,
                    )
                )
                count = len(markers[vehicle_id])
                self._records[vehicle_id] = lifecycle.model_copy(
                    update={
                        "readiness_samples": count,
                        "readiness_reason": (
                            "TELEMETRY_STABLE"
                            if count >= required_distinct_samples
                            else "STABILIZING_TELEMETRY"
                        ),
                    }
                )
            ready = [
                vehicle_id
                for vehicle_id in self.deployment.required_vehicle_ids
                if len(markers.get(vehicle_id, set())) >= required_distinct_samples
            ]
            if set(ready) == set(self.deployment.required_vehicle_ids):
                for vehicle_id in sorted(ready):
                    self._emit(
                        vehicle_id,
                        "TELEMETRY_STABILIZED",
                        details={"distinct_samples": len(markers[vehicle_id])},
                    )
                return self.record
            await asyncio.sleep(0)
        waiting = sorted(
            vehicle_id
            for vehicle_id in self.deployment.required_vehicle_ids
            if len(markers.get(vehicle_id, set())) < required_distinct_samples
        )
        for vehicle_id in waiting:
            lifecycle = self.vehicle(vehicle_id)
            self._records[vehicle_id] = lifecycle.model_copy(
                update={
                    "observation": ObservationState.STALE,
                    "readiness_reason": "INSUFFICIENT_DISTINCT_SOURCE_SAMPLES",
                }
            )
            self._emit(vehicle_id, "READINESS_WINDOW_FAILED")
        self._status = ExecutionSessionStatus.FAULT
        raise CrazySwarmError(
            ErrorCode.TELEMETRY_STALE,
            "fleet telemetry did not satisfy the readiness window",
            details={"vehicle_ids": waiting},
        )

    def mark_stale_observations(self, *, now_s: float | None = None) -> ExecutionSessionRecord:
        now = time.monotonic() if now_s is None else now_s
        for vehicle_id, lifecycle in tuple(self._records.items()):
            observed_at = lifecycle.observed_at_monotonic_s
            if (
                lifecycle.observation is ObservationState.CURRENT
                and observed_at is not None
                and now - observed_at > self.deployment.constraints.observation_freshness_s
            ):
                self._records[vehicle_id] = lifecycle.model_copy(
                    update={
                        "observation": ObservationState.STALE,
                        "readiness_reason": "TELEMETRY_STALE",
                    }
                )
                self._emit(vehicle_id, "OBSERVATION_STALE")
        return self.record

    async def run_preflight(
        self,
        *,
        allow_simulation_low_battery: bool = False,
    ) -> FleetPreflightReport:
        reports: list[PreflightReport] = []
        failed: list[str] = []
        owner_id = f"prepare:{self.execution_session_id}"
        for member in self.deployment.fleet:
            vehicle_id = member.vehicle_id
            lifecycle = self.vehicle(vehicle_id)
            if (
                lifecycle.registration is not RegistrationState.VERIFIED
                or lifecycle.connection is not ConnectionState.READY
                or lifecycle.observation is not ObservationState.CURRENT
            ):
                if member.required:
                    failed.append(vehicle_id)
                continue
            self.supervisor.claim_control(vehicle_id, owner_id)
            try:
                report = await self.supervisor.preflight(
                    vehicle_id,
                    owner_id,
                    required_capabilities=member.required_capabilities
                    | frozenset({VehicleCapability.ARMING}),
                    allow_simulation_low_battery=allow_simulation_low_battery,
                )
                reports.append(report)
                approved = report.approved
                if member.required and not approved:
                    failed.append(vehicle_id)
                self._records[vehicle_id] = lifecycle.model_copy(
                    update={
                        "preflight_approved": approved,
                        "readiness_reason": ("READY" if approved else "PREFLIGHT_REJECTED"),
                    }
                )
                self._emit(
                    vehicle_id,
                    "PREFLIGHT_APPROVED" if approved else "PREFLIGHT_REJECTED",
                )
            finally:
                await self.supervisor.release_control(vehicle_id, owner_id)
        approved = not failed and self.deployment.required_vehicle_ids.issubset(
            report.vehicle_id for report in reports if report.approved
        )
        self._preflight = FleetPreflightReport(
            execution_session_id=self.execution_session_id,
            approved=approved,
            required_vehicle_ids=self.deployment.required_vehicle_ids,
            reports=tuple(reports),
            failed_vehicle_ids=tuple(sorted(set(failed))),
        )
        self._status = ExecutionSessionStatus.READY if approved else ExecutionSessionStatus.FAULT
        return self._preflight

    def require_ready(self) -> None:
        self.mark_stale_observations()
        unready = [
            lifecycle.vehicle_id
            for lifecycle in self._records.values()
            if lifecycle.vehicle_id in self.deployment.required_vehicle_ids
            and (
                lifecycle.registration is not RegistrationState.VERIFIED
                or lifecycle.connection is not ConnectionState.READY
                or lifecycle.observation is not ObservationState.CURRENT
                or not lifecycle.preflight_approved
            )
        ]
        if self._preflight is None or not self._preflight.approved or unready:
            raise CrazySwarmError(
                ErrorCode.PREFLIGHT_FAILED,
                "required fleet is not prepared and ready",
                details={"unready_vehicle_ids": sorted(unready)},
            )

    async def retry_vehicle(self, vehicle_id: str) -> FleetVehicleLifecycle:
        lifecycle = self.vehicle(vehicle_id)
        if lifecycle.registration is not RegistrationState.VERIFIED:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "vehicle identity is not verified")
        session = self.supervisor.session(vehicle_id)
        if session.state is VehicleState.FAULT:
            await self.supervisor.disconnect(vehicle_id)
        self._records[vehicle_id] = lifecycle.model_copy(
            update={
                "connection": ConnectionState.CONNECTING,
                "observation": ObservationState.NOT_OBSERVED,
                "preflight_approved": False,
                "readiness_samples": 0,
                "readiness_reason": "WAITING_FOR_CONNECTION",
                "fault_reason": None,
            }
        )
        self._emit(vehicle_id, "CONNECTION_RETRY")
        telemetry = await self.supervisor.connect(vehicle_id)
        self._records[vehicle_id] = self.vehicle(vehicle_id).model_copy(
            update={"connection": ConnectionState.READY, "latest_telemetry": telemetry}
        )
        self._emit(vehicle_id, "CONNECTION_READY")
        if self._observation_started_at is not None:
            await self.refresh_observations()
        return self.vehicle(vehicle_id)

    async def disconnect_all_safe(self) -> ExecutionSessionRecord:
        for vehicle_id in sorted(self._vehicles):
            session = self.supervisor.session(vehicle_id)
            if session.state is VehicleState.DISCONNECTED:
                continue
            await self.supervisor.disconnect(vehicle_id)
            lifecycle = self.vehicle(vehicle_id)
            observation = (
                ObservationState.COMPLETED_SNAPSHOT
                if lifecycle.latest_telemetry is not None
                else ObservationState.NOT_OBSERVED
            )
            self._records[vehicle_id] = lifecycle.model_copy(
                update={
                    "connection": ConnectionState.DISCONNECTED,
                    "observation": observation,
                    "preflight_approved": False,
                    "readiness_reason": "TERMINAL_SNAPSHOT",
                }
            )
            self._emit(vehicle_id, "DISCONNECTED_SAFE")
        self._status = ExecutionSessionStatus.CLOSED
        return self.record

    def normalized_trace(self) -> tuple[dict[str, str], ...]:
        """Backend-independent preparation trace suitable for parity comparisons."""

        return tuple(
            {
                "vehicle_id": event.vehicle_id,
                "event_type": event.event_type,
                "registration": event.registration.value,
                "connection": event.connection.value,
                "mission_role": event.mission_role.value,
                "observation": event.observation.value,
            }
            for event in self._events
        )

    def _validate_backend_role(self, vehicle: Vehicle) -> None:
        expected = {
            ExecutionBackend.FAST_SIM: "FAST_SIM",
            ExecutionBackend.MOCK_ISAAC: "ISAAC_SIM",
            ExecutionBackend.ISAAC: "ISAAC_SIM",
            ExecutionBackend.CRAZYFLIE: "REAL_CRAZYFLIE",
        }[self.binding.backend]
        if vehicle.backend_profile.role.value != expected:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "adapter backend role does not match binding profile",
                details={
                    "expected": expected,
                    "observed": vehicle.backend_profile.role.value,
                    "vehicle_id": vehicle.identity.vehicle_id,
                },
            )

    def _emit(
        self,
        vehicle_id: str,
        event_type: str,
        *,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        lifecycle = self.vehicle(vehicle_id)
        self._events.append(
            PreparationEvent(
                execution_session_id=self.execution_session_id,
                deployment_sha256=self.deployment.sha256,
                binding_sha256=self.binding.sha256,
                sequence=len(self._events) + 1,
                vehicle_id=vehicle_id,
                event_type=event_type,
                timestamp_monotonic_s=time.monotonic(),
                registration=lifecycle.registration,
                connection=lifecycle.connection,
                mission_role=lifecycle.mission_role,
                observation=lifecycle.observation,
                details=details or {},
            )
        )

    def _emit_external_failure(self, vehicle_id: str) -> None:
        self._events.append(
            PreparationEvent(
                execution_session_id=self.execution_session_id,
                deployment_sha256=self.deployment.sha256,
                binding_sha256=self.binding.sha256,
                sequence=len(self._events) + 1,
                vehicle_id=vehicle_id,
                event_type="IDENTITY_VERIFICATION_FAILED",
                timestamp_monotonic_s=time.monotonic(),
                registration=RegistrationState.DISCOVERED,
                connection=ConnectionState.DISCONNECTED,
                mission_role=MissionRoleState.UNASSIGNED,
                observation=ObservationState.NOT_OBSERVED,
                details={"reason": "UNEXPECTED_OR_DUPLICATE"},
            )
        )


def _mission_role(role: InitialFleetRole) -> MissionRoleState:
    return {
        InitialFleetRole.ACTIVE: MissionRoleState.ACTIVE,
        InitialFleetRole.RESERVE: MissionRoleState.RESERVE,
        InitialFleetRole.UNASSIGNED: MissionRoleState.UNASSIGNED,
    }[role]
