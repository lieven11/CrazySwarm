from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import VehicleCapability, VehicleState
from crazyswarm_app.simulation.vehicle import SimulatedVehicle

ParameterValue = bool | int | float | str


class ParameterAccess(StrEnum):
    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"


class ParameterPersistence(StrEnum):
    SESSION = "SESSION"
    STORED = "STORED"


class ParameterRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: ParameterValue
    default: ParameterValue
    value_type: str
    access: ParameterAccess
    persistence: ParameterPersistence
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    source_class: str = "CONFIGURED"


class ParameterSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    vehicle_id: str
    created_at_monotonic_s: float
    values: dict[str, ParameterValue]


@dataclass(frozen=True, slots=True)
class _Definition:
    attribute: tuple[str, ...]
    value_type: type[ParameterValue]
    minimum: float | None
    maximum: float | None
    unit: str | None
    writable: bool = True


SIMULATION_PARAMETERS: dict[str, _Definition] = {
    "sim.max_horizontal_speed_m_s": _Definition(
        ("max_horizontal_speed_m_s",), float, 0.05, 2.0, "m/s"
    ),
    "sim.max_vertical_speed_m_s": _Definition(("max_vertical_speed_m_s",), float, 0.05, 1.0, "m/s"),
    "sim.max_acceleration_m_s2": _Definition(("max_acceleration_m_s2",), float, 0.1, 5.0, "m/s²"),
    "sim.position_noise_std_m": _Definition(("position_noise_std_m",), float, 0.0, 0.25, "m"),
    "sim.flow_drift_std_m_sqrt_s": _Definition(
        ("flow_drift_std_m_sqrt_s",), float, 0.0, 0.1, "m/√s"
    ),
    "sim.range_noise_std_m": _Definition(("range_noise_std_m",), float, 0.0, 0.25, "m"),
    "sim.physics.model_version": _Definition(
        ("physics", "model_version"), str, None, None, None, writable=False
    ),
    "sim.physics.mass_kg": _Definition(("physics", "mass_kg"), float, 0.020, 0.060, "kg"),
    "sim.physics.max_motor_thrust_n": _Definition(
        ("physics", "max_motor_thrust_n"), float, 0.09, 0.25, "N"
    ),
    "sim.physics.motor_time_constant_s": _Definition(
        ("physics", "motor_time_constant_s"), float, 0.005, 0.15, "s"
    ),
    "sim.physics.linear_drag_n_s_m": _Definition(
        ("physics", "linear_drag_n_s_m"), float, 0.0, 0.1, "N·s/m"
    ),
    "sim.physics.battery_capacity_ah": _Definition(
        ("physics", "battery_capacity_ah"), float, 0.05, 1.0, "Ah"
    ),
}


@dataclass(slots=True)
class ParameterService:
    vehicles: dict[str, SimulatedVehicle]
    snapshots: dict[str, ParameterSnapshot] = field(default_factory=dict)
    _defaults: dict[str, dict[str, ParameterValue]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for vehicle_id, vehicle in self.vehicles.items():
            self._defaults[vehicle_id] = {
                name: self._get(vehicle, definition.attribute)
                for name, definition in SIMULATION_PARAMETERS.items()
            }

    def list(self, vehicle_id: str) -> tuple[ParameterRecord, ...]:
        vehicle = self._require_supported(vehicle_id)
        defaults = self._defaults[vehicle_id]
        return tuple(
            ParameterRecord(
                name=name,
                value=self._get(vehicle, definition.attribute),
                default=defaults[name],
                value_type=definition.value_type.__name__,
                access=(
                    ParameterAccess.READ_WRITE if definition.writable else ParameterAccess.READ_ONLY
                ),
                persistence=ParameterPersistence.SESSION,
                minimum=definition.minimum,
                maximum=definition.maximum,
                unit=definition.unit,
            )
            for name, definition in SIMULATION_PARAMETERS.items()
        )

    def write(
        self,
        vehicle_id: str,
        name: str,
        value: ParameterValue,
        *,
        state: VehicleState,
        armed: bool = False,
    ) -> ParameterRecord:
        vehicle = self._require_supported(vehicle_id)
        if armed or state not in {VehicleState.DISCONNECTED, VehicleState.READY}:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                "parameter writes require a disarmed vehicle",
            )
        try:
            definition = SIMULATION_PARAMETERS[name]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, f"unknown parameter: {name}"
            ) from error
        if not definition.writable:
            raise CrazySwarmError(ErrorCode.MODE_NOT_AUTHORIZED, f"parameter is read-only: {name}")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, f"parameter requires a number: {name}")
        numeric = float(value)
        if definition.minimum is not None and numeric < definition.minimum:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, f"parameter is below minimum: {name}")
        if definition.maximum is not None and numeric > definition.maximum:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, f"parameter is above maximum: {name}")
        if len(definition.attribute) == 1:
            vehicle.config = vehicle.config.model_copy(update={definition.attribute[0]: numeric})
        else:
            physics_attribute = definition.attribute[1]
            physics = vehicle.config.physics.model_copy(update={physics_attribute: numeric})
            vehicle.config = vehicle.config.model_copy(update={"physics": physics})
            vehicle.physics.config = physics
        return next(record for record in self.list(vehicle_id) if record.name == name)

    @staticmethod
    def _get(vehicle: SimulatedVehicle, attribute: tuple[str, ...]) -> ParameterValue:
        value: object = vehicle.config
        for name in attribute:
            value = getattr(value, name)
        if not isinstance(value, (bool, int, float, str)):
            raise TypeError(f"unsupported parameter value at {'.'.join(attribute)}")
        return value

    def snapshot(self, vehicle_id: str) -> ParameterSnapshot:
        values = {record.name: record.value for record in self.list(vehicle_id)}
        snapshot = ParameterSnapshot(
            snapshot_id=f"params-{uuid.uuid4().hex}",
            vehicle_id=vehicle_id,
            created_at_monotonic_s=time.monotonic(),
            values=values,
        )
        self.snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    def diff(self, vehicle_id: str, snapshot_id: str) -> dict[str, dict[str, ParameterValue]]:
        snapshot = self._require_snapshot(vehicle_id, snapshot_id)
        current = {record.name: record.value for record in self.list(vehicle_id)}
        return {
            name: {"before": value, "current": current[name]}
            for name, value in snapshot.values.items()
            if current.get(name) != value
        }

    def restore(
        self,
        vehicle_id: str,
        snapshot_id: str,
        *,
        state: VehicleState,
        armed: bool = False,
    ) -> tuple[ParameterRecord, ...]:
        snapshot = self._require_snapshot(vehicle_id, snapshot_id)
        for name, value in snapshot.values.items():
            if not SIMULATION_PARAMETERS[name].writable:
                continue
            self.write(vehicle_id, name, value, state=state, armed=armed)
        return self.list(vehicle_id)

    def _require_supported(self, vehicle_id: str) -> SimulatedVehicle:
        try:
            vehicle = self.vehicles[vehicle_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH, f"unknown vehicle: {vehicle_id}"
            ) from error
        if VehicleCapability.PARAMETER_ACCESS not in vehicle.capabilities.features:
            raise CrazySwarmError(ErrorCode.CAPABILITY_MISSING, "parameter access is unavailable")
        return vehicle

    def _require_snapshot(self, vehicle_id: str, snapshot_id: str) -> ParameterSnapshot:
        try:
            snapshot = self.snapshots[snapshot_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, f"unknown parameter snapshot: {snapshot_id}"
            ) from error
        if snapshot.vehicle_id != vehicle_id:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH, "parameter snapshot vehicle mismatch"
            )
        return snapshot
