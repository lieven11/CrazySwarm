from __future__ import annotations

import math
from itertools import pairwise

import pytest

from crazyswarm_app.domain.commands import LandCommand
from crazyswarm_app.domain.goals import GoalFailureAction, LandingGoalRegion
from crazyswarm_app.domain.models import (
    Vector3,
    VehicleCapabilities,
    VehicleCapability,
    VehicleIdentity,
)
from crazyswarm_app.domain.trajectory import (
    AcceptedExecutionProgram,
    ExecutionOperation,
    LandExecutionOperation,
    TrajectoryExecutionOperation,
)
from crazyswarm_app.fleet.artifacts import ExecutionBackend
from crazyswarm_app.fleet.planning import plan_mission_deployment
from crazyswarm_app.missions.models import MissionResult, MissionStatus
from crazyswarm_app.missions.planning import (
    MissionPlanReceipt,
    MissionPlanStatus,
    build_mission_plan,
)
from crazyswarm_app.missions.registry import MissionRegistry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.missions.script import ScriptMission, parse_python_mission
from crazyswarm_app.safety.policy import SafetyPolicy
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig

ROUTE_SOURCE = """\
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    for _ in range(24):
        await drone.move_relative(x_m=0.1, duration_s=0.8, frame="home")
    await drone.land(duration_s=2.0)
"""


class NoTrajectoryVehicle(SimulatedVehicle):
    @property
    def capabilities(self) -> VehicleCapabilities:
        return super().capabilities.model_copy(
            update={
                "features": super().capabilities.features
                - {VehicleCapability.TIME_PARAMETERIZED_TRAJECTORY}
            }
        )


async def _run_route(
    clock_mode: ClockMode,
    *,
    landing_goal_offset_x_m: float = 0.0,
    diversion_target_m: Vector3 | None = None,
) -> tuple[
    MissionResult,
    SimulatedVehicle,
    MissionPlanReceipt,
    TrajectoryExecutionOperation,
]:
    record = parse_python_mission(
        filename="continuous_route.py",
        name="Continuous route",
        source=ROUTE_SOURCE,
    )
    home = Vector3(x=-1.2)
    deployment = plan_mission_deployment(
        record,
        backend=ExecutionBackend.FAST_SIM,
        required_capabilities=frozenset(),
        implicit_vehicle_id="sim01",
        implicit_display_name="Continuous route vehicle",
        implicit_home=home,
        world_minimum_m=Vector3(x=-2.0, y=-2.0, z=0.0),
        world_maximum_m=Vector3(x=2.0, y=2.0, z=1.0),
    )
    plan = await build_mission_plan(
        record,
        deployment.deployment,
        deployment.assignments,
        SafetyPolicy(),
    )
    assert plan.status is MissionPlanStatus.APPROVED
    assert len(plan.execution_programs) == 1
    program = plan.execution_programs[0]
    if landing_goal_offset_x_m or diversion_target_m is not None:
        operations: list[ExecutionOperation] = []
        for operation in program.operations:
            if not isinstance(operation, LandExecutionOperation):
                operations.append(operation)
                continue
            goal = operation.goal_region
            assert goal is not None
            goal_update: dict[str, object] = {
                "goal_id": f"{goal.goal_id}-offset",
                "landing_target_m": goal.landing_target_m.model_copy(
                    update={"x": goal.landing_target_m.x + landing_goal_offset_x_m}
                ),
                "approach_point_m": goal.approach_point_m.model_copy(
                    update={"x": goal.approach_point_m.x + landing_goal_offset_x_m}
                ),
            }
            if diversion_target_m is not None:
                goal_update.update(
                    {
                        "maximum_correction_attempts": 0,
                        "failure_action": GoalFailureAction.DIVERT,
                        "diversion_target_m": diversion_target_m,
                    }
                )
            operations.append(
                operation.model_copy(
                    update={
                        "goal_region": goal.model_copy(update=goal_update)
                    }
                )
            )
        program = AcceptedExecutionProgram.model_validate(
            {**program.model_dump(mode="python"), "operations": tuple(operations)}
        )
    trajectory_operation = next(
        operation
        for operation in program.operations
        if isinstance(operation, TrajectoryExecutionOperation)
    )

    registry = MissionRegistry()
    registry.register(ScriptMission(record))
    supervisor = SafetySupervisor()
    config = SimulationConfig().model_copy(update={"clock_mode": clock_mode, "speed": 1.0})
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="sim01", display_name="Sim", adapter="sim"),
        IndoorWorld(WorldConfig(width_m=4.0, depth_m=4.0, height_m=1.0)),
        config=config,
        initial_position_m=home,
    )
    supervisor.register_vehicle(vehicle)
    result = await MissionRunner(supervisor, registry).run(
        record.mission_id,
        "sim01",
        mission_role_id="primary",
        accepted_plan_id=plan.plan_id,
        accepted_plan_sha256=plan.sha256,
        accepted_execution_program=program,
    )
    return result, vehicle, plan, trajectory_operation


@pytest.mark.asyncio
@pytest.mark.parametrize("clock_mode", [ClockMode.ACCELERATED, ClockMode.REALTIME])
async def test_canonical_route_is_authoritative_continuous_and_clock_invariant(
    clock_mode: ClockMode,
) -> None:
    result, vehicle, plan, operation = await _run_route(clock_mode)
    assert result.status is MissionStatus.SUCCEEDED
    assert result.reason_code == "MISSION_COMPLETED"
    assert result.accepted_plan_id == plan.plan_id
    assert result.accepted_plan_sha256 == plan.sha256
    assert result.execution_program_sha256 == plan.execution_programs[0].sha256
    assert result.accepted_trajectory_sha256s == (operation.trajectory_sha256,)
    assert result.execution_clock_policy == "ACCELERATED_OR_REALTIME"
    assert [item["action"] for item in result.normalized_intent_trace] == [
        "takeoff",
        "execute_trajectory",
        "land",
    ]
    assert len(result.goal_captures) == 1
    capture = result.goal_captures[0]
    assert capture["outcome"] == "CAPTURED"
    assert capture["descent_authorized"] is True
    assert capture["attempt_count"] >= 1
    assert capture["terminal_state"] == "READY"
    assert capture["terminal_contact"] == "SIMULATED_GROUND_CONTACT"
    assert capture["terminal_speed_m_s"] <= 0.08
    goal = capture["goal"]
    assert (
        capture["target_center_horizontal_error_m"]
        <= goal["horizontal_tolerance_m"]
    )
    assert capture["pre_contact_vertical_speed_m_s"] <= 0.05
    assert capture["contact_source_timestamp_s"] < capture["disarmed_source_timestamp_s"]
    assert capture["post_contact_settling_s"] >= 0.10
    assert capture["motors_cut_after_contact"] is True
    terminal_truth = capture["terminal_truth_position_m"]
    assert terminal_truth is not None
    assert (
        math.hypot(
            terminal_truth["x"] - goal["landing_target_m"]["x"],
            terminal_truth["y"] - goal["landing_target_m"]["y"],
        )
        <= goal["horizontal_tolerance_m"]
    )
    assert abs(terminal_truth["z"] - goal["landing_target_m"]["z"]) <= goal["vertical_tolerance_m"]

    internal_points = operation.trajectory.points[1:-1]
    assert len(internal_points) == 23
    assert all(math.isclose(point.velocity_m_s.x, 0.125, abs_tol=1e-9) for point in internal_points)
    assert operation.trajectory.declared_stop_sequences == (1, 25)

    route_speeds = [
        math.sqrt(
            sample.telemetry.velocity_m_s.x**2
            + sample.telemetry.velocity_m_s.y**2
            + sample.telemetry.velocity_m_s.z**2
        )
        for sample in vehicle.telemetry_history
        if sample.telemetry.velocity_m_s is not None
        and sample.telemetry.ground_truth_position_m is not None
        and -1.05 < sample.telemetry.ground_truth_position_m.x < 1.05
        and sample.telemetry.ground_truth_position_m.z > 0.2
    ]
    assert route_speeds
    assert min(route_speeds) > 0.04
    assert vehicle.true_position_m.x == pytest.approx(1.2, abs=0.08)
    assert vehicle.true_position_m.z == pytest.approx(0.0, abs=0.001)


@pytest.mark.asyncio
@pytest.mark.parametrize("clock_mode", [ClockMode.ACCELERATED, ClockMode.REALTIME])
async def test_landing_region_retains_capture_xy_through_contact(
    clock_mode: ClockMode,
) -> None:
    result, vehicle, _, _ = await _run_route(
        clock_mode,
        landing_goal_offset_x_m=0.04,
    )

    assert result.status is MissionStatus.SUCCEEDED
    capture = result.goal_captures[0]
    assert capture["schema_version"] == 3
    accepted = next(item for item in capture["attempts"] if item["aligned"])
    accepted_position = accepted["estimated_position_m"]
    descent_target = capture["descent_target_position_m"]
    goal_center = capture["goal"]["landing_target_m"]
    assert accepted_position is not None
    assert capture["authorized_capture_position_m"] == accepted_position
    assert descent_target["x"] == pytest.approx(accepted_position["x"], abs=1e-9)
    assert descent_target["y"] == pytest.approx(accepted_position["y"], abs=1e-9)
    assert descent_target["z"] == pytest.approx(goal_center["z"], abs=1e-9)
    assert abs(descent_target["x"] - goal_center["x"]) > 0.02
    assert capture["commanded_pre_descent_horizontal_adjustment_m"] == pytest.approx(
        0.0, abs=1e-9
    )
    assert capture["alignment_duration_s"] == pytest.approx(0.0, abs=1e-12)

    capture_identity = (
        accepted["source_clock_id"],
        accepted["source_clock_epoch"],
        accepted["source_timestamp_s"],
        accepted["source_sequence"],
    )
    contact_identity = (
        capture["contact_source_clock_id"],
        capture["contact_source_clock_epoch"],
        capture["contact_source_timestamp_s"],
        capture["contact_source_sequence"],
    )
    retained = [
        sample
        for sample in vehicle.telemetry_history
        if sample.source_clock_id == capture_identity[0]
        and sample.source_clock_epoch == capture_identity[1]
        and (sample.source_timestamp_s, sample.sequence)
        >= (capture_identity[2], capture_identity[3])
        and (sample.source_timestamp_s, sample.sequence)
        <= (contact_identity[2], contact_identity[3])
    ]
    assert len(retained) >= 4
    assert (
        retained[0].source_timestamp_s,
        retained[0].sequence,
    ) == pytest.approx((capture_identity[2], capture_identity[3]), abs=1e-9)
    assert (
        retained[-1].source_timestamp_s,
        retained[-1].sequence,
    ) == pytest.approx((contact_identity[2], contact_identity[3]), abs=1e-9)
    assert all(
        current.sequence > previous.sequence
        and current.source_timestamp_s >= previous.source_timestamp_s
        for previous, current in pairwise(retained)
    )

    retained_positions = [sample.telemetry.position_m for sample in retained]
    assert all(position is not None for position in retained_positions)
    positions = [position for position in retained_positions if position is not None]
    maximum_displacement = max(
        math.hypot(
            position.x - accepted_position["x"],
            position.y - accepted_position["y"],
        )
        for position in positions
    )
    initial_center_error = math.hypot(
        accepted_position["x"] - goal_center["x"],
        accepted_position["y"] - goal_center["y"],
    )
    minimum_center_error = min(
        math.hypot(position.x - goal_center["x"], position.y - goal_center["y"])
        for position in positions
    )
    assert maximum_displacement <= 0.015
    assert initial_center_error - minimum_center_error <= 0.010
    assert positions[-1].z <= 0.010


def test_goal_bound_land_command_distinguishes_region_from_diversion_point() -> None:
    goal = LandingGoalRegion(
        goal_id="region-or-diversion",
        role_id="primary",
        vehicle_id="sim01",
        landing_target_m=Vector3(x=1.0, z=0.0),
        approach_point_m=Vector3(x=1.0, z=0.3),
        horizontal_tolerance_m=0.05,
        vertical_tolerance_m=0.05,
        maximum_capture_speed_m_s=0.2,
        failure_action=GoalFailureAction.DIVERT,
        diversion_target_m=Vector3(x=-1.0, y=0.5, z=0.0),
    )

    nominal = LandCommand(
        target_position_m=Vector3(x=1.05, z=0.0),
        goal_region=goal,
    )
    assert nominal.target_position_m == Vector3(x=1.05, z=0.0)

    diversion = LandCommand(
        target_position_m=goal.diversion_target_m,
        goal_region=goal,
    )
    assert diversion.target_position_m == goal.diversion_target_m

    with pytest.raises(ValueError, match="outside its immutable goal region"):
        LandCommand(
            target_position_m=Vector3(x=1.0, z=0.01),
            target_height_m=0.01,
            goal_region=goal,
        )
    with pytest.raises(ValueError, match="outside its immutable goal region"):
        LandCommand(
            target_position_m=Vector3(x=-0.99, y=0.5, z=0.0),
            goal_region=goal,
        )


@pytest.mark.asyncio
async def test_landing_goal_diversion_retains_exact_point_alignment() -> None:
    diversion_target = Vector3(x=0.8, y=0.2, z=0.0)
    result, vehicle, _, _ = await _run_route(
        ClockMode.ACCELERATED,
        landing_goal_offset_x_m=0.16,
        diversion_target_m=diversion_target,
    )

    assert result.status is MissionStatus.SUCCEEDED
    capture = result.goal_captures[0]
    assert capture["outcome"] == "DIVERTED"
    assert capture["authorized_capture_position_m"] is None
    assert capture["descent_target_position_m"] == diversion_target.model_dump(mode="json")
    assert capture["alignment_duration_s"] > 0.0
    assert vehicle.true_position_m.x == pytest.approx(diversion_target.x, abs=0.08)
    assert vehicle.true_position_m.y == pytest.approx(diversion_target.y, abs=0.08)


@pytest.mark.asyncio
async def test_landing_goal_uses_bounded_correction_before_descent() -> None:
    result, vehicle, _, _ = await _run_route(
        ClockMode.ACCELERATED,
        landing_goal_offset_x_m=0.16,
    )

    assert result.status is MissionStatus.SUCCEEDED
    capture = result.goal_captures[0]
    assert capture["outcome"] == "CAPTURED"
    assert capture["attempt_count"] == 2
    assert capture["attempts"][0]["aligned"] is False
    assert capture["attempts"][1]["aligned"] is True
    assert [item["action"] for item in result.normalized_intent_trace] == [
        "takeoff",
        "execute_trajectory",
        "move_relative",
        "land",
    ]
    assert vehicle.true_position_m.x == pytest.approx(1.36, abs=0.10)


@pytest.mark.asyncio
async def test_landing_goal_rejects_unsafe_correction_without_planned_descent() -> None:
    result, _, _, _ = await _run_route(
        ClockMode.ACCELERATED,
        landing_goal_offset_x_m=1.0,
    )

    assert result.status is MissionStatus.FAILED
    assert result.reason_code == "GEOFENCE_BREACH"
    capture = result.goal_captures[0]
    assert capture["outcome"] == "REJECTED"
    assert capture["descent_authorized"] is False
    assert capture["terminal_contact"] == "DESCENT_NOT_AUTHORIZED"
    assert "land" not in [item["action"] for item in result.normalized_intent_trace]


@pytest.mark.asyncio
async def test_unsupported_trajectory_backend_fails_before_connect_or_arm() -> None:
    record = parse_python_mission(
        filename="continuous_route.py",
        name="Continuous route",
        source=ROUTE_SOURCE,
    )
    deployment = plan_mission_deployment(
        record,
        backend=ExecutionBackend.FAST_SIM,
        required_capabilities=frozenset(),
        implicit_vehicle_id="sim01",
        implicit_display_name="Unsupported vehicle",
        implicit_home=Vector3(x=-1.2),
        world_minimum_m=Vector3(x=-2.0, y=-2.0, z=0.0),
        world_maximum_m=Vector3(x=2.0, y=2.0, z=1.0),
    )
    plan = await build_mission_plan(
        record,
        deployment.deployment,
        deployment.assignments,
        SafetyPolicy(),
    )
    registry = MissionRegistry()
    registry.register(ScriptMission(record))
    supervisor = SafetySupervisor()
    vehicle = NoTrajectoryVehicle(
        VehicleIdentity(vehicle_id="sim01", display_name="Sim", adapter="sim"),
        IndoorWorld(WorldConfig(width_m=4.0, depth_m=4.0, height_m=1.0)),
        initial_position_m=Vector3(x=-1.2),
    )
    supervisor.register_vehicle(vehicle)

    result = await MissionRunner(supervisor, registry).run(
        record.mission_id,
        "sim01",
        mission_role_id="primary",
        accepted_plan_id=plan.plan_id,
        accepted_plan_sha256=plan.sha256,
        accepted_execution_program=plan.execution_programs[0],
    )

    assert result.status is MissionStatus.FAILED
    assert result.reason_code == "PREFLIGHT_FAILED"
    assert "does not support" in result.message
    assert vehicle.state.value == "DISCONNECTED"
    assert not any(event.event_type == "COMMAND_SENT" for event in supervisor.events)
