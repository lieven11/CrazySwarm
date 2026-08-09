from __future__ import annotations

import math
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.goals import LandingGoalRegion
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import (
    AcceptedExecutionProgram,
    HoldExecutionOperation,
    LandExecutionOperation,
    TakeoffExecutionOperation,
    TimeParameterizedTrajectory,
    TrajectoryExecutionOperation,
    TrajectoryPoint,
)
from crazyswarm_app.fleet.artifacts import DeploymentManifest, InitialFleetRole
from crazyswarm_app.missions.script import (
    MissionFileRecord,
    ScriptStep,
    preview_isolated_mission_role,
)
from crazyswarm_app.planning.contracts import RouteObstacle, RoutePlanStatus
from crazyswarm_app.planning.deconfliction import (
    ConflictResolutionStrategy,
    FleetDeconflictionPlan,
    plan_crossing_deconfliction,
)
from crazyswarm_app.planning.multidrone import (
    MultiDroneConflictPlan,
    plan_multi_drone_conflicts,
)
from crazyswarm_app.planning.service import (
    OperationalRouteInput,
    PlanningBundle,
    compile_operational_planning_bundle,
)
from crazyswarm_app.safety.policy import SafetyPolicy


class MissionPlanStatus(StrEnum):
    APPROVED = "APPROVED"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    BLOCKED = "BLOCKED"


class MissionPlanSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


class MissionPlanFidelity(StrEnum):
    EXACT_ROLE = "EXACT_ROLE"
    STATIC_BOUNDS = "STATIC_BOUNDS"
    PREPARED_RESERVE = "PREPARED_RESERVE"


class PlanningObstacle(ContractModel):
    obstacle_id: Identifier
    minimum_m: Vector3
    maximum_m: Vector3

    @model_validator(mode="after")
    def ordered_bounds(self) -> PlanningObstacle:
        if not (
            self.minimum_m.x <= self.maximum_m.x
            and self.minimum_m.y <= self.maximum_m.y
            and self.minimum_m.z <= self.maximum_m.z
        ):
            raise ValueError("planning obstacle minimum must not exceed maximum")
        return self


class MissionPlanFinding(ContractModel):
    code: Identifier
    severity: MissionPlanSeverity
    message: str = Field(min_length=1, max_length=500)
    role_id: Identifier | None = None
    step_sequence: int | None = Field(default=None, ge=1)
    requires_confirmation: bool = False
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class MissionPlanWaypoint(ContractModel):
    sequence: int = Field(ge=1)
    action: Identifier
    starts_at_s: float = Field(ge=0.0)
    ends_at_s: float = Field(ge=0.0)
    start_m: Vector3
    end_m: Vector3
    start_yaw_rad: float
    end_yaw_rad: float


class MissionRolePlan(ContractModel):
    role_id: Identifier
    vehicle_id: Identifier
    initial_role: InitialFleetRole
    home_m: Vector3
    start_m: Vector3
    existing_vehicle: bool
    observed_battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    minimum_battery_percent: float | None = Field(default=None, ge=0.0, le=200.0)
    preview_fidelity: MissionPlanFidelity
    planned_commands: tuple[ScriptStep, ...] = ()
    waypoints: tuple[MissionPlanWaypoint, ...] = ()
    planned_duration_s: float = Field(default=0.0, ge=0.0)
    planned_distance_m: float = Field(default=0.0, ge=0.0)
    maximum_altitude_m: float = Field(default=0.0)


class MissionSafetySnapshot(ContractModel):
    policy_sha256: SHA256
    flight_volume_minimum_m: Vector3
    flight_volume_maximum_m: Vector3
    max_altitude_m: float = Field(gt=0.0)
    max_horizontal_speed_m_s: float = Field(gt=0.0)
    max_vertical_speed_m_s: float = Field(gt=0.0)
    max_acceleration_m_s2: float = Field(gt=0.0)
    max_yaw_rate_rad_s: float = Field(gt=0.0)
    max_mission_duration_s: float = Field(gt=0.0)
    minimum_takeoff_battery_percent: float = Field(ge=0.0, le=100.0)
    warning_separation_m: float = Field(gt=0.0)
    critical_separation_m: float = Field(gt=0.0)
    observation_freshness_s: float = Field(gt=0.0)


class MissionPlanReceipt(ContractModel):
    schema_version: Literal[1] = 1
    plan_id: Identifier
    mission_id: Identifier
    mission_source_sha256: SHA256
    package_schema_version: Literal[1, 2]
    deployment_sha256: SHA256
    status: MissionPlanStatus
    roles: tuple[MissionRolePlan, ...]
    execution_programs: tuple[AcceptedExecutionProgram, ...] = ()
    deconfliction: FleetDeconflictionPlan | MultiDroneConflictPlan | None = None
    safety: MissionSafetySnapshot
    findings: tuple[MissionPlanFinding, ...]
    planning: PlanningBundle

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


async def build_mission_plan(
    record: MissionFileRecord,
    deployment: DeploymentManifest,
    assignments: dict[str, str],
    policy: SafetyPolicy,
    *,
    start_positions: dict[str, Vector3] | None = None,
    observed_batteries: dict[str, float] | None = None,
    existing_vehicle_ids: frozenset[str] = frozenset(),
    obstacles: tuple[PlanningObstacle, ...] = (),
) -> MissionPlanReceipt:
    """Compile mission intent into a deterministic, backend-neutral admission receipt."""

    starts = start_positions or {}
    batteries = observed_batteries or {}
    task_by_id = {task.task_id: task for task in deployment.tasks}
    expected_roles = set(task_by_id)
    expected_vehicles = {
        member.vehicle_id
        for member in deployment.fleet
        if member.initial_role is InitialFleetRole.ACTIVE
    }
    if (
        set(assignments) != expected_roles
        or set(assignments.values()) != expected_vehicles
        or len(set(assignments.values())) != len(assignments)
    ):
        raise CrazySwarmError(
            ErrorCode.IDENTITY_MISMATCH,
            "mission planning assignments do not match active deployment tasks",
            details={
                "expected_role_ids": sorted(expected_roles),
                "expected_vehicle_ids": sorted(expected_vehicles),
            },
        )
    findings: list[MissionPlanFinding] = []
    role_plans: list[MissionRolePlan] = []
    active_roles_by_vehicle = {vehicle_id: role_id for role_id, vehicle_id in assignments.items()}

    for member in sorted(deployment.fleet, key=lambda item: item.vehicle_id):
        role_id = active_roles_by_vehicle.get(member.vehicle_id)
        if role_id is None:
            role_id = _declared_role_id(record, member.vehicle_id) or member.vehicle_id
        start = starts.get(member.vehicle_id, member.home)
        battery = batteries.get(member.vehicle_id)
        existing_vehicle = member.vehicle_id in existing_vehicle_ids
        if existing_vehicle and member.vehicle_id not in starts:
            findings.append(
                MissionPlanFinding(
                    code="START_POSITION_UNAVAILABLE",
                    severity=MissionPlanSeverity.WARNING,
                    message=(
                        "current position is unavailable; declared home is only a proposed "
                        "start and preparation must observe the vehicle before execution"
                    ),
                    role_id=role_id,
                    details={"preflight_observation_required": True},
                )
            )
        if existing_vehicle and battery is None:
            findings.append(
                MissionPlanFinding(
                    code="BATTERY_OBSERVATION_UNAVAILABLE",
                    severity=MissionPlanSeverity.WARNING,
                    message=(
                        "current battery is unavailable and must be observed during mandatory "
                        "preflight before execution"
                    ),
                    role_id=role_id,
                    details={"preflight_observation_required": True},
                )
            )
        if member.initial_role is InitialFleetRole.RESERVE:
            role_plans.append(
                MissionRolePlan(
                    role_id=role_id,
                    vehicle_id=member.vehicle_id,
                    initial_role=member.initial_role,
                    home_m=member.home,
                    start_m=start,
                    existing_vehicle=existing_vehicle,
                    observed_battery_percent=battery,
                    preview_fidelity=MissionPlanFidelity.PREPARED_RESERVE,
                    maximum_altitude_m=start.z,
                )
            )
            continue

        commands = await preview_isolated_mission_role(record, role_id)
        fidelity = MissionPlanFidelity.EXACT_ROLE

        task = task_by_id.get(role_id)
        minimum_battery = (
            task.estimated_energy_percent + task.energy_margin_percent if task is not None else None
        )
        role_plan, role_findings = _compile_role(
            role_id=role_id,
            vehicle_id=member.vehicle_id,
            home=member.home,
            start=start,
            existing_vehicle=existing_vehicle,
            observed_battery_percent=battery,
            minimum_battery_percent=minimum_battery,
            commands=commands,
            fidelity=fidelity,
            policy=policy,
            obstacles=obstacles,
        )
        role_plans.append(role_plan)
        findings.extend(role_findings)

    planning = compile_operational_planning_bundle(
        mission_id=record.mission_id,
        deployment=deployment,
        roles=tuple(
            OperationalRouteInput(
                role_id=role.role_id,
                vehicle_id=role.vehicle_id,
                initial_role=role.initial_role,
                start_m=role.start_m,
                targets_m=tuple(waypoint.end_m for waypoint in role.waypoints),
                planned_duration_s=role.planned_duration_s,
            )
            for role in role_plans
        ),
        policy=policy,
        obstacles=tuple(
            RouteObstacle(
                obstacle_id=obstacle.obstacle_id,
                minimum_m=obstacle.minimum_m,
                maximum_m=obstacle.maximum_m,
            )
            for obstacle in obstacles
        ),
    )
    for route in planning.route_plans:
        if route.status is RoutePlanStatus.BLOCKED:
            findings.append(
                _blocker(
                    "ROUTE_PLANNER_BLOCKED",
                    "the selected route planner could not produce an admissible bounded route",
                    route.role_id,
                    details={"findings": ",".join(route.findings)},
                )
            )
    findings.extend(_starting_separation_findings(tuple(role_plans), deployment))
    safety = MissionSafetySnapshot(
        policy_sha256=canonical_sha256(policy),
        flight_volume_minimum_m=policy.flight_volume.minimum_m,
        flight_volume_maximum_m=policy.flight_volume.maximum_m,
        max_altitude_m=policy.max_altitude_m,
        max_horizontal_speed_m_s=policy.max_horizontal_speed_m_s,
        max_vertical_speed_m_s=policy.max_vertical_speed_m_s,
        max_acceleration_m_s2=policy.max_acceleration_m_s2,
        max_yaw_rate_rad_s=policy.max_yaw_rate_rad_s,
        max_mission_duration_s=policy.max_mission_duration_s,
        minimum_takeoff_battery_percent=policy.minimum_takeoff_battery_percent,
        warning_separation_m=deployment.constraints.warning_separation_m,
        critical_separation_m=deployment.constraints.critical_separation_m,
        observation_freshness_s=deployment.constraints.observation_freshness_s,
    )
    execution_programs = tuple(
        program
        for role in role_plans
        if (program := _compile_execution_program(record, role)) is not None
    )
    execution_programs, crossing_deconfliction = plan_crossing_deconfliction(
        mission_id=record.mission_id,
        deployment=deployment,
        programs=execution_programs,
        policy=policy,
        allowed_strategies=(
            tuple(
                ConflictResolutionStrategy(item) for item in record.package.deconfliction_strategies
            )
            if record.package is not None
            else tuple(ConflictResolutionStrategy)
        ),
    )
    deconfliction: FleetDeconflictionPlan | MultiDroneConflictPlan | None = crossing_deconfliction
    if deconfliction is None:
        execution_programs, multi_deconfliction = plan_multi_drone_conflicts(
            mission_id=record.mission_id,
            deployment=deployment,
            programs=execution_programs,
            policy=policy,
        )
        deconfliction = multi_deconfliction
    if deconfliction is not None and deconfliction.status.value == "BLOCKED":
        findings.append(
            _blocker(
                "PREDICTIVE_DECONFLICTION_BLOCKED",
                "no admitted fleet conflict resolution satisfies the hard constraints",
                "fleet",
                details={"deconfliction_plan_sha256": deconfliction.plan_sha256},
            )
        )
    ordered_findings = tuple(sorted(findings, key=_finding_sort_key))
    status = _plan_status(ordered_findings)
    plan_payload = {
        "mission_id": record.mission_id,
        "source_sha256": record.source_sha256,
        "package_schema_version": record.package_schema_version,
        "deployment_sha256": deployment.sha256,
        "roles": role_plans,
        "execution_programs": execution_programs,
        "deconfliction": deconfliction,
        "safety": safety,
        "findings": ordered_findings,
        "status": status,
        "planning": planning,
    }
    return MissionPlanReceipt(
        plan_id=f"mission-plan-{canonical_sha256(plan_payload)[:24]}",
        mission_id=record.mission_id,
        mission_source_sha256=record.source_sha256,
        package_schema_version=record.package_schema_version,
        deployment_sha256=deployment.sha256,
        status=status,
        roles=tuple(role_plans),
        execution_programs=execution_programs,
        deconfliction=deconfliction,
        safety=safety,
        findings=ordered_findings,
        planning=planning,
    )


def _compile_execution_program(
    record: MissionFileRecord,
    role: MissionRolePlan,
) -> AcceptedExecutionProgram | None:
    """Compile deterministic motion-only previews into executable static authority."""

    if role.initial_role is not InitialFleetRole.ACTIVE or not role.waypoints:
        return None
    if any(
        waypoint.action not in {"takeoff", "hover", "move_relative", "land"}
        for waypoint in role.waypoints
    ):
        return None

    operations: list[
        TakeoffExecutionOperation
        | HoldExecutionOperation
        | TrajectoryExecutionOperation
        | LandExecutionOperation
    ] = []
    index = 0
    while index < len(role.waypoints):
        waypoint = role.waypoints[index]
        sequence = len(operations) + 1
        if waypoint.action == "takeoff":
            operations.append(
                TakeoffExecutionOperation(
                    sequence=sequence,
                    starts_at_s=waypoint.starts_at_s,
                    ends_at_s=waypoint.ends_at_s,
                    target_height_m=waypoint.end_m.z,
                )
            )
            index += 1
            continue
        if waypoint.action == "hover":
            operations.append(
                HoldExecutionOperation(
                    sequence=sequence,
                    starts_at_s=waypoint.starts_at_s,
                    ends_at_s=waypoint.ends_at_s,
                )
            )
            index += 1
            continue
        if waypoint.action == "land":
            goal_payload = {
                "mission_source_sha256": record.source_sha256,
                "role_id": role.role_id,
                "vehicle_id": role.vehicle_id,
                "landing_target_m": waypoint.end_m,
                "approach_point_m": waypoint.start_m,
            }
            operations.append(
                LandExecutionOperation(
                    sequence=sequence,
                    starts_at_s=waypoint.starts_at_s,
                    ends_at_s=waypoint.ends_at_s,
                    target_height_m=waypoint.end_m.z,
                    goal_region=LandingGoalRegion(
                        goal_id=f"landing-goal-{canonical_sha256(goal_payload)[:20]}",
                        role_id=role.role_id,
                        vehicle_id=role.vehicle_id,
                        landing_target_m=waypoint.end_m,
                        approach_point_m=waypoint.start_m,
                        horizontal_tolerance_m=0.10,
                        vertical_tolerance_m=0.08,
                        maximum_capture_speed_m_s=0.08,
                        maximum_correction_attempts=2,
                        correction_duration_s=1.0,
                    ),
                )
            )
            index += 1
            continue

        end_index = index
        while (
            end_index + 1 < len(role.waypoints)
            and role.waypoints[end_index + 1].action == "move_relative"
        ):
            end_index += 1
        movement = role.waypoints[index : end_index + 1]
        trajectory = _compile_continuous_trajectory(record, role, movement)
        operations.append(
            TrajectoryExecutionOperation(
                sequence=sequence,
                starts_at_s=movement[0].starts_at_s,
                ends_at_s=movement[-1].ends_at_s,
                trajectory_sha256=trajectory.sha256,
                trajectory=trajectory,
            )
        )
        index = end_index + 1

    contingency_s = max(2.0, role.planned_duration_s * 0.20)
    recovery_s = 10.0
    program_payload = {
        "mission_source_sha256": record.source_sha256,
        "role_id": role.role_id,
        "vehicle_id": role.vehicle_id,
        "operations": operations,
        "schedule_duration_s": role.planned_duration_s,
        "contingency_reserve_s": contingency_s,
        "recovery_reserve_s": recovery_s,
    }
    program_id = f"execution-program-{canonical_sha256(program_payload)[:20]}"
    return AcceptedExecutionProgram(
        program_id=program_id,
        mission_source_sha256=record.source_sha256,
        role_id=role.role_id,
        vehicle_id=role.vehicle_id,
        operations=tuple(operations),
        route_sha256s=tuple(
            operation.trajectory.route_sha256
            for operation in operations
            if isinstance(operation, TrajectoryExecutionOperation)
        ),
        schedule_duration_s=role.planned_duration_s,
        contingency_reserve_s=contingency_s,
        recovery_reserve_s=recovery_s,
        execution_timeout_s=role.planned_duration_s + contingency_s + recovery_s,
    )


def _compile_continuous_trajectory(
    record: MissionFileRecord,
    role: MissionRolePlan,
    movement: tuple[MissionPlanWaypoint, ...],
) -> TimeParameterizedTrajectory:
    starts_at_s = movement[0].starts_at_s
    positions = (movement[0].start_m, *(waypoint.end_m for waypoint in movement))
    yaws = (movement[0].start_yaw_rad, *(waypoint.end_yaw_rad for waypoint in movement))
    times = (0.0, *(waypoint.ends_at_s - starts_at_s for waypoint in movement))
    velocities: list[Vector3] = []
    yaw_rates: list[float] = []
    stops = {1, len(positions)}
    for point_index, position in enumerate(positions):
        if point_index in {0, len(positions) - 1}:
            velocities.append(Vector3())
            yaw_rates.append(0.0)
            continue
        previous = positions[point_index - 1]
        following = positions[point_index + 1]
        incoming = Vector3(
            x=position.x - previous.x,
            y=position.y - previous.y,
            z=position.z - previous.z,
        )
        outgoing = Vector3(
            x=following.x - position.x,
            y=following.y - position.y,
            z=following.z - position.z,
        )
        dot = incoming.x * outgoing.x + incoming.y * outgoing.y + incoming.z * outgoing.z
        if dot <= 0.0:
            velocities.append(Vector3())
            yaw_rates.append(0.0)
            stops.add(point_index + 1)
            continue
        duration_s = times[point_index + 1] - times[point_index - 1]
        velocities.append(
            Vector3(
                x=(following.x - previous.x) / duration_s,
                y=(following.y - previous.y) / duration_s,
                z=(following.z - previous.z) / duration_s,
            )
        )
        yaw_rates.append((yaws[point_index + 1] - yaws[point_index - 1]) / duration_s)

    route_payload = {
        "mission_source_sha256": record.source_sha256,
        "role_id": role.role_id,
        "vehicle_id": role.vehicle_id,
        "times": times,
        "positions": positions,
        "yaws": yaws,
        "declared_stop_sequences": sorted(stops),
    }
    route_sha256 = canonical_sha256(route_payload)
    trajectory_id = f"trajectory-{route_sha256[:24]}"
    return TimeParameterizedTrajectory(
        trajectory_id=trajectory_id,
        role_id=role.role_id,
        vehicle_id=role.vehicle_id,
        route_sha256=route_sha256,
        points=tuple(
            TrajectoryPoint(
                sequence=point_index + 1,
                time_from_start_s=times[point_index],
                position_m=position,
                velocity_m_s=velocities[point_index],
                acceleration_m_s2=Vector3(),
                yaw_rad=yaws[point_index],
                yaw_rate_rad_s=yaw_rates[point_index],
            )
            for point_index, position in enumerate(positions)
        ),
        declared_stop_sequences=tuple(sorted(stops)),
        completion_position_tolerance_m=0.08,
        completion_velocity_tolerance_m_s=0.05,
    )


def _compile_role(
    *,
    role_id: str,
    vehicle_id: str,
    home: Vector3,
    start: Vector3,
    existing_vehicle: bool,
    observed_battery_percent: float | None,
    minimum_battery_percent: float | None,
    commands: tuple[ScriptStep, ...],
    fidelity: MissionPlanFidelity,
    policy: SafetyPolicy,
    obstacles: tuple[PlanningObstacle, ...],
) -> tuple[MissionRolePlan, list[MissionPlanFinding]]:
    findings: list[MissionPlanFinding] = []
    waypoints: list[MissionPlanWaypoint] = []
    position = start
    yaw = 0.0
    elapsed_s = 0.0
    distance_m = 0.0
    maximum_altitude_m = start.z

    if not policy.flight_volume.contains(start):
        findings.append(
            _blocker(
                "START_OUTSIDE_FLIGHT_VOLUME",
                "the planned start position is outside the configured safety volume",
                role_id,
                details=_point_details(start),
            )
        )

    for sequence, command in enumerate(commands, start=1):
        action = command.action
        arguments = command.arguments
        start_position = position
        start_yaw = yaw
        duration_s = _step_duration(command)
        if action == "takeoff":
            position = Vector3(x=position.x, y=position.y, z=float(arguments["height_m"]))
            _check_takeoff_dynamics(findings, role_id, sequence, arguments, policy)
        elif action == "move_relative":
            dx = float(arguments.get("x_m", 0.0))
            dy = float(arguments.get("y_m", 0.0))
            if str(arguments.get("frame", "home")) == "body":
                dx, dy = (
                    dx * math.cos(yaw) - dy * math.sin(yaw),
                    dx * math.sin(yaw) + dy * math.cos(yaw),
                )
            position = Vector3(
                x=position.x + dx,
                y=position.y + dy,
                z=position.z + float(arguments.get("z_m", 0.0)),
            )
            yaw += float(arguments.get("yaw_rad", 0.0))
            _check_move_dynamics(findings, role_id, sequence, arguments, policy)
        elif action == "land":
            position = Vector3(x=position.x, y=position.y, z=0.0)

        elapsed_s += duration_s
        step_distance = _distance(start_position, position)
        distance_m += step_distance
        maximum_altitude_m = max(maximum_altitude_m, position.z)
        waypoint = MissionPlanWaypoint(
            sequence=sequence,
            action=action,
            starts_at_s=elapsed_s - duration_s,
            ends_at_s=elapsed_s,
            start_m=start_position,
            end_m=position,
            start_yaw_rad=start_yaw,
            end_yaw_rad=yaw,
        )
        waypoints.append(waypoint)

        if not policy.flight_volume.contains(position) or position.z > policy.max_altitude_m:
            findings.append(
                _blocker(
                    "TARGET_OUTSIDE_FLIGHT_VOLUME",
                    "a planned command target is outside the configured safety envelope",
                    role_id,
                    sequence,
                    details={
                        **_point_details(position),
                        "max_altitude_m": policy.max_altitude_m,
                    },
                )
            )
        for obstacle in obstacles:
            if step_distance > 0.0 and _segment_intersects_box(
                start_position,
                position,
                obstacle.minimum_m,
                obstacle.maximum_m,
            ):
                findings.append(
                    _blocker(
                        "ROUTE_INTERSECTS_OBSTACLE",
                        "a planned command segment intersects configured obstacle geometry",
                        role_id,
                        sequence,
                        details={"obstacle_id": obstacle.obstacle_id},
                    )
                )

    if elapsed_s > policy.max_mission_duration_s:
        findings.append(
            _blocker(
                "MISSION_DURATION_EXCEEDS_POLICY",
                "the planned role duration exceeds the configured mission limit",
                role_id,
                details={
                    "planned_duration_s": elapsed_s,
                    "maximum_duration_s": policy.max_mission_duration_s,
                },
            )
        )
    if (
        observed_battery_percent is not None
        and minimum_battery_percent is not None
        and observed_battery_percent < minimum_battery_percent
    ):
        findings.append(
            MissionPlanFinding(
                code="BATTERY_BELOW_PLANNED_REQUIREMENT",
                severity=MissionPlanSeverity.WARNING,
                message="observed battery is below the task energy estimate plus margin",
                role_id=role_id,
                requires_confirmation=True,
                details={
                    "observed_battery_percent": observed_battery_percent,
                    "minimum_battery_percent": minimum_battery_percent,
                },
            )
        )
    if (
        observed_battery_percent is not None
        and observed_battery_percent < policy.minimum_takeoff_battery_percent
    ):
        findings.append(
            MissionPlanFinding(
                code="BATTERY_BELOW_TAKEOFF_MINIMUM",
                severity=MissionPlanSeverity.WARNING,
                message="observed battery is below the safety policy takeoff minimum",
                role_id=role_id,
                requires_confirmation=True,
                details={
                    "observed_battery_percent": observed_battery_percent,
                    "minimum_takeoff_battery_percent": policy.minimum_takeoff_battery_percent,
                },
            )
        )

    return (
        MissionRolePlan(
            role_id=role_id,
            vehicle_id=vehicle_id,
            initial_role=InitialFleetRole.ACTIVE,
            home_m=home,
            start_m=start,
            existing_vehicle=existing_vehicle,
            observed_battery_percent=observed_battery_percent,
            minimum_battery_percent=minimum_battery_percent,
            preview_fidelity=fidelity,
            planned_commands=commands,
            waypoints=tuple(waypoints),
            planned_duration_s=elapsed_s,
            planned_distance_m=distance_m,
            maximum_altitude_m=maximum_altitude_m,
        ),
        findings,
    )


def _check_takeoff_dynamics(
    findings: list[MissionPlanFinding],
    role_id: str,
    sequence: int,
    arguments: dict[str, float | str],
    policy: SafetyPolicy,
) -> None:
    height_m = float(arguments["height_m"])
    duration_s = float(arguments["duration_s"])
    vertical_speed = 1.5 * height_m / duration_s
    acceleration = 6.0 * height_m / duration_s**2
    if vertical_speed > policy.max_vertical_speed_m_s:
        findings.append(
            _dynamics_blocker(
                "TAKEOFF_VERTICAL_SPEED_EXCEEDS_POLICY",
                "planned takeoff vertical speed exceeds policy",
                role_id,
                sequence,
                vertical_speed,
                policy.max_vertical_speed_m_s,
            )
        )
    if acceleration > policy.max_acceleration_m_s2:
        findings.append(
            _dynamics_blocker(
                "TAKEOFF_ACCELERATION_EXCEEDS_POLICY",
                "planned takeoff acceleration exceeds policy",
                role_id,
                sequence,
                acceleration,
                policy.max_acceleration_m_s2,
            )
        )


def _check_move_dynamics(
    findings: list[MissionPlanFinding],
    role_id: str,
    sequence: int,
    arguments: dict[str, float | str],
    policy: SafetyPolicy,
) -> None:
    duration_s = float(arguments["duration_s"])
    horizontal = math.hypot(
        float(arguments.get("x_m", 0.0)),
        float(arguments.get("y_m", 0.0)),
    )
    vertical = abs(float(arguments.get("z_m", 0.0)))
    distance = math.sqrt(horizontal**2 + vertical**2)
    checks = (
        (
            "HORIZONTAL_SPEED_EXCEEDS_POLICY",
            "planned horizontal speed exceeds policy",
            1.5 * horizontal / duration_s,
            policy.max_horizontal_speed_m_s,
        ),
        (
            "VERTICAL_SPEED_EXCEEDS_POLICY",
            "planned vertical speed exceeds policy",
            1.5 * vertical / duration_s,
            policy.max_vertical_speed_m_s,
        ),
        (
            "ACCELERATION_EXCEEDS_POLICY",
            "planned move acceleration exceeds policy",
            6.0 * distance / duration_s**2,
            policy.max_acceleration_m_s2,
        ),
        (
            "YAW_RATE_EXCEEDS_POLICY",
            "planned yaw rate exceeds policy",
            1.5 * abs(float(arguments.get("yaw_rad", 0.0))) / duration_s,
            policy.max_yaw_rate_rad_s,
        ),
    )
    for code, message, observed, limit in checks:
        if observed > limit:
            findings.append(_dynamics_blocker(code, message, role_id, sequence, observed, limit))


def _starting_separation_findings(
    roles: tuple[MissionRolePlan, ...], deployment: DeploymentManifest
) -> list[MissionPlanFinding]:
    findings: list[MissionPlanFinding] = []
    for index, first in enumerate(roles):
        for second in roles[index + 1 :]:
            distance_m = _distance(first.start_m, second.start_m)
            details: dict[str, str | int | float | bool | None] = {
                "first_role_id": first.role_id,
                "second_role_id": second.role_id,
                "distance_m": distance_m,
            }
            if distance_m <= deployment.constraints.critical_separation_m:
                findings.append(
                    _blocker(
                        "STARTING_SEPARATION_CRITICAL",
                        "planned member starts violate critical separation",
                        first.role_id,
                        details=details,
                    )
                )
            elif distance_m <= deployment.constraints.warning_separation_m:
                findings.append(
                    MissionPlanFinding(
                        code="STARTING_SEPARATION_WARNING",
                        severity=MissionPlanSeverity.WARNING,
                        message="planned member starts are inside warning separation",
                        role_id=first.role_id,
                        details=details,
                    )
                )
    return findings


def _declared_role_id(record: MissionFileRecord, vehicle_id: str) -> str | None:
    return next(
        (role.role_id for role in record.roles if role.logical_vehicle_id == vehicle_id),
        None,
    )


def _step_duration(command: ScriptStep) -> float:
    if "duration_s" in command.arguments:
        return float(command.arguments["duration_s"])
    if command.action == "observe":
        return float(command.arguments.get("timeout_s", 0.5))
    return 0.0


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )


def _segment_intersects_box(
    start: Vector3,
    end: Vector3,
    minimum: Vector3,
    maximum: Vector3,
) -> bool:
    lower = 0.0
    upper = 1.0
    for origin, target, low, high in (
        (start.x, end.x, minimum.x, maximum.x),
        (start.y, end.y, minimum.y, maximum.y),
        (start.z, end.z, minimum.z, maximum.z),
    ):
        delta = target - origin
        if abs(delta) <= 1e-12:
            if origin < low or origin > high:
                return False
            continue
        entry = (low - origin) / delta
        exit_ = (high - origin) / delta
        if entry > exit_:
            entry, exit_ = exit_, entry
        lower = max(lower, entry)
        upper = min(upper, exit_)
        if lower > upper:
            return False
    return True


def _plan_status(findings: tuple[MissionPlanFinding, ...]) -> MissionPlanStatus:
    if any(item.severity is MissionPlanSeverity.BLOCKER for item in findings):
        return MissionPlanStatus.BLOCKED
    if any(item.requires_confirmation for item in findings):
        return MissionPlanStatus.REQUIRES_CONFIRMATION
    return MissionPlanStatus.APPROVED


def _blocker(
    code: str,
    message: str,
    role_id: str,
    step_sequence: int | None = None,
    *,
    details: dict[str, str | int | float | bool | None] | None = None,
) -> MissionPlanFinding:
    return MissionPlanFinding(
        code=code,
        severity=MissionPlanSeverity.BLOCKER,
        message=message,
        role_id=role_id,
        step_sequence=step_sequence,
        details=details or {},
    )


def _dynamics_blocker(
    code: str,
    message: str,
    role_id: str,
    step_sequence: int,
    observed: float,
    limit: float,
) -> MissionPlanFinding:
    return _blocker(
        code,
        message,
        role_id,
        step_sequence,
        details={"planned_value": observed, "policy_limit": limit},
    )


def _point_details(point: Vector3) -> dict[str, str | int | float | bool | None]:
    return {"x_m": point.x, "y_m": point.y, "z_m": point.z}


def _finding_sort_key(
    finding: MissionPlanFinding,
) -> tuple[int, str, str, int]:
    severity_order = {
        MissionPlanSeverity.BLOCKER: 0,
        MissionPlanSeverity.WARNING: 1,
        MissionPlanSeverity.INFO: 2,
    }
    return (
        severity_order[finding.severity],
        finding.role_id or "",
        finding.code,
        finding.step_sequence or 0,
    )
