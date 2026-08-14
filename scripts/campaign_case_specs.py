"""Exact authored geometry and route intent for the executable campaign curriculum."""

from __future__ import annotations

from typing import TypeAlias

Point: TypeAlias = tuple[float, float, float]
RoleRoute: TypeAlias = tuple[Point, tuple[Point, ...], Point, tuple[str, ...]]


def geometry(count: int, family: str, variation: str) -> tuple[RoleRoute, ...]:
    key = (count, family)
    if key in _BUILDERS:
        return _BUILDERS[key](variation)
    if family in _DYNAMIC_BASE:
        return geometry(count, _DYNAMIC_BASE[family], _base_variation(_DYNAMIC_BASE[family]))
    raise KeyError(f"no authored campaign geometry for {count}d {family} {variation}")


def _base_variation(family: str) -> str:
    if family == "perpendicular_crossing":
        return "nominal_equal_priority"
    if family == "simultaneous_center_conflict":
        return "wide_priority_200_150_100"
    return "canonical_nominal"


def _one(variation: str) -> tuple[RoleRoute, ...]:
    del variation
    raise AssertionError("family-specific one-drone geometry is required")


def _takeoff(_: str) -> tuple[RoleRoute, ...]:
    return (((0.0, 0.0, 0.04), ((0.0, 0.0, 0.35),), (0.0, 0.0, 0.04), ("CAPTURE_AND_HOLD",)),)


def _relocation(_: str) -> tuple[RoleRoute, ...]:
    return (((-1.20, -0.80, 0.04), ((1.00, 0.70, 0.35),), (1.00, 0.70, 0.04), ("CAPTURE",)),)


def _move_return(_: str) -> tuple[RoleRoute, ...]:
    return (
        (
            (-1.20, -0.80, 0.04),
            ((1.10, -0.80, 0.35), (-1.20, -0.80, 0.35)),
            (-1.20, -0.80, 0.04),
            ("REVERSAL", "CAPTURE"),
        ),
    )


def _altitude(variation: str) -> tuple[RoleRoute, ...]:
    heights = (0.25, 0.65, 0.35, 0.55)
    if variation == "wide":
        heights = (0.20, 0.82, 0.28, 0.72)
    goals = tuple((x, -0.60, z) for x, z in zip((-0.80, -0.20, 0.45, 1.05), heights, strict=True))
    return (((-1.20, -0.60, 0.04), goals, (1.05, -0.60, 0.04), ("FLY_THROUGH",) * 4),)


def _slalom(_: str) -> tuple[RoleRoute, ...]:
    goals = (
        (-0.90, 0.45, 0.35),
        (-0.30, -0.45, 0.35),
        (0.30, 0.45, 0.35),
        (0.90, -0.45, 0.35),
        (1.35, 0.0, 0.35),
    )
    return (((-1.35, 0.0, 0.04), goals, (1.35, 0.0, 0.04), ("FLY_THROUGH",) * 5),)


def _curve(_: str) -> tuple[RoleRoute, ...]:
    goals = (
        (-1.25, -0.75, 0.35),
        (-0.75, -0.25, 0.35),
        (-0.20, 0.45, 0.45),
        (0.35, -0.35, 0.55),
        (0.90, 0.30, 0.40),
        (1.25, 0.75, 0.35),
    )
    return (((-1.25, -0.75, 0.04), goals, (1.25, 0.75, 0.04), ("FLY_THROUGH",) * 6),)


def _shape(variation: str) -> tuple[RoleRoute, ...]:
    if variation == "circle":
        loop = (
            (-0.65, 0.0, 0.40),
            (-0.46, 0.46, 0.40),
            (0.0, 0.65, 0.40),
            (0.46, 0.46, 0.40),
            (0.65, 0.0, 0.40),
            (0.46, -0.46, 0.40),
            (0.0, -0.65, 0.40),
            (-0.46, -0.46, 0.40),
            (-0.65, 0.0, 0.40),
        )
    elif variation == "rounded_square":
        loop = (
            (-0.60, -0.35, 0.40),
            (-0.35, -0.60, 0.40),
            (0.35, -0.60, 0.40),
            (0.60, -0.35, 0.40),
            (0.60, 0.35, 0.40),
            (0.35, 0.60, 0.40),
            (-0.35, 0.60, 0.40),
            (-0.60, 0.35, 0.40),
            (-0.60, -0.35, 0.40),
        )
    elif variation == "figure_eight":
        loop = (
            (0.0, 0.0, 0.45),
            (-0.45, 0.45, 0.45),
            (-0.90, 0.0, 0.45),
            (-0.45, -0.45, 0.45),
            (0.0, 0.0, 0.45),
            (0.45, 0.45, 0.45),
            (0.90, 0.0, 0.45),
            (0.45, -0.45, 0.45),
            (0.0, 0.0, 0.45),
        )
    else:
        raise KeyError(f"unknown shape variation: {variation}")
    goals = (*loop, (1.20, 0.70, 0.35))
    start = (loop[0][0], loop[0][1], 0.04)
    return ((start, goals, (1.20, 0.70, 0.04), ("FLY_THROUGH",) * len(goals)),)


def _multi_goal(_: str) -> tuple[RoleRoute, ...]:
    goals = ((-0.60, 0.50, 0.30), (0.0, -0.50, 0.45), (0.60, 0.50, 0.30))
    return (((-1.10, -0.70, 0.04), goals, (0.95, -0.70, 0.04), ("CAPTURE_AND_HOLD",) * 3),)


def _boundary(_: str) -> tuple[RoleRoute, ...]:
    goals = ((-1.55, -0.80, 0.35), (-1.20, 1.55, 0.45), (1.55, 1.20, 0.35), (1.25, -0.95, 0.35))
    return (((-1.30, -1.20, 0.04), goals, (1.25, -0.95, 0.04), ("FLY_THROUGH",) * 4),)


def _pair(
    routes: tuple[tuple[Point, tuple[Point, ...], Point], ...], modes: str = "CAPTURE"
) -> tuple[RoleRoute, ...]:
    return tuple((start, goals, landing, (modes,) * len(goals)) for start, goals, landing in routes)


def _parallel(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            ((-1.40, -0.65, 0.04), ((1.40, -0.65, 0.35),), (1.40, -0.65, 0.04)),
            ((-1.40, 0.65, 0.04), ((1.40, 0.65, 0.35),), (1.40, 0.65, 0.04)),
        ),
        "FLY_THROUGH",
    )


def _head_on(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            (
                (-1.40, -0.90, 0.04),
                ((-1.20, 0.0, 0.35), (1.20, 0.0, 0.35)),
                (1.40, -0.90, 0.04),
            ),
            (
                (1.40, 0.90, 0.04),
                ((1.20, 0.0, 0.35), (-1.20, 0.0, 0.35)),
                (-1.40, 0.90, 0.04),
            ),
        ),
        "FLY_THROUGH",
    )


def _cross(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            ((-1.40, 0.0, 0.04), ((1.40, 0.0, 0.35),), (1.40, 0.0, 0.04)),
            ((0.0, -1.40, 0.04), ((0.0, 1.40, 0.35),), (0.0, 1.40, 0.04)),
        ),
        "FLY_THROUGH",
    )


def _merge2(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            (
                (-1.40, -0.80, 0.04),
                ((-0.50, -0.25, 0.35), (0.20, 0.0, 0.35), (1.35, -0.55, 0.35)),
                (1.35, -0.55, 0.04),
            ),
            (
                (-1.40, 0.80, 0.04),
                ((-0.50, 0.25, 0.35), (0.20, 0.0, 0.35), (1.35, 0.55, 0.35)),
                (1.35, 0.55, 0.04),
            ),
        ),
        "FLY_THROUGH",
    )


def _overtake(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            (
                (-1.35, -0.10, 0.04),
                ((-0.30, -0.10, 0.35), (1.35, -0.55, 0.35)),
                (1.35, -0.55, 0.04),
            ),
            ((-0.35, 0.10, 0.04), ((0.35, 0.10, 0.35), (1.35, 0.55, 0.35)), (1.35, 0.55, 0.04)),
        ),
        "FLY_THROUGH",
    )


def _bottleneck2(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            (
                (-1.40, -0.70, 0.04),
                ((-0.40, 0.0, 0.35), (0.40, 0.0, 0.35), (1.35, -0.70, 0.35)),
                (1.35, -0.70, 0.04),
            ),
            (
                (1.40, 0.70, 0.04),
                ((0.40, 0.0, 0.35), (-0.40, 0.0, 0.35), (-1.35, 0.70, 0.35)),
                (-1.35, 0.70, 0.04),
            ),
        ),
        "FLY_THROUGH",
    )


def _leader_follower(_: str) -> tuple[RoleRoute, ...]:
    leader = _curve("")[0]
    offset = (0.0, 0.85, 0.0)
    follower = (
        (leader[0][0] + offset[0], leader[0][1] + offset[1], leader[0][2]),
        tuple((x + offset[0], y + offset[1], z) for x, y, z in leader[1]),
        (leader[2][0] + offset[0], leader[2][1] + offset[1], leader[2][2]),
        leader[3],
    )
    return leader, follower


def _formation2(_: str) -> tuple[RoleRoute, ...]:
    alpha = (
        (-1.20, -0.50, 0.04),
        ((-0.80, -0.50, 0.30), (-0.10, 0.10, 0.60), (0.70, -0.10, 0.40), (1.20, 0.30, 0.40)),
        (1.20, 0.30, 0.04),
        ("FLY_THROUGH",) * 4,
    )
    beta = tuple((x, y + 1.0, z) for x, y, z in alpha[1])
    return alpha, ((-1.20, 0.50, 0.04), beta, (1.20, 1.30, 0.04), ("FLY_THROUGH",) * 4)


def _allocation2(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            ((-1.20, -0.80, 0.04), ((0.90, -0.65, 0.35),), (0.90, -0.65, 0.04)),
            ((-1.20, 0.80, 0.04), ((0.95, 0.75, 0.55),), (0.95, 0.75, 0.04)),
        )
    )


def _single_pair3(_: str) -> tuple[RoleRoute, ...]:
    return (
        *_cross(""),
        (
            (-1.45, 1.35, 0.04),
            ((-0.95, 1.35, 0.35), (-0.95, 0.95, 0.35)),
            (-0.95, 0.95, 0.04),
            ("FLY_THROUGH", "CAPTURE"),
        ),
    )


def _center3(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            ((-1.40, 0.0, 0.04), ((1.40, 0.0, 0.35),), (1.40, 0.0, 0.04)),
            ((0.0, -1.40, 0.04), ((0.0, 1.40, 0.35),), (0.0, 1.40, 0.04)),
            ((-1.20, -1.20, 0.04), ((1.20, 1.20, 0.35),), (1.20, 1.20, 0.04)),
        ),
        "FLY_THROUGH",
    )


def _merge3(_: str) -> tuple[RoleRoute, ...]:
    starts_y = (-1.20, 0.0, 1.20)
    return _pair(
        tuple(
            (
                (-1.45, y, 0.04),
                ((-0.40, y * 0.29, 0.35), (0.0, 0.0, 0.35), (1.40, y, 0.35)),
                (1.40, y, 0.04),
            )
            for y in starts_y
        ),
        "FLY_THROUGH",
    )


def _bottleneck3(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            (
                (-1.45, -1.20, 0.04),
                ((-0.40, 0.0, 0.35), (0.40, 0.0, 0.35), (1.35, -1.20, 0.35)),
                (1.35, -1.20, 0.04),
            ),
            (
                (-1.45, 1.20, 0.04),
                ((-0.40, 0.0, 0.35), (0.40, 0.0, 0.35), (1.35, 1.20, 0.35)),
                (1.35, 1.20, 0.04),
            ),
            (
                (1.70, 0.0, 0.04),
                ((0.40, 0.0, 0.35), (-0.40, 0.0, 0.35), (-1.35, 0.0, 0.35)),
                (-1.70, 0.0, 0.04),
            ),
        ),
        "FLY_THROUGH",
    )


def _layers3(_variation: str) -> tuple[RoleRoute, ...]:
    base = _center3("")
    heights = (0.25, 0.55, 0.85)
    output: list[RoleRoute] = []
    for route, height in zip(base, heights, strict=True):
        start, goals, landing, _modes = route
        end = goals[-1]
        mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0, height)
        output.append(
            (start, ((start[0], start[1], 0.35), mid, end), landing, ("FLY_THROUGH",) * 3)
        )
    return tuple(output)


def _formation3(_: str) -> tuple[RoleRoute, ...]:
    centroids = (
        (-1.00, -0.60, 0.30),
        (-0.45, 0.0, 0.50),
        (0.0, 0.55, 0.70),
        (0.55, 0.0, 0.55),
        (1.00, 0.60, 0.40),
    )
    # Stored per-knot offsets rotate a triangular formation by 90 degrees.
    initial = ((0.0, -0.52), (-0.45, 0.26), (0.45, 0.26))
    output = []
    for ox, oy in initial:
        goals = []
        for index, (cx, cy, cz) in enumerate(centroids):
            angle = (index / (len(centroids) - 1)) * 1.5707963267948966
            rx = ox * __import__("math").cos(angle) - oy * __import__("math").sin(angle)
            ry = ox * __import__("math").sin(angle) + oy * __import__("math").cos(angle)
            goals.append((cx + rx, cy + ry, cz))
        start = (goals[0][0], goals[0][1], 0.04)
        landing = (goals[-1][0], goals[-1][1], 0.04)
        output.append((start, tuple(goals), landing, ("FLY_THROUGH",) * len(goals)))
    return tuple(output)


def _allocation3(_: str) -> tuple[RoleRoute, ...]:
    return _pair(
        (
            ((-1.25, -0.85, 0.04), ((0.95, -0.70, 0.35),), (0.95, -0.70, 0.04)),
            ((-1.25, 0.0, 0.04), ((0.95, 0.15, 0.55),), (0.95, 0.15, 0.04)),
            ((-1.25, 0.85, 0.04), ((-1.25, 0.85, 0.30),), (-1.25, 0.85, 0.04)),
        )
    )


def _handover3(_: str) -> tuple[RoleRoute, ...]:
    alpha_loop = (
        (-0.95, -0.55, 0.35),
        (-0.35, -0.95, 0.35),
        (0.25, -0.55, 0.35),
        (-0.35, -0.15, 0.35),
        (-0.95, -0.55, 0.35),
    )
    beta_loop = (
        (0.15, 0.55, 0.50),
        (0.75, 0.15, 0.50),
        (1.35, 0.55, 0.50),
        (0.75, 0.95, 0.50),
        (0.15, 0.55, 0.50),
    )
    gamma_takeover = (
        (-1.25, 0.95, 0.30),
        (-0.95, -0.55, 0.35),
        (-0.35, -0.95, 0.35),
        (0.25, -0.55, 0.35),
        (-0.35, -0.15, 0.35),
    )
    return (
        ((-0.95, -0.55, 0.04), alpha_loop, (-1.25, -1.20, 0.04), ("FLY_THROUGH",) * 5),
        ((0.15, 0.55, 0.04), beta_loop, (1.35, 1.20, 0.04), ("FLY_THROUGH",) * 5),
        (
            (-1.25, 0.95, 0.04),
            gamma_takeover,
            (0.25, -0.55, 0.04),
            ("FLY_THROUGH", "FLY_THROUGH", "FLY_THROUGH", "FLY_THROUGH", "REVERSAL"),
        ),
    )


def _moving_target(_: str) -> tuple[RoleRoute, ...]:
    goals = ((0.55, -0.75, 0.35), (0.75, -0.40, 0.45), (0.95, -0.05, 0.35))
    return (
        (
            (-1.20, -0.80, 0.04),
            goals,
            (0.95, -0.05, 0.04),
            ("FLY_THROUGH", "FLY_THROUGH", "CAPTURE"),
        ),
    )


def _mid_route_update(_: str) -> tuple[RoleRoute, ...]:
    goals = ((-0.90, 0.45, 0.35), (0.55, -0.75, 0.35))
    return (((-1.35, 0.0, 0.04), goals, (0.55, -0.75, 0.04), ("FLY_THROUGH", "CAPTURE")),)


def _duplicate_update(_: str) -> tuple[RoleRoute, ...]:
    return (((-1.20, -0.80, 0.04), ((0.55, -0.75, 0.35),), (0.55, -0.75, 0.04), ("CAPTURE",)),)


def _operator_update(_: str) -> tuple[RoleRoute, ...]:
    return (((-1.20, -0.80, 0.04), ((0.75, -0.40, 0.45),), (0.75, -0.40, 0.04), ("CAPTURE",)),)


def _online_obstacle_replan(_: str) -> tuple[RoleRoute, ...]:
    return (
        (
            (-1.35, 0.0, 0.04),
            ((1.35, 0.0, 0.40),),
            (1.35, 0.0, 0.04),
            ("CAPTURE",),
        ),
    )


def _crossing_update(_: str) -> tuple[RoleRoute, ...]:
    return (
        (
            (-1.40, 0.0, 0.04),
            ((0.0, 0.0, 0.35), (0.55, -0.75, 0.35)),
            (0.55, -0.75, 0.04),
            ("FLY_THROUGH", "CAPTURE"),
        ),
        _cross("")[1],
    )


def _cascading_update(_variation: str) -> tuple[RoleRoute, ...]:
    base = _center3("")
    replacements = ((0.55, -0.75, 0.35), (0.75, -0.40, 0.45), (0.95, -0.05, 0.35))
    output: list[RoleRoute] = []
    for route, replacement in zip(base, replacements, strict=True):
        start, _goals, _landing, _modes = route
        output.append(
            (
                start,
                ((0.0, 0.0, 0.35), replacement),
                (replacement[0], replacement[1], 0.04),
                ("FLY_THROUGH", "CAPTURE"),
            )
        )
    return tuple(output)


_DYNAMIC_BASE = {
    "moving_target": "move_return",
    "mid_route_goal_replacement": "continuous_waypoint_sequence",
    "duplicate_stale_goal_update": "move_return",
    "planning_budget_expiry": "move_return",
    "blocked_replan": "move_return",
    "operator_approval_goal_replacement": "move_return",
    "online_obstacle_replan": "point_to_point_relocation",
    "failure_recovery": "continuous_waypoint_sequence",
    "abort_and_land_goal_fallback": "move_return",
    "leader_loss": "leader_follower",
    "duplicate_assignment_rejection": "role_allocation",
    "coordination_failure": "formation_spacing",
    "crossing_goal_change": "perpendicular_crossing",
    "simultaneous_conflicting_updates": "perpendicular_crossing",
    "partial_replacement_failure": "perpendicular_crossing",
    "role_allocation": "single_pair_conflict",
    "persistent_coverage_reserve_handover": "formation_shape_transform",
    "leader_follower_recovery": "formation_shape_transform",
    "cascading_replan": "simultaneous_center_conflict",
    "acknowledgement_loss": "simultaneous_center_conflict",
    "fleet_abort_fallback": "simultaneous_center_conflict",
}


_BUILDERS = {
    (1, "takeoff_hover_land"): _takeoff,
    (1, "point_to_point_relocation"): _relocation,
    (1, "move_return"): _move_return,
    (1, "altitude_transition"): _altitude,
    (1, "continuous_waypoint_sequence"): _slalom,
    (1, "curved_route"): _curve,
    (1, "planar_shape_loop"): _shape,
    (1, "static_multi_goal_sequence"): _multi_goal,
    (1, "boundary_constrained_route"): _boundary,
    (2, "parallel_routes"): _parallel,
    (2, "head_on_conflict"): _head_on,
    (2, "perpendicular_crossing"): _cross,
    (2, "merge"): _merge2,
    (2, "overtake"): _overtake,
    (2, "bottleneck"): _bottleneck2,
    (2, "unequal_priority"): _cross,
    (2, "constrained_border_height"): _cross,
    (2, "no_hover_crossing"): _cross,
    (2, "leader_follower"): _leader_follower,
    (2, "formation_spacing"): _formation2,
    (2, "role_allocation"): _allocation2,
    (3, "single_pair_conflict"): _single_pair3,
    (3, "simultaneous_center_conflict"): _center3,
    (3, "merge"): _merge3,
    (3, "bottleneck"): _bottleneck3,
    (3, "unequal_priorities"): _center3,
    (3, "constrained_volume"): _center3,
    (3, "alternative_layers_detours"): _layers3,
    (3, "formation_shape_transform"): _formation3,
    (3, "role_allocation"): _allocation3,
    (3, "duplicate_assignment_rejection"): _allocation3,
    (3, "persistent_coverage_reserve_handover"): _handover3,
    (3, "leader_follower_recovery"): _formation3,
    (1, "moving_target"): _moving_target,
    (1, "mid_route_goal_replacement"): _mid_route_update,
    (1, "duplicate_stale_goal_update"): _duplicate_update,
    (1, "operator_approval_goal_replacement"): _operator_update,
    (1, "online_obstacle_replan"): _online_obstacle_replan,
    (2, "crossing_goal_change"): _crossing_update,
    (3, "cascading_replan"): _cascading_update,
}
