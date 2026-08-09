from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import ClassVar

from pydantic import Field, model_validator

from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.domain.models import CoordinateFrame, VehicleCapability
from crazyswarm_app.missions.base import Mission, MissionContext, MissionParameters

_BUILTIN_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class FlightParameters(MissionParameters):
    height_m: float = Field(default=0.3, gt=0.0, le=1.0)
    takeoff_duration_s: float = Field(default=2.0, gt=0.0, le=30.0)
    landing_duration_s: float = Field(default=2.0, gt=0.0, le=30.0)


class HoverParameters(FlightParameters):
    duration_s: float = Field(default=3.0, gt=0.0, le=300.0)


class HoverMission(Mission[HoverParameters]):
    mission_id = "hover"
    mission_version = "1.0.0"
    name = "Take off, hover, and land"
    description = "Take off vertically, hold position, and land at the launch point."
    source_sha256 = _BUILTIN_SOURCE_SHA256
    required_capabilities = frozenset(
        {
            VehicleCapability.ARMING,
            VehicleCapability.RELATIVE_POSITIONING,
            VehicleCapability.HIGH_LEVEL_COMMANDS,
        }
    )
    parameters_type = HoverParameters
    presets: ClassVar[dict[str, dict[str, float]]] = {
        "gentle-30cm": {"height_m": 0.3, "duration_s": 3.0},
        "quick-check": {"height_m": 0.2, "duration_s": 1.0},
    }

    async def execute(self, context: MissionContext, parameters: HoverParameters) -> None:
        await context.hover(parameters.duration_s)

    def execution_timeout_s(self, parameters: HoverParameters) -> float:
        return parameters.duration_s + 10.0


class RelativeMoveParameters(FlightParameters):
    x_m: float = Field(default=0.3, ge=-1.0, le=1.0)
    y_m: float = Field(default=0.0, ge=-1.0, le=1.0)
    z_m: float = Field(default=0.0, ge=-0.5, le=0.5)
    yaw_rad: float = Field(default=0.0, ge=-math.pi, le=math.pi)
    move_duration_s: float = Field(default=2.0, gt=0.0, le=30.0)
    dwell_s: float = Field(default=1.0, ge=0.0, le=60.0)

    @model_validator(mode="after")
    def motion_is_nonzero(self) -> RelativeMoveParameters:
        if self.x_m == self.y_m == self.z_m == self.yaw_rad == 0.0:
            raise ValueError("relative move must change position or yaw")
        return self


class RelativeMoveMission(Mission[RelativeMoveParameters]):
    mission_id = "move-return"
    mission_version = "1.0.0"
    name = "Relative move and return"
    description = "Move by a relative offset, pause, then reverse the offset to return near home."
    source_sha256 = _BUILTIN_SOURCE_SHA256
    required_capabilities = frozenset(
        {
            VehicleCapability.ARMING,
            VehicleCapability.RELATIVE_POSITIONING,
            VehicleCapability.HIGH_LEVEL_COMMANDS,
        }
    )
    parameters_type = RelativeMoveParameters
    presets: ClassVar[dict[str, dict[str, float]]] = {
        "forward-30cm": {"x_m": 0.3, "move_duration_s": 2.0},
        "left-30cm": {"y_m": 0.3, "move_duration_s": 2.0},
    }

    async def execute(
        self,
        context: MissionContext,
        parameters: RelativeMoveParameters,
    ) -> None:
        command = MoveRelativeCommand(
            x_m=parameters.x_m,
            y_m=parameters.y_m,
            z_m=parameters.z_m,
            yaw_rad=parameters.yaw_rad,
            duration_s=parameters.move_duration_s,
            frame=CoordinateFrame.HOME,
        )
        await context.move_relative(command)
        if parameters.dwell_s > 0.0:
            await context.hover(parameters.dwell_s)
        await context.move_relative(
            command.model_copy(
                update={
                    "x_m": -parameters.x_m,
                    "y_m": -parameters.y_m,
                    "z_m": -parameters.z_m,
                    "yaw_rad": -parameters.yaw_rad,
                }
            )
        )

    def execution_timeout_s(self, parameters: RelativeMoveParameters) -> float:
        return 2.0 * parameters.move_duration_s + parameters.dwell_s + 10.0


class SquareParameters(FlightParameters):
    side_m: float = Field(default=0.3, gt=0.0, le=0.8)
    leg_duration_s: float = Field(default=2.0, gt=0.0, le=30.0)
    dwell_s: float = Field(default=0.25, ge=0.0, le=10.0)
    loops: int = Field(default=1, ge=1, le=5)


class SquareMission(Mission[SquareParameters]):
    mission_id = "square"
    mission_version = "1.0.0"
    name = "Square waypoint sequence"
    description = "Fly a four-leg square in the home frame and return to the first corner."
    source_sha256 = _BUILTIN_SOURCE_SHA256
    required_capabilities = frozenset(
        {
            VehicleCapability.ARMING,
            VehicleCapability.RELATIVE_POSITIONING,
            VehicleCapability.HIGH_LEVEL_COMMANDS,
        }
    )
    parameters_type = SquareParameters
    presets: ClassVar[dict[str, dict[str, float | int]]] = {
        "small": {"side_m": 0.2, "leg_duration_s": 1.5, "loops": 1},
        "standard": {"side_m": 0.3, "leg_duration_s": 2.0, "loops": 1},
    }

    async def execute(self, context: MissionContext, parameters: SquareParameters) -> None:
        legs = (
            (parameters.side_m, 0.0),
            (0.0, parameters.side_m),
            (-parameters.side_m, 0.0),
            (0.0, -parameters.side_m),
        )
        for _ in range(parameters.loops):
            for x_m, y_m in legs:
                await context.move_relative(
                    MoveRelativeCommand(
                        x_m=x_m,
                        y_m=y_m,
                        duration_s=parameters.leg_duration_s,
                        frame=CoordinateFrame.HOME,
                    )
                )
                if parameters.dwell_s > 0.0:
                    await context.hover(parameters.dwell_s)

    def execution_timeout_s(self, parameters: SquareParameters) -> float:
        return parameters.loops * 4 * (parameters.leg_duration_s + parameters.dwell_s) + 10.0


class ReserveTakeoverParameters(FlightParameters):
    staging_x_m: float = Field(ge=-3.0, le=3.0)
    staging_y_m: float = Field(ge=-3.0, le=3.0)
    staging_move_duration_s: float = Field(default=6.0, gt=0.0, le=30.0)
    staging_hold_s: float = Field(default=30.0, gt=0.0, le=60.0)
    takeover_x_m: float = Field(ge=-3.0, le=3.0)
    takeover_y_m: float = Field(ge=-3.0, le=3.0)
    takeover_move_duration_s: float = Field(default=3.0, gt=0.0, le=30.0)
    coverage_hold_s: float = Field(default=2.0, gt=0.0, le=30.0)
    return_x_m: float = Field(ge=-3.0, le=3.0)
    return_y_m: float = Field(ge=-3.0, le=3.0)
    return_move_duration_s: float = Field(default=6.0, gt=0.0, le=30.0)


class ReserveTakeoverMission(Mission[ReserveTakeoverParameters]):
    """Coordinator-owned staging, bounded takeover coverage, and return maneuver."""

    mission_id = "fleet-reserve-takeover"
    mission_version = "1.0.0"
    name = "Fleet reserve takeover maneuver"
    description = "Stage safely, enter a transferred coverage task, return, and land."
    source_sha256 = _BUILTIN_SOURCE_SHA256
    required_capabilities = frozenset(
        {
            VehicleCapability.ARMING,
            VehicleCapability.RELATIVE_POSITIONING,
            VehicleCapability.HIGH_LEVEL_COMMANDS,
        }
    )
    parameters_type = ReserveTakeoverParameters
    manages_flight_path = True
    operator_visible = False

    async def execute(
        self,
        context: MissionContext,
        parameters: ReserveTakeoverParameters,
    ) -> None:
        await context.takeoff(
            height_m=parameters.height_m,
            duration_s=parameters.takeoff_duration_s,
        )
        await context.move_relative(
            MoveRelativeCommand(
                x_m=parameters.staging_x_m,
                y_m=parameters.staging_y_m,
                duration_s=parameters.staging_move_duration_s,
                frame=CoordinateFrame.HOME,
            )
        )
        await context.wait_for_fleet_authority(
            task_id=context.role_id,
            minimum_lease_generation=2,
            timeout_s=parameters.staging_hold_s,
        )
        await context.move_relative(
            MoveRelativeCommand(
                x_m=parameters.takeover_x_m,
                y_m=parameters.takeover_y_m,
                duration_s=parameters.takeover_move_duration_s,
                frame=CoordinateFrame.HOME,
            )
        )
        await context.hover(parameters.coverage_hold_s)
        await context.move_relative(
            MoveRelativeCommand(
                x_m=parameters.return_x_m,
                y_m=parameters.return_y_m,
                duration_s=parameters.return_move_duration_s,
                frame=CoordinateFrame.HOME,
            )
        )
        await context.land(duration_s=parameters.landing_duration_s)

    def execution_timeout_s(self, parameters: ReserveTakeoverParameters) -> float:
        return (
            parameters.takeoff_duration_s
            + parameters.staging_move_duration_s
            + parameters.staging_hold_s
            + parameters.takeover_move_duration_s
            + parameters.coverage_hold_s
            + parameters.return_move_duration_s
            + parameters.landing_duration_s
            + 10.0
        )
