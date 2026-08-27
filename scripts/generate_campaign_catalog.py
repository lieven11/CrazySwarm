from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml
from campaign_case_specs import geometry

from crazyswarm_app.campaign.models import CampaignCase

CLUSTER_ORDER = (
    "BASIC_FLIGHT_AND_ROUTE_FOLLOWING",
    "DYNAMIC_REPLANNING",
    "GEOMETRIC_CONFLICT_RESOLUTION",
    "CONSTRAINTS_AND_OPTIMIZATION",
    "COORDINATION_AND_ALLOCATION",
    "FAILURE_RECOVERY_AND_REPLANNING",
)

CLUSTER_SLUGS = {
    "BASIC_FLIGHT_AND_ROUTE_FOLLOWING": "basic-flight-and-route-following",
    "DYNAMIC_REPLANNING": "dynamic-replanning",
    "GEOMETRIC_CONFLICT_RESOLUTION": "geometric-conflict-resolution",
    "CONSTRAINTS_AND_OPTIMIZATION": "constraints-and-optimization",
    "COORDINATION_AND_ALLOCATION": "coordination-and-allocation",
    "FAILURE_RECOVERY_AND_REPLANNING": "failure-recovery-and-replanning",
}

ONE_DRONE = (
    "takeoff_hover_land",
    "point_to_point_relocation",
    "move_return",
    "altitude_transition",
    "continuous_waypoint_sequence",
    "curved_route",
    "planar_shape_loop",
    "boundary_constrained_route",
    "static_multi_goal_sequence",
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
)
THREE_DRONE = (
    "single_pair_conflict",
    "simultaneous_center_conflict",
    "merge",
    "bottleneck",
    "unequal_priorities",
    "constrained_volume",
    "alternative_layers_detours",
    "formation_shape_transform",
    "role_allocation",
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
        "online_obstacle_replan",
        "WP-59E",
        "point_to_point_relocation",
        "AUTO_WITHIN_FROZEN_LIMITS",
    ),
    (
        1,
        "operator_approval_goal_replacement",
        "WP-34A",
        "move_return",
        "OPERATOR_APPROVAL_REQUIRED",
    ),
    (1, "abort_and_land_goal_fallback", "WP-34A", "move_return", "ABORT_ONLY"),
    (
        1,
        "failure_recovery",
        "WP-36B",
        "continuous_waypoint_sequence",
        "ABORT_ONLY",
    ),
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
    (2, "leader_loss", "WP-37B", "leader_follower", "ABORT_ONLY"),
    (
        2,
        "duplicate_assignment_rejection",
        "WP-37B",
        "role_allocation",
        "ABORT_ONLY",
    ),
    (2, "coordination_failure", "WP-37B", "formation_spacing", "ABORT_ONLY"),
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
    (
        3,
        "duplicate_assignment_rejection",
        "WP-38B",
        "role_allocation",
        "ABORT_ONLY",
    ),
    (
        3,
        "persistent_coverage_reserve_handover",
        "WP-38B",
        "formation_shape_transform",
        "AUTO_WITHIN_FROZEN_LIMITS",
    ),
    (
        3,
        "leader_follower_recovery",
        "WP-38B",
        "formation_shape_transform",
        "ABORT_ONLY",
    ),
)

SPECIAL_VARIATIONS = {
    "hover_endurance": ("hold_12s",),
    "axis_nudge_return": ("forward_x_10cm", "left_y_10cm", "right_y_10cm"),
    "short_offset_landing": ("forward_20cm", "forward_10cm", "diagonal_20cm"),
    "checkpoint_path": ("l_shape", "u_shape", "square"),
    "spatial_step_path": ("stair_step", "vertical_rectangle"),
    "polygon_loop": ("triangle", "square"),
    "altitude_transition": ("canonical_nominal", "wide"),
    "planar_shape_loop": ("circle", "rounded_square", "figure_eight"),
    "perpendicular_crossing": ("nominal_equal_priority",),
    "simultaneous_center_conflict": ("wide_priority_200_150_100",),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the immutable WP33/WP34 catalog")
    parser.add_argument("--root", type=Path, default=Path("missions"))
    args = parser.parse_args()
    cases = []
    for count, families in ((1, ONE_DRONE), (2, TWO_DRONE), (3, THREE_DRONE)):
        for family in families:
            variations = SPECIAL_VARIATIONS.get(family, ("canonical_nominal",))
            _write_template(args.root, count, family, variations)
            for variation in variations:
                cases.append(_case(count, family, variation, variations))
    for count, family, _, _, _ in DYNAMIC_CASES:
        _write_template(args.root, count, family, ("dynamic_nominal",))
    cases.extend(_dynamic_cases())
    cases.append(_legacy_three_drone_multi_conflict())
    cases = [CampaignCase.model_validate(case).model_dump(mode="json") for case in cases]
    for case in cases:
        if case.get("motion_quality_contract") is None:
            case.pop("motion_quality_contract", None)
        semantics = case.get("semantics")
        if isinstance(semantics, dict) and semantics.get("goal_seeking") is None:
            semantics.pop("goal_seeking", None)
    sim = args.root / "campaigns" / "sim" / "cases"
    for cluster in CLUSTER_ORDER:
        for count in (1, 2, 3):
            selected = [
                item
                for item in cases
                if item["cluster"] == cluster and item["drone_count"] == count
            ]
            path = sim / CLUSTER_SLUGS[cluster] / f"{count}d-cases-v1.yaml"
            if selected:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_yaml(path, {"schema_version": 1, "cases": selected})
            elif path.exists():
                path.unlink()

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
        if item.get("semantics") is not None
        if item["implementation_status"] == "EXECUTABLE"
        if item["variation_name"]
        in {"canonical_nominal", "nominal_equal_priority", "wide_priority_200_150_100"}
    ]
    real = args.root / "campaigns" / "real" / "authorized_cases"
    for cluster in CLUSTER_ORDER:
        selected = [item for item in real_cases if item["cluster"] == cluster]
        path = real / CLUSTER_SLUGS[cluster] / "real-mirrors-v1.yaml"
        if selected:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_yaml(path, {"schema_version": 1, "cases": selected})
        elif path.exists():
            path.unlink()
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
    if family in {"constrained_border_height", "constrained_volume"}:
        volume = (-1.8, -1.8, 0.0), (1.8, 1.8, 0.42)
    no_hover = "no_hover" in variation or family == "no_hover_crossing"
    vertical_allowed = (
        "vertical_forbidden" not in variation
        and "constrained_height" not in variation
        and family not in {"constrained_border_height", "constrained_volume"}
    )
    priority = "priority" in variation or family in {"unequal_priority", "unequal_priorities"}
    drones = _drones(count, family, priority, variation)
    case_id = f"{count}d.{family}.{variation}"
    if family == "simultaneous_center_conflict" and variation == "wide_priority_200_150_100":
        case_id = "3d.simultaneous_center_conflict.joint_schedule_v2"
    metrics = _metrics(family)
    cluster = _cluster(family)
    strategies = ["DIRECT", "GROUND_DELAY", "SPEED_RETIMING", "HORIZONTAL_DETOUR"]
    if not no_hover:
        strategies.append("AIRBORNE_STAGING")
    if vertical_allowed:
        strategies.extend(("VERTICAL_LAYER", "COMBINED_TIMING_GEOMETRY"))
    behavior_family = _behavior_family(family)
    if behavior_family in {
        "parallel_routes",
        "leader_follower",
        "formation_spacing",
        "formation_shape_transform",
    }:
        strategies = ["DIRECT"]
    runtime_implemented = family not in {"overtake", "role_allocation"}
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
        "implementation_status": (
            "EXECUTABLE" if runtime_implemented else "PLANNED_NOT_EXECUTABLE"
        ),
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
            "synchronized_launch_required": family
            in {
                "formation_spacing",
                "formation_shape_transform",
                "parallel_routes",
                "leader_follower",
            },
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
        "execution_eligibility": "BOTH" if runtime_implemented else "STATIC_VALIDATE_ONLY",
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
        "semantics": _semantics(count, family, variation, drones),
    }


def _drones(count: int, family: str, priority: bool, variation: str) -> list[dict[str, Any]]:
    values = []
    routes = geometry(count, family, variation)
    if len(routes) != count:
        raise ValueError(f"{count}d {family} authored {len(routes)} role routes")
    for index, (start, route_goals, landing, _) in enumerate(routes):
        role = ("Alpha", "Beta", "Gamma")[index]
        required = [
            "arming",
            "relative_positioning",
            "high_level_commands",
            "time_parameterized_trajectory",
        ]
        available = list(required)
        if family == "role_allocation" and index == 0:
            required.append("precision_positioning")
            available.append("precision_positioning")
        values.append(
            {
                "role_id": role,
                "start_region": _point_region(f"{role}-start", start, 0.04),
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
                "required_capabilities": required,
                "available_capabilities": available,
            }
        )
    return values


def _semantics(
    count: int,
    family: str,
    variation: str,
    drones: list[dict[str, Any]],
) -> dict[str, Any]:
    behavior_family = _behavior_family(family)
    routes = geometry(count, family, variation)
    route_intent = {}
    for drone, (_, _, _, modes) in zip(drones, routes, strict=True):
        route_intent[drone["role_id"]] = [
            {
                "region_id": goal["region_id"],
                "mode": mode,
                "dwell_s": (
                    12.0
                    if family == "hover_endurance"
                    else 3.0
                    if family == "takeoff_hover_land"
                    else 1.0
                    if mode == "CAPTURE_AND_HOLD"
                    else 0.0
                ),
                "capture_tolerance_m": (
                    0.03
                    if family in {"axis_nudge_return", "short_offset_landing"}
                    else 0.05
                    if family == "checkpoint_path"
                    else 0.08
                ),
            }
            for goal, mode in zip(drone["goal_sequence"], modes, strict=True)
        ]
    roles = tuple(drone["role_id"] for drone in drones)
    oracles = [
        _oracle("ordered-route-capture", "ROUTE_NODES_CAPTURED", "EXECUTION_TELEMETRY", roles),
        _oracle(
            "no-undeclared-stop", "NO_UNDECLARED_STOP", "EXECUTION_TELEMETRY", roles, 0.0, "count"
        ),
    ]
    if any(
        mode == "CAPTURE_AND_HOLD" for _start, _goals, _landing, modes in routes for mode in modes
    ):
        oracles.append(
            _oracle("declared-hold", "HOLD_DURATION", "EXECUTION_TELEMETRY", roles, 0.15, "s")
        )
    if behavior_family in {"altitude_transition", "spatial_step_path"} or behavior_family in {
        "alternative_layers_detours",
        "formation_shape_transform",
    }:
        oracles.append(
            _oracle(
                "altitude-layers",
                "ALTITUDE_TRANSITION",
                "EXECUTION_TELEMETRY",
                roles,
                2.0 if behavior_family == "spatial_step_path" else 3.0,
                "count",
            )
        )
    if behavior_family in {
        "curved_route",
        "continuous_waypoint_sequence",
        "polygon_loop",
        "leader_follower",
        "formation_spacing",
        "formation_shape_transform",
    }:
        oracles.append(
            _oracle("nonlinear-path", "CURVED_PATH", "EXECUTION_TELEMETRY", roles, 0.10, "rad")
        )
    if (
        behavior_family in {"planar_shape_loop", "polygon_loop"}
        or family == "persistent_coverage_reserve_handover"
    ):
        oracles.append(
            _oracle("closed-shape", "CLOSED_SHAPE", "EXECUTION_TELEMETRY", roles, 0.10, "m")
        )
    if any(
        drone["start_region"]["region_id"].replace("start", "landing")
        != drone["landing_region"]["region_id"]
        or _center(drone["start_region"])[:2] != _center(drone["landing_region"])[:2]
        for drone in drones
    ):
        offset_threshold_m = 0.20
        if family == "short_offset_landing":
            offset_threshold_m = 0.08
        elif family == "checkpoint_path":
            offset_threshold_m = 0.10
        oracles.append(
            _oracle(
                "offset-landing",
                "DISTINCT_START_AND_LANDING",
                "AUTHORED_ROUTE",
                roles,
                offset_threshold_m,
                "m",
            )
        )
    conflict_families = {
        "head_on_conflict",
        "perpendicular_crossing",
        "merge",
        "overtake",
        "bottleneck",
        "unequal_priority",
        "constrained_border_height",
        "no_hover_crossing",
        "single_pair_conflict",
        "simultaneous_center_conflict",
        "unequal_priorities",
        "constrained_volume",
        "alternative_layers_detours",
    }
    if behavior_family in conflict_families or family in {
        "crossing_goal_change",
        "simultaneous_conflicting_updates",
        "partial_replacement_failure",
        "cascading_replan",
        "acknowledgement_loss",
        "fleet_abort_fallback",
    }:
        oracles.append(
            _oracle("joint-separation", "CONFLICT_RESOLVED", "PLANNER_PREDICTION", roles, 0.80, "m")
        )
    if family == "boundary_constrained_route":
        oracles.append(
            _oracle(
                "sampled-boundary-margin",
                "BOUNDARY_MARGIN",
                "EXECUTION_TELEMETRY",
                roles,
                0.10,
                "m",
            )
        )
    if family == "bottleneck":
        oracles.append(
            _oracle(
                "configured-keep-out-avoidance",
                "KEEP_OUT_AVOIDED",
                "EXECUTION_TELEMETRY",
                roles,
                0.0,
                "violations",
            )
        )
    if family == "no_hover_crossing":
        oracles.append(
            _oracle(
                "zero-airborne-hold",
                "NO_AIRBORNE_HOLD",
                "EXECUTION_TELEMETRY",
                roles,
                0.0,
                "s",
            )
        )
    if family in {"unequal_priority", "unequal_priorities"}:
        oracles.append(
            _oracle(
                "priority-precedence",
                "PRIORITY_PRECEDENCE",
                "PLANNER_PREDICTION",
                roles,
                0.10,
                "s",
            )
        )
    if family in {"constrained_border_height", "constrained_volume"}:
        oracles.append(
            _oracle(
                "vertical-constraint-enforced",
                "CONSTRAINT_ENFORCED",
                "PLANNER_PREDICTION",
                roles,
                1.0,
                "boolean",
            )
        )
    if family == "single_pair_conflict":
        oracles.append(
            _oracle(
                "unaffected-gamma-delay",
                "UNAFFECTED_ROLE_NONINTERFERENCE",
                "PLANNER_PREDICTION",
                ("Gamma",),
                0.20,
                "s",
            )
        )

    coordination: dict[str, Any] = {
        "synchronized_route_start_required": False,
        "maximum_route_start_skew_s": 0.20,
        "minimum_simultaneous_flight_s": 0.0,
    }
    if behavior_family == "parallel_routes":
        coordination.update(
            synchronized_route_start_required=True,
            minimum_simultaneous_flight_s=8.0,
        )
        oracles.extend(
            (
                _oracle(
                    "synchronized-start",
                    "SYNCHRONIZED_ROUTE_START",
                    "PLANNER_PREDICTION",
                    roles,
                    0.20,
                    "s",
                ),
                _oracle(
                    "overlapping-flight",
                    "MINIMUM_FLIGHT_OVERLAP",
                    "PLANNER_PREDICTION",
                    roles,
                    8.0,
                    "s",
                ),
            )
        )
    if behavior_family in {"leader_follower", "formation_spacing"}:
        offsets = (
            {"Alpha": {"x": 0.0, "y": 0.0, "z": 0.0}, "Beta": {"x": 0.0, "y": 0.85, "z": 0.0}}
            if behavior_family == "leader_follower"
            else {
                "Alpha": {"x": 0.0, "y": -0.50, "z": 0.0},
                "Beta": {"x": 0.0, "y": 0.50, "z": 0.0},
            }
        )
        coordination.update(
            synchronized_route_start_required=True,
            minimum_simultaneous_flight_s=6.0,
            maximum_formation_error_m=0.18,
            formation_offsets_m=offsets,
        )
        oracles.extend(
            (
                _oracle(
                    "formation-error", "FORMATION_ERROR", "PLANNER_PREDICTION", roles, 0.18, "m"
                ),
                _oracle(
                    "formation-overlap",
                    "MINIMUM_FLIGHT_OVERLAP",
                    "PLANNER_PREDICTION",
                    roles,
                    6.0,
                    "s",
                ),
            )
        )
    if behavior_family == "formation_shape_transform":
        offsets_by_role: dict[str, list[dict[str, float]]] = {role: [] for role in roles}
        for goal_index in range(len(drones[0]["goal_sequence"])):
            centers = [_center(drone["goal_sequence"][goal_index]) for drone in drones]
            centroid = tuple(sum(point[axis] for point in centers) / count for axis in range(3))
            for role, point in zip(roles, centers, strict=True):
                offsets_by_role[role].append(
                    {
                        "x": point[0] - centroid[0],
                        "y": point[1] - centroid[1],
                        "z": point[2] - centroid[2],
                    }
                )
        coordination.update(
            synchronized_route_start_required=True,
            minimum_simultaneous_flight_s=8.0,
            maximum_formation_error_m=0.30,
            formation_offsets_by_node_m=offsets_by_role,
        )
        oracles.extend(
            (
                _oracle(
                    "transform-error", "FORMATION_ERROR", "PLANNER_PREDICTION", roles, 0.30, "m"
                ),
                _oracle(
                    "transform-overlap",
                    "MINIMUM_FLIGHT_OVERLAP",
                    "PLANNER_PREDICTION",
                    roles,
                    8.0,
                    "s",
                ),
            )
        )

    events = _scenario_events(count, family)
    if events:
        oracles.append(
            _oracle("causal-event-outcome", "EVENT_HANDLED", "EVENT_TRACE", roles, 1.0, "boolean")
        )
    if family != "online_obstacle_replan" and any(
        event["expected_disposition"] == "ACCEPTED_UPDATE" for event in events
    ):
        oracles.append(
            _oracle(
                "accepted-event-goal-capture",
                "ACCEPTED_EVENT_GOALS_CAPTURED",
                "EXECUTION_TELEMETRY",
                roles,
                1.0,
                "ratio",
            )
        )

    environment: dict[str, list[dict[str, Any]]] = {
        "keep_out_regions": [],
        "required_corridors": [],
    }
    if family == "bottleneck":
        environment["keep_out_regions"] = [
            _region("bottleneck-north", (-0.45, 0.18, 0.0), (0.45, 1.70, 1.0)),
            _region("bottleneck-south", (-0.45, -1.70, 0.0), (0.45, -0.18, 1.0)),
        ]

    baseline = None
    delta = None
    if family in {"unequal_priority", "no_hover_crossing", "constrained_border_height"}:
        baseline = "2d.perpendicular_crossing.nominal_equal_priority"
        delta = {
            "unequal_priority": "Alpha has priority 200 while Beta has priority 100.",
            "no_hover_crossing": (
                "Airborne holding is forbidden; resolution must remain continuous or ground-first."
            ),
            "constrained_border_height": (
                "The flight ceiling rejects vertical separation candidates."
            ),
        }[family]
    if variation == "wide" and family == "altitude_transition":
        baseline = "1d.altitude_transition.canonical_nominal"
        delta = "The stress route uses a wider 0.20 m to 0.82 m altitude envelope."
    variation_baselines = {
        "axis_nudge_return": "1d.axis_nudge_return.forward_x_10cm",
        "short_offset_landing": "1d.short_offset_landing.forward_20cm",
        "checkpoint_path": "1d.checkpoint_path.l_shape",
        "spatial_step_path": "1d.spatial_step_path.stair_step",
        "polygon_loop": "1d.polygon_loop.triangle",
    }
    if family in variation_baselines:
        baseline_case_id = variation_baselines[family]
        if not baseline_case_id.endswith(f".{variation}"):
            baseline = baseline_case_id
            delta = {
                "axis_nudge_return": (
                    f"The 0.10 m excursion uses the {variation.replace('_', ' ')} world axis."
                ),
                "short_offset_landing": (
                    f"The landing displacement uses the {variation.replace('_', ' ')} target."
                ),
                "checkpoint_path": (
                    f"The stopped route uses the {variation.replace('_', ' ')} checkpoint topology."
                ),
                "spatial_step_path": (
                    f"The continuous 3D route uses the {variation.replace('_', ' ')} topology."
                ),
                "polygon_loop": (
                    f"The closed continuous route uses the {variation.replace('_', ' ')} polygon."
                ),
            }[family]

    return {
        "contract_version": 1,
        "curriculum_level": _curriculum_level(count, family),
        "learning_objective": _learning_objective(count, family, variation),
        "difficulty_rationale": _difficulty_rationale(count, family),
        "route_intent_by_role": route_intent,
        "goal_seeking": (
            {
                "mode": "START_GOAL_CURRENT_WORLD",
                "start_source": "FRESH_COMMITTED_STATE",
                "goal_source": "CASE_GOAL_AND_LANDING",
                "world_source": "CURRENT_PERCEIVED_WORLD_GENERATION",
                "authored_reference_route": None,
                "authored_centerline": None,
                "authored_rejoin_waypoint": None,
            }
            if family == "online_obstacle_replan"
            else None
        ),
        "environment_constraints": environment,
        "coordination_constraints": coordination,
        "scenario_events": events,
        "behavior_oracles": oracles,
        "semantic_baseline_case_id": baseline,
        "intended_delta": delta,
    }


def _behavior_family(family: str) -> str:
    return {
        "leader_loss": "leader_follower",
        "coordination_failure": "formation_spacing",
        "leader_follower_recovery": "formation_shape_transform",
    }.get(family, family)


def _center(region: dict[str, Any]) -> tuple[float, float, float]:
    low, high = region["minimum_m"], region["maximum_m"]
    return (
        (low["x"] + high["x"]) / 2.0,
        (low["y"] + high["y"]) / 2.0,
        (low["z"] + high["z"]) / 2.0,
    )


def _oracle(
    oracle_id: str,
    kind: str,
    source: str,
    roles: tuple[str, ...],
    threshold: float | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    return {
        "oracle_id": oracle_id,
        "kind": kind,
        "evidence_source": source,
        "role_ids": roles,
        "threshold": threshold,
        "unit": unit,
        "required": True,
    }


def _scenario_events(count: int, family: str) -> list[dict[str, Any]]:
    if family == "online_obstacle_replan":
        first = _region("sensed-rock-1", (-0.15, -0.20, 0.10), (0.20, 0.20, 0.70))
        moved = _region("sensed-rock-1", (0.20, -0.25, 0.10), (0.50, 0.15, 0.70))
        # Keep the nominal third event outside the complete response horizon for
        # every admitted ±0.08 m seeded X perturbation. Near/late obstacle behavior
        # has its own fail-closed witness; the four-event nominal must remain a
        # moving-replan qualification rather than randomly becoming that witness.
        second = _region("sensed-wall-2", (0.85, 0.45, 0.00), (1.00, 0.90, 0.80))
        return [
            {
                "event_id": "online-obstacle-appear-1",
                "kind": "OBSTACLE_ADDED",
                "trigger_time_s": 2.0,
                "replacement_goal": first,
                "duration_s": 3.0,
                "sequence": 1,
                "generation": 1,
                "expected_disposition": "ACCEPTED_UPDATE",
            },
            {
                "event_id": "online-obstacle-move-1",
                "kind": "OBSTACLE_MOVED",
                "trigger_time_s": 5.5,
                "replacement_goal": moved,
                "duration_s": 3.0,
                "sequence": 2,
                "generation": 2,
                "expected_disposition": "ACCEPTED_UPDATE",
            },
            {
                "event_id": "online-obstacle-appear-2",
                "kind": "OBSTACLE_ADDED",
                "trigger_time_s": 6.5,
                "replacement_goal": second,
                "duration_s": 3.0,
                "sequence": 3,
                "generation": 3,
                "expected_disposition": "ACCEPTED_UPDATE",
            },
            {
                "event_id": "online-obstacle-remove-1",
                "kind": "OBSTACLE_REMOVED",
                "trigger_time_s": 12.5,
                "duration_s": 3.0,
                "sequence": 4,
                "generation": 4,
                "update_identity": "sensed-rock-1",
                "expected_disposition": "ACCEPTED_UPDATE",
            },
        ]
    goal_families = {
        "moving_target": 3,
        "mid_route_goal_replacement": 1,
        "duplicate_stale_goal_update": 3,
        "planning_budget_expiry": 1,
        "blocked_replan": 1,
        "operator_approval_goal_replacement": 2,
        "abort_and_land_goal_fallback": 1,
        "crossing_goal_change": 1,
        "simultaneous_conflicting_updates": 2,
        "partial_replacement_failure": 2,
        "cascading_replan": 3,
    }
    if family in goal_families:
        result = []
        for index in range(goal_families[family]):
            sequence = index + 1
            generation = index + 1
            update_identity = f"{family}-update-identity-{index + 1}"
            expected = "ACCEPTED_UPDATE"
            if family == "duplicate_stale_goal_update":
                sequence = (2, 2, 1)[index]
                generation = (2, 2, 1)[index]
                update_identity = (
                    f"{family}-accepted-update" if index < 2 else f"{family}-stale-update"
                )
                expected = ("ACCEPTED_UPDATE", "REJECTED_DUPLICATE", "REJECTED_STALE")[index]
            elif family == "planning_budget_expiry":
                expected = "BLOCKED_BUDGET"
            elif family in {"blocked_replan", "abort_and_land_goal_fallback"}:
                expected = "BLOCKED_INFEASIBLE"
            elif family == "operator_approval_goal_replacement" and index == 0:
                expected = "REJECTED_AUTHORITY"
            elif family in {"simultaneous_conflicting_updates", "partial_replacement_failure"}:
                expected = "ZERO_PARTIAL_COMMIT"
            result.append(
                {
                    "event_id": f"{family}-update-{index + 1}",
                    "kind": "GOAL_UPDATE",
                    "trigger_time_s": 3.0 + index * 0.75,
                    "role_id": ("Alpha", "Beta", "Gamma")[min(index, count - 1)],
                    "replacement_goal": _point_region(
                        f"{family}-replacement-{index + 1}",
                        (0.55 + 0.20 * index, -0.75 + 0.35 * index, 0.35 + 0.10 * (index % 2)),
                        0.05,
                    ),
                    "duration_s": 3.0 if family == "planning_budget_expiry" else None,
                    "sequence": sequence,
                    "generation": generation,
                    "update_identity": update_identity,
                    "authenticated": True,
                    "acknowledgement_required": family
                    in {"operator_approval_goal_replacement", "partial_replacement_failure"},
                    "acknowledgement_received": not (
                        (family == "operator_approval_goal_replacement" and index == 0)
                        or (family == "partial_replacement_failure" and index == 1)
                    ),
                    "expected_disposition": expected,
                }
            )
        if family == "abort_and_land_goal_fallback":
            result.append(
                {
                    "event_id": f"{family}-abort",
                    "kind": "ABORT_REQUEST",
                    "trigger_time_s": 4.5,
                    "role_id": "Alpha",
                    "expected_disposition": "COORDINATED_ABORT",
                }
            )
        return result
    event_kind = {
        "failure_recovery": "TELEMETRY_LOSS",
        "leader_loss": "VEHICLE_LOSS",
        "duplicate_assignment_rejection": "ASSIGNMENT_CONFLICT",
        "coordination_failure": "ACKNOWLEDGEMENT_LOSS",
        "persistent_coverage_reserve_handover": "BATTERY_DROP",
        "leader_follower_recovery": "VEHICLE_LOSS",
        "acknowledgement_loss": "ACKNOWLEDGEMENT_LOSS",
        "fleet_abort_fallback": "ABORT_REQUEST",
    }.get(family)
    if event_kind is None:
        return []
    return [
        {
            "event_id": f"{family}-event-1",
            "kind": event_kind,
            "trigger_time_s": 4.0,
            "role_id": "Alpha",
            "battery_percent": 34.0 if event_kind == "BATTERY_DROP" else None,
            "duration_s": 1.0 if event_kind == "TELEMETRY_LOSS" else None,
            "acknowledgement_required": event_kind == "ACKNOWLEDGEMENT_LOSS",
            "acknowledgement_received": event_kind != "ACKNOWLEDGEMENT_LOSS",
            "expected_disposition": {
                "TELEMETRY_LOSS": "SAFE_ROLE_RECOVERY",
                "VEHICLE_LOSS": "SAFE_ROLE_RECOVERY",
                "ASSIGNMENT_CONFLICT": "REJECTED_ASSIGNMENT_CONFLICT",
                "ACKNOWLEDGEMENT_LOSS": "ZERO_PARTIAL_COMMIT",
                "BATTERY_DROP": "RESERVE_HANDOVER",
                "ABORT_REQUEST": "COORDINATED_ABORT",
            }[event_kind],
        }
    ]


def _learning_objective(count: int, family: str, variation: str) -> str:
    return (
        f"Learn and verify the causal {family.replace('_', ' ')} behavior for {count} "
        f"drone(s) in the {variation.replace('_', ' ')} authored scenario."
    )


def _curriculum_level(count: int, family: str) -> int:
    if family in {item[1] for item in DYNAMIC_CASES}:
        return 5
    levels = {
        "takeoff_hover_land": 1,
        "hover_endurance": 1,
        "parallel_routes": 1,
        "single_pair_conflict": 1,
        "point_to_point_relocation": 2,
        "move_return": 2,
        "axis_nudge_return": 2,
        "short_offset_landing": 2,
        "head_on_conflict": 2,
        "perpendicular_crossing": 2,
        "simultaneous_center_conflict": 2,
        "altitude_transition": 3,
        "checkpoint_path": 3,
        "spatial_step_path": 3,
        "continuous_waypoint_sequence": 3,
        "merge": 3,
        "overtake": 3,
        "bottleneck": 3,
    }
    return levels.get(family, 4)


def _difficulty_rationale(count: int, family: str) -> str:
    dimension = "route geometry"
    if family in {item[1] for item in DYNAMIC_CASES}:
        dimension = "event authority, safe fallback, and retained causal evidence"
    elif count > 1:
        dimension = "time-aligned separation and joint coordination"
    return f"Difficulty reflects {count} active role(s) plus {dimension}."


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
                # The typed reducer and static route are useful qualification inputs,
                # but they are not a live source-time event injection/cutover.  Keep
                # the definition visible without granting execution authority.
                "implementation_status": "PLANNED_NOT_EXECUTABLE",
                "execution_eligibility": "STATIC_VALIDATE_ONLY",
                "prerequisites": (prerequisite_id,),
                "replanning_authority": authority,
                "expected_decisions": _dynamic_expected_decisions(family),
            }
        )
        if family == "online_obstacle_replan":
            value.update(
                {
                    "parent_case_sha256": (
                        "b265e16a9b54cfc0271f38c03486244da6e1fe6558c1d6580aa47b79acdac401"
                    ),
                    "implementation_milestone": "WP-66",
                    "implementation_status": "EXECUTABLE",
                    "execution_eligibility": "BOTH",
                }
            )
        cases.append(value)
    return cases


def _legacy_three_drone_multi_conflict() -> dict[str, Any]:
    """Frozen qualified WP-33 baseline retained for historical evidence identity."""

    variations = (
        "wide_priority_200_150_100",
        "compact_equal_priority",
        "nominal_equal_priority",
        "wide_unequal_priority",
        "compact_no_hover",
        "constrained_height",
        "vertical_allowed",
        "vertical_forbidden",
        "latency_and_noise",
    )
    value = _case(3, "simultaneous_center_conflict", variations[0], variations)
    value["case_id"] = "three_drone_multi_conflict"
    value["drones"] = _legacy_default_drones()
    value["prerequisites"] = ("1d.takeoff_hover_land.canonical_nominal",)
    value.pop("semantics")
    return value


def _legacy_default_drones() -> list[dict[str, Any]]:
    starts = ((-1.50, 0.0, 0.04), (0.0, -1.50, 0.04), (-1.06, -1.06, 0.04))
    goals = ((1.50, 0.0, 0.30), (0.0, 1.50, 0.30), (1.06, 1.06, 0.30))
    output = []
    capabilities = [
        "arming",
        "relative_positioning",
        "high_level_commands",
        "time_parameterized_trajectory",
    ]
    for index, (start, goal) in enumerate(zip(starts, goals, strict=True)):
        role = ("Alpha", "Beta", "Gamma")[index]
        output.append(
            {
                "role_id": role,
                "start_region": _point_region(f"{role}-start", start, 0.04),
                "goal_sequence": [_point_region(f"{role}-goal-1", goal, 0.05)],
                "landing_region": _point_region(f"{role}-landing", (goal[0], goal[1], 0.04), 0.04),
                "initial_battery_percent": 100.0,
                "minimum_reserve_battery_percent": 20.0,
                "health": "HEALTHY",
                "priority": 200 - index * 50,
                "roles": ("active-route",),
                "required_capabilities": capabilities,
                "available_capabilities": capabilities,
            }
        )
    return output


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
    output = CampaignCase.model_validate(mirrored).model_dump(mode="json")
    if output.get("motion_quality_contract") is None:
        output.pop("motion_quality_contract", None)
    semantics = output.get("semantics")
    if isinstance(semantics, dict) and semantics.get("goal_seeking") is None:
        semantics.pop("goal_seeking", None)
    return output


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
        "hover_endurance": (
            "Checks a bounded 12-second stationary hold before controlled descent and landing "
            "at home."
        ),
        "axis_nudge_return": (
            "Checks a 0.10 m world-axis excursion, declared reversal, return capture, and "
            "landing at home."
        ),
        "short_offset_landing": (
            "Checks low-distance relocation, capture above a distinct landing region, and "
            "terminal contact away from home."
        ),
        "checkpoint_path": (
            "Checks ordered L, U, or square checkpoint capture with a declared one-second stop "
            "at every vertex."
        ),
        "spatial_step_path": (
            "Checks a continuous stair-step or vertical-rectangle route across multiple "
            "altitude levels."
        ),
        "polygon_loop": (
            "Checks continuous triangle or square traversal with explicit loop closure and "
            "no undeclared stops."
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
        "formation_shape_transform",
        "role_allocation",
        "duplicate_assignment_rejection",
        "persistent_coverage_reserve_handover",
    }
    if family == "online_obstacle_replan":
        return "DYNAMIC_REPLANNING"
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
    prerequisites = {
        (1, "hover_endurance"): "1d.takeoff_hover_land.canonical_nominal",
        (1, "axis_nudge_return"): "1d.hover_endurance.hold_12s",
        (1, "short_offset_landing"): "1d.axis_nudge_return.forward_x_10cm",
        (1, "checkpoint_path"): "1d.axis_nudge_return.forward_x_10cm",
        (1, "spatial_step_path"): "1d.altitude_transition.canonical_nominal",
        (1, "polygon_loop"): "1d.checkpoint_path.square",
        (1, "point_to_point_relocation"): "1d.takeoff_hover_land.canonical_nominal",
        (1, "move_return"): "1d.takeoff_hover_land.canonical_nominal",
        (1, "altitude_transition"): "1d.point_to_point_relocation.canonical_nominal",
        (1, "continuous_waypoint_sequence"): "1d.point_to_point_relocation.canonical_nominal",
        (1, "curved_route"): "1d.continuous_waypoint_sequence.canonical_nominal",
        (1, "planar_shape_loop"): "1d.curved_route.canonical_nominal",
        (1, "static_multi_goal_sequence"): "1d.continuous_waypoint_sequence.canonical_nominal",
        (1, "boundary_constrained_route"): "1d.curved_route.canonical_nominal",
        (2, "parallel_routes"): "1d.move_return.canonical_nominal",
        (2, "head_on_conflict"): "2d.parallel_routes.canonical_nominal",
        (2, "perpendicular_crossing"): "2d.parallel_routes.canonical_nominal",
        (2, "merge"): "2d.perpendicular_crossing.nominal_equal_priority",
        (2, "overtake"): "2d.head_on_conflict.canonical_nominal",
        (2, "bottleneck"): "2d.merge.canonical_nominal",
        (2, "unequal_priority"): "2d.perpendicular_crossing.nominal_equal_priority",
        (2, "constrained_border_height"): "2d.perpendicular_crossing.nominal_equal_priority",
        (2, "no_hover_crossing"): "2d.perpendicular_crossing.nominal_equal_priority",
        (2, "leader_follower"): "1d.curved_route.canonical_nominal",
        (2, "formation_spacing"): "2d.leader_follower.canonical_nominal",
        (2, "role_allocation"): "1d.point_to_point_relocation.canonical_nominal",
        (3, "single_pair_conflict"): "2d.perpendicular_crossing.nominal_equal_priority",
        (3, "simultaneous_center_conflict"): "3d.single_pair_conflict.canonical_nominal",
        (3, "merge"): "3d.simultaneous_center_conflict.joint_schedule_v2",
        (3, "bottleneck"): "3d.merge.canonical_nominal",
        (3, "unequal_priorities"): "3d.simultaneous_center_conflict.joint_schedule_v2",
        (3, "constrained_volume"): "3d.simultaneous_center_conflict.joint_schedule_v2",
        (3, "alternative_layers_detours"): "3d.constrained_volume.canonical_nominal",
        (3, "formation_shape_transform"): "2d.formation_spacing.canonical_nominal",
        (3, "role_allocation"): "2d.role_allocation.canonical_nominal",
    }
    prerequisite = prerequisites.get((count, family))
    return () if prerequisite is None else (prerequisite,)


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
