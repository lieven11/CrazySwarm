from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from crazyswarm_app import __version__
from crazyswarm_app.domain.commands import CommandAcknowledgement, CommandEnvelope
from crazyswarm_app.domain.models import CoordinateFrame, OperatingMode, VehicleState
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.missions.models import MissionResult, MissionRunEvent, MissionRunSnapshot
from crazyswarm_app.observability.bus import TelemetryBus
from crazyswarm_app.observability.events import (
    AcknowledgementPayload,
    CommandPayload,
    EvidenceEvent,
    EvidencePayload,
    FaultPayload,
    MissionEventPayload,
    MissionResultPayload,
    MissionStartedPayload,
    OperatorActionPayload,
    StatePayload,
    TelemetryPayload,
    event_kind_for_payload,
)
from crazyswarm_app.safety.models import SafetyEvent


class EvidenceBridge:
    """Maps supervisor and mission audit callbacks onto the shared event bus."""

    def __init__(
        self,
        bus: TelemetryBus,
        *,
        mode_provider: Callable[[], OperatingMode] = lambda: OperatingMode.SIM,
        configuration_schema_version: int = 1,
    ) -> None:
        self.bus = bus
        self.mode_provider = mode_provider
        self.configuration_schema_version = configuration_schema_version
        self._system_run_id = f"system-{uuid.uuid4().hex}"
        self._active_runs: dict[str, str] = {}
        self._commands: dict[str, tuple[str, OperatingMode]] = {}

    def mission_started(self, run: MissionRunSnapshot) -> None:
        self._active_runs[run.vehicle_id] = run.mission_run_id
        self._publish(
            vehicle_id=run.vehicle_id,
            run_id=run.mission_run_id,
            mode=run.mode,
            source="mission-runner",
            timestamp_s=run.started_at_monotonic_s,
            unit="event",
            frame=CoordinateFrame.WORLD,
            payload=MissionStartedPayload(
                run=run,
                software_version=__version__,
                configuration_schema_version=self.configuration_schema_version,
            ),
        )

    def mission_event(self, event: MissionRunEvent) -> None:
        vehicle_id = self._vehicle_for_run(event.mission_run_id)
        self._publish(
            vehicle_id=vehicle_id,
            run_id=event.mission_run_id,
            mode=self.mode_provider(),
            source="mission-runner",
            timestamp_s=event.timestamp_monotonic_s,
            unit="event",
            frame=CoordinateFrame.WORLD,
            payload=MissionEventPayload(event=event),
        )

    def mission_finished(self, result: MissionResult) -> None:
        self._publish(
            vehicle_id=result.vehicle_id,
            run_id=result.mission_run_id,
            mode=result.mode,
            source="mission-runner",
            timestamp_s=result.finished_at_monotonic_s,
            unit="event",
            frame=CoordinateFrame.WORLD,
            payload=MissionResultPayload(result=result),
        )
        self._active_runs.pop(result.vehicle_id, None)

    def command_sent(self, command: CommandEnvelope) -> None:
        run_id = command.mission_run_id or self._run_for_vehicle(command.vehicle_id)
        self._commands[command.command_id] = (run_id, command.mode)
        self._publish(
            vehicle_id=command.vehicle_id,
            run_id=run_id,
            mode=command.mode,
            source=command.source.value.lower(),
            timestamp_s=command.issued_at_monotonic_s,
            unit="command",
            frame=CoordinateFrame.WORLD,
            payload=CommandPayload(command=command),
        )

    def command_acknowledged(self, acknowledgement: CommandAcknowledgement) -> None:
        run_id, mode = self._commands.get(
            acknowledgement.command_id,
            (self._run_for_vehicle(acknowledgement.vehicle_id), self.mode_provider()),
        )
        self._publish(
            vehicle_id=acknowledgement.vehicle_id,
            run_id=run_id,
            mode=mode,
            source="vehicle-adapter",
            timestamp_s=acknowledgement.received_at_monotonic_s,
            unit="acknowledgement",
            frame=CoordinateFrame.WORLD,
            payload=AcknowledgementPayload(acknowledgement=acknowledgement),
        )

    def safety_event(self, event: SafetyEvent) -> None:
        run_id = self._run_for_vehicle(event.vehicle_id)
        self._publish(
            vehicle_id=event.vehicle_id,
            run_id=run_id,
            mode=self.mode_provider(),
            source=event.source.value.lower(),
            timestamp_s=event.timestamp_monotonic_s,
            unit="event",
            frame=CoordinateFrame.WORLD,
            payload=StatePayload(event=event),
        )
        if event.to_state in {VehicleState.FAULT, VehicleState.EMERGENCY} or any(
            marker in event.event_type for marker in ("FAULT", "TIMEOUT", "EXPIRED")
        ):
            self._publish(
                vehicle_id=event.vehicle_id,
                run_id=run_id,
                mode=self.mode_provider(),
                source="safety-supervisor",
                timestamp_s=event.timestamp_monotonic_s,
                unit="fault",
                frame=CoordinateFrame.WORLD,
                payload=FaultPayload(
                    code=event.event_type,
                    message=event.message,
                    details=event.details,
                ),
            )

    def telemetry_received(self, telemetry: TelemetryEnvelope) -> None:
        self._publish(
            vehicle_id=telemetry.vehicle_id,
            run_id=self._run_for_vehicle(telemetry.vehicle_id),
            mode=self.mode_provider(),
            source="vehicle-adapter",
            timestamp_s=telemetry.source_timestamp_s,
            received_timestamp_s=telemetry.received_timestamp_s,
            unit="SI",
            frame=telemetry.telemetry.frame,
            payload=TelemetryPayload(telemetry=telemetry),
        )

    def operator_action(
        self,
        *,
        vehicle_id: str,
        client_id: str,
        request_id: str,
        action: str,
        details: dict[str, object] | None = None,
    ) -> None:
        now = time.monotonic()
        self._publish(
            vehicle_id=vehicle_id,
            run_id=self._run_for_vehicle(vehicle_id),
            mode=self.mode_provider(),
            source="operator",
            timestamp_s=now,
            unit="action",
            frame=CoordinateFrame.WORLD,
            payload=OperatorActionPayload(
                client_id=client_id,
                action=action,
                request_id=request_id,
                details=details or {},
            ),
        )

    def _publish(
        self,
        *,
        vehicle_id: str,
        run_id: str,
        mode: OperatingMode,
        source: str,
        timestamp_s: float,
        unit: str,
        frame: CoordinateFrame | None,
        payload: EvidencePayload,
        received_timestamp_s: float | None = None,
    ) -> EvidenceEvent:
        event = EvidenceEvent(
            event_id=f"evt-{uuid.uuid4().hex}",
            sequence=0,
            kind=event_kind_for_payload(payload),
            vehicle_id=vehicle_id,
            run_id=run_id,
            mode=mode,
            source=source,
            source_timestamp_s=timestamp_s,
            received_timestamp_s=(
                time.monotonic() if received_timestamp_s is None else received_timestamp_s
            ),
            unit=unit,
            frame=frame,
            payload=payload,
        )
        return self.bus.publish_nowait(event)

    def _run_for_vehicle(self, vehicle_id: str) -> str:
        return self._active_runs.get(vehicle_id, self._system_run_id)

    def _vehicle_for_run(self, run_id: str) -> str:
        return next(
            (vehicle_id for vehicle_id, active in self._active_runs.items() if active == run_id),
            "system",
        )
