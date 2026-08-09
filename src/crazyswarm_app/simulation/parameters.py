from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import VehicleState
from crazyswarm_app.engineering import (
    ParameterAccess,
    ParameterPersistence,
    ParameterRecord,
    ParameterValue,
)

if TYPE_CHECKING:
    from crazyswarm_app.simulation.vehicle import SimulatedVehicle


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


class SimulationParameterProvider:
    def __init__(self, vehicle: SimulatedVehicle) -> None:
        self.vehicle = vehicle
        self.defaults = {
            name: self._get(definition.attribute)
            for name, definition in SIMULATION_PARAMETERS.items()
        }

    def list_parameters(self) -> tuple[ParameterRecord, ...]:
        return tuple(
            ParameterRecord(
                name=name,
                value=self._get(definition.attribute),
                default=self.defaults[name],
                value_type=definition.value_type.__name__,
                access=ParameterAccess.READ_WRITE
                if definition.writable
                else ParameterAccess.READ_ONLY,
                persistence=ParameterPersistence.SESSION,
                minimum=definition.minimum,
                maximum=definition.maximum,
                unit=definition.unit,
            )
            for name, definition in SIMULATION_PARAMETERS.items()
        )

    def write_parameter(
        self,
        name: str,
        value: ParameterValue,
        *,
        state: VehicleState,
        armed: bool,
    ) -> ParameterRecord:
        if armed or state not in {VehicleState.DISCONNECTED, VehicleState.READY}:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE, "parameter writes require a disarmed vehicle"
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
            self.vehicle.config = self.vehicle.config.model_copy(
                update={definition.attribute[0]: numeric}
            )
        else:
            physics_attribute = definition.attribute[1]
            physics = self.vehicle.config.physics.model_copy(update={physics_attribute: numeric})
            self.vehicle.config = self.vehicle.config.model_copy(update={"physics": physics})
            self.vehicle.physics.config = physics
        return next(record for record in self.list_parameters() if record.name == name)

    def _get(self, attribute: tuple[str, ...]) -> ParameterValue:
        value: object = self.vehicle.config
        for name in attribute:
            value = getattr(value, name)
        if not isinstance(value, (bool, int, float, str)):
            raise TypeError(f"unsupported parameter value at {'.'.join(attribute)}")
        return value
