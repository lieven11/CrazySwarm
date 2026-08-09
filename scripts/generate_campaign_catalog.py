from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from crazyswarm_app.campaign.models import CampaignCase

CLUSTER_ORDER = (
    "BASIC_FLIGHT_AND_ROUTE_FOLLOWING",
    "GEOMETRIC_CONFLICT_RESOLUTION",
    "CONSTRAINTS_AND_OPTIMIZATION",
    "COORDINATION_AND_ALLOCATION",
    "FAILURE_RECOVERY_AND_REPLANNING",
)

CLUSTER_SLUGS = {
    "BASIC_FLIGHT_AND_ROUTE_FOLLOWING": "basic-flight-and-route-following",
    "GEOMETRIC_CONFLICT_RESOLUTION": "geometric-conflict-resolution",
    "CONSTRAINTS_AND_OPTIMIZATION": "constraints-and-optimization",
    "COORDINATION_AND_ALLOCATION": "coordination-and-allocation",
    "FAILURE_RECOVERY_AND_REPLANNING": "failure-recovery-and-replanning",
}

ONE_DRONE = (
    "takeoff_hover_land",
    "move_return",
    "continuous_waypoint_sequence",
    "curved_route",
    "altitude_transition",
    "boundary_constrained_route",
    "static_multi_goal_sequence",
    "failure_recovery",
)
TWO_DRONE = (
    "parallel_routes",
    "head_on_conflict",
    "perpendicular_crossing",
    "merge",
    "overtake",
    "bottleneck",
    "unequal_priority",
    "constrained_border_height",
    "no_hover_crossing",
    "leader_follower",
    "formation_spacing",
    "role_allocation",
    "leader_loss",
    "duplicate_assignment_rejection",
    "coordination_failure",
)
THREE_DRONE = (
    "single_pair_conflict",
    "simultaneous_center_conflict",
    "merge",
    "bottleneck",
    "unequal_priorities",
    "constrained_volume",
    "alternative_layers_detours",
    "role_allocation",
    "leader_follower_recovery",
    "duplicate_assignment_rejection",
    "persistent_coverage_reserve_handover",
)

DYNAMIC_CASES = (
    (1, "moving_target", "WP-34A", "move_return", "AUTO_WITHIN_FROZEN_LIMITS"),
    (
        1,
        "mid_route_goal_replacement",
        "WP-34A",
        "continuous_waypoint_sequence",
        "AUTO_WITHIN_FROZEN_LIMITS",
    ),
    (1, "duplicate_stale_goal_update", "WP-34A", "move_return", "AUTO_WITHIN_FROZEN_LIMITS"),
    (1, "planning_budget_expiry", "WP-34A", "move_return", "AUTO_WITHIN_FROZEN_LIMITS"),
    (1, "blocked_replan", "WP-34A", "move_return", "AUTO_WITHIN_FROZEN_LIMITS"),
    (
        1,
        "operator_approval_goal_replacement",
        "WP-34A",
        "move_return",
        "OPERATOR_APPROVAL_REQUIRED",
    ),
    (1, "abort_and_land_goal_fallback", "WP-34A", "move_return", "ABORT_ONLY"),
    (
        2,
        "crossing_goal_change",
        "WP-34B",
        "perpendicular_crossing",
        "AUTO_WITHIN_FROZEN_LIMITS",
    ),
    (
        2,
        "simultaneous_conflicting_updates",
        "WP-34B",
        "head_on_conflict",
        "AUTO_WITHIN_FROZEN_LIMITS",
    ),
    (
        2,
        "partial_replacement_failure",
        "WP-34B",
        "perpendicular_crossing",
        "AUTO_WITHIN_FROZEN_LIMITS",
    ),
    (
        3,
        "cascading_replan",
        "WP-34B",
        "simultaneous_center_conflict",
        "AUTO_WITHIN_FROZEN_LIMITS",
    ),
    (
        3,
        "acknowledgement_loss",
        "WP-34B",
        "simultaneous_center_conflict",
        "AUTO_WITHIN_FROZEN_LIMITS",
    ),
    (
        3,
        "fleet_abort_fallback",
        "WP-34B",
        "simultaneous_center_conflict",
        "AUTO_WITHIN_FROZEN_LIMITS",
    ),
)

SPECIAL_VARIATIONS = {
    "perpendicular_crossing": (
        "compact_equal_priority",
        "nominal_equal_priority",
        "wide_equal_priority",
        "wide_alpha_priority",
        "compact_no_hover",
        "constrained_height",
        "vertical_allowed",
        "vertical_forbidden",
        "latency_and_noise",
    ),
    "simultaneous_center_conflict": (
        "wide_priority_200_150_100",
        "compact_equal_priority",
        "nominal_equal_priority",
        "wide_unequal_priority",
        "compact_no_hover",
        "constrained_height",
        "vertical_allowed",
        "vertical_forbidden",
        "latency_and_noise",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the immutable WP33/WP34 catalog")
    parser.add_argument("--root", type=Path, default=Path("missions"))
    args = parser.parse_args()
    cases = []
    for count, families in ((1, ONE_DRONE), (2, TWO_DRONE), (3, THREE_DRONE)):
        for family in families:
            variations = SPECIAL_VARIATIONS.get(family, ("canonical_nominal", "compact", "wide"))
            _write_template(args.root, count, family, variations)
            for variation in variations:
                cases.append(_case(count, family, variation, variations))
    for count, family, _, _, _ in DYNAMIC_CASES:
        _write_template(args.root, count, family, ("dynamic_nominal",))
    cases.extend(_dynamic_cases())
    cases = [CampaignCase.model_validate(case).model_dump(mode="json") for case in cases]
    sim = args.root / "campaigns" / "sim" / "cases"
    for cluster in CLUSTER_ORDER:
        for count in (1, 2, 3):
            selected = [
                item
                for item in cases
                if item["cluster"] == cluster and item["drone_count"] == count
            ]
            if selected:
                path = sim / CLUSTER_SLUGS[cluster] / f"{count}d-cases-v1.yaml"
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_yaml(path, {"schema_version": 1, "cases": selected})

    canonical = next(item for item in cases if item["case_id"] == "three_drone_multi_conflict")
    profiles = args.root / "campaigns" / "sim" / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    _write_yaml(
        profiles / "default-development-preset-v1.yaml",
        {
            "schema_version": 1,
            "preset_id": "default-campaign-development-v1",
            "case_id": canonical["case_id"],
            "case_sha256": CampaignCase.model_validate(canonical).case_sha256,
            "backend_profile_id": "fast-sim-v1",
            "physical_flight_authorized": False,
        },
    )
    real_cases = [
        _real_mirror(item)
        for item in cases
        if item["variation_name"]
        in {"canonical_nominal", "nominal_equal_priority", "wide_priority_200_150_100"}
    ]
    real = args.root / "campaigns" / "real" / "authorized_cases"
    for cluster in CLUSTER_ORDER:
        selected = [item for item in real_cases if item["cluster"] == cluster]
        if selected:
            path = real / CLUSTER_SLUGS[cluster] / "real-mirrors-v1.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_yaml(path, {"schema_version": 1, "cases": selected})
    for directory in (
        args.root / "campaigns" / "sim" / "environments",
        args.root / "campaigns" / "sim" / "baselines",
        args.root / "campaigns" / "real" / "qualification_profiles",
        args.root / "campaigns" / "real" / "evidence",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return 0


def _case(count: int, family: str, variation: str, variations: tuple[str, ...]) -> dict[str, Any]:
    volume = _volume(variation)
    no_hover = "no_hover" in variation or family == "no_hover_crossing"
    vertical_allowed = (
        "vertical_forbidden" not in variation and "constrained_height" not in variation
    )
    priority = "priority" in variation or family in {"unequal_priority", "unequal_priorities"}
    drones = _drones(count, family, priority)
    case_id = f"{count}d.{family}.{variation}"
    if family == "simultaneous_center_conflict" and variation == "wide_priority_200_150_100":
        case_id = "three_drone_multi_conflict"
    metrics = _metrics(family)
    cluster = _cluster(family)
    strategies = ["DIRECT", "GROUND_DELAY", "SPEED_RETIMING", "HORIZONTAL_DETOUR"]
    if not no_hover:
        strategies.append("AIRBORNE_STAGING")
    if vertical_allowed:
        strategies.extend(("VERTICAL_LAYER", "COMBINED_TIMING_GEOMETRY"))
    return {
        "schema_version": 2,
        "case_id": case_id,
        "template_id": f"template.{count}d.{family}",
        "cluster": cluster,
        "family": family,
        "variation_name": variation,
        "purpose": f"Qualify the bounded {family.replace('_', ' ')} behavior for {count} drone(s).",
        "behavior_under_test": _behavior(family),
        "expected_outcome": _expected_outcome(cluster, family, variation),
        "environment": "SIMULATION",
        "authorization": "SOFTWARE_SIMULATION_ONLY",
        "implementation_status": "EXECUTABLE",
        "drone_count": count,
        "drones": drones,
        "hard_constraints": {
            "flight_volume": _region("flight-volume", volume[0], volume[1]),
            "warning_separation_m": 0.75,
            "critical_separation_m": 0.50,
            "position_uncertainty_m": 0.05,
            "dynamics": {
                "maximum_horizontal_speed_m_s": 0.5,
                "maximum_vertical_speed_m_s": 0.3,
                "maximum_acceleration_m_s2": 1.0,
                "maximum_jerk_m_s3": 8.0,
                "stop_speed_threshold_m_s": 0.02,
                "unintended_stop_persistence_s": 0.20,
            },
            "deadline_s": 180.0,
            "hover_allowed": not no_hover,
            "maximum_hover_s": 0.0 if no_hover else 60.0,
            "vertical_layers_allowed": vertical_allowed,
            "synchronized_launch_required": family in {"formation_spacing", "parallel_routes"},
            "maximum_unrequired_airborne_wait_s": 2.0,
            "maximum_equal_route_battery_spread_percent": 1.0,
            "minimum_realtime_factor": 0.80,
            "watchdog_guard_s": 2.0,
            "observation_freshness_limit_s": 0.25,
            "minimum_goal_update_interval_s": 0.50,
            "planning_budget_s": 2.0,
        },
        "allowed_strategies": strategies,
        "objective_order": [
            "PRIORITY_INVERSION",
            "STARVATION",
            "MISSION_COMPLETION_TIME_S",
            "MAXIMUM_WAIT_S",
            "TOTAL_ENERGY_PERCENT",
            "AIRBORNE_HOVER_TIME_S",
            "PATH_LENGTH_M",
            "ACCELERATION_M_S2",
            "JERK_M_S3",
            "SEPARATION_ROBUSTNESS_M",
            "BOUNDARY_ROBUSTNESS_M",
        ],
        "expected_decisions": _expected(family, vertical_allowed),
        "pass_fail_metrics": metrics,
        "execution_eligibility": "BOTH",
        "operator_observation_questions": (
            "Did displayed motion remain smooth without hiding delayed evidence?",
            "Did every role reach the declared goal and landing region?",
            "Did the selected strategy match the pre-play rationale?",
        ),
        "difficulty": _difficulty(count, cluster, family, variation),
        "prerequisites": _prerequisites(count, family),
        "claim_boundary": (
            "Bounded Fast Sim behavior for at most three drones; no physical-flight claim."
        ),
        "named_variations": variations,
        "search": {
            "implementation_id": "bounded-joint-candidate-planner",
            "implementation_version": "1.0.0",
            "prediction_step_s": 0.02,
            "maximum_candidate_count": 256,
            "planning_budget_s": 5.0,
            "lateral_offsets_m": [0.20, -0.20, 0.35, -0.35],
            "arc_radii_m": [0.20, 0.35],
            "vertical_offsets_m": [0.20, -0.20],
            "speed_factors": [0.80, 1.20],
            "delay_grid_s": [2.0, 4.0, 8.0, 12.0, 24.0, 40.0],
        },
        "execution": {
            "seed": 42 if "latency_and_noise" not in variation else 811,
            "repetitions": 1,
            "clock_modes": ["ACCELERATED", "REALTIME"],
            "backend_profile_id": "fast-sim-v1",
            "noise_latency_profile_id": "latency-noise-v1"
            if "latency_and_noise" in variation
            else "nominal-v1",
            "evidence_profile_id": "complete-evidence-v1",
            "configuration_sha256": "0" * 64,
            "playback_buffer_s": 0.25,
            "maximum_interpolation_gap_s": 0.20,
            "maximum_extrapolation_s": 0.10,
        },
        "replanning_authority": "ABORT_ONLY",
    }


def _drones(count: int, family: str, priority: bool) -> list[dict[str, Any]]:
    starts = (
        (-1.50, 0.0, 0.04),
        (0.0, -1.50, 0.04),
        (-1.06, -1.06, 0.04),
    )
    goals = (
        (1.50, 0.0, 0.30),
        (0.0, 1.50, 0.30),
        (1.06, 1.06, 0.30),
    )
    if family == "parallel_routes":
        starts = ((-1.50, -0.50, 0.04), (-1.50, 0.50, 0.04), starts[2])
        goals = ((1.50, -0.50, 0.30), (1.50, 0.50, 0.30), goals[2])
    if family in {"head_on_conflict", "overtake"}:
        starts = ((-1.50, 0.0, 0.04), (1.50, 0.0, 0.04), starts[2])
        goals = ((1.50, 0.0, 0.30), (-1.50, 0.0, 0.30), goals[2])
    values = []
    for index in range(count):
        role = ("Alpha", "Beta", "Gamma")[index]
        route_goals = [goals[index]]
        if family == "static_multi_goal_sequence":
            route_goals = [(-0.6, 0.3, 0.30), (0.0, -0.3, 0.45), (0.6, 0.3, 0.30)]
        landing = (route_goals[-1][0], route_goals[-1][1], 0.04)
        values.append(
            {
                "role_id": role,
                "start_region": _point_region(f"{role}-start", starts[index], 0.04),
                "goal_sequence": [
                    _point_region(f"{role}-goal-{goal_index + 1}", goal, 0.05)
                    for goal_index, goal in enumerate(route_goals)
                ],
                "landing_region": _point_region(f"{role}-landing", landing, 0.04),
                "initial_battery_percent": 100.0,
                "minimum_reserve_battery_percent": 20.0,
                "health": "HEALTHY",
                "priority": (200 - index * 50) if priority else 100,
                "roles": _roles(family, index),
                "required_capabilities": [
                    "arming",
                    "relative_positioning",
                    "high_level_commands",
                    "time_parameterized_trajectory",
                ],
                "available_capabilities": [
                    "arming",
                    "relative_positioning",
                    "high_level_commands",
                    "time_parameterized_trajectory",
                ],
            }
        )
    return values


def _dynamic_cases() -> list[dict[str, Any]]:
    cases = []
    for count, family, milestone, prerequisite, authority in DYNAMIC_CASES:
        value = _case(
            count,
            family,
            "dynamic_nominal",
            ("dynamic_nominal",),
        )
        prerequisite_id = f"{count}d.{prerequisite}.canonical_nominal"
        if prerequisite == "perpendicular_crossing":
            prerequisite_id = "2d.perpendicular_crossing.nominal_equal_priority"
        elif prerequisite == "simultaneous_center_conflict":
            prerequisite_id = "three_drone_multi_conflict"
        value.update(
            {
                "implementation_milestone": milestone,
                "prerequisites": (prerequisite_id,),
                "replanning_authority": authority,
                "expected_decisions": _dynamic_expected_decisions(family),
            }
        )
        cases.append(value)
    return cases


def _dynamic_expected_decisions(family: str) -> tuple[str, ...]:
    if family in {
        "duplicate_stale_goal_update",
        "planning_budget_expiry",
        "blocked_replan",
        "operator_approval_goal_replacement",
        "abort_and_land_goal_fallback",
        "partial_replacement_failure",
        "acknowledgement_loss",
        "fleet_abort_fallback",
    }:
        return ("SAFE_REJECTION", "DECLARED_FALLBACK")
    return ("ATOMIC_BOUNDED_REPLAN",)


def _real_mirror(case: dict[str, Any]) -> dict[str, Any]:
    source = CampaignCase.model_validate(case)
    mirrored = dict(case)
    mirrored.update(
        {
            "case_id": f"real.{case['case_id']}",
            "parent_case_sha256": source.case_sha256,
            "environment": "REAL",
            "authorization": "NOT_AUTHORIZED",
            "execution_eligibility": "STATIC_VALIDATE_ONLY",
        }
    )
    return CampaignCase.model_validate(mirrored).model_dump(mode="json")


def _volume(variation: str) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if "compact" in variation:
        return (-1.6, -1.6, 0.0), (1.6, 1.6, 0.7)
    if "constrained_height" in variation:
        return (-1.8, -1.8, 0.0), (1.8, 1.8, 0.42)
    return (-1.8, -1.8, 0.0), (1.8, 1.8, 1.0)


def _metrics(family: str) -> list[dict[str, Any]]:
    values = [
        _metric("minimum_truth_separation_m", "GREATER_THAN_OR_EQUAL", 0.75, "m"),
        _metric("maximum_tracking_rms_m", "LESS_THAN_OR_EQUAL", 0.05, "m"),
        _metric("maximum_tracking_error_m", "LESS_THAN_OR_EQUAL", 0.10, "m"),
        _metric("maximum_touchdown_horizontal_error_m", "LESS_THAN_OR_EQUAL", 0.10, "m"),
        _metric("maximum_touchdown_vertical_error_m", "LESS_THAN_OR_EQUAL", 0.08, "m"),
        _metric("maximum_terminal_speed_m_s", "LESS_THAN_OR_EQUAL", 0.05, "m/s"),
    ]
    if family == "persistent_coverage_reserve_handover":
        values.extend(
            (
                _metric("handover_trigger_battery_percent", "LESS_THAN_OR_EQUAL", 35.0, "%"),
                _metric("minimum_reserve_battery_percent", "GREATER_THAN_OR_EQUAL", 20.0, "%"),
                _metric("maximum_handover_latency_s", "LESS_THAN_OR_EQUAL", 5.0, "s"),
                _metric("maximum_coverage_gap_s", "LESS_THAN_OR_EQUAL", 1.0, "s"),
                _metric("maximum_coverage_gap_percent", "LESS_THAN_OR_EQUAL", 1.0, "%"),
                _metric("minimum_terminal_reserve_percent", "GREATER_THAN_OR_EQUAL", 20.0, "%"),
                _metric("duplicate_active_assignments", "EQUAL", 0.0, "count"),
            )
        )
    return values


def _metric(metric_id: str, comparator: str, threshold: float, unit: str) -> dict[str, Any]:
    return {"metric_id": metric_id, "comparator": comparator, "threshold": threshold, "unit": unit}


def _region(
    region_id: str, minimum: tuple[float, float, float], maximum: tuple[float, float, float]
) -> dict[str, Any]:
    return {
        "region_id": region_id,
        "frame": "world",
        "minimum_m": {"x": minimum[0], "y": minimum[1], "z": minimum[2]},
        "maximum_m": {"x": maximum[0], "y": maximum[1], "z": maximum[2]},
    }


def _point_region(
    region_id: str, point: tuple[float, float, float], half_width: float
) -> dict[str, Any]:
    return _region(
        region_id,
        (point[0] - half_width, point[1] - half_width, max(0.0, point[2] - half_width)),
        (point[0] + half_width, point[1] + half_width, point[2] + half_width),
    )


def _roles(family: str, index: int) -> tuple[str, ...]:
    if "leader" in family:
        return ("leader",) if index == 0 else ("follower",)
    if family == "persistent_coverage_reserve_handover":
        return ("coverage-owner",) if index == 0 else ("reserve",)
    return ("active-route",)


def _expected(family: str, vertical_allowed: bool) -> tuple[str, ...]:
    if family in {"duplicate_assignment_rejection", "coordination_failure"}:
        return ("SAFE_REJECTION",)
    if "failure" in family or "loss" in family:
        return ("BOUNDED_RECOVERY", "ABORT_AND_LAND")
    values = ["DIRECT", "GROUND_DELAY", "HORIZONTAL_DETOUR"]
    if vertical_allowed:
        values.append("VERTICAL_LAYER")
    return tuple(values)


def _behavior(family: str) -> str:
    descriptions = {
        "takeoff_hover_land": (
            "Checks a clean takeoff, stable hover, controlled descent, and landed/disarmed "
            "terminal state."
        ),
        "move_return": (
            "Checks continuous outbound and return motion, route tracking, and landing at the "
            "declared home region."
        ),
        "continuous_waypoint_sequence": (
            "Checks that ordered goal regions are visited smoothly without unintended stops "
            "between them."
        ),
        "curved_route": (
            "Checks curved-path construction, C2 continuity, dynamics limits, tracking, and "
            "touchdown."
        ),
        "altitude_transition": (
            "Checks bounded vertical motion and smooth transitions between altitude layers."
        ),
        "static_multi_goal_sequence": (
            "Checks three ordered goal captures before the final accepted landing region."
        ),
        "parallel_routes": (
            "Checks synchronized independent routes while preserving the required fleet spacing."
        ),
        "leader_follower": (
            "Checks leader/follower role binding, relative offset tracking, and isolated command "
            "routing."
        ),
        "formation_spacing": (
            "Checks synchronized formation motion and continuous spacing constraints."
        ),
        "role_allocation": (
            "Checks deterministic task ownership, capability matching, priority, and unique "
            "assignment."
        ),
        "persistent_coverage_reserve_handover": (
            "Checks reserve selection, atomic lease transfer, uninterrupted ownership, and safe "
            "outgoing landing."
        ),
    }
    if family in descriptions:
        return descriptions[family]
    name = family.replace("_", " ")
    if _cluster(family) == "GEOMETRIC_CONFLICT_RESOLUTION":
        return (
            f"Checks joint {name} prediction and resolution using admitted timing, speed, "
            "detour, or altitude candidates."
        )
    if _cluster(family) == "CONSTRAINTS_AND_OPTIMIZATION":
        return (
            f"Checks that {name} hard limits and objective order control admission and candidate "
            "ranking."
        )
    if _cluster(family) == "FAILURE_RECOVERY_AND_REPLANNING":
        return (
            f"Checks bounded {name} detection, authority handling, deterministic recovery, and "
            "retained failure evidence."
        )
    return (
        f"Checks deterministic {name} planning, execution, terminal state, and evidence "
        "classification."
    )


def _expected_outcome(cluster: str, family: str, variation: str) -> str:
    name = family.replace("_", " ")
    variation_name = variation.replace("_", " ")
    if cluster == "BASIC_FLIGHT_AND_ROUTE_FOLLOWING":
        return (
            f"The {name} route completes for the {variation_name} variation with smooth motion, "
            "bounded tracking error, accepted goal capture, and a landed/disarmed terminal state."
        )
    if cluster == "GEOMETRIC_CONFLICT_RESOLUTION":
        return (
            "The joint planner selects a fully validated separation strategy, or blocks with an "
            "exact reason; an admitted run stays outside warning and critical separation limits."
        )
    if cluster == "CONSTRAINTS_AND_OPTIMIZATION":
        return (
            "Forbidden strategies are rejected, hard limits are never weakened, and the selected "
            "candidate is optimal in the declared bounded objective order."
        )
    if cluster == "COORDINATION_AND_ALLOCATION":
        return (
            "Every task has one authoritative owner, assignments and leases remain unique, and all "
            "roles finish or enter their declared safe recovery state."
        )
    return (
        "The update or fault is accepted only with current authority and complete "
        "acknowledgements; otherwise it is rejected deterministically and the declared hold, "
        "abort, or landing fallback runs."
    )


def _cluster(family: str) -> str:
    failure = {
        "failure_recovery",
        "leader_loss",
        "coordination_failure",
        "moving_target",
        "mid_route_goal_replacement",
        "duplicate_stale_goal_update",
        "planning_budget_expiry",
        "blocked_replan",
        "operator_approval_goal_replacement",
        "abort_and_land_goal_fallback",
        "crossing_goal_change",
        "simultaneous_conflicting_updates",
        "partial_replacement_failure",
        "cascading_replan",
        "acknowledgement_loss",
        "fleet_abort_fallback",
        "leader_follower_recovery",
    }
    constraints = {
        "boundary_constrained_route",
        "unequal_priority",
        "constrained_border_height",
        "no_hover_crossing",
        "unequal_priorities",
        "constrained_volume",
        "alternative_layers_detours",
    }
    geometry = {
        "head_on_conflict",
        "perpendicular_crossing",
        "merge",
        "overtake",
        "bottleneck",
        "single_pair_conflict",
        "simultaneous_center_conflict",
    }
    coordination = {
        "parallel_routes",
        "leader_follower",
        "formation_spacing",
        "role_allocation",
        "duplicate_assignment_rejection",
        "persistent_coverage_reserve_handover",
    }
    if family in failure:
        return "FAILURE_RECOVERY_AND_REPLANNING"
    if family in constraints:
        return "CONSTRAINTS_AND_OPTIMIZATION"
    if family in geometry:
        return "GEOMETRIC_CONFLICT_RESOLUTION"
    if family in coordination:
        return "COORDINATION_AND_ALLOCATION"
    return "BASIC_FLIGHT_AND_ROUTE_FOLLOWING"


def _difficulty(count: int, cluster: str, family: str, variation: str) -> int:
    value = {1: 2, 2: 4, 3: 6}[count]
    if cluster in {
        "GEOMETRIC_CONFLICT_RESOLUTION",
        "CONSTRAINTS_AND_OPTIMIZATION",
        "COORDINATION_AND_ALLOCATION",
    }:
        value += 1
    if cluster == "FAILURE_RECOVERY_AND_REPLANNING":
        value += 2
    if any(token in variation for token in ("compact", "constrained", "latency")):
        value += 1
    if family in {"persistent_coverage_reserve_handover", "simultaneous_center_conflict"}:
        value += 1
    return min(10, value)


def _prerequisites(count: int, family: str) -> tuple[str, ...]:
    if count == 1 or family in {"parallel_routes", "single_pair_conflict"}:
        return ()
    return ("1d.takeoff_hover_land.canonical_nominal",)


def _write_template(root: Path, count: int, family: str, variations: tuple[str, ...]) -> None:
    fleet = {1: "one_drone", 2: "two_drone", 3: "three_drone"}[count]
    path = root / "library" / fleet / family / "mission.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    variation_rows = "\n".join(f'    "{variation}",' for variation in variations)
    content = (
        '"""Data-only campaign behavior template; catalog discovery never imports this file."""\n\n'
        f'TEMPLATE_ID = "template.{count}d.{family}"\n'
        f'CLUSTER = "{_cluster(family)}"\n'
        "PURPOSE = (\n"
        f'    "Deterministic {family.replace("_", " ")} planning and execution with "\n'
        '    "terminal-state and evidence classification."\n'
        ")\n"
        "EXPECTED_OUTCOME = (\n"
        f'    "{_expected_outcome(_cluster(family), family, variations[0])}"\n'
        ")\n"
        "NAMED_VARIATIONS = (\n"
        f"{variation_rows}\n"
        ")\n"
        "EXECUTES_ON_IMPORT = False\n"
    )
    path.write_text(content, encoding="utf-8")


def _write_yaml(path: Path, value: Any) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
