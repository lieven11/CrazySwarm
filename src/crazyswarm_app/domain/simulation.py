from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.commands import CommandKind
from crazyswarm_app.domain.models import (
    ContractModel,
    CoordinateFrame,
    Identifier,
    Vector3,
    VehicleCapability,
)

SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ADAPTER_CONTRACT_VERSION: Final[Literal["1.0.0"]] = "1.0.0"


def canonical_json(value: Any) -> str:
    """Serialize shared configuration without adapter- or process-specific ordering."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=False)
    elif isinstance(value, (list, tuple)):
        value = [
            item.model_dump(mode="json", exclude_none=False)
            if hasattr(item, "model_dump")
            else item
            for item in value
        ]
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class SourceClass(StrEnum):
    MEASURED_REAL = "MEASURED_REAL"
    SIMULATED_MODEL = "SIMULATED_MODEL"
    DERIVED = "DERIVED"
    PLANNED = "PLANNED"
    CONFIGURED = "CONFIGURED"
    REPLAYED = "REPLAYED"


class SignalPresence(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    UNSUPPORTED = "UNSUPPORTED"


class SignalValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


class QuaternionValue(ContractModel):
    """Hamilton quaternion in explicit `(w, x, y, z)` order."""

    w: float
    x: float
    y: float
    z: float

    @model_validator(mode="after")
    def finite_nonzero(self) -> QuaternionValue:
        values = (self.w, self.x, self.y, self.z)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("quaternion components must be finite")
        if sum(value * value for value in values) <= 1e-24:
            raise ValueError("quaternion norm cannot be zero")
        return self

    def normalized(self) -> QuaternionValue:
        norm = math.sqrt(self.w**2 + self.x**2 + self.y**2 + self.z**2)
        return QuaternionValue(w=self.w / norm, x=self.x / norm, y=self.y / norm, z=self.z / norm)


class FrameDefinition(ContractModel):
    frame: CoordinateFrame
    parent: CoordinateFrame | None
    handedness: Literal["RIGHT_HANDED"] = "RIGHT_HANDED"
    x_axis: str
    y_axis: str
    z_axis: str
    origin: str
    angular_sign: Literal["RIGHT_HAND_RULE"] = "RIGHT_HAND_RULE"
    quaternion_order: Literal["wxyz"] = "wxyz"
    linear_unit: Literal["m"] = "m"
    angular_unit: Literal["rad"] = "rad"


class FrameConvention(ContractModel):
    schema_version: Literal[1] = 1
    convention_id: Identifier = "crazyswarm-frames-v1"
    frames: tuple[FrameDefinition, ...]

    @model_validator(mode="after")
    def unique_complete_frames(self) -> FrameConvention:
        declared = [item.frame for item in self.frames]
        if len(declared) != len(set(declared)):
            raise ValueError("frame declarations must be unique")
        required = {
            CoordinateFrame.WORLD,
            CoordinateFrame.HOME,
            CoordinateFrame.BODY,
            CoordinateFrame.SENSOR,
        }
        if set(declared) != required:
            raise ValueError("world, home, body, and sensor frames must all be declared")
        return self


CANONICAL_FRAME_CONVENTION = FrameConvention(
    frames=(
        FrameDefinition(
            frame=CoordinateFrame.WORLD,
            parent=None,
            x_axis="east/room-forward",
            y_axis="north/room-left",
            z_axis="up",
            origin="configured world origin",
        ),
        FrameDefinition(
            frame=CoordinateFrame.HOME,
            parent=CoordinateFrame.WORLD,
            x_axis="world +x",
            y_axis="world +y",
            z_axis="world +z",
            origin="vehicle launch/home point",
        ),
        FrameDefinition(
            frame=CoordinateFrame.BODY,
            parent=CoordinateFrame.HOME,
            x_axis="vehicle forward",
            y_axis="vehicle left",
            z_axis="vehicle up",
            origin="configured center of mass",
        ),
        FrameDefinition(
            frame=CoordinateFrame.SENSOR,
            parent=CoordinateFrame.BODY,
            x_axis="declared by sensor extrinsic",
            y_axis="declared by sensor extrinsic",
            z_axis="declared by sensor extrinsic",
            origin="declared sensor mounting point",
        ),
    )
)


def rotate_vector(quaternion: QuaternionValue, value: Vector3) -> Vector3:
    q = quaternion.normalized()
    xx, yy, zz = q.x * q.x, q.y * q.y, q.z * q.z
    xy, xz, yz = q.x * q.y, q.x * q.z, q.y * q.z
    wx, wy, wz = q.w * q.x, q.w * q.y, q.w * q.z
    return Vector3(
        x=(1 - 2 * (yy + zz)) * value.x + 2 * (xy - wz) * value.y + 2 * (xz + wy) * value.z,
        y=2 * (xy + wz) * value.x + (1 - 2 * (xx + zz)) * value.y + 2 * (yz - wx) * value.z,
        z=2 * (xz - wy) * value.x + 2 * (yz + wx) * value.y + (1 - 2 * (xx + yy)) * value.z,
    )


def inverse_rotate_vector(quaternion: QuaternionValue, value: Vector3) -> Vector3:
    return rotate_vector(
        QuaternionValue(w=quaternion.w, x=-quaternion.x, y=-quaternion.y, z=-quaternion.z),
        value,
    )


class RotorParameters(ContractModel):
    rotor_id: Identifier
    position_body_m: Vector3
    thrust_axis_body: Vector3
    rotation_direction: Literal["CW", "CCW"]
    maximum_thrust_n: Annotated[float, Field(gt=0.0)]
    reaction_torque_per_thrust_m: Annotated[float, Field(gt=0.0)]
    thrust_curve_exponent: Annotated[float, Field(gt=0.0)] = 1.0


class InertiaTensor(ContractModel):
    xx_kg_m2: Annotated[float, Field(gt=0.0)]
    yy_kg_m2: Annotated[float, Field(gt=0.0)]
    zz_kg_m2: Annotated[float, Field(gt=0.0)]
    xy_kg_m2: float = 0.0
    xz_kg_m2: float = 0.0
    yz_kg_m2: float = 0.0


class ActuatorParameters(ContractModel):
    response: Literal["FIRST_ORDER_THRUST"] = "FIRST_ORDER_THRUST"
    time_constant_s: Annotated[float, Field(gt=0.0)]
    command_min: Annotated[float, Field(ge=0.0, le=0.0)] = 0.0
    command_max: Annotated[float, Field(ge=1.0, le=1.0)] = 1.0


class DragParameters(ContractModel):
    linear_n_s_m: Annotated[float, Field(ge=0.0)]
    angular_n_m_s: Annotated[float, Field(ge=0.0)]
    aerodynamic_model: Literal["LINEAR_BODY_APPROXIMATION"] = "LINEAR_BODY_APPROXIMATION"


class BatteryParameters(ContractModel):
    model: Literal["COULOMB_COUNTING_WITH_RESISTIVE_SAG"] = "COULOMB_COUNTING_WITH_RESISTIVE_SAG"
    capacity_ah: Annotated[float, Field(gt=0.0)]
    full_voltage_v: Annotated[float, Field(gt=0.0)]
    empty_voltage_v: Annotated[float, Field(gt=0.0)]
    cutoff_voltage_v: Annotated[float, Field(gt=0.0)]
    internal_resistance_ohm: Annotated[float, Field(ge=0.0)]
    idle_current_a: Annotated[float, Field(ge=0.0)]
    maximum_motor_current_a: Annotated[float, Field(gt=0.0)]

    @model_validator(mode="after")
    def ordered_voltage(self) -> BatteryParameters:
        if self.empty_voltage_v >= self.full_voltage_v:
            raise ValueError("empty voltage must be below full voltage")
        if self.cutoff_voltage_v >= self.full_voltage_v:
            raise ValueError("cutoff voltage must be below full voltage")
        return self


class ControllerLimits(ContractModel):
    maximum_horizontal_speed_m_s: Annotated[float, Field(gt=0.0)]
    maximum_vertical_speed_m_s: Annotated[float, Field(gt=0.0)]
    maximum_acceleration_m_s2: Annotated[float, Field(gt=0.0)]
    maximum_yaw_rate_rad_s: Annotated[float, Field(gt=0.0)]
    maximum_tilt_rad: Annotated[float, Field(gt=0.0, lt=math.pi / 2)]


class SensorParameters(ContractModel):
    sensor_id: Identifier
    signal: Identifier
    frame: CoordinateFrame
    sample_rate_hz: Annotated[float, Field(gt=0.0)]
    latency_s: Annotated[float, Field(ge=0.0)]
    noise_std: Annotated[float, Field(ge=0.0)]
    bias: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    clipping: Literal["CLAMP", "INVALIDATE", "NONE"] = "NONE"
    dropout_probability: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0

    @model_validator(mode="after")
    def ordered_range(self) -> SensorParameters:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("sensor minimum cannot exceed maximum")
        return self


class VehicleParameterSchema(ContractModel):
    schema_version: Literal[1] = 1
    parameter_set_id: Identifier
    model_id: Identifier
    model_version: str
    parameter_source: Literal["CONFIGURED_UNQUALIFIED", "MEASURED_QUALIFIED"]
    frame_convention_id: Identifier = CANONICAL_FRAME_CONVENTION.convention_id
    base_mass_kg: Annotated[float, Field(gt=0.0)]
    payload_mass_kg: Annotated[float, Field(ge=0.0)] = 0.0
    center_of_mass_body_m: Vector3
    inertia: InertiaTensor
    rotors: tuple[RotorParameters, RotorParameters, RotorParameters, RotorParameters]
    actuator: ActuatorParameters
    drag: DragParameters
    battery: BatteryParameters
    controller_limits: ControllerLimits
    sensors: tuple[SensorParameters, ...]

    @property
    def total_mass_kg(self) -> float:
        return self.base_mass_kg + self.payload_mass_kg

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


class SignalSpecification(ContractModel):
    schema_version: Literal[1] = 1
    signal_id: Identifier
    unit: str
    frame: CoordinateFrame | None
    source_class: SourceClass
    presence: SignalPresence
    nominal_sample_rate_hz: Annotated[float, Field(gt=0.0)] | None
    nominal_latency_s: Annotated[float, Field(ge=0.0)] | None
    noise_std: Annotated[float, Field(ge=0.0)] | None
    bias: float | None
    minimum: float | None
    maximum: float | None
    clipping: Literal["CLAMP", "INVALIDATE", "NONE"]
    dropout_probability: Annotated[float, Field(ge=0.0, le=1.0)] | None
    provenance_required: bool = True

    @model_validator(mode="after")
    def unsupported_has_no_numeric_model(self) -> SignalSpecification:
        if self.presence is SignalPresence.UNSUPPORTED:
            modeled = (
                self.nominal_sample_rate_hz,
                self.nominal_latency_s,
                self.noise_std,
                self.bias,
                self.minimum,
                self.maximum,
                self.dropout_probability,
            )
            if any(value is not None for value in modeled):
                raise ValueError("unsupported signals cannot declare modeled numeric defaults")
        return self

    def validate_observation(self, observation: SignalObservation) -> None:
        if observation.signal_id != self.signal_id:
            raise ValueError("signal identity mismatch")
        if observation.frame is not self.frame:
            raise ValueError("signal frame mismatch")
        if self.presence is SignalPresence.UNSUPPORTED:
            raise ValueError("unsupported signal produced an observation")
        if observation.source_class is not self.source_class:
            raise ValueError("signal provenance mismatch")


class SignalObservation(ContractModel):
    signal_id: Identifier
    validity: SignalValidity
    source_class: SourceClass
    source_id: Identifier
    model_id: Identifier | None = None
    model_version: str | None = None
    unit: str
    frame: CoordinateFrame | None
    source_timestamp_s: Annotated[float, Field(ge=0.0)] | None
    value: Any | None = None

    @model_validator(mode="after")
    def unavailable_has_no_value(self) -> SignalObservation:
        if self.validity is SignalValidity.UNAVAILABLE and self.value is not None:
            raise ValueError("unavailable observations cannot carry a value")
        if self.validity is SignalValidity.VALID and self.value is None:
            raise ValueError("valid observations require a value")
        return self


class TimeContext(ContractModel):
    simulation_time_s: Annotated[float, Field(ge=0.0)] | None = None
    source_time_s: Annotated[float, Field(ge=0.0)]
    receive_time_s: Annotated[float, Field(ge=0.0)]
    wall_time_utc: str
    replay_time_s: Annotated[float, Field(ge=0.0)] | None = None
    source_clock_id: Identifier
    source_clock_epoch: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def receive_not_before_source_for_same_clock(self) -> TimeContext:
        if self.receive_time_s < self.source_time_s:
            raise ValueError("receive time cannot precede source time")
        return self


class CommandSemantics(ContractModel):
    command: CommandKind
    required_capabilities: frozenset[VehicleCapability]
    allowed_frames: frozenset[CoordinateFrame] = frozenset()
    duration_semantics: Literal["NONE", "REQUESTED_TRAJECTORY_DURATION", "MAXIMUM_DURATION"]
    completion_semantics: str


COMMAND_SEMANTICS: tuple[CommandSemantics, ...] = (
    CommandSemantics(
        command=CommandKind.CONNECT,
        required_capabilities=frozenset(),
        duration_semantics="NONE",
        completion_semantics="adapter ready or rejected",
    ),
    CommandSemantics(
        command=CommandKind.DISCONNECT,
        required_capabilities=frozenset(),
        duration_semantics="NONE",
        completion_semantics="adapter disconnected",
    ),
    CommandSemantics(
        command=CommandKind.ARM,
        required_capabilities=frozenset({VehicleCapability.ARMING}),
        duration_semantics="NONE",
        completion_semantics="armed state acknowledged",
    ),
    CommandSemantics(
        command=CommandKind.DISARM,
        required_capabilities=frozenset({VehicleCapability.ARMING}),
        duration_semantics="NONE",
        completion_semantics="disarmed state acknowledged",
    ),
    CommandSemantics(
        command=CommandKind.TAKEOFF,
        required_capabilities=frozenset({VehicleCapability.HIGH_LEVEL_COMMANDS}),
        allowed_frames=frozenset({CoordinateFrame.HOME}),
        duration_semantics="REQUESTED_TRAJECTORY_DURATION",
        completion_semantics="requested height trajectory completed",
    ),
    CommandSemantics(
        command=CommandKind.HOVER,
        required_capabilities=frozenset({VehicleCapability.HIGH_LEVEL_COMMANDS}),
        allowed_frames=frozenset({CoordinateFrame.HOME}),
        duration_semantics="REQUESTED_TRAJECTORY_DURATION",
        completion_semantics="hold duration completed",
    ),
    CommandSemantics(
        command=CommandKind.MOVE_RELATIVE,
        required_capabilities=frozenset({VehicleCapability.RELATIVE_POSITIONING}),
        allowed_frames=frozenset({CoordinateFrame.HOME, CoordinateFrame.BODY}),
        duration_semantics="REQUESTED_TRAJECTORY_DURATION",
        completion_semantics="relative trajectory completed",
    ),
    CommandSemantics(
        command=CommandKind.STOP_AND_HOLD,
        required_capabilities=frozenset({VehicleCapability.HIGH_LEVEL_COMMANDS}),
        duration_semantics="NONE",
        completion_semantics="hold target accepted",
    ),
    CommandSemantics(
        command=CommandKind.LAND,
        required_capabilities=frozenset({VehicleCapability.HIGH_LEVEL_COMMANDS}),
        allowed_frames=frozenset({CoordinateFrame.HOME}),
        duration_semantics="REQUESTED_TRAJECTORY_DURATION",
        completion_semantics="landing trajectory completed and disarmed",
    ),
    CommandSemantics(
        command=CommandKind.ABORT,
        required_capabilities=frozenset({VehicleCapability.HIGH_LEVEL_COMMANDS}),
        duration_semantics="MAXIMUM_DURATION",
        completion_semantics="abort-and-land completed",
    ),
    CommandSemantics(
        command=CommandKind.EMERGENCY_STOP,
        required_capabilities=frozenset({VehicleCapability.EMERGENCY_STOP}),
        duration_semantics="NONE",
        completion_semantics="motor cutoff acknowledged and latched",
    ),
)


class SimulationRunIdentity(ContractModel):
    schema_version: Literal[1] = 1
    adapter_contract_version: Literal["1.0.0"] = "1.0.0"
    mission_source_sha256: SHA256
    model_id: Identifier
    model_version: str
    model_configuration_sha256: SHA256
    scenario_id: Identifier
    scenario_configuration_sha256: SHA256
    initial_state_sha256: SHA256
    seed: int
    fixed_step_s: Annotated[float, Field(gt=0.0)]

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


class AdapterContractManifest(ContractModel):
    schema_version: Literal[1] = 1
    adapter_id: Identifier
    contract_version: Literal["1.0.0"] = "1.0.0"
    supported_capabilities: frozenset[VehicleCapability]
    supported_signals: frozenset[Identifier]
    supported_model_ids: frozenset[Identifier]

    def require(
        self,
        capabilities: frozenset[VehicleCapability],
        *,
        model_id: str | None = None,
    ) -> None:
        missing = capabilities - self.supported_capabilities
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"adapter capability missing: {names}")
        if model_id is not None and model_id not in self.supported_model_ids:
            raise ValueError(f"adapter model unsupported: {model_id}")
