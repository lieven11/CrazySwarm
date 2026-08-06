from __future__ import annotations

import math

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


class SimulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int = 7
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
    range_noise_std_m: float = Field(default=0.002, ge=0.0)
    max_range_m: float = Field(default=4.0, gt=0.0)
    physics: PhysicsModelConfig = Field(default_factory=PhysicsModelConfig)

    def vehicle_parameters(self) -> VehicleParameterSchema:
        physics = self.physics
        arm = physics.arm_length_m
        rotors = (
            RotorParameters(
                rotor_id="M1",
                position_body_m=Vector3(x=arm),
                thrust_axis_body=Vector3(z=1.0),
                rotation_direction="CCW",
                maximum_thrust_n=physics.max_motor_thrust_n,
                reaction_torque_per_thrust_m=physics.yaw_moment_per_thrust_m,
                thrust_curve_exponent=physics.thrust_curve_exponent,
            ),
            RotorParameters(
                rotor_id="M2",
                position_body_m=Vector3(y=arm),
                thrust_axis_body=Vector3(z=1.0),
                rotation_direction="CW",
                maximum_thrust_n=physics.max_motor_thrust_n,
                reaction_torque_per_thrust_m=physics.yaw_moment_per_thrust_m,
                thrust_curve_exponent=physics.thrust_curve_exponent,
            ),
            RotorParameters(
                rotor_id="M3",
                position_body_m=Vector3(x=-arm),
                thrust_axis_body=Vector3(z=1.0),
                rotation_direction="CCW",
                maximum_thrust_n=physics.max_motor_thrust_n,
                reaction_torque_per_thrust_m=physics.yaw_moment_per_thrust_m,
                thrust_curve_exponent=physics.thrust_curve_exponent,
            ),
            RotorParameters(
                rotor_id="M4",
                position_body_m=Vector3(y=-arm),
                thrust_axis_body=Vector3(z=1.0),
                rotation_direction="CW",
                maximum_thrust_n=physics.max_motor_thrust_n,
                reaction_torque_per_thrust_m=physics.yaw_moment_per_thrust_m,
                thrust_curve_exponent=physics.thrust_curve_exponent,
            ),
        )
        sample_rate_hz = 1.0 / self.fixed_step_s
        sensors = (
            SensorParameters(
                sensor_id="imu-model-v1",
                signal="imu",
                frame=CoordinateFrame.BODY,
                sample_rate_hz=sample_rate_hz,
                latency_s=self.acknowledgement_latency_s,
                noise_std=0.0,
            ),
            SensorParameters(
                sensor_id="flow-model-v1",
                signal="optical-flow",
                frame=CoordinateFrame.BODY,
                sample_rate_hz=sample_rate_hz,
                latency_s=self.acknowledgement_latency_s,
                noise_std=self.flow_drift_std_m_sqrt_s,
                minimum=0.0,
                clipping="CLAMP",
            ),
            SensorParameters(
                sensor_id="multiranger-model-v1",
                signal="range-rays",
                frame=CoordinateFrame.SENSOR,
                sample_rate_hz=sample_rate_hz,
                latency_s=self.acknowledgement_latency_s,
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
            parameter_set_id=f"{physics.model_id}-{physics.model_version}",
            model_id=physics.model_id,
            model_version=physics.model_version,
            parameter_source="CONFIGURED_UNQUALIFIED",
            base_mass_kg=physics.mass_kg,
            payload_mass_kg=physics.payload_mass_kg,
            center_of_mass_body_m=physics.center_of_mass_body_m,
            inertia=InertiaTensor(
                xx_kg_m2=physics.inertia_x_kg_m2,
                yy_kg_m2=physics.inertia_y_kg_m2,
                zz_kg_m2=physics.inertia_z_kg_m2,
            ),
            rotors=rotors,
            actuator=ActuatorParameters(time_constant_s=physics.motor_time_constant_s),
            drag=DragParameters(
                linear_n_s_m=physics.linear_drag_n_s_m,
                angular_n_m_s=physics.angular_drag_n_m_s,
            ),
            battery=BatteryParameters(
                capacity_ah=physics.battery_capacity_ah,
                full_voltage_v=physics.battery_full_voltage_v,
                empty_voltage_v=physics.battery_empty_voltage_v,
                cutoff_voltage_v=physics.battery_cutoff_voltage_v,
                internal_resistance_ohm=physics.battery_internal_resistance_ohm,
                idle_current_a=physics.battery_idle_current_a,
                maximum_motor_current_a=physics.motor_max_current_a,
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
                noise_std=0.0,
                minimum=None,
                maximum=None,
                **common,
            ),
            SignalSpecification(
                signal_id="flow",
                unit="m/s,m",
                frame=CoordinateFrame.BODY,
                noise_std=self.flow_drift_std_m_sqrt_s,
                minimum=0.0,
                maximum=None,
                clipping="CLAMP",
                **{key: value for key, value in common.items() if key != "clipping"},
            ),
            SignalSpecification(
                signal_id="ranges",
                unit="m",
                frame=CoordinateFrame.SENSOR,
                noise_std=self.range_noise_std_m,
                minimum=0.0,
                maximum=self.max_range_m,
                clipping="CLAMP",
                **{key: value for key, value in common.items() if key != "clipping"},
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

    manifest_id: str = "crazyflie-6dof-v1"
    source_class: str = "SIMULATED_MODEL"
    model: str = "deterministic rigid-body 6-DOF quadrotor dynamics"
    qualification_report: str = "config/qualification/fast-sim-v1.json"
    modeled_outputs: tuple[str, ...] = (
        "position",
        "position_estimate",
        "velocity",
        "quaternion attitude and angular velocity",
        "motor thrust and body torque",
        "gravity, translational acceleration, and linear drag",
        "battery state of charge, current, and voltage sag",
        "optical_flow",
        "range_rays",
        "command_transport",
    )
    output_evidence: tuple[FidelityOutputEvidence, ...] = (
        FidelityOutputEvidence(
            output="position",
            unit="m",
            frame="HOME",
            model="seeded position estimator over rigid-body truth",
            verified_by=("tests/simulation/test_qualification.py::test_sensor_models_and_frames",),
        ),
        FidelityOutputEvidence(
            output="position_estimate",
            unit="m",
            frame="HOME",
            model="seeded noise and flow-drift approximation",
            verified_by=("tests/simulation/test_qualification.py::test_sensor_models_and_frames",),
            limitations=("not external ground truth",),
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
            unit="N,Nm",
            frame="BODY",
            model="four first-order thrust actuators in plus layout",
            verified_by=(
                "tests/simulation/test_qualification.py::test_independent_actuator_reference",
            ),
        ),
        FidelityOutputEvidence(
            output="gravity, translational acceleration, and linear drag",
            unit="m/s2,N",
            frame="WORLD",
            model="uniform gravity and linear drag",
            verified_by=(
                "tests/simulation/test_qualification.py::test_independent_free_fall_reference",
            ),
        ),
        FidelityOutputEvidence(
            output="battery state of charge, current, and voltage sag",
            unit="percent,A,V",
            frame="BODY",
            model="coulomb counting and resistive sag with cutoff",
            verified_by=("tests/simulation/test_qualification.py::test_battery_energy_and_cutoff",),
            limitations=("not endurance-qualified",),
        ),
        FidelityOutputEvidence(
            output="optical_flow",
            unit="m/s,m,percent",
            frame="BODY",
            model="body velocity and tilt/height quality approximation",
            verified_by=("tests/simulation/test_qualification.py::test_sensor_models_and_frames",),
            limitations=("not a pixel-level optical model",),
        ),
        FidelityOutputEvidence(
            output="range_rays",
            unit="m",
            frame="SENSOR",
            model="attitude-transformed rays against configured axis-aligned geometry",
            verified_by=("tests/simulation/test_qualification.py::test_sensor_models_and_frames",),
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
    )
    assumptions: tuple[str, ...] = (
        "plus-layout rigid body with four first-order thrust actuators",
        "configured coefficients are unqualified until matched to hardware evidence",
        "axis-aligned configured room and obstacle geometry",
        "seeded estimator and range noise",
        "simulated decks are software models, not detected hardware",
    )
    limitations: tuple[str, ...] = (
        "not qualified for controller-gain or endurance prediction",
        "does not model propeller RPM, ground effect, or aerodynamic wash",
        "does not predict real radio performance",
        "collision is configured-geometry termination, not resolved crash dynamics",
        "vehicles have independent dynamics; separation is observed, not aerodynamically coupled",
    )

    @model_validator(mode="after")
    def every_modeled_output_has_evidence(self) -> SimulationFidelityManifest:
        if {item.output for item in self.output_evidence} != set(self.modeled_outputs):
            raise ValueError("every modeled output requires exactly one fidelity evidence entry")
        return self


DEFAULT_FIDELITY_MANIFEST = SimulationFidelityManifest()
