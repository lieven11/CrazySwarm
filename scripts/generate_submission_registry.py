#!/usr/bin/env python3
"""Generate the reviewed WP-52--WP-56 case-submission registry.

The source matrix is intentionally compact here, while the generated YAML freezes
every discovered case hash and expands each admission record through the production
schema.  Regeneration fails if the catalog or the reviewed 20/18/16 inventory moves.
"""

# The compact reviewed matrix intentionally keeps one complete experiment per line.
# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

import yaml

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import ImplementationStatus
from crazyswarm_app.domain.simulation import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "missions/campaigns/sim/submissions/case-submissions-v1.yaml"
ADMISSION_OUTPUT = ROOT / "missions/campaigns/sim/submissions/admission-records-v1.yaml"


def s(
    submission_id: str,
    experiment_id: str,
    axis: str,
    axis_value: str,
    *,
    strategies: tuple[str, ...] = (),
    objectives: tuple[str, ...] = (),
    layer: str = "P",
    fallback: str | None = None,
    capability: str | None = None,
    kind: str | None = None,
    parameters: dict[str, float] | None = None,
    adherence: str = "REQUIRED_REGIONS",
    deviation: float | None = None,
    synchronized: bool | None = None,
    overlap_s: float | None = None,
    selection_oracle: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "submission_id": submission_id,
        "display_name": submission_id.replace(".", " · ").replace("_", " "),
        "layer": layer,
        "experiment_id": experiment_id,
        "axis": axis,
        "axis_value": axis_value,
        "rationale": (
            f"Applies the reviewed {axis_value.replace('_', ' ')} alternative while "
            "preserving the immutable case and every unmentioned authority field."
        ),
        "causal_question": (
            f"For {experiment_id}, does {axis}={axis_value} change the accepted behavior "
            "while the immutable case and all unmentioned authority remain fixed?"
        ),
        "baseline_limitation": (
            f"The retained baseline cannot isolate the {experiment_id} value {axis_value}."
        ),
        "behavior_difference": (
            f"Only {axis} is authored as {axis_value}; its exact behavior-driving fields "
            "are bound into the semantic fingerprint."
        ),
        "distinguishing_oracle": (
            f"Compile {experiment_id}={axis_value}, independently certify the candidate, "
            "and compare its accepted plan and trajectory identities with the exact baseline."
        ),
        "reused_evidence": ["immutable_case_hash", "bounded_planner_contract"],
        "new_integration_gate": (
            f"The normal planning and trajectory path must demonstrate the {experiment_id} "
            f"value {axis_value}; runtime/evidence claims remain open unless separately retained."
        ),
        "backend_semantics": (
            "The configured fast-sim-v1 planner may compile this row; no live simulator, "
            "physical, or hardware equivalence is implied."
        ),
        "safety_bounds": (
            "Case volume, separation, dynamics, energy, freshness, authority, atomicity, "
            "and terminal gates remain immutable and cannot be weakened."
        ),
        "operator_comparison": (
            f"Show {experiment_id}={axis_value}, support status, accepted plan/trajectory "
            "difference, and every applicable safety metric beside the exact baseline."
        ),
        "learning_value": (
            f"Retain {experiment_id}={axis_value} only when compilation or the independent "
            "behavior oracle distinguishes it from the baseline or its experiment peer."
        ),
        "path_adherence_mode": adherence,
    }
    if strategies:
        item["strategy_authority"] = list(strategies)
    if objectives:
        item["objective_focus"] = list(objectives)
    if fallback:
        item["fallback_policy"] = fallback
    if capability:
        item["capability_id"] = capability
    if kind:
        item["execution_kind"] = kind
    if parameters:
        item["execution_parameters"] = parameters
    if deviation is not None:
        item["maximum_centerline_deviation_m"] = deviation
    if synchronized is not None:
        item["synchronized"] = synchronized
    if overlap_s is not None:
        item["minimum_simultaneous_flight_s"] = overlap_s
    if selection_oracle is not None:
        item["selection_oracle"] = selection_oracle
    return item


P = "PLANNED_NOT_EXECUTABLE"
T = ("GROUND_DELAY",)
S = ("SPEED_RETIMING",)
L = ("HORIZONTAL_DETOUR",)
V = ("VERTICAL_LAYER",)
C = ("COMBINED_TIMING_GEOMETRY",)


MATRIX: dict[str, list[dict[str, object]] | str] = {
    "1d.takeoff_hover_land.canonical_nominal": [
        s(
            "vertical_cycle.precision_first",
            "vertical_cycle.duration",
            "SCALAR_PARAMETER",
            "precision",
            layer="E",
            kind="DURATION_SCALE",
            parameters={"duration_scale": 1.25},
        ),
        s(
            "vertical_cycle.minimum_duration",
            "vertical_cycle.duration",
            "SCALAR_PARAMETER",
            "minimum_duration",
            layer="E",
            kind="DURATION_SCALE",
            parameters={"duration_scale": 0.85},
        ),
    ],
    "1d.point_to_point_relocation.canonical_nominal": [
        s(
            "relocation.minimum_time",
            "relocation.objective",
            "OBJECTIVE_ORDER",
            "minimum_time",
            objectives=("MISSION_COMPLETION_TIME_S",),
        ),
        s(
            "relocation.energy_reserve",
            "relocation.objective",
            "OBJECTIVE_ORDER",
            "energy_reserve",
            objectives=("TOTAL_ENERGY_PERCENT",),
        ),
    ],
    "1d.move_return.canonical_nominal": [
        s(
            "turnaround.reversal_stop_first",
            "turnaround.objective",
            "OBJECTIVE_ORDER",
            "reversal_stop",
            objectives=("PATH_LENGTH_M", "MISSION_COMPLETION_TIME_S"),
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
        s(
            "turnaround.continuity_first",
            "turnaround.objective",
            "OBJECTIVE_ORDER",
            "continuity",
            objectives=("JERK_M_S3", "MISSION_COMPLETION_TIME_S"),
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
    ],
    "1d.altitude_transition.canonical_nominal": "RETAIN_EXISTING",
    "1d.altitude_transition.wide": "RETAIN_EXISTING",
    "1d.continuous_waypoint_sequence.canonical_nominal": [
        s(
            "waypoint.centerline_first",
            "waypoint.objective",
            "OBJECTIVE_ORDER",
            "centerline",
            objectives=("PATH_LENGTH_M", "JERK_M_S3"),
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
        s(
            "waypoint.smoothness_first",
            "waypoint.execution_profile",
            "CAPABILITY_BINDING",
            "corner_transition_0_60s_at_0_08m_s",
            layer="E",
            capability="core.corner_transition",
            kind="CORNER_TRANSITION",
            parameters={"target_path_speed_m_s": 0.08, "lookahead_time_s": 0.60},
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
    ],
    "1d.curved_route.canonical_nominal": [
        s(
            "curve.centerline_fidelity",
            "curve.objective",
            "OBJECTIVE_ORDER",
            "centerline",
            objectives=("PATH_LENGTH_M", "JERK_M_S3"),
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
        s(
            "curve.jerk_first",
            "curve.execution_profile",
            "SCALAR_PARAMETER",
            "duration_scale_1_30",
            layer="E",
            kind="DURATION_SCALE",
            parameters={"duration_scale": 1.30},
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
    ],
    "1d.planar_shape_loop.circle": [
        s(
            "loop.radial_fidelity",
            "circle.objective",
            "OBJECTIVE_ORDER",
            "radial_fidelity",
            objectives=("PATH_LENGTH_M", "JERK_M_S3"),
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
        s(
            "core.constant_path_speed",
            "circle.capability",
            "CAPABILITY_BINDING",
            "constant_path_speed",
            layer="C",
            capability="core.constant_path_speed",
            kind="CONSTANT_PATH_SPEED",
            parameters={"target_path_speed_m_s": 0.18},
        ),
    ],
    "1d.planar_shape_loop.rounded_square": [
        s(
            "corner_transition.lookahead_0_20s",
            "corner_transition.lookahead",
            "SCALAR_PARAMETER",
            "lookahead_0_20s",
            layer="E",
            kind="CORNER_TRANSITION",
            parameters={"target_path_speed_m_s": 0.40, "lookahead_time_s": 0.20},
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
        s(
            "corner_transition.lookahead_0_60s",
            "corner_transition.lookahead",
            "SCALAR_PARAMETER",
            "lookahead_0_60s",
            layer="E",
            kind="CORNER_TRANSITION",
            parameters={"target_path_speed_m_s": 0.40, "lookahead_time_s": 0.60},
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
    ],
    "1d.planar_shape_loop.figure_eight": [
        s(
            "loop.crossover_fidelity",
            "figure_eight.objective",
            "OBJECTIVE_ORDER",
            "crossover_fidelity",
            objectives=("PATH_LENGTH_M", "JERK_M_S3"),
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
        s(
            "loop.curvature_continuity",
            "figure_eight.execution_profile",
            "CAPABILITY_BINDING",
            "corner_transition_0_60s_at_0_08m_s",
            layer="E",
            capability="core.corner_transition",
            kind="CORNER_TRANSITION",
            parameters={"target_path_speed_m_s": 0.08, "lookahead_time_s": 0.60},
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
    ],
    "1d.static_multi_goal_sequence.canonical_nominal": [
        s(
            "goals.shortest_valid_capture",
            "multi_goal.objective",
            "OBJECTIVE_ORDER",
            "shortest_capture",
            objectives=("MISSION_COMPLETION_TIME_S", "JERK_M_S3"),
        ),
        s(
            "goals.smooth_transition",
            "multi_goal.objective",
            "OBJECTIVE_ORDER",
            "smooth_transition",
            objectives=("JERK_M_S3", "MISSION_COMPLETION_TIME_S"),
        ),
    ],
    "1d.boundary_constrained_route.canonical_nominal": [
        s(
            "boundary.route_fidelity",
            "boundary.objective",
            "OBJECTIVE_ORDER",
            "route_fidelity",
            objectives=("PATH_LENGTH_M", "BOUNDARY_ROBUSTNESS_M"),
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
        s(
            "boundary.robustness_first",
            "boundary.objective",
            "OBJECTIVE_ORDER",
            "robustness",
            objectives=("BOUNDARY_ROBUSTNESS_M", "PATH_LENGTH_M"),
            adherence="HARD_TUBE",
            deviation=0.03,
        ),
    ],
    "1d.moving_target.dynamic_nominal": [
        s(
            "moving_target.earliest_intercept",
            "moving_target.objective",
            "OBJECTIVE_ORDER",
            "earliest_intercept",
            objectives=("MISSION_COMPLETION_TIME_S", "JERK_M_S3"),
            layer="R",
            fallback="SAFE_PREFIX",
        ),
        s(
            "moving_target.smooth_intercept",
            "moving_target.objective",
            "OBJECTIVE_ORDER",
            "smooth_intercept",
            objectives=("JERK_M_S3", "MISSION_COMPLETION_TIME_S"),
            layer="R",
            fallback="SAFE_PREFIX",
        ),
    ],
    "1d.mid_route_goal_replacement.dynamic_nominal": [
        s(
            "goal_replacement.minimum_latency",
            "goal_replacement.objective",
            "OBJECTIVE_ORDER",
            "minimum_latency",
            objectives=("MISSION_COMPLETION_TIME_S", "JERK_M_S3"),
            layer="R",
            fallback="SAFE_PREFIX",
        ),
        s(
            "goal_replacement.smooth_splice",
            "goal_replacement.objective",
            "OBJECTIVE_ORDER",
            "smooth_splice",
            objectives=("JERK_M_S3", "MISSION_COMPLETION_TIME_S"),
            layer="R",
            fallback="SAFE_PREFIX",
        ),
    ],
    "1d.duplicate_stale_goal_update.dynamic_nominal": "Duplicate and stale generations must always reject without changing route, hash, or cutover.",
    "1d.planning_budget_expiry.dynamic_nominal": [
        s(
            "budget_expiry.safe_prefix",
            "budget_expiry.fallback",
            "FALLBACK_POLICY",
            "safe_prefix",
            layer="R",
            fallback="SAFE_PREFIX",
        ),
        s(
            "budget_expiry.bounded_hold",
            "budget_expiry.fallback",
            "FALLBACK_POLICY",
            "bounded_hold",
            layer="R",
            fallback="BOUNDED_HOLD",
        ),
    ],
    "1d.blocked_replan.dynamic_nominal": [
        s(
            "blocked_replan.safe_prefix",
            "blocked_replan.fallback",
            "FALLBACK_POLICY",
            "safe_prefix",
            layer="R",
            fallback="SAFE_PREFIX",
        ),
        s(
            "blocked_replan.controlled_land",
            "blocked_replan.fallback",
            "FALLBACK_POLICY",
            "controlled_land",
            layer="R",
            fallback="CONTROLLED_LAND",
        ),
    ],
    "1d.operator_approval_goal_replacement.dynamic_nominal": "Hash-bound operator approval is the causal question; bypass authority is not a valid alternative.",
    "1d.abort_and_land_goal_fallback.dynamic_nominal": "The approved abort-and-land fallback defines the case; another destination requires a successor case.",
    "1d.failure_recovery.dynamic_nominal": "Observation loss retains the reviewed safe recovery; speculative navigation is not admitted.",
    "2d.head_on_conflict.canonical_nominal": [
        s(
            "constraint_directed.head_on.same_path",
            "head_on.compatibility",
            "CAPABILITY_BINDING",
            "retained",
            synchronized=True,
            overlap_s=2.0,
            adherence="GOAL_SEQUENCE_ONLY",
        ),
        s(
            "head_on.earliest_safe_release",
            "head_on.timing",
            "MANEUVER_DIMENSION",
            "timing",
            strategies=T,
            selection_oracle="ARGMIN_BOUNDED_RELEASE",
        ),
        s(
            "head_on.synchronized_lateral",
            "head_on.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
            synchronized=True,
            overlap_s=2.0,
        ),
        s(
            "head_on.synchronized_vertical",
            "head_on.authority",
            "MANEUVER_DIMENSION",
            "vertical",
            strategies=V,
            synchronized=True,
            overlap_s=2.0,
        ),
        s(
            "head_on.path_fidelity_combined",
            "head_on.objective",
            "OBJECTIVE_ORDER",
            "path_fidelity",
            strategies=C,
            objectives=("PATH_LENGTH_M", "SEPARATION_ROBUSTNESS_M"),
            synchronized=True,
            overlap_s=2.0,
        ),
        s(
            "head_on.robustness_combined",
            "head_on.objective",
            "OBJECTIVE_ORDER",
            "robustness",
            strategies=C,
            objectives=("SEPARATION_ROBUSTNESS_M", "PATH_LENGTH_M"),
            synchronized=True,
            overlap_s=2.0,
        ),
    ],
    "2d.perpendicular_crossing.nominal_equal_priority": [
        s(
            "crossing.earliest_equal_release",
            "crossing.timing",
            "MANEUVER_DIMENSION",
            "timing",
            strategies=T,
            selection_oracle="ARGMIN_BOUNDED_RELEASE",
        ),
        s(
            "crossing.synchronized_lateral",
            "crossing.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
            synchronized=True,
            overlap_s=2.0,
        ),
        s(
            "crossing.synchronized_vertical",
            "crossing.authority",
            "MANEUVER_DIMENSION",
            "vertical",
            strategies=V,
            synchronized=True,
            overlap_s=2.0,
        ),
    ],
    "2d.merge.canonical_nominal": [
        s(
            "constraint_directed.merge.flexible_geometry",
            "merge.compatibility",
            "CAPABILITY_BINDING",
            "retained",
            synchronized=True,
            overlap_s=2.0,
            adherence="GOAL_SEQUENCE_ONLY",
        ),
        s(
            "merge.earliest_precedence",
            "merge.objective",
            "OBJECTIVE_ORDER",
            "earliest",
            objectives=("MISSION_COMPLETION_TIME_S", "MAXIMUM_WAIT_S"),
        ),
        s(
            "merge.fair_release",
            "merge.objective",
            "OBJECTIVE_ORDER",
            "fair",
            objectives=("MAXIMUM_WAIT_S", "MISSION_COMPLETION_TIME_S"),
        ),
        s(
            "merge.parallel_lanes",
            "merge.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
            synchronized=True,
            overlap_s=2.0,
        ),
        s(
            "merge.vertical_stack",
            "merge.authority",
            "MANEUVER_DIMENSION",
            "vertical",
            strategies=V,
            synchronized=True,
            overlap_s=2.0,
        ),
    ],
    "2d.overtake.canonical_nominal": [
        s(
            "overtake.speed_retimed_follow",
            "overtake.authority",
            "MANEUVER_DIMENSION",
            "speed",
            strategies=S,
        ),
        s(
            "overtake.lateral_pass",
            "overtake.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
        ),
        s(
            "overtake.vertical_pass",
            "overtake.authority",
            "MANEUVER_DIMENSION",
            "vertical",
            strategies=V,
        ),
    ],
    "2d.bottleneck.canonical_nominal": [
        s(
            "constraint_directed.bottleneck.simultaneous_vertical",
            "bottleneck.vertical",
            "MANEUVER_DIMENSION",
            "vertical",
            strategies=V,
            synchronized=True,
            overlap_s=2.0,
            adherence="GOAL_SEQUENCE_ONLY",
        ),
        s(
            "bottleneck.earliest_safe_release",
            "bottleneck.objective",
            "OBJECTIVE_ORDER",
            "earliest",
            strategies=T,
            objectives=("MISSION_COMPLETION_TIME_S", "MAXIMUM_WAIT_S"),
        ),
        s(
            "bottleneck.fair_precedence",
            "bottleneck.objective",
            "OBJECTIVE_ORDER",
            "fair",
            strategies=T,
            objectives=("MAXIMUM_WAIT_S", "MISSION_COMPLETION_TIME_S"),
        ),
    ],
    "2d.parallel_routes.canonical_nominal": [
        s(
            "parallel.phase_locked",
            "parallel.objective",
            "OBJECTIVE_ORDER",
            "phase_locked",
            objectives=("MISSION_COMPLETION_TIME_S", "TOTAL_ENERGY_PERCENT"),
        ),
        s(
            "parallel.energy_balanced",
            "parallel.objective",
            "OBJECTIVE_ORDER",
            "energy_balanced",
            objectives=("TOTAL_ENERGY_PERCENT", "MISSION_COMPLETION_TIME_S"),
        ),
    ],
    "2d.leader_follower.canonical_nominal": [
        s(
            "leader_follower.rigid_offset",
            "leader_follower.objective",
            "OBJECTIVE_ORDER",
            "rigid_offset",
            objectives=("PATH_LENGTH_M", "JERK_M_S3"),
        ),
        s(
            "leader_follower.elastic_smooth",
            "leader_follower.objective",
            "OBJECTIVE_ORDER",
            "elastic_smooth",
            objectives=("JERK_M_S3", "PATH_LENGTH_M"),
        ),
    ],
    "2d.formation_spacing.canonical_nominal": [
        s(
            "formation.spacing_fidelity",
            "formation.objective",
            "OBJECTIVE_ORDER",
            "spacing",
            objectives=("PATH_LENGTH_M", "JERK_M_S3"),
        ),
        s(
            "formation.centroid_smoothness",
            "formation.objective",
            "OBJECTIVE_ORDER",
            "centroid_smoothness",
            objectives=("JERK_M_S3", "PATH_LENGTH_M"),
        ),
    ],
    "2d.role_allocation.canonical_nominal": [
        s(
            "allocation.capability_first",
            "allocation.objective",
            "OBJECTIVE_ORDER",
            "capability",
            objectives=("PRIORITY_INVERSION", "TOTAL_ENERGY_PERCENT"),
        ),
        s(
            "allocation.energy_reserve",
            "allocation.objective",
            "OBJECTIVE_ORDER",
            "energy",
            objectives=("TOTAL_ENERGY_PERCENT", "PRIORITY_INVERSION"),
        ),
    ],
    "2d.duplicate_assignment_rejection.dynamic_nominal": "Atomic duplicate rejection has no safe acceptance alternative.",
    "2d.unequal_priority.canonical_nominal": [
        s(
            "priority.strict_lexicographic",
            "priority.objective",
            "OBJECTIVE_ORDER",
            "strict",
            objectives=("PRIORITY_INVERSION", "MAXIMUM_WAIT_S"),
        ),
        s(
            "priority.bounded_fairness",
            "priority.objective",
            "OBJECTIVE_ORDER",
            "bounded_fairness",
            objectives=("MAXIMUM_WAIT_S", "PRIORITY_INVERSION"),
        ),
    ],
    "2d.constrained_border_height.canonical_nominal": [
        s(
            "constrained_height.timing_only",
            "constrained_height.authority",
            "MANEUVER_DIMENSION",
            "timing",
            strategies=T,
        ),
        s(
            "constrained_height.lateral_only",
            "constrained_height.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
        ),
    ],
    "2d.no_hover_crossing.canonical_nominal": [
        s(
            "no_hover.ground_release",
            "no_hover.authority",
            "MANEUVER_DIMENSION",
            "ground_release",
            strategies=T,
        ),
        s("no_hover.speed_only", "no_hover.authority", "MANEUVER_DIMENSION", "speed", strategies=S),
        s(
            "no_hover.lateral_only",
            "no_hover.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
        ),
    ],
    "2d.crossing_goal_change.dynamic_nominal": [
        s(
            "crossing_update.minimum_delay",
            "crossing_update.objective",
            "OBJECTIVE_ORDER",
            "minimum_delay",
            layer="R",
            fallback="SAFE_PREFIX",
            objectives=("MISSION_COMPLETION_TIME_S",),
        ),
        s(
            "crossing_update.minimum_affected_set",
            "crossing_update.objective",
            "OBJECTIVE_ORDER",
            "minimum_affected_set",
            layer="R",
            fallback="SAFE_PREFIX",
            objectives=("MAXIMUM_WAIT_S",),
        ),
    ],
    "2d.simultaneous_conflicting_updates.dynamic_nominal": [
        s(
            "conflicting_updates.source_order",
            "conflicting_updates.policy",
            "FALLBACK_POLICY",
            "source_order",
            layer="R",
            fallback="SAFE_OLD_EPOCH",
        ),
        s(
            "conflicting_updates.role_priority",
            "conflicting_updates.policy",
            "FALLBACK_POLICY",
            "role_priority",
            layer="R",
            fallback="SAFE_PREFIX",
        ),
    ],
    "2d.partial_replacement_failure.dynamic_nominal": "Partial prepare or commit is always forbidden; accepting a subset is not a submission.",
    "2d.leader_loss.dynamic_nominal": [
        s(
            "leader_loss.promote_follower",
            "leader_loss.fallback",
            "FALLBACK_POLICY",
            "promote_follower",
            layer="R",
            fallback="PROMOTE_SUCCESSOR",
        ),
        s(
            "leader_loss.coordinated_land",
            "leader_loss.fallback",
            "FALLBACK_POLICY",
            "coordinated_land",
            layer="R",
            fallback="COORDINATED_LAND",
        ),
    ],
    "2d.coordination_failure.dynamic_nominal": [
        s(
            "coordination_failure.safe_old_epoch",
            "coordination_failure.fallback",
            "FALLBACK_POLICY",
            "safe_old_epoch",
            layer="R",
            fallback="SAFE_OLD_EPOCH",
        ),
        s(
            "coordination_failure.coordinated_land",
            "coordination_failure.fallback",
            "FALLBACK_POLICY",
            "coordinated_land",
            layer="R",
            fallback="COORDINATED_LAND",
        ),
    ],
    "3d.single_pair_conflict.canonical_nominal": [
        s(
            "single_pair.selective_timing",
            "single_pair.authority",
            "MANEUVER_DIMENSION",
            "timing",
            strategies=T,
        ),
        s(
            "single_pair.selective_lateral",
            "single_pair.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
        ),
        s(
            "single_pair.selective_vertical",
            "single_pair.authority",
            "MANEUVER_DIMENSION",
            "vertical",
            strategies=V,
        ),
    ],
    "3d.simultaneous_center_conflict.joint_schedule_v2": [
        s(
            "center.global_earliest_schedule",
            "center.timing",
            "MANEUVER_DIMENSION",
            "timing",
            strategies=T,
        ),
        s(
            "center.synchronized_lateral",
            "center.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
            synchronized=True,
            overlap_s=2.0,
        ),
        s(
            "center.synchronized_layers",
            "center.authority",
            "MANEUVER_DIMENSION",
            "vertical",
            strategies=V,
            synchronized=True,
            overlap_s=2.0,
        ),
        s(
            "center.earliest_combined",
            "center.objective",
            "OBJECTIVE_ORDER",
            "earliest",
            objectives=("MISSION_COMPLETION_TIME_S", "SEPARATION_ROBUSTNESS_M"),
            synchronized=True,
            overlap_s=2.0,
        ),
        s(
            "center.robust_combined",
            "center.objective",
            "OBJECTIVE_ORDER",
            "robust",
            objectives=("SEPARATION_ROBUSTNESS_M", "MISSION_COMPLETION_TIME_S"),
            synchronized=True,
            overlap_s=2.0,
            selection_oracle="ARGMAX_BOUNDED_CLEARANCE",
        ),
    ],
    "3d.merge.canonical_nominal": [
        s(
            "merge.fifo_fair",
            "merge3.objective",
            "OBJECTIVE_ORDER",
            "fifo_fair",
            objectives=("MAXIMUM_WAIT_S", "PRIORITY_INVERSION"),
        ),
        s(
            "merge.priority_precedence",
            "merge3.objective",
            "OBJECTIVE_ORDER",
            "priority",
            objectives=("PRIORITY_INVERSION", "MAXIMUM_WAIT_S"),
        ),
        s(
            "merge.parallel_capacity",
            "merge3.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
        ),
        s(
            "merge.vertical_capacity",
            "merge3.authority",
            "MANEUVER_DIMENSION",
            "vertical",
            strategies=V,
        ),
    ],
    "3d.bottleneck.canonical_nominal": [
        s(
            "bottleneck.earliest_queue",
            "bottleneck3.objective",
            "OBJECTIVE_ORDER",
            "earliest",
            objectives=("MISSION_COMPLETION_TIME_S", "MAXIMUM_WAIT_S"),
        ),
        s(
            "bottleneck.max_wait_fair",
            "bottleneck3.objective",
            "OBJECTIVE_ORDER",
            "max_wait",
            objectives=("MAXIMUM_WAIT_S", "MISSION_COMPLETION_TIME_S"),
        ),
        s(
            "bottleneck.direction_batch",
            "bottleneck3.objective",
            "OBJECTIVE_ORDER",
            "direction_batch",
            objectives=("AIRBORNE_HOVER_TIME_S", "MISSION_COMPLETION_TIME_S"),
        ),
    ],
    "three_drone_multi_conflict": "Legacy compatibility case overlaps the canonical simultaneous-center family; no new choice is admitted.",
    "3d.formation_shape_transform.canonical_nominal": [
        s(
            "formation.shape_fidelity",
            "formation3.objective",
            "OBJECTIVE_ORDER",
            "shape",
            objectives=("PATH_LENGTH_M", "JERK_M_S3"),
        ),
        s(
            "formation.centroid_smoothness",
            "formation3.objective",
            "OBJECTIVE_ORDER",
            "centroid",
            objectives=("JERK_M_S3", "PATH_LENGTH_M"),
        ),
        s(
            "formation.energy_balance",
            "formation3.objective",
            "OBJECTIVE_ORDER",
            "energy",
            objectives=("TOTAL_ENERGY_PERCENT", "PATH_LENGTH_M"),
        ),
    ],
    "3d.role_allocation.canonical_nominal": [
        s(
            "allocation.capability_priority",
            "allocation3.objective",
            "OBJECTIVE_ORDER",
            "capability_priority",
            objectives=("PRIORITY_INVERSION", "TOTAL_ENERGY_PERCENT"),
        ),
        s(
            "allocation.energy_reserve",
            "allocation3.objective",
            "OBJECTIVE_ORDER",
            "energy",
            objectives=("TOTAL_ENERGY_PERCENT", "PRIORITY_INVERSION"),
        ),
        s(
            "allocation.balanced_utilization",
            "allocation3.objective",
            "OBJECTIVE_ORDER",
            "balanced",
            objectives=("MAXIMUM_WAIT_S", "TOTAL_ENERGY_PERCENT"),
        ),
    ],
    "3d.duplicate_assignment_rejection.dynamic_nominal": "Duplicate ownership must atomically reject for every role order.",
    "3d.persistent_coverage_reserve_handover.dynamic_nominal": [
        s(
            "handover.minimum_coverage_gap",
            "handover.objective",
            "OBJECTIVE_ORDER",
            "minimum_gap",
            objectives=("MISSION_COMPLETION_TIME_S", "TOTAL_ENERGY_PERCENT"),
            layer="R",
            fallback="PROMOTE_SUCCESSOR",
        ),
        s(
            "handover.maximum_reserve_margin",
            "handover.objective",
            "OBJECTIVE_ORDER",
            "reserve_margin",
            objectives=("TOTAL_ENERGY_PERCENT", "MISSION_COMPLETION_TIME_S"),
            layer="R",
            fallback="PROMOTE_SUCCESSOR",
        ),
    ],
    "3d.unequal_priorities.canonical_nominal": [
        s(
            "priorities.strict_lexicographic",
            "priorities3.objective",
            "OBJECTIVE_ORDER",
            "strict",
            objectives=("PRIORITY_INVERSION", "MAXIMUM_WAIT_S"),
        ),
        s(
            "priorities.bounded_fairness",
            "priorities3.objective",
            "OBJECTIVE_ORDER",
            "bounded_fairness",
            objectives=("MAXIMUM_WAIT_S", "PRIORITY_INVERSION"),
        ),
        s(
            "priorities.minimax_wait",
            "priorities3.objective",
            "OBJECTIVE_ORDER",
            "minimax_wait",
            objectives=("STARVATION", "MAXIMUM_WAIT_S", "PRIORITY_INVERSION"),
        ),
    ],
    "3d.constrained_volume.canonical_nominal": [
        s(
            "constrained.timing_makespan",
            "constrained3.objective",
            "OBJECTIVE_ORDER",
            "makespan",
            strategies=T,
            objectives=("MISSION_COMPLETION_TIME_S", "MAXIMUM_WAIT_S"),
        ),
        s(
            "constrained.priority_order",
            "constrained3.objective",
            "OBJECTIVE_ORDER",
            "priority",
            strategies=T,
            objectives=("PRIORITY_INVERSION", "MISSION_COMPLETION_TIME_S"),
        ),
        s(
            "constrained.robust_schedule",
            "constrained3.objective",
            "OBJECTIVE_ORDER",
            "robust",
            strategies=T,
            objectives=("SEPARATION_ROBUSTNESS_M", "MISSION_COMPLETION_TIME_S"),
        ),
    ],
    "3d.alternative_layers_detours.canonical_nominal": [
        s(
            "alternatives.lateral_only",
            "alternatives.authority",
            "MANEUVER_DIMENSION",
            "lateral",
            strategies=L,
        ),
        s(
            "alternatives.vertical_only",
            "alternatives.authority",
            "MANEUVER_DIMENSION",
            "vertical",
            strategies=V,
        ),
        s(
            "alternatives.energy_combined",
            "alternatives.objective",
            "OBJECTIVE_ORDER",
            "energy",
            strategies=C,
            objectives=("TOTAL_ENERGY_PERCENT", "SEPARATION_ROBUSTNESS_M"),
        ),
        s(
            "alternatives.robust_combined",
            "alternatives.objective",
            "OBJECTIVE_ORDER",
            "robust",
            strategies=C,
            objectives=("SEPARATION_ROBUSTNESS_M", "TOTAL_ENERGY_PERCENT"),
        ),
    ],
    "3d.cascading_replan.dynamic_nominal": [
        s(
            "cascade.minimum_affected_set",
            "cascade.objective",
            "OBJECTIVE_ORDER",
            "affected_set",
            layer="R",
            fallback="SAFE_OLD_EPOCH",
            objectives=("MAXIMUM_WAIT_S",),
        ),
        s(
            "cascade.minimum_completion",
            "cascade.objective",
            "OBJECTIVE_ORDER",
            "completion",
            layer="R",
            fallback="SAFE_OLD_EPOCH",
            objectives=("MISSION_COMPLETION_TIME_S",),
        ),
        s(
            "cascade.robustness_first",
            "cascade.objective",
            "OBJECTIVE_ORDER",
            "robustness",
            layer="R",
            fallback="SAFE_OLD_EPOCH",
            objectives=("SEPARATION_ROBUSTNESS_M",),
        ),
    ],
    "3d.acknowledgement_loss.dynamic_nominal": [
        s(
            "ack_loss.safe_old_epoch",
            "ack_loss.fallback",
            "FALLBACK_POLICY",
            "safe_old_epoch",
            layer="R",
            fallback="SAFE_OLD_EPOCH",
        ),
        s(
            "ack_loss.fleet_land",
            "ack_loss.fallback",
            "FALLBACK_POLICY",
            "fleet_land",
            layer="R",
            fallback="COORDINATED_LAND",
        ),
    ],
    "3d.fleet_abort_fallback.dynamic_nominal": "The defining safe outcome is coordinated all-fleet abort and landing; weaker alternatives are not admitted.",
    "3d.leader_follower_recovery.dynamic_nominal": [
        s(
            "formation_loss.deterministic_successor",
            "formation_loss.fallback",
            "FALLBACK_POLICY",
            "successor",
            layer="R",
            fallback="PROMOTE_SUCCESSOR",
        ),
        s(
            "formation_loss.fleet_land",
            "formation_loss.fallback",
            "FALLBACK_POLICY",
            "fleet_land",
            layer="R",
            fallback="COORDINATED_LAND",
        ),
    ],
}

# Production-path audit dispositions.  These are deliberately retained in the
# 54-row inventory but cannot be selected for a run: the first set did not produce a
# certified plan inside the immutable case bounds, while the second compiled to the
# same accepted candidate as its baseline or experiment peer.
UNSUPPORTED_IDS = {
    "corner_transition.lookahead_0_20s",
    "constrained_height.lateral_only",
    "no_hover.speed_only",
    "no_hover.lateral_only",
    "alternatives.lateral_only",
    "alternatives.vertical_only",
    "alternatives.energy_combined",
    "alternatives.robust_combined",
    "bottleneck.earliest_queue",
    "bottleneck.max_wait_fair",
    "bottleneck.direction_batch",
    "center.earliest_combined",
    "single_pair.selective_lateral",
}

ATOMIC_DISABLED_IDS = {
    "head_on.synchronized_lateral",
    "head_on.synchronized_vertical",
    "head_on.path_fidelity_combined",
    "head_on.robustness_combined",
    "merge.parallel_lanes",
    "merge.vertical_stack",
    "crossing.synchronized_lateral",
    "crossing.synchronized_vertical",
    "merge.parallel_capacity",
    "merge.vertical_capacity",
    "center.synchronized_lateral",
    "center.synchronized_layers",
}

R6_COLLAPSE_KEYS = {
    "1d.boundary_constrained_route.canonical_nominal/boundary.route_fidelity",
    "1d.continuous_waypoint_sequence.canonical_nominal/waypoint.centerline_first",
    "1d.curved_route.canonical_nominal/curve.centerline_fidelity",
    "1d.move_return.canonical_nominal/turnaround.reversal_stop_first",
    "1d.planar_shape_loop.circle/loop.radial_fidelity",
    "1d.planar_shape_loop.figure_eight/loop.crossover_fidelity",
    "1d.point_to_point_relocation.canonical_nominal/relocation.minimum_time",
    "1d.point_to_point_relocation.canonical_nominal/relocation.energy_reserve",
    "1d.static_multi_goal_sequence.canonical_nominal/goals.shortest_valid_capture",
    "2d.bottleneck.canonical_nominal/bottleneck.fair_precedence",
    "2d.constrained_border_height.canonical_nominal/constrained_height.timing_only",
    "2d.formation_spacing.canonical_nominal/formation.spacing_fidelity",
    "2d.formation_spacing.canonical_nominal/formation.centroid_smoothness",
    "2d.leader_follower.canonical_nominal/leader_follower.rigid_offset",
    "2d.leader_follower.canonical_nominal/leader_follower.elastic_smooth",
    "2d.merge.canonical_nominal/merge.earliest_precedence",
    "2d.parallel_routes.canonical_nominal/parallel.phase_locked",
    "2d.parallel_routes.canonical_nominal/parallel.energy_balanced",
    "2d.unequal_priority.canonical_nominal/priority.bounded_fairness",
    "3d.constrained_volume.canonical_nominal/constrained.priority_order",
    "3d.formation_shape_transform.canonical_nominal/formation.shape_fidelity",
    "3d.formation_shape_transform.canonical_nominal/formation.centroid_smoothness",
    "3d.formation_shape_transform.canonical_nominal/formation.energy_balance",
    "3d.merge.canonical_nominal/merge.fifo_fair",
    "3d.merge.canonical_nominal/merge.priority_precedence",
    "3d.simultaneous_center_conflict.joint_schedule_v2/center.global_earliest_schedule",
    "3d.unequal_priorities.canonical_nominal/priorities.bounded_fairness",
    "3d.unequal_priorities.canonical_nominal/priorities.minimax_wait",
}

R6_PEER_COLLAPSE_TARGETS = {
    "2d.bottleneck.canonical_nominal/bottleneck.fair_precedence": (
        "2d.bottleneck.canonical_nominal/bottleneck.earliest_safe_release"
    ),
    "2d.unequal_priority.canonical_nominal/priority.bounded_fairness": (
        "2d.unequal_priority.canonical_nominal/priority.strict_lexicographic"
    ),
    "3d.constrained_volume.canonical_nominal/constrained.priority_order": (
        "3d.constrained_volume.canonical_nominal/constrained.timing_makespan"
    ),
    "3d.unequal_priorities.canonical_nominal/priorities.bounded_fairness": (
        "3d.unequal_priorities.canonical_nominal/priorities.strict_lexicographic"
    ),
    "3d.unequal_priorities.canonical_nominal/priorities.minimax_wait": (
        "3d.unequal_priorities.canonical_nominal/priorities.strict_lexicographic"
    ),
}

R6_CAPACITY_RELATIONS = {
    "2d.head_on_conflict.canonical_nominal/head_on.earliest_safe_release": (
        "CAT(DS_MANEUVER=timing),ARGMIN_BOUNDED(TM_RELEASE),"
        "PASS(TM_OVERLAP),PASS(SP_CLEARANCE)"
    ),
    "2d.merge.canonical_nominal/merge.fair_release": (
        "MIN(TM_WAIT),PASS(TM_OVERLAP),PASS(SP_CLEARANCE)"
    ),
    "2d.perpendicular_crossing.nominal_equal_priority/crossing.earliest_equal_release": (
        "CAT(DS_MANEUVER=timing),ARGMIN_BOUNDED(TM_RELEASE),"
        "PASS(TM_OVERLAP),PASS(SP_CLEARANCE)"
    ),
}

R6_PROFILE_ORACLES = {
    "1d.continuous_waypoint_sequence.canonical_nominal/waypoint.smoothness_first": {
        "experiment_id": "waypoint.execution_profile",
        "axis": "CAPABILITY_BINDING",
        "axis_value": "corner_transition_0_60s_at_0_08m_s",
        "qualifying_relation": (
            "MIN(DY_CURVATURE),MIN(SP_REFERENCE),MAX(TM_DURATION),PASS(SP_CAPTURE),"
            "ZERO(DS_UNINTENDED_STOP_COUNT)"
        ),
    },
    "1d.curved_route.canonical_nominal/curve.jerk_first": {
        "experiment_id": "curve.execution_profile",
        "axis": "SCALAR_PARAMETER",
        "axis_value": "duration_scale_1_30",
        "qualifying_relation": (
            "MIN(DY_JERK),MAX(TM_DURATION),PASS(SP_RADIAL),PASS(SP_REFERENCE),"
            "PASS(SP_CAPTURE)"
        ),
    },
    "1d.planar_shape_loop.figure_eight/loop.curvature_continuity": {
        "experiment_id": "figure_eight.execution_profile",
        "axis": "CAPABILITY_BINDING",
        "axis_value": "corner_transition_0_60s_at_0_08m_s",
        "qualifying_relation": (
            "MIN(DY_CURVATURE),MIN(SP_REFERENCE),PASS(SP_CAPTURE),"
            "CAT(DS_TOPOLOGY=figure_eight),CAT(DS_LOBE_ORDER=authored)"
        ),
    },
}

R6_ATOMIC_PEERS = {
    "2d.head_on_conflict.canonical_nominal/head_on.synchronized_lateral": (
        "2d.head_on_conflict.canonical_nominal/head_on.synchronized_vertical"
    ),
    "2d.head_on_conflict.canonical_nominal/head_on.synchronized_vertical": (
        "2d.head_on_conflict.canonical_nominal/head_on.synchronized_lateral"
    ),
    "2d.head_on_conflict.canonical_nominal/head_on.path_fidelity_combined": (
        "2d.head_on_conflict.canonical_nominal/head_on.robustness_combined"
    ),
    "2d.head_on_conflict.canonical_nominal/head_on.robustness_combined": (
        "2d.head_on_conflict.canonical_nominal/head_on.path_fidelity_combined"
    ),
    "2d.merge.canonical_nominal/merge.parallel_lanes": (
        "2d.merge.canonical_nominal/merge.vertical_stack"
    ),
    "2d.merge.canonical_nominal/merge.vertical_stack": (
        "2d.merge.canonical_nominal/merge.parallel_lanes"
    ),
    "2d.perpendicular_crossing.nominal_equal_priority/crossing.synchronized_lateral": (
        "2d.perpendicular_crossing.nominal_equal_priority/crossing.synchronized_vertical"
    ),
    "2d.perpendicular_crossing.nominal_equal_priority/crossing.synchronized_vertical": (
        "2d.perpendicular_crossing.nominal_equal_priority/crossing.synchronized_lateral"
    ),
    "3d.merge.canonical_nominal/merge.parallel_capacity": (
        "3d.merge.canonical_nominal/merge.vertical_capacity"
    ),
    "3d.merge.canonical_nominal/merge.vertical_capacity": (
        "3d.merge.canonical_nominal/merge.parallel_capacity"
    ),
    "3d.simultaneous_center_conflict.joint_schedule_v2/center.synchronized_lateral": (
        "3d.simultaneous_center_conflict.joint_schedule_v2/center.synchronized_layers"
    ),
    "3d.simultaneous_center_conflict.joint_schedule_v2/center.synchronized_layers": (
        "3d.simultaneous_center_conflict.joint_schedule_v2/center.synchronized_lateral"
    ),
}


def _reconcile_admission_registry() -> None:
    payload = yaml.safe_load(ADMISSION_OUTPUT.read_text(encoding="utf-8"))
    payload["oracle_contract_version"] = "wp52-56-r6-verified-oracle-v1"
    proposal_count = 0
    collapse_count = 0
    context_keys: set[str] = set()
    for row in payload["rows"]:
        case_id = row["case_id"]
        for proposal in row.get("proposals", []):
            proposal_count += 1
            key = f"{case_id}/{proposal['submission_id']}"
            if key in R6_COLLAPSE_KEYS:
                proposal["qualifying_relation"] = "COLLAPSE_ALL"
                target = R6_PEER_COLLAPSE_TARGETS.get(key)
                proposal["comparator_id"] = (
                    f"PEER({target})" if target else f"BASELINE({case_id})"
                )
                proposal["comparison_context_id"] = None
                collapse_count += 1
            elif key in R6_PROFILE_ORACLES:
                proposal.update(R6_PROFILE_ORACLES[key])
                proposal["comparator_id"] = f"BASELINE_EXECUTION_PROFILE({case_id})"
                proposal["comparison_context_id"] = None
            elif key in R6_CAPACITY_RELATIONS:
                proposal["qualifying_relation"] = R6_CAPACITY_RELATIONS[key]
                proposal["comparator_id"] = (
                    f"BASELINE({case_id},overlap-capacity-v1)"
                )
                proposal["comparison_context_id"] = "overlap-capacity-v1"
                context_keys.add(key)
            elif key in R6_ATOMIC_PEERS:
                proposal["comparator_id"] = f"PEER({R6_ATOMIC_PEERS[key]})"
                proposal["comparison_context_id"] = None
            elif key.endswith("/center.earliest_combined"):
                proposal["qualifying_relation"] = (
                    "OPEN(INCONCLUSIVE_MISSING_FEASIBLE_WITNESS)"
                )
                proposal["comparator_id"] = None
                proposal["comparison_context_id"] = None
            elif key.endswith("/center.robust_combined"):
                proposal["qualifying_relation"] = (
                    "ARGMAX_BOUNDED(SP_CLEARANCE),PASS(TM_OVERLAP),"
                    "SET(DS_ALL_ROLE_COMPLETION={Alpha,Beta,Gamma})"
                )
                proposal["comparator_id"] = None
                proposal["comparison_context_id"] = None
            elif proposal.get("comparison_context_id") is not None:
                raise ValueError(f"unexpected R6 comparison context key: {key}")
    if proposal_count != 111 or collapse_count != 28 or len(context_keys) != 3:
        raise ValueError(
            "R6 admission cardinality mismatch: "
            f"proposals={proposal_count}, collapses={collapse_count}, contexts={len(context_keys)}"
        )
    hashed_payload = dict(payload)
    hashed_payload.pop("source_payload_sha256", None)
    payload["source_payload_sha256"] = canonical_sha256(hashed_payload)
    ADMISSION_OUTPUT.write_text(
        yaml.safe_dump(payload, sort_keys=False, width=100),
        encoding="utf-8",
    )


def main() -> None:
    catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
    catalog.discover()
    cases = {case.case_id: case for case in catalog.cases()}
    if set(MATRIX) != set(cases):
        raise SystemExit(
            f"reviewed matrix mismatch: missing={sorted(set(cases) - set(MATRIX))}, "
            f"extra={sorted(set(MATRIX) - set(cases))}"
        )
    counts = {
        "1d": sum(case_id.startswith("1d.") for case_id in cases),
        "2d": sum(case_id.startswith("2d.") for case_id in cases),
        "3d": sum(
            case_id.startswith("3d.") or case_id == "three_drone_multi_conflict"
            for case_id in cases
        ),
    }
    if counts != {"1d": 20, "2d": 18, "3d": 16}:
        raise SystemExit(f"reviewed catalog cardinality changed: {counts}")

    rows: list[dict[str, object]] = []
    for case_id in sorted(cases):
        case = cases[case_id]
        disposition = MATRIX[case_id]
        row: dict[str, object] = {
            "case_id": case_id,
            "expected_case_sha256": case.case_sha256,
            "compatible_template_ids": [case.template_id],
            "default_strategy_authority": [item.value for item in case.allowed_strategies],
        }
        if disposition == "RETAIN_EXISTING":
            row["retain_existing_only"] = True
        elif isinstance(disposition, str):
            row["baseline_only"] = True
            row["baseline_only_rationale"] = disposition
        else:
            submissions = []
            for item in disposition:
                compiled = dict(item)
                proposal_key = f"{case_id}/{compiled['submission_id']}"
                production_disposition = (
                    compiled["submission_id"]
                    not in (UNSUPPORTED_IDS | ATOMIC_DISABLED_IDS)
                    and proposal_key not in R6_COLLAPSE_KEYS
                )
                compiled["status"] = (
                    "EXECUTABLE"
                    if case.implementation_status is ImplementationStatus.EXECUTABLE
                    and production_disposition
                    else P
                )
                if compiled["submission_id"] in ATOMIC_DISABLED_IDS:
                    compiled["support_reason"] = (
                        "The verified synchronized peer experiment is atomic and at least one "
                        "member lacks an accepted feasible witness; both members remain visible "
                        "and disabled without a runtime or safe-rejection claim."
                    )
                elif compiled["submission_id"] in UNSUPPORTED_IDS:
                    compiled["support_reason"] = (
                        "The validated 0.20 s lookahead compiler requires safety retiming that "
                        "exceeds the immutable rounded-square deadline; it remains visible as a "
                        "precise safe rejection and issues no command."
                        if compiled["submission_id"] == "corner_transition.lookahead_0_20s"
                        else "Production planning did not certify this alternative inside the immutable "
                        "case bounds; it remains visible as a precise safe rejection and issues no command."
                    )
                elif proposal_key in R6_COLLAPSE_KEYS:
                    compiled["catalog_visible"] = False
                    compiled["support_reason"] = (
                        "Production audit selected the same candidate as the exact baseline or its "
                        "experiment peer, so this label is collapsed and issues no command."
                    )
                else:
                    compiled["support_reason"] = (
                        "Executable through the configured Fast-Sim production planning path."
                        if compiled["status"] == "EXECUTABLE"
                        else "The immutable case or owning runtime capability remains planned-not-executable; selection issues no command."
                    )
                submissions.append(compiled)
            row["submissions"] = submissions
        rows.append(row)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "reviewed_counts": counts, "rows": rows},
            sort_keys=False,
            width=100,
        ),
        encoding="utf-8",
    )
    _reconcile_admission_registry()


if __name__ == "__main__":
    main()
