from __future__ import annotations

from collections.abc import Mapping

from crazyswarm_app.campaign.models import CampaignCase
from crazyswarm_app.campaign.planner import BoundedPlanningResult, PlanningStatus
from crazyswarm_app.campaign.scheduling import (
    GroundFirstSchedule,
    LaunchActionKind,
    RoleLaunchSchedule,
)
from crazyswarm_app.campaign.submissions import BASELINE_PLANNING_SUBMISSION_ID
from crazyswarm_app.campaign.trajectory import SmoothTrajectorySet
from crazyswarm_app.domain.goals import LandingGoalRegion
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.domain.trajectory import (
    AcceptedExecutionProgram,
    ExecutionOperation,
    GroundWaitExecutionOperation,
    HoldExecutionOperation,
    LandExecutionOperation,
    TakeoffExecutionOperation,
    TrajectoryExecutionOperation,
)


def compile_campaign_execution_programs(
    *,
    case: CampaignCase,
    plan: BoundedPlanningResult,
    schedule: GroundFirstSchedule,
    trajectories: SmoothTrajectorySet,
    mission_source_sha256: str,
) -> tuple[AcceptedExecutionProgram, ...]:
    """Compile the exact admitted campaign schedule into existing runtime authority."""

    if plan.status is not PlanningStatus.READY or plan.selected is None:
        raise ValueError("campaign execution requires a ready selected plan")
    schedule_planning_matches = (
        schedule.planning_submission_id == plan.planning_submission_id
        and schedule.planning_submission_sha256 == plan.planning_submission_sha256
    ) or (
        plan.planning_submission_id == BASELINE_PLANNING_SUBMISSION_ID
        and schedule.planning_submission_id is None
        and schedule.planning_submission_sha256 is None
    )
    trajectory_planning_matches = (
        trajectories.planning_submission_id == plan.planning_submission_id
        and trajectories.planning_submission_sha256 == plan.planning_submission_sha256
    ) or (
        plan.planning_submission_id == BASELINE_PLANNING_SUBMISSION_ID
        and trajectories.planning_submission_id is None
        and trajectories.planning_submission_sha256 is None
    )
    if (
        schedule.case_sha256 != case.case_sha256
        or trajectories.case_sha256 != case.case_sha256
        or schedule.candidate_sha256 != plan.selected.candidate_sha256
        or trajectories.candidate_sha256 != plan.selected.candidate_sha256
        or not schedule_planning_matches
        or not trajectory_planning_matches
    ):
        raise ValueError("campaign plan, schedule, trajectory, and case identities differ")

    route_by_role = {route.role_id: route for route in plan.selected.routes}
    trajectory_by_role = {item.role_id: item for item in trajectories.trajectories}
    schedule_by_role = {item.role_id: item for item in schedule.roles}
    drone_by_role = {item.role_id: item for item in case.drones}
    expected = set(drone_by_role)
    if not (set(route_by_role) == set(trajectory_by_role) == set(schedule_by_role) == expected):
        raise ValueError("campaign role identities are incomplete or crossed")

    return tuple(
        _compile_role_program(
            case=case,
            role_schedule=schedule_by_role[role_id],
            trajectory=trajectory_by_role[role_id],
            landing_region=drone_by_role[role_id].landing_region,
            mission_source_sha256=mission_source_sha256,
            fleet_watchdog_s=schedule.wall_watchdog_s,
        )
        for role_id in sorted(expected)
    )


def _compile_role_program(
    *,
    case: CampaignCase,
    role_schedule: RoleLaunchSchedule,
    trajectory: object,
    landing_region: object,
    mission_source_sha256: str,
    fleet_watchdog_s: float,
) -> AcceptedExecutionProgram:
    # Runtime contracts carry concrete Pydantic types. Keeping the public compiler's
    # role join above explicit makes these casts safe and fail-closed on construction.
    from crazyswarm_app.campaign.models import Region3D
    from crazyswarm_app.domain.trajectory import TimeParameterizedTrajectory

    if not isinstance(trajectory, TimeParameterizedTrajectory) or not isinstance(
        landing_region, Region3D
    ):
        raise TypeError("campaign execution received an invalid role artifact")
    actions = tuple(
        action for action in role_schedule.actions if action.kind is not LaunchActionKind.ARM
    )
    operations: list[ExecutionOperation] = []
    for action in actions:
        sequence = len(operations) + 1
        if action.kind is LaunchActionKind.GROUND_WAIT:
            operation: ExecutionOperation = GroundWaitExecutionOperation(
                sequence=sequence,
                starts_at_s=action.starts_at_source_s,
                ends_at_s=action.ends_at_source_s,
            )
        elif action.kind is LaunchActionKind.TAKEOFF:
            operation = TakeoffExecutionOperation(
                sequence=sequence,
                starts_at_s=action.starts_at_source_s,
                ends_at_s=action.ends_at_source_s,
                target_height_m=trajectory.points[0].position_m.z,
            )
        elif action.kind in {LaunchActionKind.STABILIZE, LaunchActionKind.AIRBORNE_STAGE}:
            operation = HoldExecutionOperation(
                sequence=sequence,
                starts_at_s=action.starts_at_source_s,
                ends_at_s=action.ends_at_source_s,
            )
        elif action.kind is LaunchActionKind.START_ROUTE:
            operation = TrajectoryExecutionOperation(
                sequence=sequence,
                starts_at_s=action.starts_at_source_s,
                ends_at_s=action.ends_at_source_s,
                trajectory_sha256=trajectory.sha256,
                trajectory=trajectory,
            )
        elif action.kind is LaunchActionKind.LAND:
            target = landing_region.center_m
            approach = trajectory.points[-1].position_m
            goal_identity = canonical_sha256([case.case_sha256, role_schedule.role_id])[:20]
            goal = LandingGoalRegion(
                goal_id=f"campaign-landing-{goal_identity}",
                role_id=role_schedule.role_id,
                vehicle_id=role_schedule.role_id,
                landing_target_m=target,
                approach_point_m=approach,
                horizontal_tolerance_m=0.10,
                vertical_tolerance_m=0.08,
                # Fast Sim's contact transition can retain roughly 0.09 m/s in the
                # terminal sample even after ground truth has reached z=0.  Keep the
                # gate tight, but above that quantified contact-model residual.
                maximum_capture_speed_m_s=0.10,
                maximum_correction_attempts=2,
                correction_duration_s=1.0,
            )
            operation = LandExecutionOperation(
                sequence=sequence,
                starts_at_s=action.starts_at_source_s,
                ends_at_s=action.ends_at_source_s,
                target_height_m=target.z,
                goal_region=goal,
            )
        else:
            raise ValueError(f"unsupported campaign launch action: {action.kind}")
        operations.append(operation)

    if not operations or operations[0].starts_at_s != 0.0:
        raise ValueError("compiled campaign role program does not begin at source time zero")
    schedule_duration_s = operations[-1].ends_at_s
    watchdog_margin_s = max(0.0, fleet_watchdog_s - schedule_duration_s)
    recovery_reserve_s = min(10.0, watchdog_margin_s)
    contingency_reserve_s = watchdog_margin_s - recovery_reserve_s
    payload: Mapping[str, object] = {
        "case_sha256": case.case_sha256,
        "role_id": role_schedule.role_id,
        "operations": tuple(operations),
        "fleet_watchdog_s": fleet_watchdog_s,
    }
    return AcceptedExecutionProgram(
        program_id=f"campaign-program-{canonical_sha256(payload)[:20]}",
        mission_source_sha256=mission_source_sha256,
        role_id=role_schedule.role_id,
        vehicle_id=role_schedule.role_id,
        operations=tuple(operations),
        route_sha256s=(trajectory.route_sha256,),
        schedule_duration_s=schedule_duration_s,
        contingency_reserve_s=contingency_reserve_s,
        recovery_reserve_s=recovery_reserve_s,
        execution_timeout_s=fleet_watchdog_s,
    )
