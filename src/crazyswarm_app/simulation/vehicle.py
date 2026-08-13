from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
from collections import deque
from collections.abc import AsyncIterator

from crazyswarm_app.domain.commands import (
    AbortCommand,
    AcknowledgementStatus,
    ArmCommand,
    CommandAcknowledgement,
    CommandEnvelope,
    ConnectCommand,
    DisarmCommand,
    DisconnectCommand,
    EmergencyStopCommand,
    ExecuteTrajectoryCommand,
    HoverCommand,
    LandCommand,
    MoveRelativeCommand,
    StopAndHoldCommand,
    TakeoffCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.goals import LandingGoalRegion
from crazyswarm_app.domain.models import (
    AuthorityClass,
    BackendRole,
    CommandCompletionMode,
    CommandSource,
    CoordinateFrame,
    DeckStatus,
    DeckType,
    EulerAttitude,
    HealthStatus,
    SourceClockPolicy,
    Vector3,
    VehicleBackendProfile,
    VehicleCapabilities,
    VehicleCapability,
    VehicleIdentity,
    VehicleState,
)
from crazyswarm_app.domain.simulation import (
    AdapterContractManifest,
    FleetAuthorityTransition,
    FleetAuthorityTransitionReceipt,
    MissionRunBinding,
    canonical_sha256,
)
from crazyswarm_app.domain.telemetry import (
    FlowReading,
    FlowStatus,
    ImuReading,
    LocalizationSource,
    MotorReading,
    MotorTelemetry,
    RangeReadings,
    RangeStatus,
    TelemetryEnvelope,
    TransportReading,
    VehicleTelemetry,
)
from crazyswarm_app.domain.trajectory import sample_trajectory_segment
from crazyswarm_app.simulation.clock import ClockMode, SimulationClock
from crazyswarm_app.simulation.faults import FaultInjector, FaultType
from crazyswarm_app.simulation.models import ControllerProfile, SimulationConfig
from crazyswarm_app.simulation.physics import ControllerState, Quaternion, SixDofPhysics
from crazyswarm_app.simulation.powertrain import BatteryCutoffReason, PowertrainModel
from crazyswarm_app.simulation.sensors import SampledImuModel
from crazyswarm_app.simulation.world import IndoorWorld
from crazyswarm_app.vehicles.base import Vehicle


def _vector_length(value: Vector3) -> float:
    return math.sqrt(value.x**2 + value.y**2 + value.z**2)


class SimulatedVehicle(Vehicle):
    def __init__(
        self,
        identity: VehicleIdentity,
        world: IndoorWorld,
        *,
        config: SimulationConfig | None = None,
        initial_position_m: Vector3 | None = None,
        initial_yaw_rad: float = 0.0,
        faults: FaultInjector | None = None,
        scenario_id: str | None = None,
        scenario_schema_version: str | None = None,
        scenario_configuration_sha256: str | None = None,
    ) -> None:
        self._identity = identity
        self.world = world
        self.config = config or SimulationConfig()
        self.clock = SimulationClock(
            fixed_step_s=self.config.fixed_step_s,
            mode=self.config.clock_mode,
            speed=self.config.speed,
        )
        self.faults = faults or FaultInjector()
        self._scenario_id = scenario_id or world.config.world_id
        self._scenario_schema_version = scenario_schema_version or "1"
        self._scenario_configuration_sha256 = scenario_configuration_sha256 or canonical_sha256(
            world.config
        )
        self._random = random.Random(self.config.seed)
        self._sensor_random = random.Random(self.config.seed ^ 0x51A7E)
        self._imu_model = SampledImuModel(self.config.imu, self._sensor_random)
        self._initial_position = initial_position_m or Vector3()
        if not self.world.contains(self._initial_position):
            raise ValueError("initial position is outside the world")
        self._initial_yaw = initial_yaw_rad
        self.physics = SixDofPhysics(
            self.config.physics,
            position_m=self._initial_position,
            yaw_rad=self._initial_yaw,
            battery_percent=self.config.battery_start_percent,
            initial_roll_rad=self.config.disturbance.initial_roll_rad,
            initial_pitch_rad=self.config.disturbance.initial_pitch_rad,
            initial_velocity_m_s=self.config.disturbance.initial_velocity_m_s,
        )
        self._capabilities = VehicleCapabilities(
            features=frozenset(
                {
                    VehicleCapability.ARMING,
                    VehicleCapability.RELATIVE_POSITIONING,
                    VehicleCapability.HIGH_LEVEL_COMMANDS,
                    VehicleCapability.RANGE_SENSING,
                    VehicleCapability.PARAMETER_ACCESS,
                    VehicleCapability.EMERGENCY_STOP,
                    VehicleCapability.TIME_PARAMETERIZED_TRAJECTORY,
                }
            ),
            decks=(
                DeckStatus(
                    deck_type=DeckType.FLOW,
                    name="Simulated Flow Deck",
                    present=True,
                    health=HealthStatus.HEALTHY,
                ),
                DeckStatus(
                    deck_type=DeckType.MULTIRANGER,
                    name="Simulated Multi-ranger Deck",
                    present=True,
                    health=HealthStatus.HEALTHY,
                ),
            ),
        )
        self._subscribers: set[asyncio.Queue[TelemetryEnvelope]] = set()
        self._parameter_provider: object | None = None
        self.telemetry_history: list[TelemetryEnvelope] = []
        self._source_clock_epoch = -1
        self._binding: MissionRunBinding | None = None
        self._authority_transition_sequence = 0
        self._authority_transition_receipts: list[FleetAuthorityTransitionReceipt] = []
        self._state: VehicleState
        self._armed: bool
        self._flying: bool
        self._yaw_rad: float
        self.reset()

    @property
    def identity(self) -> VehicleIdentity:
        return self._identity

    @property
    def capabilities(self) -> VehicleCapabilities:
        return self._capabilities

    @property
    def backend_profile(self) -> VehicleBackendProfile:
        return VehicleBackendProfile(
            role=BackendRole.FAST_SIM,
            authority=AuthorityClass.SIMULATION,
            clock_policy=SourceClockPolicy.ACCELERATED_OR_REALTIME,
            command_completion=CommandCompletionMode.BLOCKING_COMPLETION,
            supports_duration_aware_timeout=True,
            supports_source_clock_reset=True,
            supports_parameters=True,
            recommended_watchdog_period_s=(
                0.0 if self.clock.mode is ClockMode.ACCELERATED else self.config.fixed_step_s
            ),
        )

    @property
    def parameter_provider(self) -> object:
        if self._parameter_provider is None:
            from crazyswarm_app.simulation.parameters import SimulationParameterProvider

            self._parameter_provider = SimulationParameterProvider(self)
        return self._parameter_provider

    @property
    def simulation_controls(self) -> SimulatedVehicle:
        return self

    @property
    def contract_manifest(self) -> AdapterContractManifest:
        return AdapterContractManifest(
            adapter_id="fast-sim",
            supported_capabilities=self.capabilities.features,
            supported_signals=frozenset(
                specification.signal_id
                for specification in self.config.signal_specifications()
                if specification.presence.value != "UNSUPPORTED"
            ),
            supported_model_ids=frozenset({self.config.physics.model_id}),
        )

    @property
    def execution_metadata(self) -> dict[str, str | int | float | None]:
        physics_configuration_sha256 = self.config.vehicle_parameters().sha256
        initial_state = json.dumps(
            {
                "position_m": self.physics.state.position_m.model_dump(mode="json"),
                "yaw_rad": self._yaw_rad,
                "battery_percent": self.battery_percent,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {
            "vehicle_adapter": self.identity.adapter,
            "backend_role": self.backend_profile.role.value,
            "authority_class": self.backend_profile.authority.value,
            "physics_model_id": self.config.physics.model_id,
            "physics_model_version": self.config.physics.model_version,
            "physics_configuration_sha256": physics_configuration_sha256,
            "scenario_id": self._scenario_id,
            "scenario_schema_version": self._scenario_schema_version,
            "scenario_configuration_sha256": self._scenario_configuration_sha256,
            "simulation_seed": self.config.seed,
            "simulation_fixed_step_s": self.config.fixed_step_s,
            "initial_state_sha256": hashlib.sha256(initial_state).hexdigest(),
            "run_identity_sha256": None,
        }

    @property
    def state(self) -> VehicleState:
        return self._state

    @property
    def true_position_m(self) -> Vector3:
        return self.physics.state.position_m

    @property
    def battery_percent(self) -> float:
        return self.physics.state.battery_state_of_charge * 100.0

    def reset(self) -> None:
        self.clock.reset()
        self._source_clock_epoch += 1
        self._random.seed(self.config.seed)
        self._sensor_random.seed(self.config.seed ^ 0x51A7E)
        self._restore_pose_and_dynamics(self.config.battery_start_percent)
        self._sequence = 0
        self._fault_messages: list[str] = []
        self.telemetry_history.clear()
        self._binding = None
        self._authority_transition_sequence = 0
        self._authority_transition_receipts.clear()
        self.last_landing_evidence: dict[
            str, str | float | bool | dict[str, float] | None
        ] | None = None
        self._landing_contact_source_timestamp_s: float | None = None
        self._landing_pre_contact_vertical_speed_m_s: float | None = None
        self._last_published = self._build_telemetry()

    async def advance_idle(self, duration_s: float) -> None:
        """Advance a connected, non-flying simulator during an admitted ground wait."""

        if duration_s <= 0.0:
            raise ValueError("idle advance duration must be positive")
        if self._state is VehicleState.DISCONNECTED or self._armed or self._flying:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "simulation idle advance requires a connected, disarmed ground vehicle",
            )
        await self._elapse(duration_s)

    async def reset_pose(self) -> None:
        """Return a safely disconnected simulator to its configured home pose."""

        self._restore_pose_and_dynamics(self.battery_percent)
        await self._publish(bypass_transport_loss=True)

    async def set_battery_level(self, battery_percent: float) -> None:
        """Set simulated battery charge without changing the current pose."""

        self.physics.set_battery_percent(battery_percent)
        self._sync_physics_state()
        if (
            not self._armed
            and not self._flying
            and self._state
            in {
                VehicleState.LANDING,
                VehicleState.ABORTING,
                VehicleState.FAULT,
                VehicleState.EMERGENCY,
            }
        ):
            self._state = VehicleState.READY
        await self._publish(bypass_transport_loss=True)

    def _restore_pose_and_dynamics(self, battery_percent: float) -> None:
        self._state = VehicleState.DISCONNECTED
        self._armed = False
        self._flying = False
        self.physics.reset(
            self._initial_position,
            self._initial_yaw,
            battery_percent,
            initial_roll_rad=self.config.disturbance.initial_roll_rad,
            initial_pitch_rad=self.config.disturbance.initial_pitch_rad,
            initial_velocity_m_s=self.config.disturbance.initial_velocity_m_s,
        )
        self._position = self.physics.state.position_m
        self._estimator_drift = Vector3()
        self._estimated_position = Vector3(
            x=self._initial_position.x + self.config.position_bias_m.x,
            y=self._initial_position.y + self.config.position_bias_m.y,
            z=max(0.0, self._initial_position.z + self.config.position_bias_m.z),
        )
        self._estimator_nominal_position = self._initial_position
        self._velocity = self.physics.state.velocity_m_s
        self._estimated_velocity = self.physics.state.velocity_m_s
        self._acceleration = self.physics.state.acceleration_world_m_s2
        self._estimated_attitude = self.physics.state.attitude.euler()
        self._estimated_angular_velocity = self.physics.state.angular_velocity_body_rad_s
        self._estimator_history: deque[tuple[float, Vector3, Vector3, EulerAttitude, Vector3]] = (
            deque()
        )
        self._yaw_rad = self._estimated_attitude.yaw_rad
        self._yaw_rate_rad_s = self.physics.state.angular_velocity_body_rad_s.z
        self._battery_percent = self.physics.state.battery_state_of_charge * 100.0
        self._force_impulse_applied = False
        acceleration_body, angular_velocity_body = self._truth_imu_vectors()
        self._imu_model.reset(
            now_s=self.clock.now_s,
            acceleration_body_m_s2=acceleration_body,
            angular_velocity_body_rad_s=angular_velocity_body,
        )
        self._reset_sampled_observations()

    async def bind_run(self, binding: MissionRunBinding) -> None:
        current = self._binding
        if current is not None and current.mission_run_id == binding.mission_run_id:
            if current != binding:
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "same-run authority changes require an explicit fleet transition",
                )
            return
        if (
            self._state not in {VehicleState.DISCONNECTED, VehicleState.READY}
            or self._armed
            or self._flying
        ):
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "a new mission run can bind only while the simulator is safe and idle",
            )
        self._binding = binding
        self._authority_transition_sequence = 0
        self._authority_transition_receipts.clear()

    @property
    def authority_transition_receipts(
        self,
    ) -> tuple[FleetAuthorityTransitionReceipt, ...]:
        return tuple(self._authority_transition_receipts)

    async def transition_fleet_authority(
        self,
        transition: FleetAuthorityTransition,
    ) -> FleetAuthorityTransitionReceipt:
        binding = self._binding
        if binding is None or binding.fleet_session_id is None:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "simulator has no fleet-bound mission authority to transition",
            )
        if self._state in {VehicleState.DISCONNECTED, VehicleState.EMERGENCY}:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "fleet authority cannot transition while the simulator is unavailable",
            )
        actual_identity = (
            self.identity.vehicle_id,
            binding.mission_run_id,
            binding.fleet_session_id,
            binding.fleet_run_id,
            binding.deployment_sha256,
        )
        requested_identity = (
            transition.vehicle_id,
            transition.mission_run_id,
            transition.fleet_session_id,
            transition.fleet_run_id,
            transition.deployment_sha256,
        )
        if requested_identity != actual_identity:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "fleet authority transition identity does not match the bound run",
            )
        if (
            binding.task_id,
            binding.task_lease_generation,
        ) != (
            transition.expected_task_id,
            transition.expected_task_lease_generation,
        ):
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "fleet authority transition does not own the current task lease",
            )
        expected_sequence = self._authority_transition_sequence + 1
        if transition.sequence != expected_sequence:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "fleet authority transition sequence is not the next expected value",
                details={"expected": expected_sequence, "actual": transition.sequence},
            )
        next_binding = binding.model_copy(
            update={
                "task_id": transition.next_task_id,
                "task_lease_generation": transition.next_task_lease_generation,
            }
        )
        receipt = FleetAuthorityTransitionReceipt(
            transition_id=transition.transition_id,
            sequence=transition.sequence,
            vehicle_id=self.identity.vehicle_id,
            mission_run_id=binding.mission_run_id,
            fleet_session_id=binding.fleet_session_id,
            fleet_run_id=transition.fleet_run_id,
            deployment_sha256=transition.deployment_sha256,
            previous_task_id=transition.expected_task_id,
            previous_task_lease_generation=transition.expected_task_lease_generation,
            current_task_id=transition.next_task_id,
            current_task_lease_generation=transition.next_task_lease_generation,
            reason_code=transition.reason_code,
            authorization_sha256=transition.authorization_sha256,
            previous_binding_sha256=canonical_sha256(binding),
            current_binding_sha256=canonical_sha256(next_binding),
            transition_sha256=transition.sha256,
        )
        self._binding = next_binding
        self._authority_transition_sequence = transition.sequence
        self._authority_transition_receipts.append(receipt)
        return receipt

    async def connect(self) -> None:
        if self._state is not VehicleState.DISCONNECTED:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle is already connected")
        self._state = VehicleState.CONNECTING
        await self._elapse(self.config.command_latency_s)
        self._state = VehicleState.READY
        await self._publish()

    async def disconnect(self) -> None:
        self._armed = False
        self._flying = False
        self._cut_motors()
        self._state = VehicleState.DISCONNECTED
        await self._publish()

    async def execute(self, command: CommandEnvelope) -> CommandAcknowledgement:
        if command.vehicle_id != self.identity.vehicle_id:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "command target does not match simulated vehicle",
                details={"expected": self.identity.vehicle_id, "actual": command.vehicle_id},
            )
        self._validate_run_binding(command)
        if self.faults.active(FaultType.COMMAND_DROP, self.clock.now_s) or (
            self._random.random() < self.config.packet_loss_probability
        ):
            raise CrazySwarmError(ErrorCode.COMMAND_DROPPED, "simulated command was dropped")

        await self._elapse(self.config.command_latency_s)
        received_at_s = self.clock.now_s
        payload = command.payload
        if isinstance(payload, ConnectCommand):
            await self.connect()
        elif isinstance(payload, DisconnectCommand):
            await self.disconnect()
        elif isinstance(payload, ArmCommand):
            self._require_state(VehicleState.READY)
            self._armed = True
            await self._publish()
        elif isinstance(payload, DisarmCommand):
            if self._flying:
                raise CrazySwarmError(ErrorCode.INVALID_STATE, "cannot disarm while flying")
            self._armed = False
            await self._publish()
        elif isinstance(payload, TakeoffCommand):
            await self._takeoff(payload)
        elif isinstance(payload, HoverCommand):
            self._require_state(VehicleState.FLYING)
            await self._hold(payload.duration_s)
        elif isinstance(payload, MoveRelativeCommand):
            await self._move_relative(payload)
        elif isinstance(payload, ExecuteTrajectoryCommand):
            while self.faults.active(FaultType.TRAJECTORY_TIMEOUT, self.clock.now_s):
                await asyncio.sleep(self.config.fixed_step_s)
                await self.clock.advance(self.config.fixed_step_s)
                await self._publish()
            await self._execute_trajectory(payload)
        elif isinstance(payload, StopAndHoldCommand):
            self._require_state(VehicleState.FLYING)
            await self._hold(self.config.fixed_step_s)
        elif isinstance(payload, LandCommand):
            await self._land(
                payload.duration_s,
                payload.target_height_m,
                payload.target_position_m,
                payload.goal_region,
            )
        elif isinstance(payload, AbortCommand):
            await self._abort(payload.reason)
        elif isinstance(payload, EmergencyStopCommand):
            await self._emergency_stop(payload.reason)
        else:  # pragma: no cover - discriminated contract keeps this unreachable
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "unsupported command")

        await self._elapse(self.config.acknowledgement_latency_s)
        return CommandAcknowledgement(
            vehicle_id=self.identity.vehicle_id,
            command_id=command.command_id,
            status=AcknowledgementStatus.COMPLETED,
            received_at_monotonic_s=received_at_s,
            completed_at_monotonic_s=self.clock.now_s,
            message=f"{payload.kind.value} completed",
        )

    def _validate_run_binding(self, command: CommandEnvelope) -> None:
        binding = self._binding
        if binding is None:
            return
        if command.mission_run_id != binding.mission_run_id:
            unbound_safety_override = (
                command.mission_run_id is None
                and command.fleet is None
                and (
                    (
                        command.source is CommandSource.SUPERVISOR
                        and isinstance(
                            command.payload,
                            (
                                StopAndHoldCommand,
                                LandCommand,
                                AbortCommand,
                                EmergencyStopCommand,
                            ),
                        )
                    )
                    or (
                        command.source is CommandSource.MISSION
                        and isinstance(command.payload, DisarmCommand)
                    )
                )
            )
            if unbound_safety_override:
                return
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "simulator mission run mismatch")
        expected_fleet = binding.fleet_session_id
        if expected_fleet is None:
            if command.fleet is not None:
                raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "unexpected fleet binding")
            return
        fleet = command.fleet
        if fleet is None or (
            fleet.fleet_session_id,
            fleet.fleet_run_id,
            fleet.deployment_sha256,
            fleet.task_id,
            fleet.task_lease_generation,
        ) != (
            binding.fleet_session_id,
            binding.fleet_run_id,
            binding.deployment_sha256,
            binding.task_id,
            binding.task_lease_generation,
        ):
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "simulator fleet run mismatch")

    async def snapshot(self) -> TelemetryEnvelope:
        if self.faults.active(FaultType.STALE_TELEMETRY, self.clock.now_s):
            raise CrazySwarmError(
                ErrorCode.TELEMETRY_STALE,
                "simulated telemetry source is not publishing",
            )
        return self._last_published

    def telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]:
        return self._telemetry_stream()

    async def _telemetry_stream(self) -> AsyncIterator[TelemetryEnvelope]:
        queue: asyncio.Queue[TelemetryEnvelope] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    def _require_state(self, expected: VehicleState) -> None:
        if self._state is not expected:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                f"command requires {expected.value}, current state is {self._state.value}",
            )

    async def _takeoff(self, command: TakeoffCommand) -> None:
        self._require_state(VehicleState.READY)
        if not self._armed:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle must be armed before takeoff")
        control_position = self._control_position()
        target = Vector3(x=control_position.x, y=control_position.y, z=command.height_m)
        self._flying = True
        await self._move_to(target, self._yaw_rad, command.duration_s, VehicleState.TAKING_OFF)
        self._state = VehicleState.FLYING
        await self._publish()

    async def _move_relative(self, command: MoveRelativeCommand) -> None:
        self._require_state(VehicleState.FLYING)
        control_position = self._control_position()
        control_yaw = self._control_yaw()
        if command.frame is CoordinateFrame.BODY:
            cos_yaw = math.cos(control_yaw)
            sin_yaw = math.sin(control_yaw)
            dx = command.x_m * cos_yaw - command.y_m * sin_yaw
            dy = command.x_m * sin_yaw + command.y_m * cos_yaw
        else:
            dx, dy = command.x_m, command.y_m
        target = Vector3(
            x=control_position.x + dx,
            y=control_position.y + dy,
            z=control_position.z + command.z_m,
        )
        await self._move_to(
            target,
            control_yaw + command.yaw_rad,
            command.duration_s,
            VehicleState.FLYING,
        )

    async def _execute_trajectory(self, command: ExecuteTrajectoryCommand) -> None:
        self._require_state(VehicleState.FLYING)
        trajectory = command.trajectory
        if trajectory.vehicle_id != self.identity.vehicle_id:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "trajectory vehicle identity does not match simulated vehicle",
            )
        self._validate_absolute_trajectory(command)
        self._state = VehicleState.FLYING
        elapsed_s = 0.0
        segment_index = 0
        while elapsed_s < trajectory.duration_s:
            dt = min(self.config.fixed_step_s, trajectory.duration_s - elapsed_s)
            sample_time_s = elapsed_s + dt
            while (
                segment_index + 1 < len(trajectory.points) - 1
                and sample_time_s > trajectory.points[segment_index + 1].time_from_start_s
            ):
                segment_index += 1
            setpoint = sample_trajectory_segment(
                trajectory.points[segment_index],
                trajectory.points[segment_index + 1],
                sample_time_s,
            )
            motor_commands = self._motor_commands(
                target_position_m=setpoint.position_m,
                target_velocity_m_s=setpoint.velocity_m_s,
                target_acceleration_world_m_s2=setpoint.acceleration_m_s2,
                target_yaw_rad=setpoint.yaw_rad,
                target_yaw_rate_rad_s=setpoint.yaw_rate_rad_s,
            )
            await self._step(dt, motor_commands=motor_commands)
            elapsed_s = sample_time_s

        terminal = trajectory.points[-1]
        settle_elapsed_s = 0.0
        settle_limit_s = max(2.0, 4.0 * self.config.estimator_latency_s)
        while settle_elapsed_s < settle_limit_s:
            position_error = _vector_length(
                Vector3(
                    x=terminal.position_m.x - self._control_position().x,
                    y=terminal.position_m.y - self._control_position().y,
                    z=terminal.position_m.z - self._control_position().z,
                )
            )
            velocity = _vector_length(self._estimated_velocity)
            if (
                position_error <= trajectory.completion_position_tolerance_m
                and velocity <= trajectory.completion_velocity_tolerance_m_s
            ):
                await self._publish()
                return
            dt = min(self.config.fixed_step_s, settle_limit_s - settle_elapsed_s)
            motor_commands = self._motor_commands(
                target_position_m=terminal.position_m,
                target_velocity_m_s=Vector3(),
                target_acceleration_world_m_s2=Vector3(),
                target_yaw_rad=terminal.yaw_rad,
            )
            await self._step(dt, motor_commands=motor_commands)
            settle_elapsed_s += dt
        raise CrazySwarmError(
            ErrorCode.COMMAND_TIMEOUT,
            "trajectory did not satisfy its tracking completion tolerance",
            details={
                "trajectory_sha256": command.trajectory_sha256,
                "completion_position_tolerance_m": (trajectory.completion_position_tolerance_m),
                "completion_velocity_tolerance_m_s": (trajectory.completion_velocity_tolerance_m_s),
            },
        )

    def _validate_absolute_trajectory(self, command: ExecuteTrajectoryCommand) -> None:
        trajectory = command.trajectory
        start_error = _vector_length(
            Vector3(
                x=trajectory.points[0].position_m.x - self._control_position().x,
                y=trajectory.points[0].position_m.y - self._control_position().y,
                z=trajectory.points[0].position_m.z - self._control_position().z,
            )
        )
        if start_error > max(0.15, trajectory.completion_position_tolerance_m * 2.0):
            raise CrazySwarmError(
                ErrorCode.LOCALIZATION_INVALID,
                "trajectory start is inconsistent with current position",
                details={"start_error_m": start_error},
            )
        for previous, current in zip(
            trajectory.points,
            trajectory.points[1:],
            strict=False,
        ):
            duration_s = current.time_from_start_s - previous.time_from_start_s
            for sample_index in range(21):
                sample_time_s = previous.time_from_start_s + duration_s * sample_index / 20.0
                setpoint = sample_trajectory_segment(
                    previous,
                    current,
                    sample_time_s,
                )
                if not self.world.contains(setpoint.position_m):
                    raise CrazySwarmError(
                        ErrorCode.GEOFENCE_BREACH,
                        "trajectory spline leaves the simulated world",
                    )
                if (
                    math.hypot(setpoint.velocity_m_s.x, setpoint.velocity_m_s.y)
                    > self.config.max_horizontal_speed_m_s
                ):
                    raise CrazySwarmError(
                        ErrorCode.INVALID_COMMAND,
                        "trajectory horizontal speed exceeds simulator limit",
                    )
                if abs(setpoint.velocity_m_s.z) > self.config.max_vertical_speed_m_s:
                    observed_vertical_speed_m_s = abs(setpoint.velocity_m_s.z)
                    raise CrazySwarmError(
                        ErrorCode.INVALID_COMMAND,
                        (
                            f"trajectory vertical speed {observed_vertical_speed_m_s:.6f} m/s "
                            "exceeds simulator limit "
                            f"{self.config.max_vertical_speed_m_s:.6f} m/s"
                        ),
                        details={
                            "observed_vertical_speed_m_s": observed_vertical_speed_m_s,
                            "maximum_vertical_speed_m_s": self.config.max_vertical_speed_m_s,
                            "segment_start_sequence": previous.sequence,
                            "segment_end_sequence": current.sequence,
                            "sample_time_s": sample_time_s,
                        },
                    )
                if _vector_length(setpoint.acceleration_m_s2) > self.config.max_acceleration_m_s2:
                    raise CrazySwarmError(
                        ErrorCode.INVALID_COMMAND,
                        "trajectory acceleration exceeds simulator limit",
                    )
                if abs(setpoint.yaw_rate_rad_s) > self.config.max_yaw_rate_rad_s:
                    raise CrazySwarmError(
                        ErrorCode.INVALID_COMMAND,
                        "trajectory yaw rate exceeds simulator limit",
                    )

    async def _land(
        self,
        duration_s: float,
        target_height_m: float = 0.0,
        target_position_m: Vector3 | None = None,
        goal_region: LandingGoalRegion | None = None,
    ) -> None:
        if self._state not in {
            VehicleState.FLYING,
            VehicleState.TAKING_OFF,
            VehicleState.RETURNING,
            VehicleState.ABORTING,
        }:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle is not in a landable state")
        control_position = self._control_position()
        target = target_position_m or Vector3(
            x=control_position.x,
            y=control_position.y,
            z=target_height_m,
        )
        self.last_landing_evidence = None
        self._landing_contact_source_timestamp_s = None
        self._landing_pre_contact_vertical_speed_m_s = None
        alignment_duration_s = max(
            0.5,
            1.5
            * math.hypot(target.x - control_position.x, target.y - control_position.y)
            / self.config.max_horizontal_speed_m_s,
        )
        await self._move_to(
            Vector3(x=target.x, y=target.y, z=control_position.z),
            self._control_yaw(),
            alignment_duration_s,
            VehicleState.LANDING,
        )
        alignment_completed_source_timestamp_s = self.clock.now_s
        await self._move_to(target, self._control_yaw(), duration_s, VehicleState.LANDING)

        # The time-profile command can finish while the modeled rigid body still has
        # a small tracking residual above the floor. Retain controller authority until
        # actual simulated contact and a bounded low-speed settle are observed.
        settle_limit_s = 2.0
        contact_source_timestamp_s = self._landing_contact_source_timestamp_s
        settled_s = (
            max(0.0, self.clock.now_s - contact_source_timestamp_s)
            if contact_source_timestamp_s is not None
            else 0.0
        )
        elapsed_s = 0.0
        while elapsed_s < settle_limit_s:
            position = self.physics.state.position_m
            speed = _vector_length(self.physics.state.velocity_m_s)
            in_contact = position.z <= 0.001
            if in_contact:
                if contact_source_timestamp_s is None:
                    contact_source_timestamp_s = (
                        self._landing_contact_source_timestamp_s or self.clock.now_s
                    )
                settled_s = settled_s + self.config.fixed_step_s if speed <= 0.05 else 0.0
                if settled_s >= 0.10:
                    break
            else:
                settled_s = 0.0
            motor_commands = self._motor_commands(
                target_position_m=target,
                target_velocity_m_s=Vector3(),
                target_acceleration_world_m_s2=Vector3(),
                target_yaw_rad=self._control_yaw(),
            )
            await self._step(self.config.fixed_step_s, motor_commands=motor_commands)
            elapsed_s += self.config.fixed_step_s
        if contact_source_timestamp_s is None or settled_s < 0.10:
            raise CrazySwarmError(
                ErrorCode.COMMAND_TIMEOUT,
                "landing did not establish stable simulated ground contact",
            )

        pre_contact_vertical_speed_m_s = self._landing_pre_contact_vertical_speed_m_s
        self._armed = False
        self._cut_motors()
        disarmed_source_timestamp_s = self.clock.now_s
        self._flying = False
        self._state = VehicleState.READY
        self.last_landing_evidence = {
            "target_position_m": target.model_dump(mode="json"),
            "landing_goal_id": goal_region.goal_id if goal_region is not None else None,
            "alignment_duration_s": alignment_duration_s,
            "alignment_completed_source_timestamp_s": (
                alignment_completed_source_timestamp_s
            ),
            "pre_contact_vertical_speed_m_s": pre_contact_vertical_speed_m_s,
            "contact_source_timestamp_s": contact_source_timestamp_s,
            "disarmed_source_timestamp_s": disarmed_source_timestamp_s,
            "post_contact_settling_s": max(
                0.0, disarmed_source_timestamp_s - contact_source_timestamp_s
            ),
            "motors_cut_after_contact": disarmed_source_timestamp_s
            >= contact_source_timestamp_s,
        }
        await self._publish()

    async def _abort(self, reason: str) -> None:
        if not self._flying:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "abort requires an airborne vehicle")
        self._state = VehicleState.ABORTING
        self._fault_messages.append(f"ABORT:{reason}")
        await self._publish()
        duration = max(1.0, self._position.z / self.config.max_vertical_speed_m_s)
        await self._land(duration)

    async def _emergency_stop(self, reason: str) -> None:
        self._armed = False
        self._flying = False
        self._cut_motors()
        self._state = VehicleState.EMERGENCY
        self._fault_messages.append(f"EMERGENCY_STOP:{reason}")
        elapsed = 0.0
        while self.physics.state.position_m.z > 0.001 and elapsed < 2.0:
            await self._step(self.config.fixed_step_s, motor_commands=(0.0, 0.0, 0.0, 0.0))
            elapsed += self.config.fixed_step_s
        await self._publish()

    async def _hold(self, duration_s: float) -> None:
        target = self._control_position()
        target_yaw = self._control_yaw()
        steps = max(1, math.ceil(duration_s / self.config.fixed_step_s))
        for index in range(steps):
            dt = min(self.config.fixed_step_s, duration_s - index * self.config.fixed_step_s)
            if dt <= 0.0:
                break
            motor_commands = self._motor_commands(
                target_position_m=target,
                target_velocity_m_s=Vector3(),
                target_acceleration_world_m_s2=Vector3(),
                target_yaw_rad=target_yaw,
            )
            await self._step(dt, motor_commands=motor_commands)

    async def _move_to(
        self,
        target: Vector3,
        target_yaw_rad: float,
        duration_s: float,
        state: VehicleState,
    ) -> None:
        if not self.world.contains(target):
            raise CrazySwarmError(ErrorCode.GEOFENCE_BREACH, "target is outside the indoor world")
        start = self._control_position()
        start_yaw = self._control_yaw()
        delta = Vector3(x=target.x - start.x, y=target.y - start.y, z=target.z - start.z)
        horizontal_distance = math.hypot(delta.x, delta.y)
        self._validate_motion_limits(
            horizontal_distance, abs(delta.z), abs(target_yaw_rad - start_yaw), duration_s
        )

        self._state = state
        steps = max(1, math.ceil(duration_s / self.config.fixed_step_s))
        for index in range(1, steps + 1):
            elapsed = min(index * self.config.fixed_step_s, duration_s)
            u = elapsed / duration_s
            blend = 3.0 * u**2 - 2.0 * u**3
            desired_position = Vector3(
                x=start.x + delta.x * blend,
                y=start.y + delta.y * blend,
                z=start.z + delta.z * blend,
            )
            dt = elapsed - min((index - 1) * self.config.fixed_step_s, duration_s)
            blend_rate = 6.0 * u * (1.0 - u) / duration_s
            blend_acceleration = (6.0 - 12.0 * u) / duration_s**2
            desired_velocity = Vector3(
                x=delta.x * blend_rate,
                y=delta.y * blend_rate,
                z=delta.z * blend_rate,
            )
            desired_acceleration = Vector3(
                x=delta.x * blend_acceleration,
                y=delta.y * blend_acceleration,
                z=delta.z * blend_acceleration,
            )
            desired_yaw = start_yaw + (target_yaw_rad - start_yaw) * blend
            desired_yaw_rate = blend_rate * (target_yaw_rad - start_yaw)
            motor_commands = self._motor_commands(
                target_position_m=desired_position,
                target_velocity_m_s=desired_velocity,
                target_acceleration_world_m_s2=desired_acceleration,
                target_yaw_rad=desired_yaw,
                target_yaw_rate_rad_s=desired_yaw_rate,
            )
            await self._step(dt, motor_commands=motor_commands)

    def _validate_motion_limits(
        self,
        horizontal_distance_m: float,
        vertical_distance_m: float,
        yaw_distance_rad: float,
        duration_s: float,
    ) -> None:
        peak_horizontal_speed = 1.5 * horizontal_distance_m / duration_s
        peak_vertical_speed = 1.5 * vertical_distance_m / duration_s
        peak_acceleration = (
            6.0
            * _vector_length(Vector3(x=horizontal_distance_m, z=vertical_distance_m))
            / duration_s**2
        )
        peak_yaw_rate = 1.5 * yaw_distance_rad / duration_s
        if peak_horizontal_speed > self.config.max_horizontal_speed_m_s:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "horizontal speed exceeds simulator limit"
            )
        if peak_vertical_speed > self.config.max_vertical_speed_m_s:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "vertical speed exceeds simulator limit"
            )
        if peak_acceleration > self.config.max_acceleration_m_s2:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "acceleration exceeds simulator limit")
        if peak_yaw_rate > self.config.max_yaw_rate_rad_s:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "yaw rate exceeds simulator limit")

    async def _elapse(self, duration_s: float) -> None:
        steps = max(1, math.ceil(duration_s / self.config.fixed_step_s))
        for index in range(steps):
            dt = min(self.config.fixed_step_s, duration_s - index * self.config.fixed_step_s)
            if dt <= 0.0:
                break
            await self._step(dt)

    async def _step(
        self,
        dt: float,
        *,
        motor_commands: tuple[float, float, float, float] | None = None,
    ) -> None:
        await self.clock.advance(dt)
        if self.faults.active(FaultType.LOW_BATTERY, self.clock.now_s):
            forced_percent = max(0.0, self.config.critical_battery_percent * 0.5)
            self.physics.set_battery_percent(
                min(
                    self.physics.state.battery_state_of_charge * 100.0,
                    forced_percent,
                )
            )
        terminal_faults = (
            (
                FaultType.GEOFENCE_BREACH,
                ErrorCode.GEOFENCE_BREACH,
                "GEOFENCE_BREACH_INJECTED",
                "injected geofence termination",
            ),
            (
                FaultType.COLLISION,
                ErrorCode.GEOFENCE_BREACH,
                "COLLISION_CONFIGURED_TERMINATION",
                "injected configured collision termination",
            ),
            (
                FaultType.NUMERICAL_FAILURE,
                ErrorCode.INTERNAL_ERROR,
                "NUMERICAL_FAILURE_INJECTED",
                "injected numerical termination",
            ),
        )
        for fault, code, receipt, message in terminal_faults:
            if self.faults.active(fault, self.clock.now_s):
                self._state = VehicleState.FAULT
                self._armed = False
                self._flying = False
                self._cut_motors()
                if receipt not in self._fault_messages:
                    self._fault_messages.append(receipt)
                await self._publish()
                raise CrazySwarmError(
                    code,
                    message,
                    details={"contact_model": "termination_only"},
                )
        if self.faults.active(FaultType.DISCONNECT, self.clock.now_s):
            self._state = VehicleState.DISCONNECTED
            self._armed = False
            self._flying = False
            self._cut_motors()
            await self._publish(bypass_transport_loss=True)
            raise CrazySwarmError(ErrorCode.LINK_LOST, "simulated link disconnected")

        previous_position = self.physics.state.position_m
        previous_velocity = self.physics.state.velocity_m_s
        configured_percent_per_s = self.config.battery_idle_drain_percent_s
        if self._flying:
            configured_percent_per_s += self.config.battery_flight_drain_percent_s
            configured_percent_per_s += self.config.battery_motion_drain_percent_m * _vector_length(
                self.physics.state.velocity_m_s
            )
        configured_current = (
            self.config.physics.battery_capacity_ah * 3600.0 * configured_percent_per_s / 100.0
        )
        selected_motor_commands = motor_commands or tuple(
            motor.command for motor in self.physics.state.motors
        )
        actuator_health_scales = self.faults.actuator_health_scales(self.clock.now_s)
        for index, health_scale in enumerate(actuator_health_scales, start=1):
            if health_scale >= 1.0:
                continue
            receipt = (
                f"ACTUATOR_LOSS_M{index}" if health_scale == 0.0 else f"ACTUATOR_DEGRADED_M{index}"
            )
            if receipt not in self._fault_messages:
                self._fault_messages.append(receipt)
        impulse_at_s = self.config.disturbance.force_impulse_at_s
        if (
            not self._force_impulse_applied
            and impulse_at_s is not None
            and self.clock.now_s >= impulse_at_s
        ):
            self.physics.apply_force_impulse(self.config.disturbance.force_impulse_n_s)
            self._force_impulse_applied = True
        self.physics.step(
            selected_motor_commands,  # type: ignore[arg-type]
            dt,
            additional_current_a=configured_current,
            actuator_health_scales=actuator_health_scales,
        )
        if (
            self._state is VehicleState.LANDING
            and self._landing_contact_source_timestamp_s is None
            and previous_position.z > 0.001
            and self.physics.state.position_m.z <= 0.001
        ):
            self._landing_contact_source_timestamp_s = self.clock.now_s
            self._landing_pre_contact_vertical_speed_m_s = (
                abs(previous_velocity.z) if previous_velocity.z < 0.0 else 0.0
            )
        if self.physics.state.battery_cutoff_active:
            cutoff_reason = self.physics.state.battery_cutoff_reason
            self._sync_physics_state()
            self._state = VehicleState.FAULT
            self._armed = False
            self._flying = self.physics.state.position_m.z > 0.001
            self._cut_motors()
            if "BATTERY_CUTOFF" not in self._fault_messages:
                self._fault_messages.append("BATTERY_CUTOFF")
            await self._publish(bypass_transport_loss=True)
            await self._settle_after_battery_cutoff(cutoff_reason)
            raise CrazySwarmError(
                ErrorCode.CRITICAL_BATTERY,
                "modeled battery reached authoritative cutoff",
                details={"cutoff_reason": (None if cutoff_reason is None else cutoff_reason.value)},
            )
        if not self.world.contains(self.physics.state.position_m):
            self.physics.state.position_m = previous_position
            self.physics.state.velocity_m_s = Vector3()
            self._state = VehicleState.FAULT
            self._armed = False
            self._flying = False
            self._cut_motors()
            self._fault_messages.append("COLLISION_CONFIGURED_TERMINATION")
            self._sync_physics_state()
            await self._publish()
            raise CrazySwarmError(
                ErrorCode.GEOFENCE_BREACH,
                "simulated rigid body collided with configured geometry",
                details={"contact_model": "termination_only"},
            )
        self._sync_physics_state()
        self._update_estimator(dt)
        await self._publish()

    async def _settle_after_battery_cutoff(
        self,
        cutoff_reason: BatteryCutoffReason | None,
    ) -> None:
        """Advance an airborne power loss through ground impact before going terminal."""

        zero_commands = (0.0, 0.0, 0.0, 0.0)
        initial_height_m = max(0.0, self.physics.state.position_m.z)
        fall_limit_s = max(
            2.0,
            4.0 * math.sqrt(2.0 * initial_height_m / self.config.physics.gravity_m_s2) + 1.0,
        )
        elapsed_s = 0.0
        while self.physics.state.position_m.z > 0.001 and elapsed_s < fall_limit_s:
            dt = min(self.config.fixed_step_s, fall_limit_s - elapsed_s)
            await self.clock.advance(dt)
            self.physics.step(zero_commands, dt)
            self.physics.state.battery_cutoff_active = True
            self.physics.state.battery_cutoff_reason = cutoff_reason
            self._cut_motors()
            self._sync_physics_state()
            self._update_estimator(dt)
            self._flying = self.physics.state.position_m.z > 0.001
            await self._publish()
            elapsed_s += dt

        if self.physics.state.position_m.z <= 0.001:
            self.physics.state.position_m = self.physics.state.position_m.model_copy(
                update={"z": 0.0}
            )
            self.physics.state.velocity_m_s = Vector3()
            self.physics.state.acceleration_world_m_s2 = Vector3()
            self._flying = False
            estimator_settle_steps = max(
                1,
                math.ceil(self.config.estimator_latency_s / self.config.fixed_step_s) + 1,
            )
            for _ in range(estimator_settle_steps):
                await self.clock.advance(self.config.fixed_step_s)
                self.physics.step(zero_commands, self.config.fixed_step_s)
                self.physics.state.battery_cutoff_active = True
                self.physics.state.battery_cutoff_reason = cutoff_reason
                self._cut_motors()
                self._sync_physics_state()
                self._update_estimator(self.config.fixed_step_s)
                await self._publish()
        else:
            if "BATTERY_CUTOFF_SETTLE_TIMEOUT" not in self._fault_messages:
                self._fault_messages.append("BATTERY_CUTOFF_SETTLE_TIMEOUT")
            self._flying = True
        await self._publish(bypass_transport_loss=True)

    def _update_estimator(self, dt: float) -> None:
        if self.faults.active(FaultType.SENSOR_FAILURE, self.clock.now_s):
            return
        state = self.physics.state
        acceleration_body, angular_velocity_body = self._truth_imu_vectors()
        self._imu_model.update(
            now_s=self.clock.now_s,
            acceleration_body_m_s2=acceleration_body,
            angular_velocity_body_rad_s=angular_velocity_body,
        )
        is_physical_v2 = self.config.physics.powertrain_model is PowertrainModel.BATTERY_COUPLED_V2
        if is_physical_v2:
            self._update_sampled_observations()
            estimated_rotation = Quaternion.from_euler(
                self._estimated_attitude.roll_rad,
                self._estimated_attitude.pitch_rad,
                self._estimated_attitude.yaw_rad,
            ).integrate(self._imu_model.reading.angular_velocity_body_rad_s, dt)
            observed_attitude = estimated_rotation.euler()
            observed_velocity = self._estimated_velocity
            flow_velocity = self._held_flow.velocity_body_m_s
            if flow_velocity is not None:
                flow_world = estimated_rotation.rotate_body_to_world(flow_velocity)
                observed_velocity = Vector3(
                    x=flow_world.x,
                    y=flow_world.y,
                    z=observed_velocity.z,
                )
            ground_distance_m = self._held_flow.ground_distance_m
            if ground_distance_m is None:
                down_status = self._held_ranges.statuses.get("down")
                if down_status is RangeStatus.VALID:
                    ground_distance_m = self._held_ranges.down_m
            nominal_z = self._estimator_nominal_position.z
            if ground_distance_m is not None:
                down_world = estimated_rotation.rotate_body_to_world(Vector3(z=-1.0))
                nominal_z = max(0.0, ground_distance_m * max(0.0, -down_world.z))
                observed_velocity = Vector3(
                    x=observed_velocity.x,
                    y=observed_velocity.y,
                    z=(nominal_z - self._estimator_nominal_position.z) / dt,
                )
            self._estimator_nominal_position = Vector3(
                x=self._estimator_nominal_position.x + observed_velocity.x * dt,
                y=self._estimator_nominal_position.y + observed_velocity.y * dt,
                z=nominal_z,
            )
            estimator_sample = (
                self.clock.now_s,
                self._estimator_nominal_position,
                observed_velocity,
                observed_attitude,
                self._imu_model.reading.angular_velocity_body_rad_s,
            )
        else:
            estimator_sample = (
                self.clock.now_s,
                state.position_m,
                state.velocity_m_s,
                state.attitude.euler(),
                state.angular_velocity_body_rad_s,
            )
        self._estimator_history.append(estimator_sample)
        cutoff_s = self.clock.now_s - self.config.estimator_latency_s
        selected = self._estimator_history[0]
        for item in self._estimator_history:
            if item[0] <= cutoff_s:
                selected = item
            else:
                break
        while len(self._estimator_history) > 2 and self._estimator_history[1][0] <= cutoff_s:
            self._estimator_history.popleft()
        _, source_position, source_velocity, source_attitude, _source_omega = selected
        drift_scale = self.config.flow_drift_std_m_sqrt_s * math.sqrt(dt)
        self._estimator_drift = Vector3(
            x=self._estimator_drift.x + self._random.gauss(0.0, drift_scale),
            y=self._estimator_drift.y + self._random.gauss(0.0, drift_scale),
            z=self._estimator_drift.z,
        )
        error = Vector3(
            x=self.config.position_bias_m.x
            + self._estimator_drift.x
            + self._random.gauss(0.0, self.config.position_noise_std_m),
            y=self.config.position_bias_m.y
            + self._estimator_drift.y
            + self._random.gauss(0.0, self.config.position_noise_std_m),
            z=self.config.position_bias_m.z
            + self._random.gauss(0.0, self.config.position_noise_std_m),
        )
        clip = self.config.estimator_error_clip_m
        if clip is not None:
            error = Vector3(
                x=max(-clip, min(clip, error.x)),
                y=max(-clip, min(clip, error.y)),
                z=max(-clip, min(clip, error.z)),
            )
        self._estimated_position = Vector3(
            x=source_position.x + error.x,
            y=source_position.y + error.y,
            z=max(0.0, source_position.z + error.z),
        )
        self._estimated_velocity = source_velocity
        self._estimated_attitude = source_attitude
        self._estimated_angular_velocity = self._imu_model.reading.angular_velocity_body_rad_s

    def _control_position(self) -> Vector3:
        if self.config.controller_profile is ControllerProfile.IDEAL_TRUTH_TEST_ONLY:
            return self.physics.state.position_m
        return self._estimated_position

    def _control_yaw(self) -> float:
        if self.config.controller_profile is ControllerProfile.IDEAL_TRUTH_TEST_ONLY:
            return self.physics.state.attitude.euler().yaw_rad
        return self._estimated_attitude.yaw_rad

    def _motor_commands(
        self,
        *,
        target_position_m: Vector3,
        target_velocity_m_s: Vector3,
        target_acceleration_world_m_s2: Vector3,
        target_yaw_rad: float,
        target_yaw_rate_rad_s: float = 0.0,
    ) -> tuple[float, float, float, float]:
        if self.config.controller_profile is ControllerProfile.IDEAL_TRUTH_TEST_ONLY:
            return self.physics.motor_commands_for_trajectory(
                target_position_m=target_position_m,
                target_velocity_m_s=target_velocity_m_s,
                target_acceleration_world_m_s2=target_acceleration_world_m_s2,
                target_yaw_rad=target_yaw_rad,
                target_yaw_rate_rad_s=target_yaw_rate_rad_s,
            )
        return self.physics.motor_commands_for_control_state(
            ControllerState(
                position_m=self._estimated_position,
                velocity_m_s=self._estimated_velocity,
                attitude=self._estimated_attitude,
                angular_velocity_body_rad_s=self._estimated_angular_velocity,
            ),
            target_position_m=target_position_m,
            target_velocity_m_s=target_velocity_m_s,
            target_acceleration_world_m_s2=target_acceleration_world_m_s2,
            target_yaw_rad=target_yaw_rad,
            target_yaw_rate_rad_s=target_yaw_rate_rad_s,
            nominal_total_mass_kg=self.config.controller_nominal_mass_kg,
            nominal_max_motor_thrust_n=self.config.controller_nominal_max_motor_thrust_n,
        )

    def _sync_physics_state(self) -> None:
        state = self.physics.state
        self._position = state.position_m
        self._velocity = state.velocity_m_s
        self._acceleration = state.acceleration_world_m_s2
        attitude = state.attitude.euler()
        self._yaw_rad = attitude.yaw_rad
        self._yaw_rate_rad_s = state.angular_velocity_body_rad_s.z
        self._battery_percent = state.battery_state_of_charge * 100.0

    def _cut_motors(self) -> None:
        for motor in self.physics.state.motors:
            motor.command = 0.0
            motor.requested_thrust_n = 0.0
            motor.applied_pwm = 0.0
            motor.motor_voltage_v = 0.0
            motor.thrust_n = 0.0
            motor.available_thrust_n = 0.0
            motor.current_a = 0.0
            motor.saturated = False

    async def _publish(self, *, bypass_transport_loss: bool = False) -> None:
        if self.faults.active(FaultType.STALE_TELEMETRY, self.clock.now_s):
            return
        if (
            not bypass_transport_loss
            and self._random.random() < self.config.packet_loss_probability
        ):
            return
        if self.config.physics.powertrain_model is PowertrainModel.LEGACY_UNCOUPLED_V1:
            # Model v1 sampled ranges once per publication. Preserve that random draw
            # ordering exactly; independent sensor clocks are a model-v2 feature.
            self._held_flow = self._sample_flow_reading(self.clock.now_s)
            self._held_ranges = self._sample_range_readings(self.clock.now_s)
        self._sequence += 1
        envelope = self._build_telemetry()
        self._last_published = envelope
        self.telemetry_history.append(envelope)
        for queue in tuple(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(envelope)

    def _build_telemetry(self) -> TelemetryEnvelope:
        sensor_failed = self.faults.active(FaultType.SENSOR_FAILURE, self.clock.now_s)
        localization_lost = self.faults.active(FaultType.LOCALIZATION_LOSS, self.clock.now_s)
        faults = list(self._fault_messages)
        if sensor_failed:
            faults.append("SENSOR_FAILURE")
        if localization_lost:
            faults.append("LOCALIZATION_LOSS")
        if self.faults.active(FaultType.RANGE_STALE, self.clock.now_s):
            faults.append("RANGE_STALE")
        if self.faults.active(FaultType.RANGE_UNAVAILABLE, self.clock.now_s):
            faults.append("RANGE_UNAVAILABLE")
        if self._battery_percent <= self.config.critical_battery_percent:
            faults.append("CRITICAL_BATTERY")
        elif self._battery_percent <= self.config.low_battery_percent:
            faults.append("LOW_BATTERY")

        return TelemetryEnvelope(
            vehicle_id=self.identity.vehicle_id,
            sequence=self._sequence,
            source_timestamp_s=self.clock.now_s,
            received_timestamp_s=self.clock.now_s + self.config.acknowledgement_latency_s,
            simulation_timestamp_s=self.clock.now_s,
            source_clock_id=f"fast-sim-{self.identity.vehicle_id}",
            source_clock_epoch=self._source_clock_epoch,
            telemetry=VehicleTelemetry(
                state=self._state,
                armed=self._armed,
                flying=self._flying,
                position_m=None if localization_lost else self._estimated_position,
                ground_truth_position_m=self._position,
                velocity_m_s=self._estimated_velocity,
                attitude=self._estimated_attitude,
                frame=CoordinateFrame.HOME,
                position_is_estimate=None if localization_lost else True,
                localization_source=(
                    LocalizationSource.NONE if localization_lost else LocalizationSource.SIMULATED
                ),
                localization_quality_percent=(
                    None if localization_lost else self._localization_quality_percent()
                ),
                battery_percent=self._battery_percent,
                battery_open_circuit_voltage_v=self.physics.state.battery_open_circuit_voltage_v,
                battery_voltage_v=self.physics.state.battery_voltage_v,
                battery_current_a=self.physics.state.battery_current_a,
                battery_cutoff_active=self.physics.state.battery_cutoff_active,
                battery_cutoff_reason=(
                    None
                    if self.physics.state.battery_cutoff_reason is None
                    else self.physics.state.battery_cutoff_reason.value
                ),
                powertrain_current_limited=self.physics.state.powertrain_current_limited,
                transport=TransportReading(
                    kind="modeled_transport",
                    source_class="SIMULATED_MODEL",
                    delivery_quality_percent=100.0 * (1.0 - self.config.packet_loss_probability),
                    latency_ms=(
                        self.config.command_latency_s + self.config.acknowledgement_latency_s
                    )
                    * 1000.0,
                    packet_loss_percent=self.config.packet_loss_probability * 100.0,
                ),
                capabilities=self._capabilities,
                imu=None if sensor_failed else self._imu_reading(),
                flow=None if sensor_failed else self._flow_reading(),
                ranges=None if sensor_failed else self._range_readings(),
                motors=self._motor_telemetry(),
                faults=tuple(faults),
            ),
        )

    def _imu_reading(self) -> ImuReading:
        reading = self._imu_model.reading
        return ImuReading(
            acceleration_body_m_s2=reading.acceleration_body_m_s2,
            angular_velocity_body_rad_s=reading.angular_velocity_body_rad_s,
            source_timestamp_s=reading.source_timestamp_s,
        )

    def _truth_imu_vectors(self) -> tuple[Vector3, Vector3]:
        body_acceleration = self.physics.state.attitude.rotate_world_to_body(
            Vector3(
                x=self._acceleration.x,
                y=self._acceleration.y,
                z=self._acceleration.z + self.config.physics.gravity_m_s2,
            )
        )
        return body_acceleration, self.physics.state.angular_velocity_body_rad_s

    def _reset_sampled_observations(self) -> None:
        now_s = self.clock.now_s
        initial_flow = self._sample_flow_reading(now_s)
        initial_ranges = self._sample_range_readings(now_s)
        self._flow_history: deque[FlowReading] = deque((initial_flow,))
        self._range_history: deque[RangeReadings] = deque((initial_ranges,))
        self._held_flow = initial_flow
        self._held_ranges = initial_ranges
        self._next_flow_sample_s = now_s + 1.0 / self.config.flow.sample_rate_hz
        self._next_range_sample_s = now_s + 1.0 / self.config.range_sensor.sample_rate_hz

    def _update_sampled_observations(self) -> None:
        now_s = self.clock.now_s
        flow_period_s = 1.0 / self.config.flow.sample_rate_hz
        if now_s + 1e-12 >= self._next_flow_sample_s:
            self._flow_history.append(self._sample_flow_reading(now_s))
            skipped = max(
                1,
                math.floor((now_s - self._next_flow_sample_s) / flow_period_s) + 1,
            )
            self._next_flow_sample_s += skipped * flow_period_s
        range_period_s = 1.0 / self.config.range_sensor.sample_rate_hz
        if now_s + 1e-12 >= self._next_range_sample_s:
            self._range_history.append(self._sample_range_readings(now_s))
            skipped = max(
                1,
                math.floor((now_s - self._next_range_sample_s) / range_period_s) + 1,
            )
            self._next_range_sample_s += skipped * range_period_s

        self._held_flow = self._select_flow_sample(now_s - self.config.flow.latency_s)
        self._held_ranges = self._select_range_sample(now_s - self.config.range_sensor.latency_s)

    def _select_flow_sample(self, boundary_s: float) -> FlowReading:
        selected = self._flow_history[0]
        for sample in self._flow_history:
            if sample.source_timestamp_s is not None and sample.source_timestamp_s <= boundary_s:
                selected = sample
            else:
                break
        while (
            len(self._flow_history) > 2
            and self._flow_history[1].source_timestamp_s is not None
            and self._flow_history[1].source_timestamp_s <= boundary_s
        ):
            self._flow_history.popleft()
        return selected

    def _select_range_sample(self, boundary_s: float) -> RangeReadings:
        selected = self._range_history[0]
        for sample in self._range_history:
            if sample.source_timestamp_s is not None and sample.source_timestamp_s <= boundary_s:
                selected = sample
            else:
                break
        while (
            len(self._range_history) > 2
            and self._range_history[1].source_timestamp_s is not None
            and self._range_history[1].source_timestamp_s <= boundary_s
        ):
            self._range_history.popleft()
        return selected

    def _flow_reading(self) -> FlowReading:
        return self._held_flow

    def _sample_flow_reading(self, source_timestamp_s: float) -> FlowReading:
        body_velocity = self.physics.state.attitude.rotate_world_to_body(self._velocity)
        attitude = self.physics.state.attitude.euler()
        tilt_rad = math.hypot(attitude.roll_rad, attitude.pitch_rad)
        tilt_factor = max(0.0, 1.0 - tilt_rad / self.config.flow.maximum_tilt_rad)
        down_direction = self.physics.state.attitude.rotate_body_to_world(Vector3(z=-1.0))
        ground_distance = self.world.ray_distance(
            self._position,
            down_direction,
            self.config.max_range_m,
        )
        height_factor = min(1.0, max(0.0, ground_distance / 0.05))
        if ground_distance > self.config.flow.maximum_height_m:
            height_factor *= max(
                0.0,
                1.0
                - (ground_distance - self.config.flow.maximum_height_m)
                / self.config.flow.maximum_height_m,
            )
        horizontal_speed = math.hypot(body_velocity.x, body_velocity.y)
        blur_factor = max(0.0, 1.0 - horizontal_speed / self.config.flow.blur_speed_m_s)
        quality_percent = max(
            0.0,
            min(
                100.0,
                100.0
                * tilt_factor
                * height_factor
                * blur_factor
                * self.config.flow_environment.modeled_quality_scale,
            ),
        )
        dropped = self._sensor_random.random() < self.config.flow.dropout_probability
        unavailable = dropped or quality_percent < self.config.flow.minimum_quality_percent
        status = (
            FlowStatus.UNAVAILABLE
            if unavailable
            else FlowStatus.DEGRADED
            if quality_percent < 99.999
            else FlowStatus.VALID
        )
        measured_velocity: Vector3 | None = None
        if not unavailable:
            noise_scale = self.config.flow.velocity_noise_std_m_s / max(
                quality_percent / 100.0,
                0.05,
            )
            yaw = self.config.flow.mounting_yaw_rad
            mounted_x = math.cos(yaw) * body_velocity.x + math.sin(yaw) * body_velocity.y
            mounted_y = -math.sin(yaw) * body_velocity.x + math.cos(yaw) * body_velocity.y
            measured_velocity = Vector3(
                x=mounted_x + self._sensor_random.gauss(0.0, noise_scale),
                y=mounted_y + self._sensor_random.gauss(0.0, noise_scale),
                z=0.0,
            )
        return FlowReading(
            velocity_body_m_s=measured_velocity,
            ground_distance_m=ground_distance,
            quality_percent=quality_percent,
            status=status,
            source_timestamp_s=source_timestamp_s,
        )

    def _localization_quality_percent(self) -> float:
        if (
            self.config.physics.powertrain_model is PowertrainModel.BATTERY_COUPLED_V2
            and self._position.z > 0.05
            and self._held_flow.status is FlowStatus.UNAVAILABLE
        ):
            return 0.0
        noise_penalty = min(40.0, self.config.position_noise_std_m * 1000.0)
        drift_penalty = min(
            40.0,
            100.0 * math.hypot(self._estimator_drift.x, self._estimator_drift.y),
        )
        return max(
            0.0,
            100.0 * self.config.flow_environment.modeled_quality_scale
            - noise_penalty
            - drift_penalty,
        )

    def _range_readings(self) -> RangeReadings:
        if self.faults.active(FaultType.RANGE_UNAVAILABLE, self.clock.now_s):
            return RangeReadings(
                max_range_m=self.config.max_range_m,
                statuses={
                    direction: RangeStatus.UNAVAILABLE
                    for direction in ("front", "back", "left", "right", "up", "down")
                },
                source_timestamp_s=self._held_ranges.source_timestamp_s,
            )
        if self.faults.active(FaultType.RANGE_STALE, self.clock.now_s):
            return self._held_ranges.model_copy(
                update={
                    "statuses": {
                        direction: RangeStatus.STALE
                        for direction in ("front", "back", "left", "right", "up", "down")
                    },
                    "source_timestamp_s": max(0.0, self.clock.now_s - 2.0),
                }
            )
        return self._held_ranges

    def _sample_range_readings(self, source_timestamp_s: float) -> RangeReadings:
        directions = {
            "front_m": self.physics.state.attitude.rotate_body_to_world(Vector3(x=1.0)),
            "back_m": self.physics.state.attitude.rotate_body_to_world(Vector3(x=-1.0)),
            "left_m": self.physics.state.attitude.rotate_body_to_world(Vector3(y=1.0)),
            "right_m": self.physics.state.attitude.rotate_body_to_world(Vector3(y=-1.0)),
            "up_m": self.physics.state.attitude.rotate_body_to_world(Vector3(z=1.0)),
            "down_m": self.physics.state.attitude.rotate_body_to_world(Vector3(z=-1.0)),
        }
        readings: dict[str, float] = {}
        statuses: dict[str, RangeStatus] = {}
        range_random = (
            self._random
            if self.config.physics.powertrain_model is PowertrainModel.LEGACY_UNCOUPLED_V1
            else self._sensor_random
        )
        for name, direction in directions.items():
            value = self.world.ray_distance(self._position, direction, self.config.max_range_m)
            noisy = (
                value
                + self.config.range_sensor.bias_m
                + range_random.gauss(0.0, self.config.range_noise_std_m)
            )
            readings[name] = min(self.config.max_range_m, max(0.0, noisy))
            direction_name = name.removesuffix("_m")
            if value >= self.config.max_range_m:
                statuses[direction_name] = RangeStatus.NO_HIT
            elif noisy < 0.0 or noisy > self.config.max_range_m:
                statuses[direction_name] = RangeStatus.CLIPPED
            else:
                statuses[direction_name] = RangeStatus.VALID
        return RangeReadings(
            max_range_m=self.config.max_range_m,
            statuses=statuses,
            source_timestamp_s=source_timestamp_s,
            **readings,
        )

    def _motor_telemetry(self) -> MotorTelemetry:
        readings = tuple(
            MotorReading(
                motor_id=f"M{index}",
                command_percent=motor.command * 100.0,
                requested_thrust_n=motor.requested_thrust_n,
                applied_pwm_percent=motor.applied_pwm * 100.0,
                motor_voltage_v=motor.motor_voltage_v,
                thrust_n=motor.thrust_n,
                available_thrust_n=motor.available_thrust_n,
                current_a=motor.current_a,
                saturated=motor.saturated,
                health_percent=motor.health_scale * 100.0,
                faulted=motor.health_scale < 1.0,
            )
            for index, motor in enumerate(self.physics.state.motors, start=1)
        )
        return MotorTelemetry(
            model_id=self.config.physics.model_id,
            model_version=self.config.physics.model_version,
            readings=readings,
        )
