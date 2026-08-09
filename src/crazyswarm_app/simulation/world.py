from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.domain.models import Identifier, Vector3
from crazyswarm_app.simulation.faults import FaultWindow
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.physics import PhysicsModelConfig


class ObstacleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    obstacle_id: Identifier
    minimum_m: Vector3
    maximum_m: Vector3

    @model_validator(mode="after")
    def valid_bounds(self) -> ObstacleConfig:
        if not (
            self.minimum_m.x < self.maximum_m.x
            and self.minimum_m.y < self.maximum_m.y
            and self.minimum_m.z < self.maximum_m.z
        ):
            raise ValueError("obstacle minimum must be below maximum on every axis")
        return self


class WorldConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    world_id: Identifier = "indoor-room"
    width_m: float = Field(default=4.0, gt=0.0)
    depth_m: float = Field(default=4.0, gt=0.0)
    height_m: float = Field(default=2.5, gt=0.0)
    obstacles: tuple[ObstacleConfig, ...] = ()


class VehicleSpawn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    vehicle_id: Identifier
    display_name: str
    position_m: Vector3 = Field(default_factory=Vector3)
    yaw_rad: float = 0.0


class ScenarioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    scenario_id: Identifier
    world: WorldConfig = Field(default_factory=WorldConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    vehicles: tuple[VehicleSpawn, ...]
    faults: tuple[FaultWindow, ...] = ()

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="python", exclude_none=False)
        if self.simulation.physics.model_version != "1.0.0":
            return payload
        simulation = payload["simulation"]
        simulation.pop("imu")
        simulation.pop("flow")
        simulation.pop("range_sensor")
        for fault in payload["faults"]:
            fault.pop("motor_index")
            fault.pop("actuator_health_scale")
        physics = simulation["physics"]
        for field_name in (
            "powertrain_model",
            "actuator_command_semantics",
            "rotor_layout",
            "parameter_provenance",
            "payload_position_body_m",
            "payload_inertia_x_kg_m2",
            "payload_inertia_y_kg_m2",
            "payload_inertia_z_kg_m2",
            "rotor_positions_body_m",
            "rotor_thrust_axes_body",
            "rotor_reaction_torque_signs",
            "minimum_motor_thrust_n",
            "motor_voltage_thrust_curve",
            "motor_time_constant_scales",
            "motor_thrust_scales",
            "motor_current_scales",
            "linear_drag_body_scale",
            "quadratic_drag_body_n_s2_m2",
            "ground_effect_strength",
            "ground_effect_range_m",
            "ground_effect_maximum_multiplier",
            "battery_capacity_scale",
            "battery_temperature_capacity_scale",
            "battery_age_capacity_scale",
            "battery_ocv_curve",
            "battery_cutoff_persistence_s",
            "battery_cutoff_recovery_hysteresis_v",
            "battery_resistance_scale",
            "battery_max_current_a",
            "battery_compensation_enabled",
            "battery_compensation_filter_time_constant_s",
            "battery_compensation_minimum_voltage_v",
        ):
            physics.pop(field_name)
        return payload


def load_scenario(path: Path) -> ScenarioConfig:
    with path.open(encoding="utf-8") as scenario_file:
        raw = yaml.safe_load(scenario_file) or {}
    if not isinstance(raw, dict):
        raise ValueError("scenario configuration must be a mapping")
    simulation = raw.get("simulation")
    if simulation is None:
        raw["simulation"] = {"physics": PhysicsModelConfig.legacy_v1().model_dump(mode="json")}
    elif isinstance(simulation, dict) and "physics" not in simulation:
        # Existing schema-v1 scenarios predate an explicit model discriminator. Preserve
        # their v1 meaning instead of silently replaying them through the new v2 plant.
        simulation["physics"] = PhysicsModelConfig.legacy_v1().model_dump(mode="json")
    return ScenarioConfig.model_validate(raw)


class IndoorWorld:
    def __init__(self, config: WorldConfig) -> None:
        self.config = config
        self.x_min = -config.width_m / 2.0
        self.x_max = config.width_m / 2.0
        self.y_min = -config.depth_m / 2.0
        self.y_max = config.depth_m / 2.0
        self.z_min = 0.0
        self.z_max = config.height_m

    def contains(self, point: Vector3) -> bool:
        inside_room = (
            self.x_min <= point.x <= self.x_max
            and self.y_min <= point.y <= self.y_max
            and self.z_min <= point.z <= self.z_max
        )
        return inside_room and not any(
            self._inside_obstacle(point, item) for item in self.config.obstacles
        )

    @staticmethod
    def _inside_obstacle(point: Vector3, obstacle: ObstacleConfig) -> bool:
        return (
            obstacle.minimum_m.x <= point.x <= obstacle.maximum_m.x
            and obstacle.minimum_m.y <= point.y <= obstacle.maximum_m.y
            and obstacle.minimum_m.z <= point.z <= obstacle.maximum_m.z
        )

    def ray_distance(self, origin: Vector3, direction: Vector3, max_range_m: float) -> float:
        norm = math.sqrt(direction.x**2 + direction.y**2 + direction.z**2)
        if norm == 0.0:
            raise ValueError("ray direction cannot be zero")
        unit = Vector3(x=direction.x / norm, y=direction.y / norm, z=direction.z / norm)

        distances = [
            self._room_exit_distance(origin, unit),
            *(self._box_entry_distance(origin, unit, item) for item in self.config.obstacles),
        ]
        valid = [distance for distance in distances if distance is not None and distance >= 0.0]
        if not valid:
            return max_range_m
        return min(min(valid), max_range_m)

    def _room_exit_distance(self, origin: Vector3, direction: Vector3) -> float | None:
        candidates: list[float] = []
        for value, component, lower, upper in (
            (origin.x, direction.x, self.x_min, self.x_max),
            (origin.y, direction.y, self.y_min, self.y_max),
            (origin.z, direction.z, self.z_min, self.z_max),
        ):
            if component > 0.0:
                candidates.append((upper - value) / component)
            elif component < 0.0:
                candidates.append((lower - value) / component)
        positive = [candidate for candidate in candidates if candidate >= 0.0]
        return min(positive) if positive else None

    @staticmethod
    def _box_entry_distance(
        origin: Vector3,
        direction: Vector3,
        obstacle: ObstacleConfig,
    ) -> float | None:
        t_min = -math.inf
        t_max = math.inf
        for value, component, lower, upper in (
            (origin.x, direction.x, obstacle.minimum_m.x, obstacle.maximum_m.x),
            (origin.y, direction.y, obstacle.minimum_m.y, obstacle.maximum_m.y),
            (origin.z, direction.z, obstacle.minimum_m.z, obstacle.maximum_m.z),
        ):
            if abs(component) < 1e-12:
                if value < lower or value > upper:
                    return None
                continue
            near = (lower - value) / component
            far = (upper - value) / component
            if near > far:
                near, far = far, near
            t_min = max(t_min, near)
            t_max = min(t_max, far)
            if t_min > t_max:
                return None
        if t_max < 0.0:
            return None
        return max(t_min, 0.0)
