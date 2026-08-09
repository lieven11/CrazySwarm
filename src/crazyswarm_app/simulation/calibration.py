from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.domain.models import Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.physics import PhysicsModelConfig
from crazyswarm_app.simulation.powertrain import ParameterProvenance, QualificationClass


class PhysicalCalibrationUpdates(BaseModel):
    """Allowlisted physical coefficients that a reviewed bench artifact may replace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mass_kg: float | None = Field(default=None, gt=0.0)
    payload_mass_kg: float | None = Field(default=None, ge=0.0)
    payload_position_body_m: Vector3 | None = None
    inertia_x_kg_m2: float | None = Field(default=None, gt=0.0)
    inertia_y_kg_m2: float | None = Field(default=None, gt=0.0)
    inertia_z_kg_m2: float | None = Field(default=None, gt=0.0)
    max_motor_thrust_n: float | None = Field(default=None, gt=0.0)
    motor_time_constant_s: float | None = Field(default=None, gt=0.0)
    motor_thrust_scales: tuple[float, float, float, float] | None = None
    motor_current_scales: tuple[float, float, float, float] | None = None
    motor_time_constant_scales: tuple[float, float, float, float] | None = None
    battery_capacity_ah: float | None = Field(default=None, gt=0.0)
    battery_internal_resistance_ohm: float | None = Field(default=None, ge=0.0)
    battery_idle_current_a: float | None = Field(default=None, ge=0.0)
    battery_max_current_a: float | None = Field(default=None, gt=0.0)
    motor_max_current_a: float | None = Field(default=None, gt=0.0)
    linear_drag_n_s_m: float | None = Field(default=None, ge=0.0)
    linear_drag_body_scale: Vector3 | None = None
    quadratic_drag_body_n_s2_m2: Vector3 | None = None
    angular_drag_n_m_s: float | None = Field(default=None, ge=0.0)
    ground_effect_strength: float | None = Field(default=None, ge=0.0)
    ground_effect_range_m: float | None = Field(default=None, gt=0.0)
    ground_effect_maximum_multiplier: float | None = Field(default=None, ge=1.0)

    @model_validator(mode="after")
    def at_least_one_valid_update(self) -> PhysicalCalibrationUpdates:
        updates = self.model_dump(exclude_none=True)
        if not updates:
            raise ValueError("calibration import requires at least one coefficient update")
        for name in (
            "motor_thrust_scales",
            "motor_current_scales",
            "motor_time_constant_scales",
        ):
            values = updates.get(name)
            if values is None:
                continue
            if any(value <= 0.0 for value in values):
                raise ValueError(f"{name} calibration values must be positive")
        return self


class PhysicalCalibrationArtifact(BaseModel):
    """Immutable import request; it never mutates the configured default parameter set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    calibration_id: Identifier
    base_configuration_sha256: SHA256
    source_id: Identifier
    source_url: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    hardware_configuration: str = Field(min_length=1)
    qualification: QualificationClass = QualificationClass.CONFIGURED_UNQUALIFIED
    uncertainty: str = Field(min_length=1)
    calibration_run_ids: tuple[Identifier, ...] = ()
    validation_run_ids: tuple[Identifier, ...] = ()
    updates: PhysicalCalibrationUpdates

    @model_validator(mode="after")
    def evidence_split_is_disjoint(self) -> PhysicalCalibrationArtifact:
        overlap = set(self.calibration_run_ids) & set(self.validation_run_ids)
        if overlap:
            raise ValueError(f"calibration and validation runs overlap: {sorted(overlap)}")
        if self.qualification is QualificationClass.MEASURED_QUALIFIED and (
            not self.calibration_run_ids or not self.validation_run_ids
        ):
            raise ValueError(
                "measured calibration evidence requires non-empty calibration and "
                "held-out validation run IDs"
            )
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


class ImportedPhysicalCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    calibration_id: Identifier
    calibration_artifact_sha256: SHA256
    base_configuration_sha256: SHA256
    imported_configuration_sha256: SHA256
    model_version: str
    parameter_source: str
    physics: PhysicsModelConfig


def import_physical_calibration(
    artifact: PhysicalCalibrationArtifact,
    *,
    base: PhysicsModelConfig | None = None,
) -> ImportedPhysicalCalibration:
    """Create a new validated model version and hash from reviewed calibration evidence."""

    selected_base = base or PhysicsModelConfig()
    base_parameters = SimulationConfig(physics=selected_base).vehicle_parameters()
    if base_parameters.sha256 != artifact.base_configuration_sha256:
        raise ValueError("calibration artifact does not match the selected base configuration")
    if not selected_base.model_version.startswith("2.0.0"):
        raise ValueError("physical calibration imports require a model-v2 base")

    updates = artifact.updates.model_dump(exclude_none=True)
    updated_names = set(updates)
    provenance: list[ParameterProvenance] = []
    for source in selected_base.parameter_provenance:
        retained_names = tuple(name for name in source.parameter_names if name not in updated_names)
        if retained_names:
            provenance.append(source.model_copy(update={"parameter_names": retained_names}))
    provenance.append(
        ParameterProvenance(
            parameter_names=tuple(sorted(updated_names)),
            source_id=artifact.source_id,
            source_url=artifact.source_url,
            source_version=artifact.source_version,
            hardware_configuration=artifact.hardware_configuration,
            qualification=artifact.qualification,
            uncertainty=artifact.uncertainty,
        )
    )

    artifact_sha256 = artifact.sha256
    payload = selected_base.model_dump(mode="python")
    payload.update(updates)
    payload.update(
        {
            "model_version": f"2.0.0-cal.{artifact_sha256[:12]}",
            "parameter_source": "CONFIGURED_UNQUALIFIED",
            "parameter_provenance": tuple(provenance),
        }
    )
    imported_physics = PhysicsModelConfig.model_validate(payload)
    imported_parameters = SimulationConfig(physics=imported_physics).vehicle_parameters()
    if imported_parameters.sha256 == base_parameters.sha256:
        raise RuntimeError("calibration import did not create a new configuration identity")
    return ImportedPhysicalCalibration(
        calibration_id=artifact.calibration_id,
        calibration_artifact_sha256=artifact_sha256,
        base_configuration_sha256=base_parameters.sha256,
        imported_configuration_sha256=imported_parameters.sha256,
        model_version=imported_physics.model_version,
        parameter_source=imported_physics.parameter_source,
        physics=imported_physics,
    )
