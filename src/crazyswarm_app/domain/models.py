from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

Identifier = Annotated[
    str,
    Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]
NonNegativeSeconds = Annotated[float, Field(ge=0.0)]


class ContractModel(BaseModel):
    """Strict base for serialized application contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class OperatingMode(StrEnum):
    SIM = "SIM"
    LIVE = "LIVE"
    SHADOW = "SHADOW"
    REPLAY = "REPLAY"


class CoordinateFrame(StrEnum):
    WORLD = "world"
    HOME = "home"
    BODY = "body"
    SENSOR = "sensor"


class VehicleState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    ARMING = "ARMING"
    TAKING_OFF = "TAKING_OFF"
    FLYING = "FLYING"
    RETURNING = "RETURNING"
    LANDING = "LANDING"
    ABORTING = "ABORTING"
    FAULT = "FAULT"
    EMERGENCY = "EMERGENCY"


class CommandSource(StrEnum):
    CLI = "CLI"
    UI = "UI"
    MISSION = "MISSION"
    SUPERVISOR = "SUPERVISOR"
    TEST = "TEST"


class VehicleCapability(StrEnum):
    ARMING = "arming"
    RELATIVE_POSITIONING = "relative_positioning"
    GLOBAL_POSITIONING = "global_positioning"
    HIGH_LEVEL_COMMANDS = "high_level_commands"
    RANGE_SENSING = "range_sensing"
    PARAMETER_ACCESS = "parameter_access"
    EMERGENCY_STOP = "emergency_stop"


class DeckType(StrEnum):
    FLOW = "flow"
    MULTIRANGER = "multiranger"
    LIGHTHOUSE = "lighthouse"
    LOCO = "loco"
    AI = "ai"
    UNKNOWN = "unknown"


class HealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class Vector3(ContractModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class EulerAttitude(ContractModel):
    roll_rad: float = 0.0
    pitch_rad: float = 0.0
    yaw_rad: float = 0.0


class VehicleIdentity(ContractModel):
    vehicle_id: Identifier
    display_name: str = Field(min_length=1, max_length=120)
    adapter: Identifier
    radio_uri: str | None = None
    firmware_version: str | None = None


class DeckStatus(ContractModel):
    deck_type: DeckType
    name: str
    present: bool
    health: HealthStatus = HealthStatus.UNKNOWN
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class VehicleCapabilities(ContractModel):
    features: frozenset[VehicleCapability] = Field(default_factory=frozenset)
    decks: tuple[DeckStatus, ...] = ()

    def supports(self, required: set[VehicleCapability] | frozenset[VehicleCapability]) -> bool:
        return required.issubset(self.features)
