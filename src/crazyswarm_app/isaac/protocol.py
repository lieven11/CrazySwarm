from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import (
    AuthorityClass,
    ContractModel,
    CoordinateFrame,
    Identifier,
    VehicleCapability,
)
from crazyswarm_app.domain.simulation import SHA256
from crazyswarm_app.domain.telemetry import VehicleTelemetry

GATEWAY_PROTOCOL_VERSION: Final[Literal["1.3.0"]] = "1.3.0"
MAX_GATEWAY_MESSAGE_BYTES: Final = 1_048_576


class GatewayOperation(StrEnum):
    CONNECT = "connect"
    BIND_RUN = "bind_run"
    COMMAND = "command"
    SNAPSHOT = "snapshot"
    HEALTH = "health"
    STEP = "step"
    RESET_CLOCK = "reset_clock"
    DISCONNECT = "disconnect"


class GatewayLifecycleState(StrEnum):
    NEW = "NEW"
    STARTING = "STARTING"
    READY = "READY"
    RUN_BOUND = "RUN_BOUND"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class SimulatorProcessState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    STARTING = "STARTING"
    READY = "READY"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    CRASHED = "CRASHED"


class GatewayRunBinding(ContractModel):
    """Immutable mission/model identity attached before command authority is used."""

    mission_run_id: Identifier
    mission_source_sha256: SHA256
    run_identity_sha256: SHA256
    model_id: Identifier
    model_version: str
    model_configuration_sha256: SHA256
    scenario_id: Identifier
    scenario_configuration_sha256: SHA256
    fleet_session_id: Identifier | None = None
    fleet_run_id: Identifier | None = None
    deployment_sha256: SHA256 | None = None
    task_id: Identifier | None = None
    task_lease_generation: Annotated[int, Field(ge=1)] | None = None
    backend_namespace: str | None = Field(default=None, min_length=1, max_length=500)
    preparation_state: Literal["READY"] | None = None

    @model_validator(mode="after")
    def fleet_identity_is_complete(self) -> GatewayRunBinding:
        fleet_values = (
            self.fleet_session_id,
            self.fleet_run_id,
            self.deployment_sha256,
            self.task_id,
            self.task_lease_generation,
            self.backend_namespace,
            self.preparation_state,
        )
        if any(item is not None for item in fleet_values) and any(
            item is None for item in fleet_values
        ):
            raise ValueError("gateway fleet binding must be complete")
        return self


class GatewayCapabilities(ContractModel):
    protocol_version: Literal["1.3.0"] = GATEWAY_PROTOCOL_VERSION
    authority: Literal[AuthorityClass.SIMULATION] = AuthorityClass.SIMULATION
    commands: frozenset[str]
    vehicle_capabilities: frozenset[VehicleCapability]
    signals: frozenset[Identifier]
    maximum_vehicles: Annotated[int, Field(ge=1)] = 1
    telemetry_queue_bound: Annotated[int, Field(ge=1)] = 100
    supports_headless: bool = True
    supports_manual_step: bool = True
    supports_clock_reset: bool = True
    supports_reconnect_after_unknown_command: bool = False
    cameras_enabled: bool = False
    rtx_lidar_enabled: bool = False
    digital_twin_enabled: Literal[False] = False


class GatewayHealth(ContractModel):
    lifecycle: GatewayLifecycleState
    simulator_process: SimulatorProcessState
    ready: bool
    gateway_instance_id: Identifier
    session_id: Identifier | None = None
    telemetry_queue_depth: Annotated[int, Field(ge=0)] = 0
    telemetry_dropped_total: Annotated[int, Field(ge=0)] = 0
    issues: tuple[str, ...] = ()


class GatewayTelemetrySample(ContractModel):
    vehicle_id: Identifier
    sequence: Annotated[int, Field(ge=0)]
    source_timestamp_s: Annotated[float, Field(ge=0.0)]
    source_clock_id: Identifier
    source_clock_epoch: Annotated[int, Field(ge=0)] = 0
    simulation_timestamp_s: Annotated[float, Field(ge=0.0)]
    source_class: Literal["SIMULATED_MODEL"] = "SIMULATED_MODEL"
    model_id: Identifier
    model_version: str
    frame: CoordinateFrame
    linear_unit: Literal["m"] = "m"
    angular_unit: Literal["rad"] = "rad"
    run_identity_sha256: SHA256 | None = None
    telemetry: VehicleTelemetry

    @model_validator(mode="after")
    def spatial_frame_matches_payload(self) -> GatewayTelemetrySample:
        if self.telemetry.frame is not None and self.telemetry.frame is not self.frame:
            raise ValueError("gateway sample frame does not match telemetry frame")
        return self


class GatewayRequest(ContractModel):
    protocol_version: Literal["1.3.0"] = GATEWAY_PROTOCOL_VERSION
    request_id: Annotated[int, Field(ge=1)]
    operation: GatewayOperation
    vehicle_id: Identifier
    session_id: Identifier | None = None
    authentication_token: str | None = Field(default=None, min_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


class GatewayResponse(ContractModel):
    protocol_version: Literal["1.3.0"] = GATEWAY_PROTOCOL_VERSION
    request_id: Annotated[int, Field(ge=1)]
    operation: GatewayOperation
    ok: bool
    vehicle_id: Identifier
    gateway_instance_id: Identifier
    session_id: Identifier | None = None
    model_id: Identifier
    model_version: str
    frame: CoordinateFrame
    capabilities: GatewayCapabilities | None = None
    health: GatewayHealth | None = None
    telemetry: GatewayTelemetrySample | None = None
    command_id: Identifier | None = None
    error_code: Identifier | None = None
    error: str | None = None

    @model_validator(mode="after")
    def explicit_success_or_error(self) -> GatewayResponse:
        if self.ok and (self.error is not None or self.error_code is not None):
            raise ValueError("successful gateway response cannot contain an error")
        if not self.ok and (self.error is None or self.error_code is None):
            raise ValueError("failed gateway response requires a named error")
        if self.operation is GatewayOperation.CONNECT and self.ok and self.capabilities is None:
            raise ValueError("connect response requires capability discovery")
        return self
