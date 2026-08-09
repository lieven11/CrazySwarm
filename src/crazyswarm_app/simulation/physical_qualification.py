from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections.abc import Mapping
from typing import Any

from crazyswarm_app.domain.models import Vector3, VehicleIdentity
from crazyswarm_app.domain.telemetry import FlowStatus
from crazyswarm_app.simulation.models import (
    FlowEnvironmentConfig,
    FlowSurfaceClass,
    LightingClass,
    SimulationConfig,
)
from crazyswarm_app.simulation.physics import PhysicsModelConfig, SixDofPhysics
from crazyswarm_app.simulation.sensors import FlowModelConfig, ImuModelConfig, RangeModelConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig

SOC_PERCENTAGES = (100.0, 50.0, 30.0, 20.0, 10.0, 5.0, 0.0)
FIXED_STEPS_S = (0.005, 0.01, 0.02)
SEEDS = (311, 907, 1601)


def _physics_config(**updates: object) -> PhysicsModelConfig:
    payload = PhysicsModelConfig().model_dump(mode="python")
    payload.update(updates)
    return PhysicsModelConfig.model_validate(payload)


def _round(value: float) -> float:
    return round(value, 9)


def _run_plant(
    config: PhysicsModelConfig,
    *,
    state_of_charge_percent: float,
    command: float,
    fixed_step_s: float,
    duration_s: float = 2.0,
    actuator_health_scales: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
) -> dict[str, Any]:
    physics = SixDofPhysics(
        config,
        position_m=Vector3(z=2.0),
        battery_percent=state_of_charge_percent,
    )
    energy_wh = 0.0
    minimum_voltage_v = math.inf
    maximum_current_a = 0.0
    for _ in range(round(duration_s / fixed_step_s)):
        physics.step(
            (command, command, command, command),
            fixed_step_s,
            actuator_health_scales=actuator_health_scales,
        )
        energy_wh += (
            physics.state.battery_voltage_v
            * physics.state.battery_current_a
            * fixed_step_s
            / 3600.0
        )
        minimum_voltage_v = min(minimum_voltage_v, physics.state.battery_voltage_v)
        maximum_current_a = max(maximum_current_a, physics.state.battery_current_a)
    motors = physics.state.motors
    cutoff_reason = physics.state.battery_cutoff_reason
    return {
        "terminal_voltage_v": _round(physics.state.battery_voltage_v),
        "minimum_terminal_voltage_v": _round(minimum_voltage_v),
        "maximum_current_a": _round(maximum_current_a),
        "total_current_a": _round(physics.state.battery_current_a),
        "total_thrust_n": _round(sum(motor.thrust_n for motor in motors)),
        "requested_thrust_n": _round(sum(motor.requested_thrust_n for motor in motors)),
        "maximum_applied_pwm_percent": _round(max(motor.applied_pwm for motor in motors) * 100.0),
        "minimum_available_thrust_n": _round(min(motor.available_thrust_n for motor in motors)),
        "energy_used_wh": _round(energy_wh),
        "final_state_of_charge_percent": _round(physics.state.battery_state_of_charge * 100.0),
        "saturated": any(motor.saturated for motor in motors),
        "current_limited": physics.state.powertrain_current_limited,
        "cutoff": physics.state.battery_cutoff_active,
        "cutoff_reason": None if cutoff_reason is None else cutoff_reason.value,
        "finite": all(
            math.isfinite(value)
            for value in (
                *physics.state.position_m.model_dump().values(),
                *physics.state.velocity_m_s.model_dump().values(),
                *physics.state.angular_velocity_body_rad_s.model_dump().values(),
            )
        ),
    }


def _powertrain_matrix() -> list[dict[str, Any]]:
    conditions: Mapping[str, Mapping[str, object]] = {
        "nominal": {},
        "increased_resistance": {"battery_resistance_scale": 1.5},
        "reduced_capacity": {"battery_capacity_scale": 0.8},
        "temperature_and_age": {
            "battery_temperature_capacity_scale": 0.9,
            "battery_age_capacity_scale": 0.9,
        },
    }
    matrix: list[dict[str, Any]] = []
    for condition, updates in conditions.items():
        config = _physics_config(**dict(updates))
        hover_command = (
            config.total_mass_kg * config.gravity_m_s2 / (4.0 * config.max_motor_thrust_n)
        )
        for state_of_charge_percent in SOC_PERCENTAGES:
            for load, command in (("hover", hover_command), ("maximum_collective", 1.0)):
                for fixed_step_s in FIXED_STEPS_S:
                    matrix.append(
                        {
                            "condition": condition,
                            "state_of_charge_percent": state_of_charge_percent,
                            "load": load,
                            "fixed_step_s": fixed_step_s,
                            "metrics": _run_plant(
                                config,
                                state_of_charge_percent=state_of_charge_percent,
                                command=command,
                                fixed_step_s=fixed_step_s,
                            ),
                        }
                    )
    return matrix


def _mechanical_matrix() -> list[dict[str, Any]]:
    cases: Mapping[str, Mapping[str, object]] = {
        "nominal": {},
        "mass_plus_10_percent": {"mass_kg": PhysicsModelConfig().mass_kg * 1.1},
        "offset_payload": {
            "payload_mass_kg": 0.01,
            "payload_position_body_m": Vector3(x=0.02),
        },
        "motor_mismatch": {
            "motor_thrust_scales": (0.8, 1.0, 1.0, 1.0),
            "motor_current_scales": (0.9, 1.0, 1.0, 1.0),
            "motor_time_constant_scales": (1.2, 1.0, 1.0, 1.0),
        },
    }
    matrix: list[dict[str, Any]] = []
    for case, updates in cases.items():
        config = _physics_config(**dict(updates))
        command = config.total_mass_kg * config.gravity_m_s2 / (4.0 * config.max_motor_thrust_n)
        matrix.append(
            {
                "case": case,
                "metrics": _run_plant(
                    config,
                    state_of_charge_percent=100.0,
                    command=command,
                    fixed_step_s=0.01,
                ),
            }
        )
    for case, health in (
        ("motor_1_degraded", (0.5, 1.0, 1.0, 1.0)),
        ("motor_1_loss", (0.0, 1.0, 1.0, 1.0)),
    ):
        matrix.append(
            {
                "case": case,
                "metrics": _run_plant(
                    PhysicsModelConfig(),
                    state_of_charge_percent=100.0,
                    command=0.7,
                    fixed_step_s=0.01,
                    actuator_health_scales=health,
                ),
            }
        )
    return matrix


async def _sensor_case(case: str, seed: int) -> dict[str, Any]:
    config_updates: dict[str, object] = {
        "seed": seed,
        "position_noise_std_m": 0.0,
        "flow_drift_std_m_sqrt_s": 0.0,
        "range_noise_std_m": 0.0,
    }
    if case == "imu_latency_bias":
        config_updates["imu"] = ImuModelConfig(
            sample_rate_hz=50.0,
            latency_s=0.02,
            angular_velocity_bias_rad_s=Vector3(z=0.05),
        )
    elif case == "flow_degraded":
        config_updates["flow_environment"] = FlowEnvironmentConfig(
            surface=FlowSurfaceClass.LOW_TEXTURE,
            lighting=LightingClass.LOW,
        )
    elif case == "flow_dropout":
        config_updates["flow"] = FlowModelConfig(dropout_probability=1.0)
    elif case == "range_latency_bias":
        config_updates["range_sensor"] = RangeModelConfig(
            sample_rate_hz=20.0,
            latency_s=0.05,
            bias_m=0.01,
        )
    config = SimulationConfig.model_validate(config_updates)
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id=f"sensor-{case}-{seed}", display_name=case, adapter="sim"),
        IndoorWorld(WorldConfig()),
        config=config,
        initial_position_m=Vector3(z=0.5),
    )
    vehicle.physics.state.velocity_m_s = Vector3(x=0.2)
    for _ in range(20):
        await vehicle._step(0.01, motor_commands=(0.65, 0.65, 0.65, 0.65))
    sample = (await vehicle.snapshot()).telemetry
    flow = sample.flow
    ranges = sample.ranges
    imu = sample.imu
    return {
        "case": case,
        "seed": seed,
        "flow_status": None if flow is None else flow.status.value,
        "flow_quality_percent": None if flow is None else _round(flow.quality_percent),
        "flow_timestamp_s": None if flow is None else flow.source_timestamp_s,
        "range_timestamp_s": None if ranges is None else ranges.source_timestamp_s,
        "range_statuses": (
            {}
            if ranges is None
            else {name: status.value for name, status in sorted(ranges.statuses.items())}
        ),
        "imu_timestamp_s": None if imu is None else imu.source_timestamp_s,
        "estimated_velocity_m_s": vehicle._estimated_velocity.model_dump(mode="json"),
        "finite": all(
            math.isfinite(value) for value in vehicle._estimated_position.model_dump().values()
        ),
    }


async def _sensor_matrix() -> list[dict[str, Any]]:
    return [
        await _sensor_case(case, seed)
        for case in (
            "nominal",
            "imu_latency_bias",
            "flow_degraded",
            "flow_dropout",
            "range_latency_bias",
        )
        for seed in SEEDS
    ]


def _aerodynamic_matrix() -> dict[str, Any]:
    drag = _physics_config(
        linear_drag_body_scale=Vector3(x=2.0, y=1.0, z=0.5),
        quadratic_drag_body_n_s2_m2=Vector3(x=0.02, y=0.01, z=0.005),
    )
    drag_physics = SixDofPhysics(
        drag,
        position_m=Vector3(z=2.0),
        initial_velocity_m_s=Vector3(x=1.0, y=-0.5),
    )
    kinetic_before = (
        0.5
        * drag.total_mass_kg
        * (drag_physics.state.velocity_m_s.x**2 + drag_physics.state.velocity_m_s.y**2)
    )
    drag_physics.step((0.0, 0.0, 0.0, 0.0), 0.01)
    kinetic_after = (
        0.5
        * drag.total_mass_kg
        * (drag_physics.state.velocity_m_s.x**2 + drag_physics.state.velocity_m_s.y**2)
    )

    ground_effect = _physics_config(
        ground_effect_strength=0.2,
        ground_effect_maximum_multiplier=1.15,
    )
    height_matrix: list[dict[str, float]] = []
    for height_m in (0.01, 0.06, 0.12, 0.3):
        physics = SixDofPhysics(ground_effect, position_m=Vector3(z=height_m))
        physics.step((0.7, 0.7, 0.7, 0.7), 0.01)
        height_matrix.append(
            {
                "height_m": height_m,
                "vertical_acceleration_m_s2": _round(physics.state.acceleration_world_m_s2.z),
            }
        )
    return {
        "drag_energy_before_j": _round(kinetic_before),
        "drag_energy_after_j": _round(kinetic_after),
        "drag_dissipative": kinetic_after < kinetic_before,
        "ground_effect_height_matrix": height_matrix,
    }


def _model_comparison() -> list[dict[str, Any]]:
    comparison: list[dict[str, Any]] = []
    for state_of_charge_percent in (100.0, 5.0, 0.0):
        for version, config in (
            ("1.0.0", PhysicsModelConfig.legacy_v1()),
            ("2.0.0", PhysicsModelConfig()),
        ):
            comparison.append(
                {
                    "model_version": version,
                    "state_of_charge_percent": state_of_charge_percent,
                    "metrics": _run_plant(
                        config,
                        state_of_charge_percent=state_of_charge_percent,
                        command=0.7,
                        fixed_step_s=0.01,
                    ),
                }
            )
    return comparison


def _long_duration_and_performance() -> dict[str, Any]:
    config = PhysicsModelConfig()
    command = config.total_mass_kg * config.gravity_m_s2 / (4.0 * config.max_motor_thrust_n)
    long_duration = _run_plant(
        config,
        state_of_charge_percent=100.0,
        command=command,
        fixed_step_s=0.01,
        duration_s=120.0,
    )
    simulated_duration_s = 30.0
    steps = round(simulated_duration_s / 0.01)
    start = time.perf_counter()
    vehicles = [
        SixDofPhysics(config, position_m=Vector3(x=float(index), z=1.0)) for index in range(3)
    ]
    for _ in range(steps):
        for vehicle in vehicles:
            vehicle.step((command, command, command, command), 0.01)
    wall_duration_s = time.perf_counter() - start
    represented_vehicle_seconds = simulated_duration_s * len(vehicles)
    return {
        "long_duration_simulated_s": 120.0,
        "long_duration_metrics": long_duration,
        "performance_vehicle_count": len(vehicles),
        "performance_simulated_s_per_vehicle": simulated_duration_s,
        "performance_wall_s": round(wall_duration_s, 6),
        "represented_vehicle_seconds_per_wall_second": round(
            represented_vehicle_seconds / wall_duration_s,
            3,
        ),
        "faster_than_wall_time": wall_duration_s < simulated_duration_s,
        "all_final_states_finite": all(
            all(
                math.isfinite(value)
                for value in (
                    *vehicle.state.position_m.model_dump().values(),
                    *vehicle.state.velocity_m_s.model_dump().values(),
                )
            )
            for vehicle in vehicles
        ),
    }


def _verified_invariants(
    powertrain_matrix: list[dict[str, Any]],
    mechanical_matrix: list[dict[str, Any]],
    sensor_matrix: list[dict[str, Any]],
    aerodynamics: dict[str, Any],
    performance: dict[str, Any],
) -> dict[str, bool]:
    zero_soc = [item for item in powertrain_matrix if item["state_of_charge_percent"] == 0.0]
    nominal_maximum = [
        item
        for item in powertrain_matrix
        if item["condition"] == "nominal"
        and item["load"] == "maximum_collective"
        and item["fixed_step_s"] == 0.01
    ]
    by_soc = {item["state_of_charge_percent"]: item["metrics"] for item in nominal_maximum}
    actuator_loss = next(item for item in mechanical_matrix if item["case"] == "motor_1_loss")
    return {
        "zero_soc_sustained_thrust_impossible": all(
            item["metrics"]["total_thrust_n"] == 0.0 and item["metrics"]["cutoff"]
            for item in zero_soc
        ),
        "lower_soc_reduces_maximum_collective_thrust": (
            by_soc[5.0]["total_thrust_n"] < by_soc[100.0]["total_thrust_n"]
        ),
        "total_current_is_bounded": all(
            item["metrics"]["maximum_current_a"]
            <= PhysicsModelConfig().battery_max_current_a + 1e-7
            for item in powertrain_matrix
        ),
        "all_powertrain_states_finite": all(
            item["metrics"]["finite"] for item in powertrain_matrix
        ),
        "actuator_loss_reduces_available_authority": (
            actuator_loss["metrics"]["minimum_available_thrust_n"] == 0.0
        ),
        "sensor_cases_are_finite": all(item["finite"] for item in sensor_matrix),
        "flow_dropout_is_explicit": all(
            item["flow_status"] == FlowStatus.UNAVAILABLE.value
            for item in sensor_matrix
            if item["case"] == "flow_dropout"
        ),
        "drag_is_dissipative": bool(aerodynamics["drag_dissipative"]),
        "long_duration_is_finite": bool(performance["long_duration_metrics"]["finite"]),
        "three_vehicle_workload_is_faster_than_wall_time": bool(
            performance["faster_than_wall_time"]
        ),
    }


def _normalized_report_sha256(report: Mapping[str, Any]) -> str:
    normalized_report = dict(report)
    normalized_report.pop("normalized_report_sha256", None)
    normalized_performance = dict(report["performance_and_long_duration"])
    normalized_performance.pop("performance_wall_s")
    normalized_performance.pop("represented_vehicle_seconds_per_wall_second")
    normalized_report["performance_and_long_duration"] = normalized_performance
    normalized = json.dumps(
        normalized_report,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(normalized).hexdigest()


async def build_fast_sim_physical_v2_report() -> dict[str, Any]:
    powertrain_matrix = _powertrain_matrix()
    mechanical_matrix = _mechanical_matrix()
    sensor_matrix = await _sensor_matrix()
    aerodynamics = _aerodynamic_matrix()
    comparison = _model_comparison()
    performance = _long_duration_and_performance()
    invariants = _verified_invariants(
        powertrain_matrix,
        mechanical_matrix,
        sensor_matrix,
        aerodynamics,
        performance,
    )
    report: dict[str, Any] = {
        "schema_version": 2,
        "qualification_id": "fast-sim-physical-v2-software",
        "decision": (
            "SOFTWARE_QUALIFIED_CONFIGURED_UNQUALIFIED"
            if all(invariants.values())
            else "FAILED_SOFTWARE_QUALIFICATION"
        ),
        "model_id": "crazyflie-6dof",
        "model_version": "2.0.0",
        "parameter_source": "CONFIGURED_UNQUALIFIED",
        "hardware_qualified": False,
        "digital_twin_claim": False,
        "failure_repetitions_per_class": 100,
        "actuator_command_semantics": "NORMALIZED_DESIRED_THRUST",
        "state_of_charge_percentages": list(SOC_PERCENTAGES),
        "fixed_steps_s": list(FIXED_STEPS_S),
        "seeds": list(SEEDS),
        "powertrain_matrix": powertrain_matrix,
        "mechanical_and_actuator_matrix": mechanical_matrix,
        "sensor_matrix": sensor_matrix,
        "aerodynamic_matrix": aerodynamics,
        "model_v1_v2_comparison": comparison,
        "performance_and_long_duration": performance,
        "verified_invariants": invariants,
        "verification_tests": [
            "tests/simulation/test_physical_fidelity_v2.py",
            "tests/simulation/test_physics.py",
            "tests/simulation/test_qualification.py",
            "tests/reality/test_estimator_and_health.py",
        ],
        "external_evidence": {
            "exact_aircraft_bench": "NOT_RUN",
            "contained_flight": "NOT_RUN",
            "isaac": "NOT_RUN",
        },
        "normalized_report_exclusions": [
            "performance_and_long_duration.performance_wall_s",
            "performance_and_long_duration.represented_vehicle_seconds_per_wall_second",
        ],
        "claim_limit": (
            "Software-qualified configured model only; exact-aircraft performance, "
            "endurance, controller transfer, and digital-twin claims require Reality "
            "WP-04 through WP-06 evidence."
        ),
    }
    report["normalized_report_sha256"] = _normalized_report_sha256(report)
    return report


def run_fast_sim_physical_v2_qualification() -> dict[str, Any]:
    return asyncio.run(build_fast_sim_physical_v2_report())
