from __future__ import annotations

import time
from typing import Any

from crazyswarm_app.domain.commands import CommandEnvelope, CommandKind
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import AuthorityClass, OperatingMode
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.isaac.protocol import GatewayRunBinding, GatewayTelemetrySample


def command_to_gateway_payload(
    command: CommandEnvelope,
    *,
    binding: GatewayRunBinding | None,
) -> dict[str, Any]:
    """Translate canonical intent without admitting physical or replay authority."""

    if command.mode is not OperatingMode.SIM:
        raise CrazySwarmError(
            ErrorCode.MODE_NOT_AUTHORIZED,
            "Isaac gateway accepts simulation commands only",
        )
    if binding is not None and command.mission_run_id != binding.mission_run_id:
        supervised_recovery = command.source.value == "SUPERVISOR" and command.payload.kind in {
            CommandKind.STOP_AND_HOLD,
            CommandKind.LAND,
            CommandKind.ABORT,
            CommandKind.EMERGENCY_STOP,
        }
        mission_cleanup = (
            command.source.value == "MISSION" and command.payload.kind is CommandKind.DISARM
        )
        if not supervised_recovery and not mission_cleanup:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "Isaac command mission-run identity does not match the bound run",
            )
    return {
        "authority": AuthorityClass.SIMULATION.value,
        "run_identity_sha256": binding.run_identity_sha256 if binding is not None else None,
        "command": command.model_dump(mode="json"),
    }


def gateway_sample_to_canonical(
    sample: GatewayTelemetrySample,
    *,
    vehicle_id: str,
    expected_model_id: str,
    expected_model_version: str,
    binding: GatewayRunBinding | None,
    received_timestamp_s: float | None = None,
) -> TelemetryEnvelope:
    if sample.vehicle_id != vehicle_id:
        raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Isaac telemetry vehicle mismatch")
    if sample.model_id != expected_model_id or sample.model_version != expected_model_version:
        raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Isaac telemetry model mismatch")
    if binding is not None and sample.run_identity_sha256 != binding.run_identity_sha256:
        raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "Isaac telemetry run mismatch")
    received = max(received_timestamp_s or time.monotonic(), sample.source_timestamp_s)
    return TelemetryEnvelope(
        vehicle_id=vehicle_id,
        sequence=sample.sequence,
        source_timestamp_s=sample.source_timestamp_s,
        received_timestamp_s=received,
        simulation_timestamp_s=sample.simulation_timestamp_s,
        source_clock_id=sample.source_clock_id,
        source_clock_epoch=sample.source_clock_epoch,
        telemetry=sample.telemetry,
    )
