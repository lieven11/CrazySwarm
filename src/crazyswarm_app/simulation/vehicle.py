from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
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
    HoverCommand,
    LandCommand,
    MoveRelativeCommand,
    StopAndHoldCommand,
    TakeoffCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    CoordinateFrame,
    DeckStatus,
    DeckType,
    HealthStatus,
    Vector3,
    VehicleCapabilities,
    VehicleCapability,
    VehicleIdentity,
    VehicleState,
)
from crazyswarm_app.domain.simulation import AdapterContractManifest, canonical_sha256
from crazyswarm_app.domain.telemetry import (
    FlowReading,
    ImuReading,
    LocalizationSource,
    MotorReading,
    MotorTelemetry,
    RangeReadings,
    TelemetryEnvelope,
    TransportReading,
    VehicleTelemetry,
)
from crazyswarm_app.simulation.clock import SimulationClock
from crazyswarm_app.simulation.faults import FaultInjector, FaultType
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.physics import SixDofPhysics
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
        self._initial_position = initial_position_m or Vector3()
        if not self.world.contains(self._initial_position):
            raise ValueError("initial position is outside the world")
        self._initial_yaw = initial_yaw_rad
        self.physics = SixDofPhysics(
            self.config.physics,
            position_m=self._initial_position,
            yaw_rad=self._initial_yaw,
            battery_percent=self.config.battery_start_percent,
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
        self.telemetry_history: list[TelemetryEnvelope] = []
        self._source_clock_epoch = -1
        self.reset()

    @property
    def identity(self) -> VehicleIdentity:
        return self._identity

    @property
    def capabilities(self) -> VehicleCapabilities:
        return self._capabilities

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
                "position_m": self._initial_position.model_dump(mode="json"),
                "yaw_rad": self._initial_yaw,
                "battery_percent": self.config.battery_start_percent,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {
            "vehicle_adapter": self.identity.adapter,
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
        self._state = VehicleState.DISCONNECTED
        self._armed = False
        self._flying = False
        self.physics.reset(
            self._initial_position,
            self._initial_yaw,
            self.config.battery_start_percent,
        )
        self._position = self.physics.state.position_m
        self._estimated_position = self._initial_position
        self._velocity = self.physics.state.velocity_m_s
        self._acceleration = self.physics.state.acceleration_world_m_s2
        self._yaw_rad = self.physics.state.attitude.euler().yaw_rad
        self._yaw_rate_rad_s = self.physics.state.angular_velocity_body_rad_s.z
        self._battery_percent = self.physics.state.battery_state_of_charge * 100.0
        self._sequence = 0
        self._fault_messages: list[str] = []
        self.telemetry_history.clear()

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
        elif isinstance(payload, StopAndHoldCommand):
            self._require_state(VehicleState.FLYING)
            await self._hold(self.config.fixed_step_s)
        elif isinstance(payload, LandCommand):
            await self._land(payload.duration_s, payload.target_height_m)
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

    async def snapshot(self) -> TelemetryEnvelope:
        return self._build_telemetry()

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
        target = Vector3(x=self._position.x, y=self._position.y, z=command.height_m)
        self._flying = True
        await self._move_to(target, self._yaw_rad, command.duration_s, VehicleState.TAKING_OFF)
        self._state = VehicleState.FLYING
        await self._publish()

    async def _move_relative(self, command: MoveRelativeCommand) -> None:
        self._require_state(VehicleState.FLYING)
        if command.frame is CoordinateFrame.BODY:
            cos_yaw = math.cos(self._yaw_rad)
            sin_yaw = math.sin(self._yaw_rad)
            dx = command.x_m * cos_yaw - command.y_m * sin_yaw
            dy = command.x_m * sin_yaw + command.y_m * cos_yaw
        else:
            dx, dy = command.x_m, command.y_m
        target = Vector3(
            x=self._position.x + dx,
            y=self._position.y + dy,
            z=self._position.z + command.z_m,
        )
        await self._move_to(
            target,
            self._yaw_rad + command.yaw_rad,
            command.duration_s,
            VehicleState.FLYING,
        )

    async def _land(self, duration_s: float, target_height_m: float = 0.0) -> None:
        if self._state not in {
            VehicleState.FLYING,
            VehicleState.TAKING_OFF,
            VehicleState.RETURNING,
            VehicleState.ABORTING,
        }:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, "vehicle is not in a landable state")
        target = Vector3(x=self._position.x, y=self._position.y, z=target_height_m)
        await self._move_to(target, self._yaw_rad, duration_s, VehicleState.LANDING)
        self._armed = False
        self._cut_motors()
        settle_limit_s = 2.0
        settled_s = 0.0
        while self.physics.state.position_m.z > 0.001 and settled_s < settle_limit_s:
            await self._step(self.config.fixed_step_s, motor_commands=(0.0, 0.0, 0.0, 0.0))
            settled_s += self.config.fixed_step_s
        self._flying = False
        self._state = VehicleState.READY
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
        target = self._position
        target_yaw = self._yaw_rad
        steps = max(1, math.ceil(duration_s / self.config.fixed_step_s))
        for index in range(steps):
            dt = min(self.config.fixed_step_s, duration_s - index * self.config.fixed_step_s)
            if dt <= 0.0:
                break
            motor_commands = self.physics.motor_commands_for_trajectory(
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
        start = self.physics.state.position_m
        start_yaw = self._yaw_rad
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
            motor_commands = self.physics.motor_commands_for_trajectory(
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
            self.physics.state.battery_state_of_charge = min(
                self.physics.state.battery_state_of_charge,
                forced_percent / 100.0,
            )
            self.physics.state.battery_voltage_v = (
                self.config.physics.battery_empty_voltage_v
                + self.physics.state.battery_state_of_charge
                * (
                    self.config.physics.battery_full_voltage_v
                    - self.config.physics.battery_empty_voltage_v
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
            raise CrazySwarmError(ErrorCode.LINK_LOST, "simulated link disconnected")

        previous_position = self.physics.state.position_m
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
        self.physics.step(
            selected_motor_commands,  # type: ignore[arg-type]
            dt,
            additional_current_a=configured_current,
        )
        if self.physics.state.battery_voltage_v <= self.config.physics.battery_cutoff_voltage_v:
            self._sync_physics_state()
            self._state = VehicleState.FAULT
            self._armed = False
            self._flying = False
            self._cut_motors()
            if "BATTERY_CUTOFF" not in self._fault_messages:
                self._fault_messages.append("BATTERY_CUTOFF")
            await self._publish()
            raise CrazySwarmError(
                ErrorCode.CRITICAL_BATTERY,
                "modeled battery voltage reached cutoff",
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

        drift_scale = self.config.flow_drift_std_m_sqrt_s * math.sqrt(dt)
        self._estimated_position = Vector3(
            x=self._position.x
            + self._random.gauss(0.0, self.config.position_noise_std_m)
            + self._random.gauss(0.0, drift_scale),
            y=self._position.y
            + self._random.gauss(0.0, self.config.position_noise_std_m)
            + self._random.gauss(0.0, drift_scale),
            z=max(
                0.0, self._position.z + self._random.gauss(0.0, self.config.position_noise_std_m)
            ),
        )
        await self._publish()

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
            motor.thrust_n = 0.0
            motor.current_a = 0.0

    async def _publish(self) -> None:
        if self.faults.active(FaultType.STALE_TELEMETRY, self.clock.now_s):
            return
        if self._random.random() < self.config.packet_loss_probability:
            return
        envelope = self._build_telemetry()
        self._sequence += 1
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
                velocity_m_s=self._velocity,
                attitude=self.physics.state.attitude.euler(),
                frame=CoordinateFrame.HOME,
                position_is_estimate=None if localization_lost else True,
                localization_source=(
                    LocalizationSource.NONE if localization_lost else LocalizationSource.SIMULATED
                ),
                localization_quality_percent=(
                    None
                    if localization_lost
                    else max(0.0, 100.0 - self.config.position_noise_std_m * 1000.0)
                ),
                battery_percent=self._battery_percent,
                battery_voltage_v=self.physics.state.battery_voltage_v,
                battery_current_a=self.physics.state.battery_current_a,
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
        body_acceleration = self.physics.state.attitude.rotate_world_to_body(
            Vector3(
                x=self._acceleration.x,
                y=self._acceleration.y,
                z=self._acceleration.z + self.config.physics.gravity_m_s2,
            )
        )
        return ImuReading(
            acceleration_body_m_s2=body_acceleration,
            angular_velocity_body_rad_s=self.physics.state.angular_velocity_body_rad_s,
        )

    def _flow_reading(self) -> FlowReading:
        body_velocity = self.physics.state.attitude.rotate_world_to_body(self._velocity)
        attitude = self.physics.state.attitude.euler()
        tilt_factor = max(0.0, math.cos(attitude.roll_rad) * math.cos(attitude.pitch_rad))
        height_factor = min(1.0, max(0.0, self._position.z / 0.05))
        return FlowReading(
            velocity_body_m_s=body_velocity,
            ground_distance_m=self._position.z,
            quality_percent=100.0 * tilt_factor * height_factor,
        )

    def _range_readings(self) -> RangeReadings:
        directions = {
            "front_m": self.physics.state.attitude.rotate_body_to_world(Vector3(x=1.0)),
            "back_m": self.physics.state.attitude.rotate_body_to_world(Vector3(x=-1.0)),
            "left_m": self.physics.state.attitude.rotate_body_to_world(Vector3(y=1.0)),
            "right_m": self.physics.state.attitude.rotate_body_to_world(Vector3(y=-1.0)),
            "up_m": self.physics.state.attitude.rotate_body_to_world(Vector3(z=1.0)),
            "down_m": self.physics.state.attitude.rotate_body_to_world(Vector3(z=-1.0)),
        }
        readings: dict[str, float] = {}
        for name, direction in directions.items():
            value = self.world.ray_distance(self._position, direction, self.config.max_range_m)
            noisy = value + self._random.gauss(0.0, self.config.range_noise_std_m)
            readings[name] = min(self.config.max_range_m, max(0.0, noisy))
        return RangeReadings(max_range_m=self.config.max_range_m, **readings)

    def _motor_telemetry(self) -> MotorTelemetry:
        readings = tuple(
            MotorReading(
                motor_id=f"M{index}",
                command_percent=motor.command * 100.0,
                thrust_n=motor.thrust_n,
                current_a=motor.current_a,
            )
            for index, motor in enumerate(self.physics.state.motors, start=1)
        )
        return MotorTelemetry(
            model_id=self.config.physics.model_id,
            model_version=self.config.physics.model_version,
            readings=readings,
        )
