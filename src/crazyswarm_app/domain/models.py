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


class BackendRole(StrEnum):
    """The backend's system role; never infer this from an adapter name."""

    FAST_SIM = "FAST_SIM"
    ISAAC_SIM = "ISAAC_SIM"
    REAL_CRAZYFLIE = "REAL_CRAZYFLIE"
    REPLAY = "REPLAY"
    TWIN_OBSERVER = "TWIN_OBSERVER"


class AuthorityClass(StrEnum):
    SIMULATION = "SIMULATION"
    PHYSICAL = "PHYSICAL"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"


class SourceClockPolicy(StrEnum):
    ACCELERATED_OR_REALTIME = "ACCELERATED_OR_REALTIME"
    REALTIME_MONOTONIC = "REALTIME_MONOTONIC"
    REPLAY_CONTROLLED = "REPLAY_CONTROLLED"


class CommandCompletionMode(StrEnum):
    BLOCKING_COMPLETION = "BLOCKING_COMPLETION"
    ASYNC_ACCEPTANCE = "ASYNC_ACCEPTANCE"


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
    BODY_RATE_THRUST = "body_rate_thrust"
    RANGE_SENSING = "range_sensing"
    PARAMETER_ACCESS = "parameter_access"
    EMERGENCY_STOP = "emergency_stop"
    TIME_PARAMETERIZED_TRAJECTORY = "time_parameterized_trajectory"


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


class VehicleBackendProfile(ContractModel):
    """Backend-neutral authority, timing, and completion declarations."""

    role: BackendRole
    authority: AuthorityClass
    clock_policy: SourceClockPolicy
    command_completion: CommandCompletionMode
    supports_duration_aware_timeout: bool = True
    supports_source_clock_reset: bool = False
    supports_parameters: bool = False
    recommended_watchdog_period_s: float = Field(default=0.02, ge=0.0, le=1.0)

    @property
    def is_simulation(self) -> bool:
        return self.authority is AuthorityClass.SIMULATION

    @property
    def is_physical(self) -> bool:
        return self.authority is AuthorityClass.PHYSICAL


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
