from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from crazyswarm_app.domain.commands import (
    AbortCommand,
    AcknowledgementStatus,
    ArmCommand,
    CommandAcknowledgement,
    CommandEnvelope,
    CommandPayload,
    DisarmCommand,
    EmergencyStopCommand,
    HoverCommand,
    LandCommand,
    MoveRelativeCommand,
    StopAndHoldCommand,
    TakeoffCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    CommandSource,
    OperatingMode,
    VehicleCapability,
    VehicleState,
)
from crazyswarm_app.domain.telemetry import TelemetryEnvelope, VehicleTelemetry
from crazyswarm_app.safety.audit import SupervisorAuditSink
from crazyswarm_app.safety.models import (
    ControlLease,
    HealthAssessment,
    HealthIssue,
    LiveModeAuthorization,
    PreflightCheck,
    PreflightReport,
    RecoveryAction,
    SafetyEvent,
)
from crazyswarm_app.safety.policy import SafetyPolicy
from crazyswarm_app.safety.state_machine import require_transition
from crazyswarm_app.vehicles.base import Vehicle


@dataclass(slots=True)
class VehicleSession:
    vehicle: Vehicle
    state: VehicleState = VehicleState.DISCONNECTED
    telemetry: TelemetryEnvelope | None = None
    telemetry_received_at_monotonic_s: float | None = None
    preflight: PreflightReport | None = None
    lease: ControlLease | None = None


class SafetySupervisor:
    def __init__(
        self,
        policy: SafetyPolicy | None = None,
        *,
        audit_sinks: Iterable[SupervisorAuditSink] = (),
    ) -> None:
        self.policy = policy or SafetyPolicy()
        self.mode = OperatingMode.SIM
        self._sessions: dict[str, VehicleSession] = {}
        self._live_authorizations: dict[str, LiveModeAuthorization] = {}
        self._command_sequence = 0
        self._event_sequence = 0
        self.events: list[SafetyEvent] = []
        self._audit_sinks = list(audit_sinks)

    def add_audit_sink(self, sink: SupervisorAuditSink) -> None:
        self._audit_sinks.append(sink)

    def register_vehicle(self, vehicle: Vehicle) -> None:
        vehicle_id = vehicle.identity.vehicle_id
        if vehicle_id in self._sessions:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "vehicle ID is already registered")
        self._sessions[vehicle_id] = VehicleSession(vehicle=vehicle)
        self._event(vehicle_id, "VEHICLE_REGISTERED", "vehicle registered")

    def session(self, vehicle_id: str) -> VehicleSession:
        try:
            return self._sessions[vehicle_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                f"unknown vehicle: {vehicle_id}",
            ) from error

    def set_mode(
        self,
        mode: OperatingMode,
        *,
        authorization: LiveModeAuthorization | None = None,
    ) -> None:
        if any(self._is_armed_or_flying(session) for session in self._sessions.values()):
            raise CrazySwarmError(ErrorCode.MODE_NOT_AUTHORIZED, "cannot change mode while armed")
        if mode in {OperatingMode.LIVE, OperatingMode.SHADOW}:
            if (
                authorization is None
                or not authorization.confirmed
                or authorization.mode is not mode
            ):
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    f"{mode.value} requires explicit operator authorization",
                )
            session = self.session(authorization.vehicle_id)
            if session.vehicle.identity.adapter == "sim":
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "simulated vehicle cannot authorize real-flight mode",
                )
            self._live_authorizations[authorization.vehicle_id] = authorization
        self.mode = mode
        for vehicle_id in self._sessions:
            self._event(vehicle_id, "MODE_CHANGED", f"mode changed to {mode.value}")

    def claim_control(self, vehicle_id: str, owner_id: str, *, now_s: float | None = None) -> None:
        session = self.session(vehicle_id)
        now = self._now(now_s)
        if (
            session.lease is not None
            and session.lease.expires_at_monotonic_s > now
            and session.lease.owner_id != owner_id
        ):
            raise CrazySwarmError(ErrorCode.MODE_NOT_AUTHORIZED, "vehicle has another owner")
        session.lease = ControlLease(
            owner_id=owner_id,
            expires_at_monotonic_s=now + self.policy.control_lease_timeout_s,
        )
        self._event(vehicle_id, "CONTROL_CLAIMED", f"control claimed by {owner_id}")

    def renew_control(self, vehicle_id: str, owner_id: str, *, now_s: float | None = None) -> None:
        self._require_owner(self.session(vehicle_id), owner_id, self._now(now_s))
        self.session(vehicle_id).lease = ControlLease(
            owner_id=owner_id,
            expires_at_monotonic_s=self._now(now_s) + self.policy.control_lease_timeout_s,
        )

    async def release_control(self, vehicle_id: str, owner_id: str) -> None:
        session = self.session(vehicle_id)
        self._require_owner(session, owner_id, time.monotonic())
        if session.state in {
            VehicleState.TAKING_OFF,
            VehicleState.FLYING,
            VehicleState.RETURNING,
        }:
            await self.abort_and_land(vehicle_id, owner_id, reason="control owner released")
        session.lease = None
        self._event(vehicle_id, "CONTROL_RELEASED", f"control released by {owner_id}")

    async def expire_control_leases(self, *, now_s: float | None = None) -> None:
        now = self._now(now_s)
        for vehicle_id, session in self._sessions.items():
            if session.lease is None or session.lease.expires_at_monotonic_s > now:
                continue
            owner_id = session.lease.owner_id
            if session.state in {
                VehicleState.TAKING_OFF,
                VehicleState.FLYING,
                VehicleState.RETURNING,
            }:
                await self.abort_and_land(
                    vehicle_id,
                    owner_id,
                    reason="control lease expired",
                    allow_expired_owner=True,
                )
            session.lease = None
            self._event(vehicle_id, "CONTROL_EXPIRED", f"control lease expired for {owner_id}")

    async def connect(self, vehicle_id: str) -> TelemetryEnvelope:
        session = self.session(vehicle_id)
        self._transition(vehicle_id, VehicleState.CONNECTING, CommandSource.SUPERVISOR)
        try:
            await asyncio.wait_for(session.vehicle.connect(), timeout=self.policy.command_timeout_s)
            telemetry = await self._refresh(session)
        except TimeoutError as error:
            self._transition(vehicle_id, VehicleState.FAULT, CommandSource.SUPERVISOR)
            raise CrazySwarmError(ErrorCode.COMMAND_TIMEOUT, "connection timed out") from error
        except Exception:
            self._transition(vehicle_id, VehicleState.FAULT, CommandSource.SUPERVISOR)
            raise
        self._transition(vehicle_id, telemetry.telemetry.state, CommandSource.SUPERVISOR)
        return telemetry

    async def disconnect(self, vehicle_id: str, owner_id: str | None = None) -> None:
        session = self.session(vehicle_id)
        if owner_id is not None and session.lease is not None:
            self._require_owner(session, owner_id, time.monotonic())
        if self._is_armed_or_flying(session):
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "land and disarm before disconnect")
        await asyncio.wait_for(session.vehicle.disconnect(), timeout=self.policy.command_timeout_s)
        self._transition(vehicle_id, VehicleState.DISCONNECTED, CommandSource.SUPERVISOR)
        session.telemetry = await session.vehicle.snapshot()
        session.telemetry_received_at_monotonic_s = time.monotonic()
        session.lease = None
        session.preflight = None

    async def preflight(
        self,
        vehicle_id: str,
        owner_id: str,
        *,
        required_capabilities: frozenset[VehicleCapability] = frozenset({VehicleCapability.ARMING}),
        now_s: float | None = None,
    ) -> PreflightReport:
        session = self.session(vehicle_id)
        now = self._now(now_s)
        self._require_owner(session, owner_id, now)
        telemetry = await self._refresh(session)
        checks = self._preflight_checks(session, telemetry, required_capabilities)
        approved = all(check.passed for check in checks)
        report = PreflightReport(
            report_id=f"preflight-{vehicle_id}-{self._next_command_sequence()}",
            vehicle_id=vehicle_id,
            mode=self.mode,
            operator_id=owner_id,
            created_at_monotonic_s=now,
            expires_at_monotonic_s=now + self.policy.preflight_valid_s,
            approved=approved,
            checks=tuple(checks),
        )
        session.preflight = report
        self._event(
            vehicle_id,
            "PREFLIGHT_COMPLETED",
            "preflight passed" if approved else "preflight failed",
            details={"report_id": report.report_id, "approved": approved},
        )
        return report

    async def arm(
        self,
        vehicle_id: str,
        owner_id: str,
        report_id: str,
        *,
        now_s: float | None = None,
        source: CommandSource = CommandSource.UI,
        mission_run_id: str | None = None,
    ) -> CommandAcknowledgement:
        session = self.session(vehicle_id)
        now = self._now(now_s)
        self._require_owner(session, owner_id, now)
        self._require_preflight(session, owner_id, report_id, now)
        self._require_real_authority(session)
        self._transition(vehicle_id, VehicleState.ARMING, source)
        try:
            acknowledgement = await self._send(
                session,
                ArmCommand(),
                source=source,
                mission_run_id=mission_run_id,
            )
            telemetry = await self._refresh(session)
            if not telemetry.telemetry.armed:
                raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "adapter did not report armed")
        except Exception:
            self._transition(vehicle_id, VehicleState.FAULT, CommandSource.SUPERVISOR)
            raise
        self._transition(vehicle_id, VehicleState.READY, CommandSource.SUPERVISOR)
        return acknowledgement

    async def disarm(
        self,
        vehicle_id: str,
        owner_id: str,
        *,
        source: CommandSource = CommandSource.UI,
        mission_run_id: str | None = None,
    ) -> CommandAcknowledgement:
        session = self.session(vehicle_id)
        self._require_owner(session, owner_id, time.monotonic())
        if session.state is not VehicleState.READY:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle must be ready to disarm")
        acknowledgement = await self._send(
            session,
            DisarmCommand(),
            source=source,
            mission_run_id=mission_run_id,
        )
        await self._refresh(session)
        return acknowledgement

    async def takeoff(
        self,
        vehicle_id: str,
        owner_id: str,
        *,
        height_m: float,
        duration_s: float,
        source: CommandSource = CommandSource.UI,
        mission_run_id: str | None = None,
    ) -> CommandAcknowledgement:
        session = self.session(vehicle_id)
        self._require_command_ready(session, owner_id)
        self._validate_takeoff(height_m, duration_s)
        self._transition(vehicle_id, VehicleState.TAKING_OFF, source)
        try:
            acknowledgement = await self._send(
                session,
                TakeoffCommand(height_m=height_m, duration_s=duration_s),
                source=source,
                mission_run_id=mission_run_id,
            )
            telemetry = await self._refresh(session)
            if not telemetry.telemetry.flying:
                raise CrazySwarmError(ErrorCode.INVALID_STATE, "adapter did not report flying")
        except Exception:
            self._transition(vehicle_id, VehicleState.FAULT, CommandSource.SUPERVISOR)
            raise
        self._transition(vehicle_id, VehicleState.FLYING, CommandSource.SUPERVISOR)
        return acknowledgement

    async def hover(
        self,
        vehicle_id: str,
        owner_id: str,
        duration_s: float,
        *,
        source: CommandSource = CommandSource.UI,
        mission_run_id: str | None = None,
    ) -> CommandAcknowledgement:
        session = self.session(vehicle_id)
        self._require_flying(session, owner_id)
        if duration_s <= 0.0 or duration_s > self.policy.max_mission_duration_s:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "hover duration exceeds policy")
        acknowledgement = await self._send(
            session,
            HoverCommand(duration_s=duration_s),
            source=source,
            mission_run_id=mission_run_id,
        )
        await self._refresh(session)
        return acknowledgement

    async def move_relative(
        self,
        vehicle_id: str,
        owner_id: str,
        command: MoveRelativeCommand,
        *,
        source: CommandSource = CommandSource.UI,
        mission_run_id: str | None = None,
    ) -> CommandAcknowledgement:
        session = self.session(vehicle_id)
        self._require_flying(session, owner_id)
        telemetry = cast(TelemetryEnvelope, session.telemetry)
        self._validate_relative_move(telemetry, command)
        acknowledgement = await self._send(
            session,
            command,
            source=source,
            mission_run_id=mission_run_id,
        )
        await self._refresh(session)
        return acknowledgement

    async def stop_and_hold(
        self,
        vehicle_id: str,
        owner_id: str,
        *,
        source: CommandSource = CommandSource.UI,
        mission_run_id: str | None = None,
    ) -> CommandAcknowledgement:
        session = self.session(vehicle_id)
        self._require_flying(session, owner_id)
        acknowledgement = await self._send(
            session,
            StopAndHoldCommand(),
            source=source,
            mission_run_id=mission_run_id,
        )
        await self._refresh(session)
        return acknowledgement

    async def land(
        self,
        vehicle_id: str,
        owner_id: str,
        *,
        duration_s: float = 2.0,
        source: CommandSource = CommandSource.UI,
        mission_run_id: str | None = None,
    ) -> CommandAcknowledgement:
        session = self.session(vehicle_id)
        self._require_flying(session, owner_id)
        self._transition(vehicle_id, VehicleState.LANDING, source)
        acknowledgement = await self._send(
            session,
            LandCommand(duration_s=duration_s),
            source=source,
            mission_run_id=mission_run_id,
        )
        await self._refresh(session)
        self._transition(vehicle_id, VehicleState.READY, CommandSource.SUPERVISOR)
        return acknowledgement

    async def abort_and_land(
        self,
        vehicle_id: str,
        owner_id: str,
        *,
        reason: str,
        allow_expired_owner: bool = False,
    ) -> CommandAcknowledgement:
        session = self.session(vehicle_id)
        self._require_owner(
            session,
            owner_id,
            time.monotonic(),
            allow_expired=allow_expired_owner,
        )
        if session.state not in {
            VehicleState.TAKING_OFF,
            VehicleState.FLYING,
            VehicleState.RETURNING,
        }:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle is not in an abortable state")
        self._transition(vehicle_id, VehicleState.ABORTING, CommandSource.SUPERVISOR)
        acknowledgement = await self._send(
            session,
            AbortCommand(reason=reason),
            source=CommandSource.SUPERVISOR,
        )
        self._transition(vehicle_id, VehicleState.LANDING, CommandSource.SUPERVISOR)
        await self._refresh(session)
        self._transition(vehicle_id, VehicleState.READY, CommandSource.SUPERVISOR)
        return acknowledgement

    async def emergency_stop(
        self,
        vehicle_id: str,
        owner_id: str,
        *,
        reason: str,
        allow_expired_owner: bool = False,
    ) -> CommandAcknowledgement:
        session = self.session(vehicle_id)
        self._require_owner(
            session,
            owner_id,
            time.monotonic(),
            allow_expired=allow_expired_owner,
        )
        self._transition(vehicle_id, VehicleState.EMERGENCY, CommandSource.SUPERVISOR)
        acknowledgement = await self._send(
            session,
            EmergencyStopCommand(reason=reason),
            source=CommandSource.SUPERVISOR,
        )
        await self._refresh(session)
        self._event(vehicle_id, "EMERGENCY_STOP", reason, command_id=acknowledgement.command_id)
        return acknowledgement

    def evaluate_health(
        self,
        vehicle_id: str,
        *,
        now_s: float | None = None,
    ) -> HealthAssessment:
        session = self.session(vehicle_id)
        now = self._now(now_s)
        issues: list[HealthIssue] = []
        airborne = session.state in {
            VehicleState.TAKING_OFF,
            VehicleState.FLYING,
            VehicleState.RETURNING,
        }
        reject_or_abort = (
            RecoveryAction.ABORT_AND_LAND if airborne else RecoveryAction.REJECT_NEW_COMMANDS
        )
        if session.telemetry is None or session.telemetry_received_at_monotonic_s is None:
            issues.append(
                HealthIssue(
                    code="NO_TELEMETRY",
                    message="no telemetry has been received",
                    action=reject_or_abort,
                )
            )
        else:
            age = now - session.telemetry_received_at_monotonic_s
            telemetry = session.telemetry.telemetry
            if age > self.policy.telemetry_timeout_s:
                issues.append(
                    HealthIssue(
                        code=ErrorCode.TELEMETRY_STALE.value,
                        message=f"telemetry is stale by {age:.3f}s",
                        action=reject_or_abort,
                    )
                )
            if telemetry.state is VehicleState.DISCONNECTED and airborne:
                issues.append(
                    HealthIssue(
                        code=ErrorCode.LINK_LOST.value,
                        message="vehicle disconnected while airborne",
                        action=RecoveryAction.EMERGENCY_STOP,
                    )
                )
            if telemetry.battery_percent is None:
                issues.append(
                    HealthIssue(
                        code="BATTERY_UNAVAILABLE",
                        message="battery observation is unavailable",
                        action=reject_or_abort,
                    )
                )
            elif telemetry.battery_percent <= self.policy.critical_battery_percent:
                issues.append(
                    HealthIssue(
                        code=ErrorCode.CRITICAL_BATTERY.value,
                        message="battery is critical",
                        action=reject_or_abort,
                    )
                )
            transport_quality = self._transport_quality(telemetry)
            if (
                transport_quality is None
                or transport_quality < self.policy.minimum_link_quality_percent
            ):
                issues.append(
                    HealthIssue(
                        code=(
                            "TRANSPORT_QUALITY_UNAVAILABLE"
                            if transport_quality is None
                            else "TRANSPORT_QUALITY_LOW"
                        ),
                        message="command transport quality does not meet policy",
                        action=reject_or_abort,
                    )
                )
            if (
                telemetry.localization_quality_percent is None
                or telemetry.localization_quality_percent
                < self.policy.minimum_localization_quality_percent
            ):
                issues.append(
                    HealthIssue(
                        code=ErrorCode.LOCALIZATION_INVALID.value,
                        message="localization quality is below policy",
                        action=reject_or_abort,
                    )
                )
            if telemetry.position_m is None or not self.policy.flight_volume.contains(
                telemetry.position_m
            ):
                issues.append(
                    HealthIssue(
                        code=ErrorCode.GEOFENCE_BREACH.value,
                        message="estimated position is outside policy volume",
                        action=reject_or_abort,
                    )
                )
        action = self._highest_action(issues)
        return HealthAssessment(
            vehicle_id=vehicle_id,
            healthy=not issues,
            action=action,
            issues=tuple(issues),
        )

    async def enforce_health(
        self,
        vehicle_id: str,
        owner_id: str,
        *,
        now_s: float | None = None,
    ) -> HealthAssessment:
        assessment = self.evaluate_health(vehicle_id, now_s=now_s)
        if assessment.action is RecoveryAction.ABORT_AND_LAND:
            await self.abort_and_land(
                vehicle_id,
                owner_id,
                reason=assessment.issues[0].code,
                allow_expired_owner=True,
            )
        elif assessment.action is RecoveryAction.EMERGENCY_STOP:
            await self.emergency_stop(
                vehicle_id,
                owner_id,
                reason=assessment.issues[0].code,
                allow_expired_owner=True,
            )
        return assessment

    def _preflight_checks(
        self,
        session: VehicleSession,
        telemetry: TelemetryEnvelope,
        required_capabilities: frozenset[VehicleCapability],
    ) -> list[PreflightCheck]:
        data = telemetry.telemetry
        transport_quality = self._transport_quality(data)
        checks = [
            PreflightCheck(
                code="IDENTITY",
                passed=telemetry.vehicle_id == session.vehicle.identity.vehicle_id,
                message="telemetry identity matches selected vehicle",
                observed=telemetry.vehicle_id,
                required=session.vehicle.identity.vehicle_id,
            ),
            PreflightCheck(
                code="STATE_READY",
                passed=session.state is VehicleState.READY,
                message="vehicle is connected and ready",
                observed=session.state.value,
                required=VehicleState.READY.value,
            ),
            PreflightCheck(
                code="CAPABILITIES",
                passed=session.vehicle.capabilities.supports(required_capabilities),
                message="required capabilities are present",
                observed=",".join(
                    sorted(item.value for item in session.vehicle.capabilities.features)
                ),
                required=",".join(sorted(item.value for item in required_capabilities)),
            ),
            PreflightCheck(
                code="BATTERY",
                passed=(
                    data.battery_percent is not None
                    and data.battery_percent >= self.policy.minimum_takeoff_battery_percent
                ),
                message="battery meets takeoff policy",
                observed=data.battery_percent,
                required=self.policy.minimum_takeoff_battery_percent,
            ),
            PreflightCheck(
                code="COMMAND_TRANSPORT",
                passed=(
                    transport_quality is not None
                    and transport_quality >= self.policy.minimum_link_quality_percent
                ),
                message="command transport quality meets policy",
                observed=transport_quality,
                required=self.policy.minimum_link_quality_percent,
            ),
            PreflightCheck(
                code="GEOFENCE",
                passed=(
                    data.position_m is not None
                    and self.policy.flight_volume.contains(data.position_m)
                ),
                message="estimated position is inside configured flight volume",
            ),
            PreflightCheck(
                code="NO_CRITICAL_FAULT",
                passed="CRITICAL_BATTERY" not in data.faults,
                message="no critical fault is active",
            ),
        ]
        positioning_required = bool(
            required_capabilities
            & {
                VehicleCapability.RELATIVE_POSITIONING,
                VehicleCapability.GLOBAL_POSITIONING,
            }
        )
        checks.append(
            PreflightCheck(
                code="LOCALIZATION",
                passed=(
                    not positioning_required
                    or (
                        data.localization_quality_percent is not None
                        and data.localization_quality_percent
                        >= self.policy.minimum_localization_quality_percent
                    )
                ),
                message="localization meets required capability policy",
                observed=data.localization_quality_percent,
                required=(
                    self.policy.minimum_localization_quality_percent
                    if positioning_required
                    else 0.0
                ),
            )
        )
        real_authorized = (
            self.mode is OperatingMode.SIM
            if session.vehicle.identity.adapter == "sim"
            else (
                self.mode in {OperatingMode.LIVE, OperatingMode.SHADOW}
                and session.vehicle.identity.vehicle_id in self._live_authorizations
            )
        )
        checks.append(
            PreflightCheck(
                code="COMMAND_AUTHORITY",
                passed=real_authorized,
                message="selected mode has command authority for this vehicle",
                observed=self.mode.value,
            )
        )
        return checks

    @staticmethod
    def _transport_quality(data: VehicleTelemetry) -> float | None:
        if data.link_quality_percent is not None:
            return data.link_quality_percent
        if data.transport is not None:
            return data.transport.delivery_quality_percent
        return None

    def _require_preflight(
        self,
        session: VehicleSession,
        owner_id: str,
        report_id: str,
        now_s: float,
    ) -> None:
        report = session.preflight
        if (
            report is None
            or report.report_id != report_id
            or report.operator_id != owner_id
            or report.mode is not self.mode
            or not report.approved
            or report.expires_at_monotonic_s < now_s
        ):
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "valid preflight is required")

    def _require_real_authority(self, session: VehicleSession) -> None:
        if session.vehicle.identity.adapter == "sim":
            if self.mode is not OperatingMode.SIM:
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "simulated vehicle can only be armed in SIM mode",
                )
            return
        if self.mode not in {OperatingMode.LIVE, OperatingMode.SHADOW}:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "real vehicle requires LIVE or SHADOW mode",
            )
        if session.vehicle.identity.vehicle_id not in self._live_authorizations:
            raise CrazySwarmError(ErrorCode.MODE_NOT_AUTHORIZED, "real mode is not authorized")

    def _require_command_ready(self, session: VehicleSession, owner_id: str) -> None:
        self._require_owner(session, owner_id, time.monotonic())
        self._require_real_authority(session)
        if session.state is not VehicleState.READY or session.telemetry is None:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle is not ready")
        if not session.telemetry.telemetry.armed:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle is not armed")

    def _require_flying(self, session: VehicleSession, owner_id: str) -> None:
        self._require_owner(session, owner_id, time.monotonic())
        if session.state is not VehicleState.FLYING:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle is not flying")

    @staticmethod
    def _require_owner(
        session: VehicleSession,
        owner_id: str,
        now_s: float,
        *,
        allow_expired: bool = False,
    ) -> None:
        if session.lease is None or session.lease.owner_id != owner_id:
            raise CrazySwarmError(ErrorCode.MODE_NOT_AUTHORIZED, "control ownership is required")
        if not allow_expired and session.lease.expires_at_monotonic_s <= now_s:
            raise CrazySwarmError(ErrorCode.MODE_NOT_AUTHORIZED, "control lease has expired")

    def _validate_takeoff(self, height_m: float, duration_s: float) -> None:
        if height_m <= 0.0 or height_m > self.policy.max_altitude_m:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "takeoff height exceeds policy")
        if duration_s <= 0.0 or duration_s > self.policy.max_mission_duration_s:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "takeoff duration exceeds policy")
        if 1.5 * height_m / duration_s > self.policy.max_vertical_speed_m_s:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "takeoff vertical speed exceeds policy"
            )
        if 6.0 * height_m / duration_s**2 > self.policy.max_acceleration_m_s2:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "takeoff acceleration exceeds policy")

    def _validate_relative_move(
        self,
        telemetry: TelemetryEnvelope,
        command: MoveRelativeCommand,
    ) -> None:
        if command.duration_s > self.policy.max_mission_duration_s:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "move duration exceeds policy")
        horizontal = math.hypot(command.x_m, command.y_m)
        if 1.5 * horizontal / command.duration_s > self.policy.max_horizontal_speed_m_s:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "horizontal speed exceeds policy")
        if 1.5 * abs(command.z_m) / command.duration_s > self.policy.max_vertical_speed_m_s:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "vertical speed exceeds policy")
        distance = math.sqrt(horizontal**2 + command.z_m**2)
        if 6.0 * distance / command.duration_s**2 > self.policy.max_acceleration_m_s2:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "acceleration exceeds policy")
        if 1.5 * abs(command.yaw_rad) / command.duration_s > self.policy.max_yaw_rate_rad_s:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "yaw rate exceeds policy")
        position = telemetry.telemetry.position_m
        if position is None:
            raise CrazySwarmError(
                ErrorCode.LOCALIZATION_INVALID,
                "relative move requires a current position observation",
            )
        if command.frame.value == "body":
            attitude = telemetry.telemetry.attitude
            if attitude is None:
                raise CrazySwarmError(
                    ErrorCode.LOCALIZATION_INVALID,
                    "body-frame move requires a current attitude observation",
                )
            yaw = attitude.yaw_rad
            dx = command.x_m * math.cos(yaw) - command.y_m * math.sin(yaw)
            dy = command.x_m * math.sin(yaw) + command.y_m * math.cos(yaw)
        else:
            dx, dy = command.x_m, command.y_m
        target = position.model_copy(
            update={"x": position.x + dx, "y": position.y + dy, "z": position.z + command.z_m}
        )
        if not self.policy.flight_volume.contains(target):
            raise CrazySwarmError(ErrorCode.GEOFENCE_BREACH, "move target exceeds policy volume")

    async def _send(
        self,
        session: VehicleSession,
        payload: CommandPayload,
        *,
        source: CommandSource,
        mission_run_id: str | None = None,
    ) -> CommandAcknowledgement:
        command_sequence = self._next_command_sequence()
        command_id = f"cmd-{command_sequence}"
        envelope = CommandEnvelope(
            vehicle_id=session.vehicle.identity.vehicle_id,
            command_id=command_id,
            mission_run_id=mission_run_id,
            issued_at_monotonic_s=time.monotonic(),
            source=source,
            mode=self.mode,
            payload=payload,
        )
        self._notify("command_sent", envelope)
        self._event(
            session.vehicle.identity.vehicle_id,
            "COMMAND_SENT",
            payload.kind.value,
            source=source,
            command_id=command_id,
        )
        commanded_duration_s = (
            payload.duration_s
            if isinstance(payload, (TakeoffCommand, HoverCommand, MoveRelativeCommand, LandCommand))
            else 0.0
        )
        if session.lease is not None and commanded_duration_s > 0.0:
            session.lease = session.lease.model_copy(
                update={
                    "expires_at_monotonic_s": max(
                        session.lease.expires_at_monotonic_s,
                        time.monotonic()
                        + commanded_duration_s
                        + self.policy.control_lease_timeout_s,
                    )
                }
            )
        try:
            timeout_s = self.policy.command_timeout_s
            if session.vehicle.identity.adapter == "sim" and isinstance(
                payload,
                (TakeoffCommand, HoverCommand, MoveRelativeCommand, LandCommand),
            ):
                # Real-time simulation executes the complete trajectory before acknowledging it.
                # The requested duration is expected work, not a stalled command transport.
                timeout_s += payload.duration_s * 1.25 + 1.0
            acknowledgement = await asyncio.wait_for(
                session.vehicle.execute(envelope),
                timeout=timeout_s,
            )
        except TimeoutError as error:
            self._event(
                session.vehicle.identity.vehicle_id,
                "COMMAND_TIMEOUT",
                payload.kind.value,
                source=source,
                command_id=command_id,
            )
            raise CrazySwarmError(ErrorCode.COMMAND_TIMEOUT, "command timed out") from error
        if acknowledgement.status is not AcknowledgementStatus.COMPLETED:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                acknowledgement.message or "adapter rejected command",
            )
        if session.lease is not None:
            session.lease = session.lease.model_copy(
                update={
                    "expires_at_monotonic_s": (
                        time.monotonic() + self.policy.control_lease_timeout_s
                    )
                }
            )
        self._notify("command_acknowledged", acknowledgement)
        self._event(
            session.vehicle.identity.vehicle_id,
            "COMMAND_COMPLETED",
            payload.kind.value,
            source=source,
            command_id=command_id,
        )
        return acknowledgement

    async def _refresh(self, session: VehicleSession) -> TelemetryEnvelope:
        telemetry = await asyncio.wait_for(
            session.vehicle.snapshot(),
            timeout=self.policy.command_timeout_s,
        )
        self.receive_telemetry(telemetry)
        return telemetry

    def receive_telemetry(self, telemetry: TelemetryEnvelope) -> None:
        """Ingest an adapter sample so safety, evidence, and UI share live state."""

        session = self.session(telemetry.vehicle_id)
        if telemetry.vehicle_id != session.vehicle.identity.vehicle_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "telemetry identity mismatch")
        session.telemetry = telemetry
        session.telemetry_received_at_monotonic_s = time.monotonic()
        self._notify("telemetry_received", telemetry)

    def _transition(
        self,
        vehicle_id: str,
        target: VehicleState,
        source: CommandSource,
    ) -> None:
        session = self.session(vehicle_id)
        current = session.state
        require_transition(current, target)
        session.state = target
        self._event(
            vehicle_id,
            "STATE_TRANSITION",
            f"{current.value} -> {target.value}",
            source=source,
            from_state=current,
            to_state=target,
        )

    def _event(
        self,
        vehicle_id: str,
        event_type: str,
        message: str,
        *,
        source: CommandSource = CommandSource.SUPERVISOR,
        from_state: VehicleState | None = None,
        to_state: VehicleState | None = None,
        command_id: str | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        event = SafetyEvent(
            sequence=self._event_sequence,
            timestamp_monotonic_s=time.monotonic(),
            vehicle_id=vehicle_id,
            event_type=event_type,
            source=source,
            message=message,
            from_state=from_state,
            to_state=to_state,
            command_id=command_id,
            details=details or {},
        )
        self.events.append(event)
        self._event_sequence += 1
        self._notify("safety_event", event)

    def _notify(self, method: str, value: object) -> None:
        for sink in self._audit_sinks:
            try:
                getattr(sink, method)(value)
            except Exception:
                # Evidence/UI paths are deliberately not safety dependencies.
                continue

    def _next_command_sequence(self) -> int:
        value = self._command_sequence
        self._command_sequence += 1
        return value

    @staticmethod
    def _is_armed_or_flying(session: VehicleSession) -> bool:
        return bool(
            session.telemetry
            and (session.telemetry.telemetry.armed or session.telemetry.telemetry.flying)
        )

    @staticmethod
    def _highest_action(issues: list[HealthIssue]) -> RecoveryAction:
        order = {
            RecoveryAction.NONE: 0,
            RecoveryAction.REJECT_NEW_COMMANDS: 1,
            RecoveryAction.ABORT_AND_LAND: 2,
            RecoveryAction.EMERGENCY_STOP: 3,
        }
        return max(
            (item.action for item in issues), key=order.__getitem__, default=RecoveryAction.NONE
        )

    @staticmethod
    def _now(value: float | None) -> float:
        return time.monotonic() if value is None else value
