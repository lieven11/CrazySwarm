from __future__ import annotations

import asyncio
import math
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict

from crazyswarm_app.domain.commands import (
    ExecuteTrajectoryCommand,
    FleetCommandBinding,
    MoveRelativeCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.goals import (
    GoalCaptureAttempt,
    GoalCaptureOutcome,
    GoalCaptureRecord,
    GoalFailureAction,
    LandingGoalRegion,
)
from crazyswarm_app.domain.models import CommandSource, CoordinateFrame, Vector3, VehicleCapability
from crazyswarm_app.domain.trajectory import (
    AcceptedExecutionProgram,
    TimeParameterizedTrajectory,
)
from crazyswarm_app.missions.authority import MissionFleetAuthority
from crazyswarm_app.missions.coordination import MissionCommandGate
from crazyswarm_app.missions.observation import MissionObservation
from crazyswarm_app.safety.supervisor import SafetySupervisor


class MissionParameters(BaseModel):
    """Strict, immutable base class for parameters rendered by the UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MissionCancelled(RuntimeError):
    """Cooperative cancellation raised at a mission checkpoint."""


def _vector_norm(value: Vector3 | None) -> float | None:
    if value is None:
        return None
    return math.sqrt(value.x**2 + value.y**2 + value.z**2)


class MissionDrone(Protocol):
    """Versioned backend-neutral API available to mission Python."""

    @property
    def role(self) -> str: ...

    async def takeoff(self, *, height_m: float, duration_s: float) -> None: ...

    async def hover(self, *, duration_s: float) -> None: ...

    async def move_relative(
        self,
        *,
        x_m: float = 0.0,
        y_m: float = 0.0,
        z_m: float = 0.0,
        yaw_rad: float = 0.0,
        duration_s: float,
        frame: str = "home",
    ) -> None: ...

    async def land(self, *, duration_s: float) -> None: ...

    async def observe(self, *, timeout_s: float = 0.5) -> MissionObservation: ...

    async def wait(self, *, duration_s: float) -> None: ...

    async def checkpoint(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MissionContext:
    mission_run_id: str
    vehicle_id: str
    owner_id: str
    supervisor: SafetySupervisor
    cancellation_requested: Callable[[], bool]
    fleet_authority: MissionFleetAuthority
    command_gate: MissionCommandGate | None = None
    role_id: str = "primary"
    accepted_plan_id: str | None = None
    accepted_plan_sha256: str | None = None
    accepted_execution_program: AcceptedExecutionProgram | None = None
    intent_trace: list[dict[str, Any]] = field(default_factory=list)
    observations_read: list[dict[str, Any]] = field(default_factory=list)
    goal_captures: list[dict[str, Any]] = field(default_factory=list)
    completed_ground_wait_sequences: set[int] = field(default_factory=set)

    @property
    def fleet_binding(self) -> FleetCommandBinding | None:
        return self.fleet_authority.current_binding

    def checkpoint(self) -> None:
        if self.cancellation_requested():
            raise MissionCancelled("mission cancellation requested")

    async def hover(self, duration_s: float) -> None:
        self.checkpoint()
        await self._wait_for_command_permission()
        self._record_intent("hover", {"duration_s": duration_s})
        await self.fleet_authority.execute(
            lambda binding: self.supervisor.hover(
                self.vehicle_id,
                self.owner_id,
                duration_s,
                source=CommandSource.MISSION,
                mission_run_id=self.mission_run_id,
                fleet_binding=binding,
            )
        )
        self.checkpoint()

    async def ground_wait(self, duration_s: float) -> None:
        """Wait against the vehicle source clock without arming or issuing motion."""

        if duration_s <= 0.0:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "ground wait must be positive")
        self.checkpoint()
        self._record_intent("ground_wait", {"duration_s": duration_s})
        first = await self.observe(timeout_s=min(0.5, self.supervisor.policy.command_timeout_s))
        deadline = first.source_timestamp_s + duration_s
        clock_identity = (first.source_clock_id, first.source_clock_epoch)
        simulation_controls = self.supervisor.session(self.vehicle_id).vehicle.simulation_controls
        while True:
            self.checkpoint()
            current = await self.observe(
                timeout_s=min(0.5, self.supervisor.policy.command_timeout_s)
            )
            if (current.source_clock_id, current.source_clock_epoch) != clock_identity:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "source clock changed during admitted ground wait",
                )
            if current.source_timestamp_s >= deadline:
                return
            remaining_s = deadline - current.source_timestamp_s
            advance_idle = getattr(simulation_controls, "advance_idle", None)
            if callable(advance_idle):
                await advance_idle(min(0.10, remaining_s))
            else:
                await asyncio.sleep(min(0.05, remaining_s))

    async def takeoff(self, *, height_m: float, duration_s: float) -> None:
        self.checkpoint()
        await self._wait_for_command_permission()
        self._record_intent("takeoff", {"height_m": height_m, "duration_s": duration_s})
        await self.fleet_authority.execute(
            lambda binding: self.supervisor.takeoff(
                self.vehicle_id,
                self.owner_id,
                height_m=height_m,
                duration_s=duration_s,
                source=CommandSource.MISSION,
                mission_run_id=self.mission_run_id,
                fleet_binding=binding,
            )
        )
        self.checkpoint()

    async def land(self, *, duration_s: float) -> None:
        self.checkpoint()
        self._record_intent("land", {"duration_s": duration_s})
        await self.fleet_authority.execute(
            lambda binding: self.supervisor.land(
                self.vehicle_id,
                self.owner_id,
                duration_s=duration_s,
                source=CommandSource.MISSION,
                mission_run_id=self.mission_run_id,
                fleet_binding=binding,
            )
        )
        self.checkpoint()

    async def move_relative(self, command: MoveRelativeCommand) -> None:
        self.checkpoint()
        await self._wait_for_command_permission()
        self._record_intent(
            "move_relative",
            command.model_dump(mode="json", exclude={"kind"}),
        )
        await self.fleet_authority.execute(
            lambda binding: self.supervisor.move_relative(
                self.vehicle_id,
                self.owner_id,
                command,
                source=CommandSource.MISSION,
                mission_run_id=self.mission_run_id,
                fleet_binding=binding,
            )
        )
        self.checkpoint()

    async def execute_trajectory(self, trajectory: TimeParameterizedTrajectory) -> None:
        self.checkpoint()
        await self._wait_for_command_permission()
        program = self.accepted_execution_program
        if (
            program is None
            or self.accepted_plan_id is None
            or self.accepted_plan_sha256 is None
            or trajectory.sha256 not in program.trajectory_sha256s
        ):
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "trajectory is not part of the accepted execution authority",
            )
        self._record_intent(
            "execute_trajectory",
            {
                "accepted_plan_id": self.accepted_plan_id,
                "accepted_plan_sha256": self.accepted_plan_sha256,
                "execution_program_sha256": program.sha256,
                "trajectory_id": trajectory.trajectory_id,
                "trajectory_sha256": trajectory.sha256,
                "route_sha256": trajectory.route_sha256,
                "duration_s": trajectory.duration_s,
            },
        )
        command = ExecuteTrajectoryCommand(
            accepted_plan_id=self.accepted_plan_id,
            accepted_plan_sha256=self.accepted_plan_sha256,
            execution_program_sha256=program.sha256,
            trajectory_sha256=trajectory.sha256,
            route_sha256=trajectory.route_sha256,
            trajectory=trajectory,
        )
        await self.fleet_authority.execute(
            lambda binding: self.supervisor.execute_trajectory(
                self.vehicle_id,
                self.owner_id,
                command,
                source=CommandSource.MISSION,
                mission_run_id=self.mission_run_id,
                fleet_binding=binding,
            )
        )
        self.checkpoint()

    async def capture_and_land(
        self,
        goal: LandingGoalRegion,
        *,
        duration_s: float,
    ) -> None:
        if goal.role_id != self.role_id or goal.vehicle_id != self.vehicle_id:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "landing goal does not match the active mission role and vehicle",
            )
        attempts: list[GoalCaptureAttempt] = []
        captured = False
        diverted = False
        for attempt_number in range(1, goal.maximum_correction_attempts + 2):
            observation = await self.observe(timeout_s=0.5)
            attempt = self._goal_capture_attempt(goal, observation, attempt_number)
            attempts.append(attempt)
            if attempt.aligned:
                captured = True
                break
            if attempt_number > goal.maximum_correction_attempts:
                break
            position = observation.estimated_position_m
            if position is None:
                continue
            delta = Vector3(
                x=goal.approach_point_m.x - position.x,
                y=goal.approach_point_m.y - position.y,
                z=goal.approach_point_m.z - position.z,
            )
            distance = math.sqrt(delta.x**2 + delta.y**2 + delta.z**2)
            if distance <= 1e-6:
                await self.hover(0.2)
                continue
            correction_duration_s = max(
                goal.correction_duration_s,
                1.5
                * math.hypot(delta.x, delta.y)
                / self.supervisor.policy.max_horizontal_speed_m_s,
                1.5 * abs(delta.z) / self.supervisor.policy.max_vertical_speed_m_s,
                math.sqrt(6.3 * distance / self.supervisor.policy.max_acceleration_m_s2),
            )
            try:
                await self.move_relative(
                    MoveRelativeCommand(
                        x_m=delta.x,
                        y_m=delta.y,
                        z_m=delta.z,
                        duration_s=correction_duration_s,
                        frame=CoordinateFrame.HOME,
                    )
                )
            except CrazySwarmError:
                self._record_goal_rejection(goal, attempts)
                raise

        if not captured and goal.failure_action is GoalFailureAction.DIVERT:
            diversion = goal.diversion_target_m
            latest = attempts[-1].estimated_position_m
            if diversion is not None and latest is not None:
                delta = Vector3(
                    x=diversion.x - latest.x,
                    y=diversion.y - latest.y,
                    z=max(goal.approach_point_m.z, diversion.z) - latest.z,
                )
                distance = math.sqrt(delta.x**2 + delta.y**2 + delta.z**2)
                correction_duration_s = max(
                    goal.correction_duration_s,
                    math.sqrt(
                        6.3 * max(distance, 1e-9) / self.supervisor.policy.max_acceleration_m_s2
                    ),
                )
                try:
                    await self.move_relative(
                        MoveRelativeCommand(
                            x_m=delta.x,
                            y_m=delta.y,
                            z_m=delta.z,
                            duration_s=correction_duration_s,
                            frame=CoordinateFrame.HOME,
                        )
                    )
                except CrazySwarmError:
                    self._record_goal_rejection(goal, attempts)
                    raise
                diverted = True
                captured = True

        if not captured:
            self._record_goal_rejection(goal, attempts)
            raise CrazySwarmError(
                ErrorCode.LOCALIZATION_INVALID,
                "landing approach did not satisfy the accepted goal capture region",
                details={"goal_id": goal.goal_id, "attempt_count": len(attempts)},
            )

        await self.land(duration_s=duration_s)
        terminal = self.supervisor.session(self.vehicle_id).telemetry
        terminal_sample = terminal.telemetry if terminal is not None else None
        terminal_estimate = terminal_sample.position_m if terminal_sample is not None else None
        terminal_truth = (
            terminal_sample.ground_truth_position_m if terminal_sample is not None else None
        )
        terminal_velocity = terminal_sample.velocity_m_s if terminal_sample is not None else None
        terminal_speed = _vector_norm(terminal_velocity)
        selected_terminal = terminal_truth or terminal_estimate
        terminal_target = (
            goal.diversion_target_m
            if diverted and goal.diversion_target_m is not None
            else goal.landing_target_m
        )
        terminal_inside = (
            selected_terminal is not None
            and math.hypot(
                selected_terminal.x - terminal_target.x,
                selected_terminal.y - terminal_target.y,
            )
            <= goal.horizontal_tolerance_m
            and abs(selected_terminal.z - terminal_target.z) <= goal.vertical_tolerance_m
            and terminal_speed is not None
            and terminal_speed <= goal.maximum_capture_speed_m_s
        )
        terminal_state = terminal_sample.state.value if terminal_sample is not None else None
        contact = (
            "SIMULATED_GROUND_CONTACT"
            if terminal_inside and terminal_state == "READY"
            else "NO_CONTACT_EVIDENCE"
        )
        outcome = (
            GoalCaptureOutcome.DIVERTED
            if diverted
            else GoalCaptureOutcome.CAPTURED
            if terminal_inside
            else GoalCaptureOutcome.TERMINAL_MISS
        )
        record = GoalCaptureRecord(
            goal=goal,
            attempts=tuple(attempts),
            attempt_count=len(attempts),
            descent_authorized=True,
            outcome=outcome,
            terminal_estimated_position_m=terminal_estimate,
            terminal_truth_position_m=terminal_truth,
            terminal_speed_m_s=terminal_speed,
            terminal_state=terminal_state,
            terminal_contact=contact,
        )
        self.goal_captures.append(record.model_dump(mode="json"))
        if not terminal_inside and not diverted:
            raise CrazySwarmError(
                ErrorCode.LOCALIZATION_INVALID,
                "landing completed outside the accepted terminal goal region",
                details={"goal_id": goal.goal_id},
            )

    def _record_goal_rejection(
        self,
        goal: LandingGoalRegion,
        attempts: list[GoalCaptureAttempt],
    ) -> None:
        record = GoalCaptureRecord(
            goal=goal,
            attempts=tuple(attempts),
            attempt_count=len(attempts),
            descent_authorized=False,
            outcome=GoalCaptureOutcome.REJECTED,
            terminal_contact="DESCENT_NOT_AUTHORIZED",
        )
        self.goal_captures.append(record.model_dump(mode="json"))

    def _goal_capture_attempt(
        self,
        goal: LandingGoalRegion,
        observation: MissionObservation,
        attempt_number: int,
    ) -> GoalCaptureAttempt:
        estimate = observation.estimated_position_m
        session_telemetry = self.supervisor.session(self.vehicle_id).telemetry
        truth = (
            session_telemetry.telemetry.ground_truth_position_m
            if session_telemetry is not None
            else None
        )
        speed = _vector_norm(observation.velocity_m_s)
        horizontal_error = (
            math.hypot(
                estimate.x - goal.approach_point_m.x,
                estimate.y - goal.approach_point_m.y,
            )
            if estimate is not None
            else None
        )
        vertical_error = abs(estimate.z - goal.approach_point_m.z) if estimate is not None else None
        aligned = (
            observation.valid
            and horizontal_error is not None
            and horizontal_error <= goal.horizontal_tolerance_m
            and vertical_error is not None
            and vertical_error <= goal.vertical_tolerance_m
            and speed is not None
            and speed <= goal.maximum_capture_speed_m_s
        )
        return GoalCaptureAttempt(
            attempt=attempt_number,
            estimated_position_m=estimate,
            truth_position_m=truth,
            speed_m_s=speed,
            horizontal_error_m=horizontal_error,
            vertical_error_m=vertical_error,
            horizontal_capture_margin_m=(
                goal.horizontal_tolerance_m - horizontal_error
                if horizontal_error is not None
                else None
            ),
            vertical_capture_margin_m=(
                goal.vertical_tolerance_m - vertical_error if vertical_error is not None else None
            ),
            speed_capture_margin_m_s=(
                goal.maximum_capture_speed_m_s - speed if speed is not None else None
            ),
            aligned=aligned,
        )

    async def observe(self, *, timeout_s: float = 0.5) -> MissionObservation:
        self.checkpoint()
        telemetry, received_at_s = await self.supervisor.observe(
            self.vehicle_id,
            self.owner_id,
            timeout_s=timeout_s,
        )
        observation = MissionObservation.from_telemetry(
            telemetry,
            now_s=received_at_s,
            received_at_monotonic_s=received_at_s,
        )
        self.observations_read.append(observation.model_dump(mode="json"))
        self.checkpoint()
        return observation

    async def wait(self, *, duration_s: float) -> None:
        await self.hover(duration_s)

    async def wait_for_fleet_authority(
        self,
        *,
        task_id: str,
        minimum_lease_generation: int,
        timeout_s: float,
    ) -> FleetCommandBinding:
        deadline = time.monotonic() + timeout_s
        while True:
            self.checkpoint()
            binding = self.fleet_binding
            if (
                binding is not None
                and binding.task_id == task_id
                and binding.task_lease_generation >= minimum_lease_generation
            ):
                return binding
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0.0:
                raise CrazySwarmError(
                    ErrorCode.COMMAND_TIMEOUT,
                    "timed out waiting for transferred fleet authority",
                )
            await self.hover(min(0.5, remaining_s))
            await asyncio.sleep(0)

    async def async_checkpoint(self) -> None:
        self.checkpoint()

    async def _wait_for_command_permission(self) -> None:
        if self.command_gate is not None:
            await self.command_gate.wait_for_permission(self.vehicle_id)
        self.checkpoint()

    def _record_intent(self, action: str, arguments: dict[str, Any]) -> None:
        self.intent_trace.append(
            {
                "sequence": len(self.intent_trace) + 1,
                "action": action,
                "arguments": arguments,
            }
        )


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
    package_schema_version: int = 1
    logical_roles: tuple[dict[str, Any], ...] = ()
    operator_visible: bool = True

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
