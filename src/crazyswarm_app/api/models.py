from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from crazyswarm_app.domain.models import Identifier, OperatingMode
from crazyswarm_app.simulation.faults import FaultType


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OperatorContext(ApiModel):
    client_id: Identifier
    request_id: Identifier


class SelectVehicleRequest(ApiModel):
    vehicle_id: Identifier


class ModeRequest(ApiModel):
    mode: OperatingMode
    confirmed: bool = False


class PreflightRequest(ApiModel):
    mission_id: Identifier | None = None


class ArmRequest(ApiModel):
    report_id: Identifier


class TakeoffRequest(ApiModel):
    height_m: float = Field(gt=0.0)
    duration_s: float = Field(default=2.0, gt=0.0)


class DurationRequest(ApiModel):
    duration_s: float = Field(default=2.0, gt=0.0)


class ReasonRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=500)


class ParameterWriteRequest(ApiModel):
    name: str = Field(min_length=1, max_length=160)
    value: bool | int | float | str


class ParameterSnapshotRequest(ApiModel):
    snapshot_id: Identifier


class MissionValidationRequest(ApiModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    preset: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class MissionStartRequest(MissionValidationRequest):
    vehicle_id: Identifier


class MissionFileUploadRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=131072)


class MissionExecutionMode(StrEnum):
    SIMULATION = "SIMULATION"
    TWIN = "TWIN"


class MissionFileStartRequest(ApiModel):
    vehicle_id: Identifier
    execution_mode: MissionExecutionMode


class SimulationClockAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    STEP = "step"
    RESET = "reset"


class SimulationClockRequest(ApiModel):
    action: SimulationClockAction


class FaultInjectionRequest(ApiModel):
    fault: FaultType
    start_s: float = Field(ge=0.0)
    end_s: float | None = Field(default=None, ge=0.0)


class ReplayAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    SEEK = "seek"
    SPEED = "speed"
    STEP = "step"


class ReplayControlRequest(ApiModel):
    action: ReplayAction
    value: float | None = None


class ErrorBody(ApiModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
