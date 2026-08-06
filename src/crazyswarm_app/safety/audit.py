from __future__ import annotations

from typing import Protocol

from crazyswarm_app.domain.commands import CommandAcknowledgement, CommandEnvelope
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.safety.models import SafetyEvent


class SupervisorAuditSink(Protocol):
    """Non-blocking observer contract; sink failures never affect vehicle safety."""

    def command_sent(self, command: CommandEnvelope) -> None: ...

    def command_acknowledged(self, acknowledgement: CommandAcknowledgement) -> None: ...

    def safety_event(self, event: SafetyEvent) -> None: ...

    def telemetry_received(self, telemetry: TelemetryEnvelope) -> None: ...
