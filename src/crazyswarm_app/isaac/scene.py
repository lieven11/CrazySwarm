from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, VehicleParameterSchema, canonical_sha256


class ConfiguredScalar(ContractModel):
    value: float
    unit: str
    qualification: Literal["CONFIGURED_UNQUALIFIED"] = "CONFIGURED_UNQUALIFIED"
    provenance: str


class PrimitiveGeometry(ContractModel):
    shape: Literal["BOX", "CYLINDER", "SPHERE"]
    dimensions_m: Vector3
    qualification: Literal["CONFIGURED_UNQUALIFIED"] = "CONFIGURED_UNQUALIFIED"
    purpose: Literal["VISUAL", "COLLISION", "VISUAL_AND_COLLISION"]


class IsaacWorldSpecification(ContractModel):
    world_frame: Literal["world"] = "world"
    dimensions_m: Vector3
    floor_thickness: ConfiguredScalar
    gravity_m_s2: ConfiguredScalar
    home_position_m: Vector3
    geofence_margin_m: ConfiguredScalar
    primitive_obstacles: tuple[PrimitiveGeometry, ...] = ()


class IsaacVehicleSceneSpecification(ContractModel):
    vehicle_id: Identifier
    ros_namespace: Identifier
    usd_prim_path: str = Field(pattern=r"^/World/[A-Za-z0-9_/]+$")
    model_id: Identifier
    model_version: str
    parameter_set_id: Identifier
    parameter_configuration_sha256: SHA256
    parameter_source: Literal["CONFIGURED_UNQUALIFIED"] = "CONFIGURED_UNQUALIFIED"
    initial_position_m: Vector3
    initial_yaw_rad: float = 0.0
    body_geometry: PrimitiveGeometry
    rotor_geometry: PrimitiveGeometry
    controller_profile: Literal["ESTIMATOR_IN_LOOP_REFERENCE"] = "ESTIMATOR_IN_LOOP_REFERENCE"


class IsaacRuntimeProfile(ContractModel):
    profile_id: Identifier
    headless: Literal[True] = True
    renderer_enabled: Literal[False] = False
    cameras_enabled: Literal[False] = False
    rtx_lidar_enabled: Literal[False] = False
    ros_bridge_enabled: bool = True
    fixed_step_s: Annotated[float, Field(gt=0.0, le=0.05)]
    maximum_vehicles: Annotated[int, Field(ge=1, le=1)] = 1
    telemetry_queue_bound: Annotated[int, Field(ge=1, le=10000)] = 100


class IsaacSceneSpecification(ContractModel):
    schema_version: Literal[1] = 1
    scene_id: Identifier
    scene_version: str
    qualification: Literal["CONFIGURED_UNQUALIFIED"] = "CONFIGURED_UNQUALIFIED"
    physical_model_authorized: Literal[False] = False
    digital_twin_enabled: Literal[False] = False
    source_class: Literal["SIMULATED_MODEL"] = "SIMULATED_MODEL"
    runtime: IsaacRuntimeProfile
    world: IsaacWorldSpecification
    vehicles: tuple[IsaacVehicleSceneSpecification, ...]

    @model_validator(mode="after")
    def exactly_one_minimal_vehicle(self) -> IsaacSceneSpecification:
        if len(self.vehicles) != 1:
            raise ValueError("the approved minimal scene must contain exactly one vehicle")
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)

    def validate_parameter_source(self, parameters: VehicleParameterSchema) -> None:
        vehicle = self.vehicles[0]
        if parameters.parameter_source != "CONFIGURED_UNQUALIFIED":
            raise ValueError("architecture/mock scene cannot consume qualified physical parameters")
        if parameters.parameter_set_id != vehicle.parameter_set_id:
            raise ValueError("scene parameter-set identity mismatch")
        if (
            parameters.model_id != vehicle.model_id
            or parameters.model_version != vehicle.model_version
        ):
            raise ValueError("scene model identity mismatch")
        if parameters.sha256 != vehicle.parameter_configuration_sha256:
            raise ValueError("scene shared parameter hash mismatch")


def load_isaac_scene(
    path: Path,
    *,
    vehicle_parameters: VehicleParameterSchema | None = None,
) -> IsaacSceneSpecification:
    raw = json.loads(path.read_text(encoding="utf-8"))
    scene = IsaacSceneSpecification.model_validate(raw)
    if vehicle_parameters is not None:
        scene.validate_parameter_source(vehicle_parameters)
    return scene
