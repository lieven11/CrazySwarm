from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.domain.models import CommandSource, VehicleCapability
from crazyswarm_app.safety.supervisor import SafetySupervisor


class MissionParameters(BaseModel):
    """Strict, immutable base class for parameters rendered by the UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MissionCancelled(RuntimeError):
    """Cooperative cancellation raised at a mission checkpoint."""


@dataclass(frozen=True, slots=True)
class MissionContext:
    mission_run_id: str
    vehicle_id: str
    owner_id: str
    supervisor: SafetySupervisor
    cancellation_requested: Callable[[], bool]

    def checkpoint(self) -> None:
        if self.cancellation_requested():
            raise MissionCancelled("mission cancellation requested")

    async def hover(self, duration_s: float) -> None:
        self.checkpoint()
        await self.supervisor.hover(
            self.vehicle_id,
            self.owner_id,
            duration_s,
            source=CommandSource.MISSION,
            mission_run_id=self.mission_run_id,
        )
        self.checkpoint()

    async def takeoff(self, *, height_m: float, duration_s: float) -> None:
        self.checkpoint()
        await self.supervisor.takeoff(
            self.vehicle_id,
            self.owner_id,
            height_m=height_m,
            duration_s=duration_s,
            source=CommandSource.MISSION,
            mission_run_id=self.mission_run_id,
        )
        self.checkpoint()

    async def land(self, *, duration_s: float) -> None:
        self.checkpoint()
        await self.supervisor.land(
            self.vehicle_id,
            self.owner_id,
            duration_s=duration_s,
            source=CommandSource.MISSION,
            mission_run_id=self.mission_run_id,
        )
        self.checkpoint()

    async def move_relative(self, command: MoveRelativeCommand) -> None:
        self.checkpoint()
        await self.supervisor.move_relative(
            self.vehicle_id,
            self.owner_id,
            command,
            source=CommandSource.MISSION,
            mission_run_id=self.mission_run_id,
        )
        self.checkpoint()


ParameterT = TypeVar("ParameterT", bound=MissionParameters)


class Mission(ABC, Generic[ParameterT]):
    """Behavior-only mission component; MissionRunner owns the safety lifecycle."""

    mission_id: str
    mission_version: str = "1.0.0"
    name: str
    description: str
    required_capabilities: frozenset[VehicleCapability] = frozenset()
    parameters_type: type[ParameterT]
    presets: ClassVar[dict[str, dict[str, Any]]] = {}
    manages_flight_path: bool = False
    source_kind: str = "BUILT_IN"
    source_filename: str | None = None
    source_sha256: str | None = None
    runtime_id: str = "crazyswarm-mission-runner"
    runtime_version: str = "1.0.0"
    planned_commands: tuple[dict[str, Any], ...] = ()

    def takeoff_height_m(self, parameters: ParameterT) -> float:
        return float(getattr(parameters, "height_m", 0.3))

    def takeoff_duration_s(self, parameters: ParameterT) -> float:
        return float(getattr(parameters, "takeoff_duration_s", 2.0))

    def landing_duration_s(self, parameters: ParameterT) -> float:
        return float(getattr(parameters, "landing_duration_s", 2.0))

    def execution_timeout_s(self, parameters: ParameterT) -> float:
        del parameters
        return 300.0

    @abstractmethod
    async def execute(self, context: MissionContext, parameters: ParameterT) -> None:
        raise NotImplementedError
