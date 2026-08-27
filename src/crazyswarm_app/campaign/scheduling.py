from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import CampaignCase
from crazyswarm_app.campaign.planner import (
    DEFAULT_LANDING_DURATION_S,
    DEFAULT_STABILIZATION_S,
    DEFAULT_TAKEOFF_DURATION_S,
    CandidateEvaluation,
)
from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class LaunchActionKind(StrEnum):
    GROUND_WAIT = "GROUND_WAIT"
    ARM = "ARM"
    TAKEOFF = "TAKEOFF"
    STABILIZE = "STABILIZE"
    AIRBORNE_STAGE = "AIRBORNE_STAGE"
    START_ROUTE = "START_ROUTE"
    LAND = "LAND"


class LaunchAction(ContractModel):
    kind: LaunchActionKind
    starts_at_source_s: float = Field(ge=0.0)
    ends_at_source_s: float = Field(ge=0.0)
    required: bool
    rationale: str


class RoleEnergyBudget(ContractModel):
    role_id: Identifier
    ground_wait_s: float = Field(ge=0.0)
    airborne_hover_s: float = Field(ge=0.0)
    route_energy_percent: float = Field(ge=0.0)
    landing_reserve_percent: float = Field(ge=0.0)
    predicted_end_battery_percent: float = Field(ge=0.0, le=100.0)


class RoleLaunchSchedule(ContractModel):
    role_id: Identifier
    actions: tuple[LaunchAction, ...]
    launch_readiness_revalidation: tuple[
        Literal["BATTERY", "HEALTH", "VOLUME_OCCUPANCY", "RESERVATIONS"], ...
    ] = ("BATTERY", "HEALTH", "VOLUME_OCCUPANCY", "RESERVATIONS")
    energy: RoleEnergyBudget


class GroundFirstSchedule(ContractModel):
    schema_version: Literal[1] = 1
    case_sha256: SHA256
    candidate_sha256: SHA256
    planning_submission_id: Identifier | None = None
    planning_submission_sha256: SHA256 | None = None
    roles: tuple[RoleLaunchSchedule, ...]
    source_schedule_duration_s: float = Field(ge=0.0)
    wall_watchdog_s: float = Field(gt=0.0)
    minimum_realtime_factor: float = Field(gt=0.0)
    watchdog_guard_s: float = Field(ge=0.0)
    schedule_sha256: SHA256

    @model_validator(mode="after")
    def planning_authority_is_paired(self) -> GroundFirstSchedule:
        if (self.planning_submission_id is None) != (
            self.planning_submission_sha256 is None
        ):
            raise ValueError("schedule planning submission identity must be complete")
        return self

    def canonical_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="python", exclude={"schedule_sha256"})
        payload.pop("schema_version", None)
        if self.planning_submission_id is None:
            payload.pop("planning_submission_id", None)
            payload.pop("planning_submission_sha256", None)
        return payload


def build_ground_first_schedule(
    case: CampaignCase,
    candidate: CandidateEvaluation,
    *,
    takeoff_duration_s: float = DEFAULT_TAKEOFF_DURATION_S,
    stabilization_s: float = DEFAULT_STABILIZATION_S,
    landing_duration_s: float = DEFAULT_LANDING_DURATION_S,
    planning_submission_id: str | None = None,
    planning_submission_sha256: str | None = None,
) -> GroundFirstSchedule:
    drone_by_role = {drone.role_id: drone for drone in case.drones}
    roles = []
    completion = 0.0
    for route in sorted(candidate.routes, key=lambda item: item.role_id):
        drone = drone_by_role[route.role_id]
        if case.hard_constraints.synchronized_launch_required:
            takeoff_start = 0.0
        else:
            takeoff_start = route.ground_wait_s
        takeoff_end = takeoff_start + takeoff_duration_s
        stabilization_end = takeoff_end + stabilization_s
        route_start = stabilization_end + route.airborne_wait_s
        route_end = route_start + route.route_duration_s
        actions: list[LaunchAction] = []
        if takeoff_start > 0.0:
            actions.append(
                LaunchAction(
                    kind=LaunchActionKind.GROUND_WAIT,
                    starts_at_source_s=0.0,
                    ends_at_source_s=takeoff_start,
                    required=True,
                    rationale="ground-first delay avoids non-required airborne battery use",
                )
            )
        actions.extend(
            (
                LaunchAction(
                    kind=LaunchActionKind.ARM,
                    starts_at_source_s=takeoff_start,
                    ends_at_source_s=takeoff_start,
                    required=True,
                    rationale="just-in-time arm after readiness revalidation",
                ),
                LaunchAction(
                    kind=LaunchActionKind.TAKEOFF,
                    starts_at_source_s=takeoff_start,
                    ends_at_source_s=takeoff_end,
                    required=True,
                    rationale="launch inside the admitted route window",
                ),
                LaunchAction(
                    kind=LaunchActionKind.STABILIZE,
                    starts_at_source_s=takeoff_end,
                    ends_at_source_s=stabilization_end,
                    required=True,
                    rationale="short declared airborne stabilization",
                ),
            )
        )
        airborne_wait = route.airborne_wait_s
        if airborne_wait > 0.0:
            actions.append(
                LaunchAction(
                    kind=LaunchActionKind.AIRBORNE_STAGE,
                    starts_at_source_s=stabilization_end,
                    ends_at_source_s=route_start,
                    required=route.airborne_wait_s > 0.0,
                    rationale=(
                        "candidate explicitly requires airborne staging"
                        if route.airborne_wait_s > 0.0
                        else "schedule alignment residual"
                    ),
                )
            )
        actions.extend(
            (
                LaunchAction(
                    kind=LaunchActionKind.START_ROUTE,
                    starts_at_source_s=route_start,
                    ends_at_source_s=route_end,
                    required=True,
                    rationale="execute accepted bounded route",
                ),
                LaunchAction(
                    kind=LaunchActionKind.LAND,
                    starts_at_source_s=route_end,
                    ends_at_source_s=route_end + landing_duration_s,
                    required=True,
                    rationale="land in the accepted terminal region",
                ),
            )
        )
        if (
            airborne_wait > case.hard_constraints.maximum_unrequired_airborne_wait_s
            and route.airborne_wait_s <= 0.0
        ):
            raise ValueError("schedule creates excessive non-required airborne waiting")
        route_energy = route.path_length_m + airborne_wait * 0.25
        end_battery = drone.initial_battery_percent - route_energy - 1.0
        if end_battery < drone.minimum_reserve_battery_percent:
            raise ValueError(f"role {route.role_id} violates landing reserve")
        roles.append(
            RoleLaunchSchedule(
                role_id=route.role_id,
                actions=tuple(actions),
                energy=RoleEnergyBudget(
                    role_id=route.role_id,
                    ground_wait_s=takeoff_start,
                    airborne_hover_s=airborne_wait,
                    route_energy_percent=route_energy,
                    landing_reserve_percent=drone.minimum_reserve_battery_percent,
                    predicted_end_battery_percent=end_battery,
                ),
            )
        )
        completion = max(completion, route_end + landing_duration_s)
    semantics = case.semantics
    if (
        semantics is not None
        and semantics.goal_seeking is not None
        and semantics.scenario_events
    ):
        # The initial route is not the terminal timing authority for a sensed-world
        # mission.  A final accepted event may legitimately replace that route from
        # the then-current state. Reserve one complete admitted route, the bounded
        # planning budget, and landing after the last trigger. This remains a finite,
        # hash-bound wall watchdog; it does not mark stalled telemetry as fresh.
        latest_trigger_s = max(
            event.trigger_time_s for event in semantics.scenario_events
        )
        route_start_s = max(
            action.starts_at_source_s
            for role in roles
            for action in role.actions
            if action.kind is LaunchActionKind.START_ROUTE
        )
        maximum_route_duration_s = max(
            route.route_duration_s for route in candidate.routes
        )
        completion = max(
            completion,
            route_start_s
            + latest_trigger_s
            + case.hard_constraints.planning_budget_s
            + maximum_route_duration_s
            + landing_duration_s,
        )
        if completion > case.hard_constraints.deadline_s:
            raise ValueError("dynamic replanning watchdog exceeds the hard mission deadline")
    watchdog = (
        completion / case.hard_constraints.minimum_realtime_factor
        + case.hard_constraints.watchdog_guard_s
    )
    payload: dict[str, object] = {
        "case_sha256": case.case_sha256,
        "candidate_sha256": candidate.candidate_sha256,
        "roles": tuple(roles),
        "source_schedule_duration_s": completion,
        "wall_watchdog_s": watchdog,
        "minimum_realtime_factor": case.hard_constraints.minimum_realtime_factor,
        "watchdog_guard_s": case.hard_constraints.watchdog_guard_s,
    }
    if planning_submission_id is not None or planning_submission_sha256 is not None:
        payload.update(
            {
                "planning_submission_id": planning_submission_id,
                "planning_submission_sha256": planning_submission_sha256,
            }
        )
    return GroundFirstSchedule(**payload, schedule_sha256=canonical_sha256(payload))


def launch_readiness(
    case: CampaignCase,
    *,
    role_id: str,
    battery_percent: float,
    health: str,
    volume_occupied: bool,
    reservations_current: bool,
) -> tuple[bool, tuple[str, ...]]:
    drone = next(drone for drone in case.drones if drone.role_id == role_id)
    failures = []
    if battery_percent < drone.minimum_reserve_battery_percent:
        failures.append("BATTERY")
    if health != "HEALTHY":
        failures.append("HEALTH")
    if volume_occupied:
        failures.append("VOLUME_OCCUPANCY")
    if not reservations_current:
        failures.append("RESERVATIONS")
    return not failures, tuple(failures)
