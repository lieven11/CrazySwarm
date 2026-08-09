from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.domain.models import CoordinateFrame, Vector3
from crazyswarm_app.domain.simulation import (
    ActuatorParameters,
    BatteryParameters,
    ControllerLimits,
    DragParameters,
    InertiaTensor,
    RotorParameters,
    SensorParameters,
    SignalPresence,
    SignalSpecification,
    SourceClass,
    VehicleParameterSchema,
)
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.physics import PhysicsModelConfig
from crazyswarm_app.simulation.powertrain import PowertrainModel
from crazyswarm_app.simulation.sensors import FlowModelConfig, ImuModelConfig, RangeModelConfig


class ControllerProfile(StrEnum):
    IDEAL_TRUTH_TEST_ONLY = "IDEAL_TRUTH_TEST_ONLY"
    ESTIMATOR_IN_LOOP_REFERENCE = "ESTIMATOR_IN_LOOP_REFERENCE"


class FlowSurfaceClass(StrEnum):
    MATTE_PATTERNED = "MATTE_PATTERNED"
    LOW_TEXTURE = "LOW_TEXTURE"
    DARK = "DARK"
    REFLECTIVE = "REFLECTIVE"
    UNSUPPORTED = "UNSUPPORTED"


class LightingClass(StrEnum):
    NORMAL = "NORMAL"
    LOW = "LOW"
    HIGH = "HIGH"


class FlowEnvironmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    surface: FlowSurfaceClass = FlowSurfaceClass.MATTE_PATTERNED
    lighting: LightingClass = LightingClass.NORMAL
    quality_scale: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def modeled_quality_scale(self) -> float:
        surface_scale = {
            FlowSurfaceClass.MATTE_PATTERNED: 1.0,
            FlowSurfaceClass.LOW_TEXTURE: 0.55,
            FlowSurfaceClass.DARK: 0.45,
            FlowSurfaceClass.REFLECTIVE: 0.35,
            FlowSurfaceClass.UNSUPPORTED: 0.0,
        }[self.surface]
        light_scale = {
            LightingClass.NORMAL: 1.0,
            LightingClass.LOW: 0.6,
            LightingClass.HIGH: 0.8,
        }[self.lighting]
        return self.quality_scale * surface_scale * light_scale


class DisturbanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_roll_rad: float = Field(default=0.0, ge=-0.35, le=0.35)
    initial_pitch_rad: float = Field(default=0.0, ge=-0.35, le=0.35)
    initial_velocity_m_s: Vector3 = Field(default_factory=Vector3)
    force_impulse_n_s: Vector3 = Field(default_factory=Vector3)
    force_impulse_at_s: float | None = Field(default=None, ge=0.0)


class SimulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int = 7
    controller_profile: ControllerProfile = ControllerProfile.ESTIMATOR_IN_LOOP_REFERENCE
    controller_nominal_mass_kg: float | None = Field(default=None, gt=0.0)
    controller_nominal_max_motor_thrust_n: float | None = Field(default=None, gt=0.0)
    fixed_step_s: float = Field(default=0.01, gt=0.0, le=0.05)
    clock_mode: ClockMode = ClockMode.ACCELERATED
    speed: float = Field(default=1.0, gt=0.0)
    command_latency_s: float = Field(default=0.02, ge=0.0)
    acknowledgement_latency_s: float = Field(default=0.01, ge=0.0)
    packet_loss_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    max_horizontal_speed_m_s: float = Field(default=0.7, gt=0.0)
    max_vertical_speed_m_s: float = Field(default=0.5, gt=0.0)
    max_acceleration_m_s2: float = Field(default=2.0, gt=0.0)
    max_yaw_rate_rad_s: float = Field(default=2.0, gt=0.0)
    battery_start_percent: float = Field(default=100.0, ge=0.0, le=100.0)
    # Accepted only for old scenarios; translated to an explicit parasitic current.
    battery_idle_drain_percent_s: float = Field(default=0.0, ge=0.0)
    battery_flight_drain_percent_s: float = Field(default=0.0, ge=0.0)
    battery_motion_drain_percent_m: float = Field(default=0.0, ge=0.0)
    low_battery_percent: float = Field(default=25.0, ge=0.0, le=100.0)
    critical_battery_percent: float = Field(default=10.0, ge=0.0, le=100.0)
    flow_drift_std_m_sqrt_s: float = Field(default=0.002, ge=0.0)
    position_noise_std_m: float = Field(default=0.001, ge=0.0)
    position_bias_m: Vector3 = Field(default_factory=Vector3)
    estimator_latency_s: float = Field(default=0.0, ge=0.0, le=1.0)
    estimator_error_clip_m: float | None = Field(default=None, gt=0.0)
    imu: ImuModelConfig = Field(default_factory=ImuModelConfig)
    flow: FlowModelConfig = Field(default_factory=FlowModelConfig)
    range_sensor: RangeModelConfig = Field(default_factory=RangeModelConfig)
    flow_environment: FlowEnvironmentConfig = Field(default_factory=FlowEnvironmentConfig)
    disturbance: DisturbanceConfig = Field(default_factory=DisturbanceConfig)
    range_noise_std_m: float = Field(default=0.002, ge=0.0)
    max_range_m: float = Field(default=4.0, gt=0.0)
    physics: PhysicsModelConfig = Field(default_factory=PhysicsModelConfig)

    @model_validator(mode="after")
    def legacy_energy_drain_is_v1_only(self) -> SimulationConfig:
        legacy_drain = (
            self.battery_idle_drain_percent_s,
            self.battery_flight_drain_percent_s,
            self.battery_motion_drain_percent_m,
        )
        if self.physics.model_version != "1.0.0" and any(value > 0.0 for value in legacy_drain):
            raise ValueError(
                "percentage-based battery drain is legacy-v1-only; model v2 derives "
                "energy use from electrical current"
            )
        return self

    def vehicle_parameters(self) -> VehicleParameterSchema:
        physics = self.physics
        is_physical_v2 = physics.powertrain_model is PowertrainModel.BATTERY_COUPLED_V2
        positions = physics.rotor_positions_body_m
        axes = physics.rotor_thrust_axes_body
        reaction_signs = physics.rotor_reaction_torque_signs
        rotors = (
            RotorParameters(
                rotor_id="M1",
                position_body_m=positions[0],
                thrust_axis_body=axes[0],
                rotation_direction="CCW",
                maximum_thrust_n=physics.max_motor_thrust_n * physics.motor_thrust_scales[0],
                reaction_torque_per_thrust_m=physics.yaw_moment_per_thrust_m,
                reaction_torque_sign=reaction_signs[0],
                thrust_curve_exponent=physics.thrust_curve_exponent,
                thrust_scale=physics.motor_thrust_scales[0],
                current_scale=physics.motor_current_scales[0],
                time_constant_scale=physics.motor_time_constant_scales[0],
            ),
            RotorParameters(
                rotor_id="M2",
                position_body_m=positions[1],
                thrust_axis_body=axes[1],
                rotation_direction="CW",
                maximum_thrust_n=physics.max_motor_thrust_n * physics.motor_thrust_scales[1],
                reaction_torque_per_thrust_m=physics.yaw_moment_per_thrust_m,
                reaction_torque_sign=reaction_signs[1],
                thrust_curve_exponent=physics.thrust_curve_exponent,
                thrust_scale=physics.motor_thrust_scales[1],
                current_scale=physics.motor_current_scales[1],
                time_constant_scale=physics.motor_time_constant_scales[1],
            ),
            RotorParameters(
                rotor_id="M3",
                position_body_m=positions[2],
                thrust_axis_body=axes[2],
                rotation_direction="CCW",
                maximum_thrust_n=physics.max_motor_thrust_n * physics.motor_thrust_scales[2],
                reaction_torque_per_thrust_m=physics.yaw_moment_per_thrust_m,
                reaction_torque_sign=reaction_signs[2],
                thrust_curve_exponent=physics.thrust_curve_exponent,
                thrust_scale=physics.motor_thrust_scales[2],
                current_scale=physics.motor_current_scales[2],
                time_constant_scale=physics.motor_time_constant_scales[2],
            ),
            RotorParameters(
                rotor_id="M4",
                position_body_m=positions[3],
                thrust_axis_body=axes[3],
                rotation_direction="CW",
                maximum_thrust_n=physics.max_motor_thrust_n * physics.motor_thrust_scales[3],
                reaction_torque_per_thrust_m=physics.yaw_moment_per_thrust_m,
                reaction_torque_sign=reaction_signs[3],
                thrust_curve_exponent=physics.thrust_curve_exponent,
                thrust_scale=physics.motor_thrust_scales[3],
                current_scale=physics.motor_current_scales[3],
                time_constant_scale=physics.motor_time_constant_scales[3],
            ),
        )
        sample_rate_hz = 1.0 / self.fixed_step_s
        sensors = (
            SensorParameters(
                sensor_id="imu-model-v1",
                signal="imu",
                frame=CoordinateFrame.BODY,
                sample_rate_hz=self.imu.sample_rate_hz if is_physical_v2 else sample_rate_hz,
                latency_s=self.imu.latency_s if is_physical_v2 else self.acknowledgement_latency_s,
                noise_std=(
                    max(self.imu.acceleration_noise_std_m_s2.model_dump().values())
                    if is_physical_v2
                    else 0.0
                ),
            ),
            SensorParameters(
                sensor_id="flow-model-v1",
                signal="optical-flow",
                frame=CoordinateFrame.BODY,
                sample_rate_hz=self.flow.sample_rate_hz if is_physical_v2 else sample_rate_hz,
                latency_s=(
                    self.flow.latency_s if is_physical_v2 else self.acknowledgement_latency_s
                ),
                noise_std=self.flow_drift_std_m_sqrt_s,
                minimum=0.0,
                clipping="CLAMP",
            ),
            SensorParameters(
                sensor_id="multiranger-model-v1",
                signal="range-rays",
                frame=CoordinateFrame.SENSOR,
                sample_rate_hz=(
                    self.range_sensor.sample_rate_hz if is_physical_v2 else sample_rate_hz
                ),
                latency_s=(
                    self.range_sensor.latency_s
                    if is_physical_v2
                    else self.acknowledgement_latency_s
                ),
                noise_std=self.range_noise_std_m,
                minimum=0.0,
                maximum=self.max_range_m,
                clipping="CLAMP",
            ),
            SensorParameters(
                sensor_id="position-estimator-model-v1",
                signal="position-estimate",
                frame=CoordinateFrame.HOME,
                sample_rate_hz=sample_rate_hz,
                latency_s=self.acknowledgement_latency_s,
                noise_std=self.position_noise_std_m,
            ),
        )
        return VehicleParameterSchema(
            schema_version=2 if is_physical_v2 else 1,
            parameter_set_id=f"{physics.model_id}-{physics.model_version}",
            model_id=physics.model_id,
            model_version=physics.model_version,
            parameter_source=physics.parameter_source,
            base_mass_kg=physics.mass_kg,
            payload_mass_kg=physics.payload_mass_kg,
            center_of_mass_body_m=physics.combined_center_of_mass_body_m,
            inertia=InertiaTensor(
                xx_kg_m2=physics.total_inertia_x_kg_m2,
                yy_kg_m2=physics.total_inertia_y_kg_m2,
                zz_kg_m2=physics.total_inertia_z_kg_m2,
            ),
            rotors=rotors,
            actuator=ActuatorParameters(
                response=(
                    "FIRST_ORDER_VOLTAGE_LIMITED_THRUST" if is_physical_v2 else "FIRST_ORDER_THRUST"
                ),
                time_constant_s=physics.motor_time_constant_s,
                battery_compensation_enabled=physics.battery_compensation_enabled,
            ),
            drag=DragParameters(
                linear_n_s_m=physics.linear_drag_n_s_m,
                angular_n_m_s=physics.angular_drag_n_m_s,
                aerodynamic_model=(
                    "BODY_AXIS_LINEAR_QUADRATIC" if is_physical_v2 else "LINEAR_BODY_APPROXIMATION"
                ),
                linear_body_scale=physics.linear_drag_body_scale,
                quadratic_body_n_s2_m2=physics.quadratic_drag_body_n_s2_m2,
                ground_effect_strength=physics.ground_effect_strength,
            ),
            battery=BatteryParameters(
                model=(
                    "OCV_COULOMB_LOAD_LINE_WITH_COMPENSATION"
                    if is_physical_v2
                    else "COULOMB_COUNTING_WITH_RESISTIVE_SAG"
                ),
                capacity_ah=physics.effective_battery_capacity_ah,
                full_voltage_v=physics.battery_full_voltage_v,
                empty_voltage_v=physics.battery_empty_voltage_v,
                cutoff_voltage_v=physics.battery_cutoff_voltage_v,
                internal_resistance_ohm=physics.battery_internal_resistance_ohm,
                idle_current_a=physics.battery_idle_current_a,
                maximum_motor_current_a=physics.motor_max_current_a,
                maximum_total_current_a=physics.battery_max_current_a,
                ocv_curve_soc_voltage=tuple(
                    (point.state_of_charge, point.voltage_v) for point in physics.battery_ocv_curve
                ),
                cutoff_persistence_s=physics.battery_cutoff_persistence_s,
                cutoff_recovery_hysteresis_v=physics.battery_cutoff_recovery_hysteresis_v,
            ),
            controller_limits=ControllerLimits(
                maximum_horizontal_speed_m_s=self.max_horizontal_speed_m_s,
                maximum_vertical_speed_m_s=self.max_vertical_speed_m_s,
                maximum_acceleration_m_s2=self.max_acceleration_m_s2,
                maximum_yaw_rate_rad_s=self.max_yaw_rate_rad_s,
                maximum_tilt_rad=physics.maximum_tilt_rad,
            ),
            sensors=sensors,
        )

    def signal_specifications(self) -> tuple[SignalSpecification, ...]:
        sample_rate_hz = 1.0 / self.fixed_step_s
        common = {
            "source_class": SourceClass.SIMULATED_MODEL,
            "presence": SignalPresence.REQUIRED,
            "nominal_sample_rate_hz": sample_rate_hz,
            "nominal_latency_s": self.acknowledgement_latency_s,
            "bias": 0.0,
            "dropout_probability": self.packet_loss_probability,
            "clipping": "NONE",
        }
        return (
            SignalSpecification(
                signal_id="position",
                unit="m",
                frame=CoordinateFrame.HOME,
                noise_std=self.position_noise_std_m,
                minimum=None,
                maximum=None,
                **common,
            ),
            SignalSpecification(
                signal_id="ground-truth-position",
                unit="m",
                frame=CoordinateFrame.WORLD,
                noise_std=0.0,
                minimum=None,
                maximum=None,
                **common,
            ),
            SignalSpecification(
                signal_id="velocity",
                unit="m/s",
                frame=CoordinateFrame.HOME,
                noise_std=0.0,
                minimum=None,
                maximum=None,
                **common,
            ),
            SignalSpecification(
                signal_id="attitude",
                unit="rad",
                frame=CoordinateFrame.BODY,
                noise_std=0.0,
                minimum=-math.pi,
                maximum=math.pi,
                **common,
            ),
            SignalSpecification(
                signal_id="imu",
                unit="m/s2,rad/s",
                frame=CoordinateFrame.BODY,
                nominal_sample_rate_hz=self.imu.sample_rate_hz,
                nominal_latency_s=self.imu.latency_s,
                noise_std=max(
                    max(self.imu.acceleration_noise_std_m_s2.model_dump().values()),
                    max(self.imu.angular_velocity_noise_std_rad_s.model_dump().values()),
                ),
                minimum=None,
                maximum=None,
                **{
                    key: value
                    for key, value in common.items()
                    if key not in {"nominal_sample_rate_hz", "nominal_latency_s", "noise_std"}
                },
            ),
            SignalSpecification(
                signal_id="flow",
                unit="m/s,m",
                frame=CoordinateFrame.BODY,
                nominal_sample_rate_hz=self.flow.sample_rate_hz,
                nominal_latency_s=self.flow.latency_s,
                noise_std=max(
                    self.flow.velocity_noise_std_m_s,
                    self.flow_drift_std_m_sqrt_s,
                ),
                minimum=0.0,
                maximum=None,
                clipping="CLAMP",
                **{
                    key: value
                    for key, value in common.items()
                    if key
                    not in {
                        "clipping",
                        "nominal_sample_rate_hz",
                        "nominal_latency_s",
                        "noise_std",
                    }
                },
            ),
            SignalSpecification(
                signal_id="ranges",
                unit="m",
                frame=CoordinateFrame.SENSOR,
                nominal_sample_rate_hz=self.range_sensor.sample_rate_hz,
                nominal_latency_s=self.range_sensor.latency_s,
                noise_std=self.range_noise_std_m,
                minimum=0.0,
                maximum=self.max_range_m,
                clipping="CLAMP",
                **{
                    key: value
                    for key, value in common.items()
                    if key
                    not in {
                        "clipping",
                        "nominal_sample_rate_hz",
                        "nominal_latency_s",
                        "noise_std",
                    }
                },
            ),
            SignalSpecification(
                signal_id="battery",
                unit="percent,V,A",
                frame=CoordinateFrame.BODY,
                noise_std=0.0,
                minimum=0.0,
                maximum=100.0,
                clipping="CLAMP",
                **{key: value for key, value in common.items() if key != "clipping"},
            ),
            SignalSpecification(
                signal_id="motors",
                unit="percent,N,A",
                frame=CoordinateFrame.BODY,
                noise_std=0.0,
                minimum=0.0,
                maximum=100.0,
                clipping="CLAMP",
                **{key: value for key, value in common.items() if key != "clipping"},
            ),
            SignalSpecification(
                signal_id="physical-radio-rssi",
                unit="dBm",
                frame=None,
                source_class=SourceClass.SIMULATED_MODEL,
                presence=SignalPresence.UNSUPPORTED,
                nominal_sample_rate_hz=None,
                nominal_latency_s=None,
                noise_std=None,
                bias=None,
                minimum=None,
                maximum=None,
                clipping="NONE",
                dropout_probability=None,
            ),
            SignalSpecification(
                signal_id="barometer-altitude",
                unit="m",
                frame=CoordinateFrame.BODY,
                source_class=SourceClass.SIMULATED_MODEL,
                presence=SignalPresence.UNSUPPORTED,
                nominal_sample_rate_hz=None,
                nominal_latency_s=None,
                noise_std=None,
                bias=None,
                minimum=None,
                maximum=None,
                clipping="NONE",
                dropout_probability=None,
            ),
        )


class FidelityOutputEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output: str
    unit: str
    frame: str
    model: str
    qualification: str = "SOFTWARE_VERIFIED_CONFIGURED_UNQUALIFIED"
    verified_by: tuple[str, ...]
    limitations: tuple[str, ...] = ()


class SimulationFidelityManifest(BaseModel):
    """Machine-readable statement of what the simulator does and does not model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_id: str = "crazyflie-6dof-v2"
    source_class: str = "SIMULATED_MODEL"
    model: str = "deterministic rigid-body 6-DOF quadrotor dynamics"
    qualification_report: str = "config/qualification/fast-sim-physical-v2.json"
    modeled_outputs: tuple[str, ...] = (
        "position",
        "position_estimate",
        "estimator-in-loop controller",
        "velocity",
        "quaternion attitude and angular velocity",
        "motor thrust and body torque",
        "gravity, translational acceleration, and linear drag",
        "battery state of charge, current, and voltage sag",
        "imu",
        "optical_flow",
        "range_rays",
        "command_transport",
    )
    output_evidence: tuple[FidelityOutputEvidence, ...] = (
        FidelityOutputEvidence(
            output="position",
            unit="m",
            frame="WORLD",
            model="rigid-body truth comparator, unavailable to the reference controller",
            verified_by=("tests/simulation/test_qualification.py::test_sensor_models_and_frames",),
        ),
        FidelityOutputEvidence(
            output="position_estimate",
            unit="m",
            frame="HOME",
            model="stateful seeded bias, accumulated Flow drift, noise, latency, and clipping",
            verified_by=(
                "tests/reality/test_estimator_and_health.py::test_flow_drift_is_accumulated_state_and_resets_deterministically",
            ),
            limitations=("not external ground truth", "not a firmware EKF implementation"),
        ),
        FidelityOutputEvidence(
            output="estimator-in-loop controller",
            unit="canonical state and motor command",
            frame="HOME,BODY",
            model="trajectory controller receives explicit estimated state, never physics truth",
            verified_by=(
                "tests/reality/test_estimator_and_health.py::test_operator_default_is_estimator_in_loop_and_pure_controller_has_no_truth_access",
            ),
            limitations=("not Crazyflie firmware controller-gain parity",),
        ),
        FidelityOutputEvidence(
            output="velocity",
            unit="m/s",
            frame="HOME",
            model="semi-implicit fixed-step rigid-body integration",
            verified_by=(
                "tests/simulation/test_qualification.py::test_cross_timestep_convergence",
            ),
        ),
        FidelityOutputEvidence(
            output="quaternion attitude and angular velocity",
            unit="quaternion,rad/s",
            frame="BODY",
            model="normalized Hamilton wxyz attitude integration",
            verified_by=(
                "tests/simulation/test_qualification.py::test_analytic_physics_invariants",
            ),
        ),
        FidelityOutputEvidence(
            output="motor thrust and body torque",
            unit="N,Nm,V,A,percent",
            frame="BODY",
            model=(
                "four X-layout first-order actuators with explicit rotor positions, "
                "cubic motor-voltage thrust, averaged current, and PWM saturation"
            ),
            verified_by=(
                "tests/simulation/test_physical_fidelity_v2.py::test_each_x_layout_rotor_has_firmware_force_torque_signs",
                "tests/simulation/test_physical_fidelity_v2.py::test_low_soc_compensation_uses_more_pwm_and_has_less_maximum_authority",
            ),
        ),
        FidelityOutputEvidence(
            output="gravity, translational acceleration, and linear drag",
            unit="m/s2,N",
            frame="WORLD",
            model="uniform gravity and body-axis linear/quadratic reduced-order drag",
            verified_by=(
                "tests/simulation/test_qualification.py::test_independent_free_fall_reference",
            ),
        ),
        FidelityOutputEvidence(
            output="battery state of charge, current, and voltage sag",
            unit="percent,A,V",
            frame="BODY",
            model=(
                "OCV table, Coulomb counting, bounded resistive load-line solve, total-current "
                "limit, filtered compensation, and persistent cutoff"
            ),
            verified_by=(
                "tests/simulation/test_physical_fidelity_v2.py::test_zero_soc_is_an_authoritative_cutoff_and_cannot_sustain_thrust",
                "tests/simulation/test_physical_fidelity_v2.py::test_undervoltage_cutoff_uses_persistence_not_a_single_crossing",
            ),
            limitations=("not endurance-qualified",),
        ),
        FidelityOutputEvidence(
            output="imu",
            unit="m/s2,rad/s,s",
            frame="BODY",
            model=(
                "independently sampled and held reduced-order IMU with configurable latency, "
                "bias, random walk, white noise, scale, misalignment, filtering, and clipping"
            ),
            verified_by=(
                "tests/simulation/test_physical_fidelity_v2.py::test_imu_sample_clock_and_snapshot_polling_are_independent",
                "tests/simulation/test_physical_fidelity_v2.py::test_configured_gyro_bias_reaches_estimator_controller_state",
            ),
            limitations=("default error coefficients are zero and unqualified",),
        ),
        FidelityOutputEvidence(
            output="optical_flow",
            unit="m/s,m,percent,s",
            frame="BODY",
            model=(
                "independently sampled and held body-velocity observation with latency, "
                "mounting, height, tilt, motion-blur, surface, lighting, noise, and dropout"
            ),
            verified_by=(
                "tests/simulation/test_physical_fidelity_v2.py::test_flow_and_range_have_independent_held_sample_clocks",
                "tests/simulation/test_physical_fidelity_v2.py::test_flow_quality_dropout_and_mounting_error_reach_estimator",
            ),
            limitations=("not a pixel-level optical model", "coefficients are unqualified"),
        ),
        FidelityOutputEvidence(
            output="range_rays",
            unit="m",
            frame="SENSOR",
            model=(
                "independently sampled and held attitude-transformed rays with latency, "
                "bias, noise, and valid/no-hit/clipped/stale/unavailable status"
            ),
            verified_by=(
                "tests/simulation/test_physical_fidelity_v2.py::test_flow_and_range_have_independent_held_sample_clocks",
                "tests/reality/test_estimator_and_health.py::test_range_no_hit_and_clipping_are_not_reported_as_valid",
            ),
            limitations=("beam/material/angle response is unsupported until evidenced",),
        ),
        FidelityOutputEvidence(
            output="command_transport",
            unit="s,percent",
            frame="transport",
            model="seeded latency and packet-loss model",
            verified_by=(
                "tests/simulation/test_qualification.py::test_seeded_transport_reproducibility",
            ),
            limitations=("no jitter or RF propagation model",),
        ),
    )
    omitted_outputs: tuple[str, ...] = (
        "physical_radio_rssi",
        "physical_radio_link_quality",
        "motor_rpm",
        "aerodynamic_wash",
        "camera_imagery",
        "transport_jitter",
        "resolved_contact_impulse",
        "inter_vehicle_aerodynamic_interaction",
        "barometer_altitude_observation",
    )
    assumptions: tuple[str, ...] = (
        "Crazyflie firmware-compatible X layout with four first-order thrust actuators",
        "normalized actuator command means desired thrust; applied PWM is separate state",
        "configured coefficients are unqualified until matched to hardware evidence",
        "axis-aligned configured room and obstacle geometry",
        "stateful seeded estimator bias/drift/noise and source-aware range status",
        "operator qualification selects ESTIMATOR_IN_LOOP_REFERENCE",
        "simulated decks are software models, not detected hardware",
    )
    limitations: tuple[str, ...] = (
        "not qualified for controller-gain or endurance prediction",
        (
            "does not model propeller RPM or aerodynamic wash; unqualified ground effect "
            "is disabled by default"
        ),
        "does not predict real radio performance",
        "collision is configured-geometry termination, not resolved crash dynamics",
        "vehicles have independent dynamics; separation is observed, not aerodynamically coupled",
        "IDEAL_TRUTH_TEST_ONLY is restricted to analytic tests and is not hardware fidelity",
    )

    @model_validator(mode="after")
    def every_modeled_output_has_evidence(self) -> SimulationFidelityManifest:
        if {item.output for item in self.output_evidence} != set(self.modeled_outputs):
            raise ValueError("every modeled output requires exactly one fidelity evidence entry")
        return self


DEFAULT_FIDELITY_MANIFEST = SimulationFidelityManifest()
