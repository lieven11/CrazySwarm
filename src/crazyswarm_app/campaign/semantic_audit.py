from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field

from crazyswarm_app.campaign.models import (
    BehaviorOracleKind,
    CampaignCase,
    ImplementationStatus,
    RouteNodeMode,
)
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256


class SemanticAuditClassification(StrEnum):
    SEMANTICALLY_EXECUTABLE = "SEMANTICALLY_EXECUTABLE"
    INTENTIONAL_SHARED_BASELINE = "INTENTIONAL_SHARED_BASELINE"
    PLACEHOLDER_QUARANTINED = "PLACEHOLDER_QUARANTINED"


class CaseSemanticAudit(ContractModel):
    case_id: Identifier
    execution_semantics_sha256: SHA256
    classification: SemanticAuditClassification
    invariant_failures: tuple[str, ...] = ()
    duplicate_case_ids: tuple[Identifier, ...] = ()
    reason: str = Field(min_length=1, max_length=1000)


class CatalogSemanticAudit(ContractModel):
    cases: tuple[CaseSemanticAudit, ...]

    @property
    def failed_executable_case_ids(self) -> tuple[str, ...]:
        return tuple(
            item.case_id
            for item in self.cases
            if item.classification is SemanticAuditClassification.PLACEHOLDER_QUARANTINED
        )


def audit_case(case: CampaignCase) -> CaseSemanticAudit:
    failures = family_invariant_failures(case)
    if case.implementation_status is ImplementationStatus.PLANNED_NOT_EXECUTABLE:
        return CaseSemanticAudit(
            case_id=case.case_id,
            execution_semantics_sha256=case.execution_semantics_sha256,
            classification=SemanticAuditClassification.PLACEHOLDER_QUARANTINED,
            invariant_failures=failures or ("CASE_DECLARED_PLANNED_NOT_EXECUTABLE",),
            reason="Case is retained as a static placeholder and has no execution authority.",
        )
    if case.semantics is None:
        if case.case_id == "three_drone_multi_conflict":
            return CaseSemanticAudit(
                case_id=case.case_id,
                execution_semantics_sha256=case.execution_semantics_sha256,
                classification=SemanticAuditClassification.INTENTIONAL_SHARED_BASELINE,
                invariant_failures=(),
                reason=(
                    "Frozen WP-33 development baseline retained for historical evidence identity."
                ),
            )
        failures = (*failures, "MISSING_EXECUTABLE_SEMANTIC_CONTRACT")
    if failures:
        return CaseSemanticAudit(
            case_id=case.case_id,
            execution_semantics_sha256=case.execution_semantics_sha256,
            classification=SemanticAuditClassification.PLACEHOLDER_QUARANTINED,
            invariant_failures=tuple(sorted(set(failures))),
            reason="The named behavior is absent from compiler-consumed case inputs.",
        )
    classification = (
        SemanticAuditClassification.INTENTIONAL_SHARED_BASELINE
        if case.semantics is not None and case.semantics.semantic_baseline_case_id is not None
        else SemanticAuditClassification.SEMANTICALLY_EXECUTABLE
    )
    return CaseSemanticAudit(
        case_id=case.case_id,
        execution_semantics_sha256=case.execution_semantics_sha256,
        classification=classification,
        reason=(
            "Executable behavior contract passes the family invariant and declares "
            "its baseline delta."
            if classification is SemanticAuditClassification.INTENTIONAL_SHARED_BASELINE
            else "Executable behavior contract passes the family invariant."
        ),
    )


def audit_catalog(cases: Iterable[CampaignCase]) -> CatalogSemanticAudit:
    values = tuple(cases)
    grouped: dict[str, list[str]] = defaultdict(list)
    for case in values:
        grouped[case.execution_semantics_sha256].append(case.case_id)
    output = []
    for case in sorted(values, key=lambda item: item.case_id):
        audit = audit_case(case)
        duplicates = tuple(
            sorted(
                case_id
                for case_id in grouped[case.execution_semantics_sha256]
                if case_id != case.case_id
            )
        )
        if duplicates and not (
            case.semantics is not None
            and case.semantics.semantic_baseline_case_id is not None
            and case.semantics.intended_delta is not None
        ):
            audit = audit.model_copy(
                update={
                    "classification": SemanticAuditClassification.PLACEHOLDER_QUARANTINED,
                    "invariant_failures": tuple(
                        sorted((*audit.invariant_failures, "UNDECLARED_SEMANTIC_DUPLICATE"))
                    ),
                    "duplicate_case_ids": duplicates,
                    "reason": (
                        "Execution semantics duplicate another case without a named causal delta."
                    ),
                }
            )
        elif duplicates:
            audit = audit.model_copy(update={"duplicate_case_ids": duplicates})
        output.append(audit)
    return CatalogSemanticAudit(cases=tuple(output))


def family_invariant_failures(case: CampaignCase) -> tuple[str, ...]:
    if case.semantics is None:
        return ()
    failures: list[str] = []
    routes = {
        drone.role_id: tuple(goal.center_m for goal in drone.goal_sequence) for drone in case.drones
    }
    modes = {
        role_id: tuple(node.mode for node in nodes)
        for role_id, nodes in case.semantics.route_intent_by_role.items()
    }
    all_points = tuple(point for route in routes.values() for point in route)
    all_modes = tuple(mode for route_modes in modes.values() for mode in route_modes)
    oracle_kinds = {oracle.kind for oracle in case.semantics.behavior_oracles}

    if case.family == "continuous_waypoint_sequence" and (
        any(len(route) < 3 for route in routes.values())
        or any(mode is not RouteNodeMode.FLY_THROUGH for mode in all_modes)
    ):
        failures.append("CONTINUOUS_SEQUENCE_REQUIRES_THREE_FLY_THROUGH_NODES")
    if case.family == "altitude_transition" and (
        len({round(point.z, 3) for point in all_points}) < 3
        or BehaviorOracleKind.ALTITUDE_TRANSITION not in oracle_kinds
    ):
        failures.append("ALTITUDE_TRANSITION_REQUIRES_THREE_LEVELS_AND_ORACLE")
    if case.family == "move_return":
        drone = case.drones[0]
        if (
            _horizontal_distance(drone.start_region.center_m, routes[drone.role_id][-1]) > 0.08
            or RouteNodeMode.REVERSAL not in modes[drone.role_id]
        ):
            failures.append("MOVE_RETURN_REQUIRES_AUTHORED_REVERSAL_AND_HOME_RETURN")
    if case.family in {"curved_route", "planar_shape_loop"} and not any(
        _integrated_turn(route) > 0.20 for route in routes.values()
    ):
        failures.append("CURVED_FAMILY_REQUIRES_NONZERO_INTEGRATED_CURVATURE")
    if case.family == "planar_shape_loop" and not any(
        _has_repeated_node(route) for route in routes.values()
    ):
        failures.append("SHAPE_LOOP_REQUIRES_EXPLICIT_LOOP_CLOSURE")
    if case.family == "static_multi_goal_sequence" and (
        len(all_points) < 3
        or any(mode is not RouteNodeMode.CAPTURE_AND_HOLD for mode in all_modes)
        or BehaviorOracleKind.HOLD_DURATION not in oracle_kinds
    ):
        failures.append("STATIC_MULTI_GOAL_REQUIRES_THREE_DECLARED_HOLDS")
    if case.family == "point_to_point_relocation":
        drone = case.drones[0]
        if _horizontal_distance(drone.start_region.center_m, drone.landing_region.center_m) < 0.20:
            failures.append("RELOCATION_REQUIRES_DISTINCT_START_AND_LANDING")
    if "leader" in case.family and not any(drone.roles for drone in case.drones):
        failures.append("LEADER_FOLLOWER_REQUIRES_EXPLICIT_ROLE_BINDING")
    if case.family in {"leader_follower", "formation_spacing", "formation_shape_transform"}:
        coordination = case.semantics.coordination_constraints
        if (
            not coordination.synchronized_route_start_required
            or coordination.minimum_simultaneous_flight_s <= 0.0
            or BehaviorOracleKind.FORMATION_ERROR not in oracle_kinds
        ):
            failures.append("FORMATION_REQUIRES_SYNCHRONIZED_OVERLAP_AND_ERROR_ORACLE")
    if case.family == "bottleneck" and not case.semantics.environment_constraints.keep_out_regions:
        failures.append("BOTTLENECK_REQUIRES_CONFIGURED_KEEP_OUT_GEOMETRY")
    if case.family == "boundary_constrained_route" and (
        BehaviorOracleKind.BOUNDARY_MARGIN not in oracle_kinds
    ):
        failures.append("BOUNDARY_ROUTE_REQUIRES_SAMPLED_MARGIN_ORACLE")
    if case.family == "bottleneck" and BehaviorOracleKind.KEEP_OUT_AVOIDED not in oracle_kinds:
        failures.append("BOTTLENECK_REQUIRES_KEEP_OUT_EVIDENCE_ORACLE")
    if case.family == "no_hover_crossing" and (
        case.hard_constraints.hover_allowed
        or case.hard_constraints.maximum_hover_s != 0.0
        or BehaviorOracleKind.NO_AIRBORNE_HOLD not in oracle_kinds
    ):
        failures.append("NO_HOVER_CASE_REQUIRES_ZERO_HOLD_CONTRACT_AND_ORACLE")
    if case.family in {"unequal_priority", "unequal_priorities"} and (
        len({drone.priority for drone in case.drones}) < 2
        or BehaviorOracleKind.PRIORITY_PRECEDENCE not in oracle_kinds
    ):
        failures.append("PRIORITY_CASE_REQUIRES_UNEQUAL_INPUTS_AND_PRECEDENCE_ORACLE")
    if case.family in {"constrained_border_height", "constrained_volume"} and (
        case.hard_constraints.vertical_layers_allowed
        or BehaviorOracleKind.CONSTRAINT_ENFORCED not in oracle_kinds
    ):
        failures.append("CONSTRAINED_VOLUME_REQUIRES_FORBIDDEN_LAYER_AND_ORACLE")
    if case.family == "single_pair_conflict" and (
        BehaviorOracleKind.UNAFFECTED_ROLE_NONINTERFERENCE not in oracle_kinds
    ):
        failures.append("SELECTIVE_CONFLICT_REQUIRES_UNAFFECTED_ROLE_ORACLE")
    dynamic_families = {
        "moving_target",
        "mid_route_goal_replacement",
        "duplicate_stale_goal_update",
        "planning_budget_expiry",
        "blocked_replan",
        "operator_approval_goal_replacement",
        "failure_recovery",
        "abort_and_land_goal_fallback",
        "leader_loss",
        "duplicate_assignment_rejection",
        "coordination_failure",
        "crossing_goal_change",
        "simultaneous_conflicting_updates",
        "partial_replacement_failure",
        "role_allocation",
        "persistent_coverage_reserve_handover",
        "leader_follower_recovery",
        "cascading_replan",
        "acknowledgement_loss",
        "fleet_abort_fallback",
    }
    if (
        case.family in dynamic_families
        and case.implementation_milestone is not None
        and (
            not case.semantics.scenario_events
            or BehaviorOracleKind.EVENT_HANDLED not in oracle_kinds
        )
    ):
        failures.append("DYNAMIC_FAMILY_REQUIRES_CAUSAL_EVENT_AND_EVENT_ORACLE")
    return tuple(sorted(set(failures)))


def _horizontal_distance(first: Vector3, second: Vector3) -> float:
    return math.hypot(first.x - second.x, first.y - second.y)


def _has_repeated_node(points: tuple[Vector3, ...]) -> bool:
    for index, point in enumerate(points):
        if any(_distance(point, other) <= 0.08 for other in points[index + 2 :]):
            return True
    return False


def _integrated_turn(points: tuple[Vector3, ...]) -> float:
    total = 0.0
    for first, middle, last in zip(points, points[1:], points[2:], strict=False):
        before = (middle.x - first.x, middle.y - first.y)
        after = (last.x - middle.x, last.y - middle.y)
        first_angle = math.atan2(before[1], before[0])
        second_angle = math.atan2(after[1], after[0])
        delta = (second_angle - first_angle + math.pi) % (2.0 * math.pi) - math.pi
        total += abs(delta)
    return total


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )
