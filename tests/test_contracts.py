from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from crazyswarm_app.domain.commands import (
    ArmCommand,
    CommandEnvelope,
    MoveRelativeCommand,
    TakeoffCommand,
)
from crazyswarm_app.domain.models import (
    CommandSource,
    OperatingMode,
    VehicleCapability,
    VehicleIdentity,
)
from crazyswarm_app.domain.telemetry import TelemetryEnvelope, VehicleTelemetry


def test_command_round_trip_is_deterministic() -> None:
    command = CommandEnvelope(
        vehicle_id="cf01",
        command_id="cmd-001",
        mission_run_id="run-001",
        issued_at_monotonic_s=12.5,
        source=CommandSource.MISSION,
        mode=OperatingMode.SIM,
        payload=TakeoffCommand(height_m=0.3, duration_s=2.0),
    )

    encoded = command.model_dump_json()
    restored = CommandEnvelope.model_validate_json(encoded)

    assert restored == command
    assert json.loads(restored.model_dump_json())["payload"]["height_m"] == 0.3


def test_replay_mode_cannot_contain_commands() -> None:
    with pytest.raises(ValidationError, match="REPLAY mode cannot"):
        CommandEnvelope(
            vehicle_id="cf01",
            command_id="cmd-001",
            issued_at_monotonic_s=0.0,
            source=CommandSource.UI,
            mode=OperatingMode.REPLAY,
            payload=ArmCommand(),
        )


@pytest.mark.parametrize("vehicle_id", ["", "spaces are invalid", "/root"])
def test_invalid_identifiers_fail(vehicle_id: str) -> None:
    with pytest.raises(ValidationError):
        VehicleIdentity(vehicle_id=vehicle_id, display_name="Drone", adapter="sim")


def test_relative_move_requires_motion_and_valid_frame() -> None:
    with pytest.raises(ValidationError, match="must change"):
        MoveRelativeCommand()


def test_unknown_contract_fields_fail() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        VehicleTelemetry(state="READY", unsupported=True)  # type: ignore[call-arg]


def test_telemetry_round_trip() -> None:
    envelope = TelemetryEnvelope(
        vehicle_id="sim01",
        sequence=7,
        source_timestamp_s=1.0,
        received_timestamp_s=1.01,
        telemetry=VehicleTelemetry(state="READY"),
    )
    assert TelemetryEnvelope.model_validate_json(envelope.model_dump_json()) == envelope


def test_capability_names_are_stable() -> None:
    assert VehicleCapability.RELATIVE_POSITIONING.value == "relative_positioning"
