#!/usr/bin/env python3
"""Reproduce the frozen WP-62 through WP-66 design audit."""

from __future__ import annotations

import argparse
import ast
import heapq
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

CURRENT_1D_CASES = {
    "1d.altitude_transition.canonical_nominal",
    "1d.altitude_transition.wide",
    "1d.boundary_constrained_route.canonical_nominal",
    "1d.continuous_waypoint_sequence.canonical_nominal",
    "1d.curved_route.canonical_nominal",
    "1d.move_return.canonical_nominal",
    "1d.planar_shape_loop.circle",
    "1d.planar_shape_loop.figure_eight",
    "1d.planar_shape_loop.rounded_square",
    "1d.point_to_point_relocation.canonical_nominal",
    "1d.static_multi_goal_sequence.canonical_nominal",
    "1d.takeoff_hover_land.canonical_nominal",
}

MISSION_GROUPS = [
    {
        "label": "Flight",
        "variants": ["1d.takeoff_hover_land.canonical_nominal"],
    },
    {
        "label": "Target",
        "variants": [
            "1d.point_to_point_relocation.canonical_nominal",
            "1d.move_return.canonical_nominal",
        ],
    },
    {
        "label": "Level path",
        "variants": [
            "1d.continuous_waypoint_sequence.canonical_nominal",
            "1d.curved_route.canonical_nominal",
            "1d.static_multi_goal_sequence.canonical_nominal",
            "1d.boundary_constrained_route.canonical_nominal",
        ],
    },
    {
        "label": "3D path",
        "variants": [
            "1d.altitude_transition.canonical_nominal",
            "1d.altitude_transition.wide",
        ],
        "planned_variant": {
            "label": "Wind shift",
            "case_id": "1d.altitude_transition.wind_shift",
            "source": "SimulationConfig.disturbance.force_impulse_n_s",
            "status": "PLANNED_NOT_EXECUTABLE",
        },
    },
    {
        "label": "Shape",
        "variants": [
            "1d.planar_shape_loop.circle",
            "1d.planar_shape_loop.rounded_square",
            "1d.planar_shape_loop.figure_eight",
        ],
    },
]

CLAIM_OWNER_PATHS = {
    "WP-62": {
        "src/crazyswarm_app/api/runtime.py",
        "src/crazyswarm_app/campaign/execution_head.py",
        "src/crazyswarm_app/campaign/runtime_executor.py",
        "src/crazyswarm_app/campaign/service.py",
        "src/crazyswarm_app/fleet/coordinator.py",
        "src/crazyswarm_app/missions/base.py",
        "src/crazyswarm_app/safety/supervisor.py",
        "src/crazyswarm_app/simulation/vehicle.py",
    },
    "WP-63": {
        "src/crazyswarm_app/campaign/catalog.py",
        "src/crazyswarm_app/campaign/models.py",
        "scripts/campaign_case_specs.py",
        "scripts/generate_campaign_catalog.py",
        "ui/app/components/CampaignLab.tsx",
    },
    "WP-64": {
        "src/crazyswarm_app/campaign/planner.py",
        "src/crazyswarm_app/campaign/submissions.py",
        "src/crazyswarm_app/campaign/trajectory.py",
        "src/crazyswarm_app/simulation/models.py",
        "src/crazyswarm_app/simulation/world.py",
        "src/crazyswarm_app/simulation/vehicle.py",
    },
    "WP-65": {
        "src/crazyswarm_app/campaign/analyzer.py",
        "src/crazyswarm_app/observability/csv_export.py",
        "src/crazyswarm_app/observability/evaluation.py",
        "src/crazyswarm_app/observability/storage.py",
        "ui/app/components/CampaignLab.tsx",
        "ui/app/components/RoomScene.tsx",
        "ui/app/lib/campaign-telemetry.ts",
    },
    "WP-66": {
        "src/crazyswarm_app/campaign/api_models.py",
        "src/crazyswarm_app/campaign/execution.py",
        "src/crazyswarm_app/campaign/execution_head.py",
        "src/crazyswarm_app/campaign/geometry.py",
        "src/crazyswarm_app/campaign/models.py",
        "src/crazyswarm_app/campaign/perception.py",
        "src/crazyswarm_app/campaign/planner.py",
        "src/crazyswarm_app/campaign/replanning.py",
        "src/crazyswarm_app/campaign/runtime_executor.py",
        "src/crazyswarm_app/campaign/scenario.py",
        "src/crazyswarm_app/campaign/submissions.py",
        "src/crazyswarm_app/simulation/sensors.py",
    },
}

IMPORT_DISCOVERY_ROOTS = {
    "src/crazyswarm_app/api/runtime.py",
    "src/crazyswarm_app/campaign/execution_head.py",
    "src/crazyswarm_app/campaign/runtime_executor.py",
    "src/crazyswarm_app/campaign/service.py",
    "src/crazyswarm_app/fleet/coordinator.py",
}

PUBLIC_AND_UI_TRANSITS = {
    "design.md",
    "docs/project/DESIGN.md",
    "docs/project/WORKFLOW_AND_REQUIREMENTS.md",
    "scripts/campaign_case_specs.py",
    "scripts/generate_campaign_catalog.py",
    "src/crazyswarm_app/campaign/api_models.py",
    "src/crazyswarm_app/dashboard.py",
    "src/crazyswarm_app/dashboard_service.py",
    "tests/campaign/test_changed_world_safety_monitor.py",
    "tests/campaign/test_dynamic_perception_replanning.py",
    "tests/campaign/test_one_drone_execution_head.py",
    "tests/campaign/test_reality_mission_e2e.py",
    "tests/fleet/test_preparation_and_coordinator.py",
    "ui/app/components/CampaignLab.tsx",
    "ui/app/components/ControlCenter.tsx",
    "ui/app/components/RoomScene.tsx",
    "ui/app/globals.css",
    "ui/app/lib/api.generated.ts",
    "ui/app/lib/api.ts",
    "ui/app/lib/campaign-telemetry.ts",
    "ui/app/lib/models.ts",
    "ui/app/page.tsx",
    "ui/tests/campaign-telemetry.test.ts",
}

NEW_PATHS = [
    "missions/campaigns/sim/cases/dynamic-replanning/1d-cases-v1.yaml",
    "missions/campaigns/sim/curriculum/1d-major-missions-v1.yaml",
    "tests/campaign/test_goal_seeking_dynamic_replanning.py",
    "tests/campaign/test_major_mission_catalog.py",
    "tests/campaign/test_replanning_runtime_stability.py",
    "tests/campaign/test_whole_route_motion_tradeoffs.py",
    "ui/tests/campaign-major-missions.test.tsx",
    "ui/tests/campaign-review-cursor.test.tsx",
]

RUN_EVIDENCE_SHA256 = {
    ".cache/crazyswarm/campaign/evidence/campaign-run-dd31f5156c7ad2adbb67/analysis.json": "9a941f17b198661eebcaac785922a32631f5359d351426e6867433d4f7ad25e7",
    ".cache/crazyswarm/campaign/evidence/campaign-run-dd31f5156c7ad2adbb67/manifest.json": "1c8552a0d33dc2ad83a017ac25b74393d38979bea86ec93ced4d9596a8bc9ee0",
    ".cache/crazyswarm/campaign/evidence/campaign-run-dd31f5156c7ad2adbb67/telemetry.csv": "536730e47f3190fa9e3e3553dfbbff49b7cc69d7b162f5aa3003c65bfbb60545",
    ".cache/crazyswarm/campaign/evidence/campaign-run-b2657ba1f323a160070f/analysis.json": "ba130789992e3c9c563777f63e8e20962ff3e9173a3f545b4ce6f3224d9234e5",
    ".cache/crazyswarm/campaign/evidence/campaign-run-b2657ba1f323a160070f/manifest.json": "289b0725f66e85ae7825006251ea127314907232956f82135e3ae325207e9936",
    ".cache/crazyswarm/campaign/evidence/campaign-run-b2657ba1f323a160070f/telemetry.csv": "59dcfb09db1452ccd8f940333a0ef90daae84f409b494978aca020c0613623df",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _local_module_path(module: str) -> str | None:
    candidate = ROOT / "src" / (module.replace(".", "/") + ".py")
    if candidate.exists():
        return candidate.relative_to(ROOT).as_posix()
    package = ROOT / "src" / module.replace(".", "/") / "__init__.py"
    if package.exists():
        return package.relative_to(ROOT).as_posix()
    return None


def _discover_direct_imports() -> set[str]:
    discovered: set[str] = set()
    for relative in IMPORT_DISCOVERY_ROOTS:
        tree = ast.parse((ROOT / relative).read_text())
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if not module.startswith("crazyswarm_app."):
                    continue
                path = _local_module_path(module)
                if path is not None:
                    discovered.add(path)
    return discovered


def _discover_generator_outputs() -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="wp62-66-generator-") as temporary:
        root = Path(temporary) / "missions"
        subprocess.run(
            [sys.executable, "scripts/generate_campaign_catalog.py", "--root", str(root)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return {
            (Path("missions") / path.relative_to(root)).as_posix(): _sha256(path)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }


def _boundary_manifest() -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    imported = _discover_direct_imports()
    generated = _discover_generator_outputs()
    paths = set().union(*CLAIM_OWNER_PATHS.values()) | PUBLIC_AND_UI_TRANSITS | imported | set(generated)
    manifest: list[dict[str, Any]] = []
    for relative in sorted(paths):
        classes: list[str] = []
        owners = sorted(key for key, values in CLAIM_OWNER_PATHS.items() if relative in values)
        if owners:
            classes.append("IMPLEMENTATION_OWNED")
        if relative in imported:
            classes.append("DISCOVERED_DIRECT_PRODUCTION_TRANSIT")
        if relative in generated:
            classes.append("DISCOVERED_GENERATED_OUTPUT")
        if relative in PUBLIC_AND_UI_TRANSITS and not owners:
            classes.append("RELIED_UPON_OR_IMPLEMENTATION_TRANSIT")
        path = ROOT / relative
        manifest.append(
            {
                "path": relative,
                "sha256": _sha256(path),
                "classifications": classes,
                "claim_owners": owners,
            }
        )
    return manifest, generated, sorted(imported)


GRID_STEP_M = 0.05
GRID_MIN_M = -1.8
GRID_MAX_M = 1.8
PROTECTED_PADDING_M = 0.055 + 0.05 + 0.15
HEADINGS = (
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
    (0, -1),
    (1, -1),
)


def _grid_index(value: float) -> int:
    index = round((value - GRID_MIN_M) / GRID_STEP_M)
    assert abs(GRID_MIN_M + index * GRID_STEP_M - value) < 1e-9
    return index


def _grid_point(index: tuple[int, int]) -> tuple[float, float]:
    return (
        round(GRID_MIN_M + index[0] * GRID_STEP_M, 10),
        round(GRID_MIN_M + index[1] * GRID_STEP_M, 10),
    )


def _point_box_distance(point: tuple[float, float], box: dict[str, Any]) -> float:
    dx = max(box["min_m"][0] - point[0], 0.0, point[0] - box["max_m"][0])
    dy = max(box["min_m"][1] - point[1], 0.0, point[1] - box["max_m"][1])
    return math.hypot(dx, dy)


def _blocked(point: tuple[float, float], obstacles: list[dict[str, Any]]) -> bool:
    if any(abs(value) > GRID_MAX_M - PROTECTED_PADDING_M + 1e-12 for value in point):
        return True
    return any(_point_box_distance(point, box) < PROTECTED_PADDING_M - 1e-12 for box in obstacles)


def _segment_clear(
    start: tuple[float, float],
    end: tuple[float, float],
    obstacles: list[dict[str, Any]],
) -> tuple[bool, float | None]:
    length = math.dist(start, end)
    count = max(1, math.ceil(length / 0.01))
    minimum: float | None = None
    for step in range(count + 1):
        fraction = step / count
        point = (
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        )
        if abs(point[0]) > GRID_MAX_M - PROTECTED_PADDING_M or abs(point[1]) > GRID_MAX_M - PROTECTED_PADDING_M:
            return False, minimum
        for obstacle in obstacles:
            clearance = _point_box_distance(point, obstacle)
            minimum = clearance if minimum is None else min(minimum, clearance)
            if clearance < PROTECTED_PADDING_M - 1e-12:
                return False, minimum
    return True, minimum


def _path_certificate(path: list[list[float]], obstacles: list[dict[str, Any]]) -> dict[str, Any]:
    minimum: float | None = None
    passed = len(path) >= 1
    for first, second in zip(path, path[1:], strict=False):
        clear, segment_minimum = _segment_clear(tuple(first), tuple(second), obstacles)
        passed = passed and clear
        if segment_minimum is not None:
            minimum = segment_minimum if minimum is None else min(minimum, segment_minimum)
    core = {
        "oracle": "independent-0.01m-swept-centerline-v1",
        "protected_padding_m": PROTECTED_PADDING_M,
        "minimum_center_to_obstacle_surface_m": minimum,
        "passed": passed,
        "path": path,
    }
    return {**core, "certificate_sha256": _canonical_sha256(core)}


def _astar(
    start_m: tuple[float, float],
    goal_m: tuple[float, float],
    obstacles: list[dict[str, Any]],
    *,
    maximum_expansions: int = 8192,
    reverse_neighbors: bool = False,
) -> dict[str, Any]:
    start_xy = (_grid_index(start_m[0]), _grid_index(start_m[1]))
    goal_xy = (_grid_index(goal_m[0]), _grid_index(goal_m[1]))
    start = (start_xy[0], start_xy[1], 0)
    queue: list[tuple[float, float, float, float, int, int, int]] = []
    heapq.heappush(queue, (math.dist(start_m, goal_m), 0.0, 0.0, 0.0, *start))
    best: dict[tuple[int, int, int], tuple[float, float, float]] = {start: (0.0, 0.0, 0.0)}
    previous: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    expanded = 0
    final: tuple[int, int, int] | None = None
    heading_order = list(range(len(HEADINGS)))
    if reverse_neighbors:
        heading_order.reverse()
    while queue:
        _, distance, turn, negative_clearance, ix, iy, heading = heapq.heappop(queue)
        state = (ix, iy, heading)
        if best.get(state) != (distance, turn, negative_clearance):
            continue
        if (ix, iy) == goal_xy:
            final = state
            break
        if expanded >= maximum_expansions:
            break
        expanded += 1
        for next_heading in heading_order:
            dx, dy = HEADINGS[next_heading]
            next_xy = (ix + dx, iy + dy)
            point = _grid_point(next_xy)
            if _blocked(point, obstacles):
                continue
            current_point = _grid_point((ix, iy))
            if dx and dy:
                if _blocked(_grid_point((ix + dx, iy)), obstacles) or _blocked(
                    _grid_point((ix, iy + dy)), obstacles
                ):
                    continue
            clear, minimum = _segment_clear(current_point, point, obstacles)
            if not clear:
                continue
            edge = GRID_STEP_M * (math.sqrt(2.0) if dx and dy else 1.0)
            heading_delta = min((next_heading - heading) % 8, (heading - next_heading) % 8)
            next_cost = (
                round(distance + edge, 12),
                round(turn + heading_delta * (math.pi / 4.0), 12),
                min(negative_clearance, -(minimum or 99.0)),
            )
            next_state = (next_xy[0], next_xy[1], next_heading)
            if next_state in best and best[next_state] <= next_cost:
                continue
            best[next_state] = next_cost
            previous[next_state] = state
            heuristic = math.dist(point, goal_m)
            heapq.heappush(queue, (next_cost[0] + heuristic, *next_cost, *next_state))
    if final is None:
        disposition = "BUDGET_EXHAUSTED" if expanded >= maximum_expansions else "NO_SOLUTION"
        core = {
            "disposition": disposition,
            "expanded_nodes": expanded,
            "maximum_expansions": maximum_expansions,
            "path": [],
            "path_length_m": None,
            "integrated_turn_rad": None,
            "minimum_center_clearance_m": None,
        }
        return {**core, "result_sha256": _canonical_sha256(core)}
    states = [final]
    while states[-1] != start:
        states.append(previous[states[-1]])
    states.reverse()
    path = [list(_grid_point((state[0], state[1]))) for state in states]
    cost = best[final]
    certificate = _path_certificate(path, obstacles)
    core = {
        "disposition": "FOUND_CERTIFIED" if certificate["passed"] else "REJECTED_UNCERTIFIED",
        "expanded_nodes": expanded,
        "maximum_expansions": maximum_expansions,
        "path": path,
        "path_length_m": cost[0],
        "integrated_turn_rad": cost[1],
        "minimum_center_clearance_m": certificate["minimum_center_to_obstacle_surface_m"],
        "certificate": certificate,
    }
    return {**core, "result_sha256": _canonical_sha256(core)}


def _search_prototypes() -> dict[str, Any]:
    obstacle = {"id": "rock", "min_m": [-0.2, -0.2], "max_m": [0.2, 0.2]}
    distant = {"id": "distant", "min_m": [0.8, 1.1], "max_m": [1.0, 1.2]}
    renamed = {**obstacle, "id": "renamed-rock"}
    no_obstacle = _astar((-1.3, 0.0), (1.3, 0.0), [])
    obstructed = _astar((-1.3, 0.0), (1.3, 0.0), [obstacle, distant])
    reordered = _astar(
        (-1.3, 0.0),
        (1.3, 0.0),
        [distant, obstacle],
        reverse_neighbors=True,
    )
    renamed_result = _astar((-1.3, 0.0), (1.3, 0.0), [renamed, distant])
    removal_before = _astar((-0.5, 0.0), (1.3, 0.0), [obstacle])
    removal_after = _astar((-0.5, 0.0), (1.3, 0.0), [])
    wall = {"id": "wall", "min_m": [-0.95, -1.8], "max_m": [-0.9, 1.8]}
    return {
        "configuration": {
            "state": "x/y grid cell plus inbound heading",
            "grid_step_m": GRID_STEP_M,
            "headings": [list(item) for item in HEADINGS],
            "edge_family": "8-connected; diagonal corner-cutting forbidden",
            "obstacle_inflation_m": PROTECTED_PADDING_M,
            "cost_order": [
                "path_length_m",
                "integrated_absolute_heading_change_rad",
                "negative_minimum_clearance_m",
                "canonical_state_key",
            ],
            "heuristic": "Euclidean distance in metres; admissible for primary path-length cost",
            "maximum_expansions": 8192,
            "wall_budget_s": 0.09,
            "budget_disposition": "NO_COMMAND_BUDGET_EXHAUSTED",
            "post_search_motion": "WP-64 PVA-continuous trajectory; uncertified smoothing rejects the corridor",
        },
        "no_obstacle": no_obstacle,
        "obstructed": obstructed,
        "candidate_reordered": reordered,
        "obstacle_renamed": renamed_result,
        "removal_before": removal_before,
        "removal_after": removal_after,
        "budget_exhausted": _astar((-1.3, 0.0), (1.3, 0.0), [obstacle], maximum_expansions=1),
        "no_solution": _astar((-1.3, 0.0), (1.3, 0.0), [wall], maximum_expansions=8192),
    }


def _jerk_limited_stop(speed_m_s: float) -> tuple[float, float]:
    acceleration = 1.0
    jerk = 8.0
    ramp_s = acceleration / jerk
    ramp_velocity_delta = 0.5 * acceleration * ramp_s
    if speed_m_s <= 2.0 * ramp_velocity_delta:
        triangular_ramp_s = math.sqrt(speed_m_s / jerk)
        stop_time_s = 2.0 * triangular_ramp_s
        stop_distance_m = speed_m_s * triangular_ramp_s
    else:
        hold_s = (speed_m_s - 2.0 * ramp_velocity_delta) / acceleration
        first_distance = speed_m_s * ramp_s - jerk * ramp_s**3 / 6.0
        first_end_speed = speed_m_s - ramp_velocity_delta
        hold_distance = first_end_speed * hold_s - 0.5 * acceleration * hold_s**2
        final_distance = ramp_velocity_delta * ramp_s - 0.5 * acceleration * ramp_s**2 + jerk * ramp_s**3 / 6.0
        stop_time_s = 2.0 * ramp_s + hold_s
        stop_distance_m = first_distance + hold_distance + final_distance
    return stop_time_s, stop_distance_m


def _observation_status(observation: dict[str, Any]) -> str:
    expected = _canonical_sha256(observation["payload"])
    if observation["authenticated_payload_sha256"] != expected:
        return "TAMPERED"
    if observation["generation"] <= observation["current_generation"]:
        return "STALE_GENERATION"
    if observation["current_source_s"] - observation["source_s"] > 0.25:
        return "LATE_SOURCE"
    if observation["received_s"] - observation["source_s"] > 0.12 + 1e-12:
        return "LATE_RECEIVE"
    return "TRUSTED_FRESH"


def _vertical_abort_certificate(
    current_x_m: float,
    speed_m_s: float,
    obstacle: dict[str, Any],
) -> dict[str, Any]:
    path = [[current_x_m, 0.0, round(0.4 - step * 0.01, 2)] for step in range(37)]
    minimum = abs(obstacle["min_m"][0] - current_x_m)
    passed = speed_m_s <= 0.02 and minimum >= PROTECTED_PADDING_M and path[-1][2] == 0.04
    core = {
        "oracle": "independent-vertical-descent-0.01m-v1",
        "path": path,
        "minimum_center_to_obstacle_surface_m": minimum,
        "required_padding_m": PROTECTED_PADDING_M,
        "entry_speed_m_s": speed_m_s,
        "maximum_vertical_abort_entry_speed_m_s": 0.02,
        "passed": passed,
    }
    return {**core, "certificate_sha256": _canonical_sha256(core)}


def _reaction_witness(
    witness_id: str,
    *,
    speed_m_s: float,
    surface_distance_m: float,
    observation_variant: str = "TRUSTED",
    block_goal: bool = False,
    maximum_hover_s: float = 60.0,
) -> dict[str, Any]:
    latency_s = 0.12 + 0.02 + 0.09 + 0.0006 + 0.0994
    stop_time_s, stop_distance_m = _jerk_limited_stop(speed_m_s)
    response_distance_m = speed_m_s * latency_s + stop_distance_m
    required_distance_m = PROTECTED_PADDING_M + response_distance_m
    margin_m = surface_distance_m - required_distance_m
    urgency = max(0.0, min(1.0, 1.0 - margin_m / 0.25))
    current_x_m = -surface_distance_m
    obstacle = {"id": "sensed-rock", "min_m": [0.0, -0.2], "max_m": [0.35, 0.2]}
    planning_obstacles = [obstacle]
    if block_goal:
        planning_obstacles = [
            {"id": "blocking-wall", "min_m": [-0.1, -1.5], "max_m": [0.1, 1.5]}
        ]
    payload = {"solid_id": obstacle["id"], "region": obstacle}
    observation = {
        "source_s": 5.0,
        "received_s": 5.12,
        "current_source_s": 5.20,
        "generation": 2,
        "current_generation": 1,
        "payload": payload,
        "authenticated_payload_sha256": _canonical_sha256(payload),
    }
    if observation_variant == "TAMPERED":
        observation["authenticated_payload_sha256"] = "0" * 64
    elif observation_variant == "STALE":
        observation["generation"] = 1
    elif observation_variant == "LATE_SOURCE":
        observation["current_source_s"] = 5.26
    elif observation_variant == "LATE_RECEIVE":
        observation["received_s"] = 5.121
    status = _observation_status(observation)
    search = _astar((current_x_m, 0.0), (1.35, 0.0), planning_obstacles)
    braking_path = [[current_x_m, 0.0], [current_x_m + response_distance_m, 0.0]]
    braking_certificate = _path_certificate(braking_path, [obstacle])
    hold_clearance_m = surface_distance_m - PROTECTED_PADDING_M
    hold_certificate_core = {
        "oracle": "independent-invariant-hold-v1",
        "speed_m_s": speed_m_s,
        "maximum_hold_speed_m_s": 0.02,
        "clearance_margin_m": hold_clearance_m,
        "prediction_horizon_s": 3.0,
        "maximum_hover_s": maximum_hover_s,
        "passed": speed_m_s <= 0.02 and hold_clearance_m >= 0.0 and maximum_hover_s >= 3.0,
    }
    hold_certificate = {
        **hold_certificate_core,
        "certificate_sha256": _canonical_sha256(hold_certificate_core),
    }
    abort_certificate = _vertical_abort_certificate(current_x_m, speed_m_s, obstacle)
    trusted = status == "TRUSTED_FRESH"
    if not trusted:
        command = "REJECT_UPDATE_AND_CERTIFIED_HOLD" if hold_certificate["passed"] else "REJECT_UPDATE_NO_CERTIFIED_CONTINGENCY"
    elif search["disposition"] == "FOUND_CERTIFIED" and braking_certificate["passed"]:
        command = "CONTINUE_WITH_MOVING_REPLAN" if urgency == 0.0 else "JERK_LIMITED_DECELERATE_AND_TURN"
    elif hold_certificate["passed"]:
        command = "CERTIFIED_HOLD"
    elif abort_certificate["passed"]:
        command = "CERTIFIED_ABORT_AND_LAND"
    else:
        command = "NO_CERTIFIED_RESPONSE_FAIL_CLOSED"
    core = {
        "witness_id": witness_id,
        "vehicle": {
            "position_m": [current_x_m, 0.0, 0.4],
            "velocity_m_s": [speed_m_s, 0.0, 0.0],
            "acceleration_m_s2": [0.0, 0.0, 0.0],
            "nominal_radius_m": 0.055,
            "maximum_acceleration_m_s2": 1.0,
            "maximum_jerk_m_s3": 8.0,
        },
        "world": {
            "flight_volume_min_m": [-1.8, -1.8, 0.0],
            "flight_volume_max_m": [1.8, 1.8, 1.0],
            "goal_m": [1.35, 0.0, 0.4],
            "obstacles": planning_obstacles,
            "center_to_obstacle_surface_distance_m": surface_distance_m,
        },
        "clocks": {
            "source_clock_id": "fast-sim-Alpha",
            "source_clock_epoch": 1,
            "observation": observation,
            "effective_cutover_s": 5.33,
            "budgets_s": {
                "sense_process": 0.12,
                "validate": 0.02,
                "plan": 0.09,
                "acknowledge": 0.0006,
                "commit_guard": 0.0994,
                "total": latency_s,
                "prediction_horizon": 3.0,
            },
        },
        "observation_status": status,
        "protection": {
            "position_uncertainty_m": 0.05,
            "policy_clearance_m": 0.15,
            "jerk_limited_stop_time_s": stop_time_s,
            "jerk_limited_stop_distance_m": stop_distance_m,
            "response_distance_m": response_distance_m,
            "required_center_surface_distance_m": required_distance_m,
            "margin_m": margin_m,
            "urgency_0_to_1": urgency,
        },
        "search": search,
        "braking_certificate": braking_certificate,
        "hold_certificate": hold_certificate,
        "abort_certificate": abort_certificate,
        "resulting_command": command,
    }
    return {**core, "decision_certificate_sha256": _canonical_sha256(core)}


def _guard_registry() -> dict[str, Any]:
    guards = [
        ("profile", "speed_compliance_fraction", ">=", 0.95, 0.96, 0.94),
        ("profile", "speed_ripple_m_s", "<=", 0.05, 0.049, 0.051),
        ("tracking", "path_tube_max_error_m", "<=", 0.05, 0.049, 0.051),
        ("dynamics", "acceleration_p95_m_s2", "<=", 1.0, 0.99, 1.01),
        ("dynamics", "jerk_p95_m_s3", "<=", 8.0, 7.9, 8.1),
        ("dynamics", "angular_rate_p95_rad_s", "<=", 0.40, 0.39, 0.41),
        ("actuation", "minimum_motor_thrust_headroom_n", ">=", 0.030, 0.031, 0.029),
        ("actuation", "motor_spread_p95_percent", "<=", 0.50, 0.49, 0.51),
        ("actuation", "motor_saturation_fraction", "<=", 0.02, 0.019, 0.021),
        ("actuation", "motor_differential_sign_agreement_fraction", ">=", 0.95, 0.96, 0.94),
        ("actuation", "motor_differential_normalized_error_p95", "<=", 0.10, 0.09, 0.11),
        ("energy", "electrical_energy_used_j", "<=", 220.0, 219.0, 221.0),
        ("clearance", "minimum_clearance_m", ">=", 0.15, 0.151, 0.149),
        ("clearance", "collision_count", "<=", 0, 0, 1),
        ("traversal", "checkpoint_hold_conformance_fraction", ">=", 1.0, 1.0, 0.99),
        ("traversal", "minimum_continuous_knot_speed_ratio", ">=", 0.85, 0.86, 0.84),
        ("traversal", "minimum_crossover_knot_speed_ratio", ">=", 0.95, 0.96, 0.94),
        ("traversal", "unintended_fly_through_stop_count", "<=", 0, 0, 1),
        ("terminal", "terminal_secondary_peak_m_s", "<=", 0.02, 0.019, 0.021),
        ("terminal", "terminal_reversal_count", "<=", 0, 0, 1),
        ("terminal", "duration_s", "<=", 180.0, 179.0, 181.0),
        ("safety", "supervisor_safety_gate_passed", "==", True, True, False),
        ("goal_landing", "goal_error_m", "<=", 0.08, 0.079, 0.081),
        ("goal_landing", "landing_horizontal_error_m", "<=", 0.10, 0.099, 0.101),
        ("goal_landing", "landing_vertical_error_m", "<=", 0.08, 0.079, 0.081),
        ("goal_landing", "terminal_landed_disarmed", "==", True, True, False),
        ("realtime", "realtime_factor", ">=", 0.8, 0.81, 0.79),
        ("realtime", "stale_abort_count", "<=", 0, 0, 1),
    ]
    rows = [
        {
            "category": category,
            "metric": metric,
            "comparator": comparator,
            "threshold": threshold,
            "pass_value": pass_value,
            "isolated_fail_value": fail_value,
        }
        for category, metric, comparator, threshold, pass_value, fail_value in guards
    ]
    pass_vector = {row["metric"]: row["pass_value"] for row in rows}
    isolated_failures = {
        row["metric"]: {row["metric"]: row["isolated_fail_value"]} for row in rows
    }
    return {
        "semantic_sources": {
            "MotionQualityContract.fields": [
                "profile",
                "tracking",
                "dynamics",
                "actuation",
                "energy",
                "clearance",
                "traversal",
                "terminal",
                "safety",
            ],
            "WP-62.exit": ["realtime", "safety"],
            "WP-64.exit": [
                "profile",
                "tracking",
                "dynamics",
                "actuation",
                "energy",
                "clearance",
                "traversal",
                "terminal",
                "safety",
            ],
            "WP-66.exit": [
                "realtime",
                "profile",
                "tracking",
                "dynamics",
                "actuation",
                "energy",
                "clearance",
                "traversal",
                "terminal",
                "safety",
                "goal_landing",
            ],
        },
        "guards": rows,
        "passing_whole_vector": pass_vector,
        "isolated_failure_overrides": isolated_failures,
        "numeric_tolerance": 1e-12,
        "repeat_semantics": "each guard passes each of three accelerated repeats and each declared realtime repeat; no median masks a failure",
    }


def _passes_guard(row: dict[str, Any], value: Any) -> bool:
    comparator = row["comparator"]
    threshold = row["threshold"]
    if comparator == ">=":
        return value >= threshold
    if comparator == "<=":
        return value <= threshold
    if comparator == "==":
        return value == threshold
    raise AssertionError(comparator)


def build_payload() -> dict[str, Any]:
    boundary_manifest, generated_outputs, discovered_imports = _boundary_manifest()
    witnesses = [
        _reaction_witness("nominal-moving-detour", speed_m_s=0.4, surface_distance_m=0.95),
        _reaction_witness("progressive-turn", speed_m_s=0.4, surface_distance_m=0.50),
        _reaction_witness("lower-speed-same-distance", speed_m_s=0.2, surface_distance_m=0.50),
        _reaction_witness("insufficient-clearance", speed_m_s=0.4, surface_distance_m=0.35),
        _reaction_witness(
            "stale-generation",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            observation_variant="STALE",
            block_goal=True,
        ),
        _reaction_witness(
            "late-source",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            observation_variant="LATE_SOURCE",
            block_goal=True,
        ),
        _reaction_witness(
            "late-receive",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            observation_variant="LATE_RECEIVE",
            block_goal=True,
        ),
        _reaction_witness(
            "tampered-observation",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            observation_variant="TAMPERED",
            block_goal=True,
        ),
        _reaction_witness(
            "certified-hold",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            block_goal=True,
        ),
        _reaction_witness(
            "certified-abort-land",
            speed_m_s=0.0,
            surface_distance_m=0.50,
            block_goal=True,
            maximum_hover_s=0.0,
        ),
        _reaction_witness(
            "no-certified-response",
            speed_m_s=0.0,
            surface_distance_m=0.20,
            block_goal=True,
        ),
    ]
    return {
        "schema_version": 1,
        "batch": "WP-62-through-WP-66",
        "base_commit": "40cd9947f87eb9bf2719d72e7c72ea867eab9977",
        "intent_value": {
            "minimum_useful_outcome": "A recoverable realtime simulator and one smooth start-goal online-obstacle mission that does not stop for an ample-margin observation.",
            "explicit": [
                "five major 1D missions with nested behavior variants",
                "plain motion controls without routine eligibility labels",
                "whole-route speed/accuracy/smoothness trade-offs",
                "graph sample to exact spatial/source-time inspection",
                "a separate dynamic-replanning cluster containing only the online-obstacle mission",
            ],
            "prerequisites": [
                "fix false stale-watchdog aborts without relaxing the freshness guard",
                "preserve hard safety bounds and independent trajectory certificates",
            ],
            "deferred": [
                "additional dynamic mission families",
                "digital-twin calibration and hardware work",
                "live computer vision, mapping, SLAM, or learned control",
            ],
        },
        "mission_groups": MISSION_GROUPS,
        "controls": {
            "normal": ["Balance"],
            "tune_disclosure": ["Speed", "Accuracy", "Smoothness"],
            "forbidden_default_copy": ["Eligible", "Planner-retimed baseline"],
            "hard_guards_never_relaxed": [
                "collision",
                "flight_volume",
                "acceleration",
                "jerk",
                "actuator_headroom",
                "energy",
                "terminal",
            ],
        },
        "latest_runtime_evidence": [
            {
                "run_id": "campaign-run-dd31f5156c7ad2adbb67",
                "status": "ABORTED",
                "telemetry_rows": 308,
                "perception_observations": 0,
                "realtime_factor": 0.7762462302035557,
                "terminal_state": "EMERGENCY",
                "primary_cause": "wall-clock watchdog expired while source-clock schedule progressed",
            },
            {
                "run_id": "campaign-run-b2657ba1f323a160070f",
                "status": "ABORTED",
                "telemetry_rows": 603,
                "perception_observations": 1,
                "replacement_dispatches": 1,
                "observation_source_s": 5.027430402413535,
                "observation_received_s": 5.147430402413535,
                "planning_latency_s": 0.08945066599972051,
                "total_reaction_s": 0.310043290999347,
                "certified_clearance_m": 0.952651849579511,
                "stopped_observed_speed_m_s": 0.16009514752424556,
                "fallback_command": "STOP_AND_HOLD",
                "realtime_factor": 0.7886796105394428,
                "terminal_state": "EMERGENCY",
                "primary_cause": "wall-clock watchdog expired while source-clock schedule progressed",
            },
        ],
        "run_evidence_sha256": RUN_EVIDENCE_SHA256,
        "search_prototypes": _search_prototypes(),
        "reaction_witnesses": witnesses,
        "guard_registry": _guard_registry(),
        "claim_owner_paths": {key: sorted(value) for key, value in CLAIM_OWNER_PATHS.items()},
        "direct_import_discovery_roots": sorted(IMPORT_DISCOVERY_ROOTS),
        "discovered_direct_import_paths": discovered_imports,
        "discovered_generator_outputs_sha256": generated_outputs,
        "boundary_manifest": boundary_manifest,
        "new_paths_absent_at_design_gate": NEW_PATHS,
    }


def check(payload: dict[str, Any]) -> None:
    labels = [group["label"] for group in payload["mission_groups"]]
    assert labels == ["Flight", "Target", "Level path", "3D path", "Shape"]
    variants = [variant for group in payload["mission_groups"] for variant in group["variants"]]
    assert len(variants) == len(set(variants))
    assert set(variants) == CURRENT_1D_CASES
    control_labels = payload["controls"]["normal"] + payload["controls"]["tune_disclosure"]
    assert all(len(label.split()) == 1 for label in control_labels)
    assert "Eligible" not in control_labels

    witness_by_id = {item["witness_id"]: item for item in payload["reaction_witnesses"]}
    assert witness_by_id["nominal-moving-detour"]["resulting_command"] == "CONTINUE_WITH_MOVING_REPLAN"
    assert witness_by_id["progressive-turn"]["resulting_command"] == "JERK_LIMITED_DECELERATE_AND_TURN"
    assert witness_by_id["insufficient-clearance"]["resulting_command"] == "NO_CERTIFIED_RESPONSE_FAIL_CLOSED"
    assert witness_by_id["stale-generation"]["observation_status"] == "STALE_GENERATION"
    assert witness_by_id["late-source"]["observation_status"] == "LATE_SOURCE"
    assert witness_by_id["late-receive"]["observation_status"] == "LATE_RECEIVE"
    assert witness_by_id["tampered-observation"]["observation_status"] == "TAMPERED"
    assert witness_by_id["certified-hold"]["resulting_command"] == "CERTIFIED_HOLD"
    assert witness_by_id["certified-abort-land"]["resulting_command"] == "CERTIFIED_ABORT_AND_LAND"
    assert witness_by_id["no-certified-response"]["resulting_command"] == "NO_CERTIFIED_RESPONSE_FAIL_CLOSED"
    assert witness_by_id["lower-speed-same-distance"]["protection"]["urgency_0_to_1"] < witness_by_id["progressive-turn"]["protection"]["urgency_0_to_1"]
    for witness in payload["reaction_witnesses"]:
        core = {key: value for key, value in witness.items() if key != "decision_certificate_sha256"}
        assert witness["decision_certificate_sha256"] == _canonical_sha256(core)
        assert abs(witness["clocks"]["budgets_s"]["total"] - 0.33) < 1e-12
        for certificate_key in ("braking_certificate", "hold_certificate", "abort_certificate"):
            certificate = witness[certificate_key]
            core = {key: value for key, value in certificate.items() if key != "certificate_sha256"}
            assert certificate["certificate_sha256"] == _canonical_sha256(core)

    search = payload["search_prototypes"]
    assert search["no_obstacle"]["disposition"] == "FOUND_CERTIFIED"
    assert search["obstructed"]["disposition"] == "FOUND_CERTIFIED"
    assert search["candidate_reordered"]["path"] == search["obstructed"]["path"]
    assert search["obstacle_renamed"]["path"] == search["obstructed"]["path"]
    assert search["obstructed"]["path_length_m"] > search["no_obstacle"]["path_length_m"]
    assert search["removal_after"]["path_length_m"] < search["removal_before"]["path_length_m"]
    assert search["budget_exhausted"]["disposition"] == "BUDGET_EXHAUSTED"
    assert search["no_solution"]["disposition"] == "NO_SOLUTION"

    registry = payload["guard_registry"]
    rows = registry["guards"]
    categories = {row["category"] for row in rows}
    source_categories = set().union(*map(set, registry["semantic_sources"].values()))
    assert categories == source_categories
    assert len({row["metric"] for row in rows}) == len(rows)
    for row in rows:
        assert _passes_guard(row, row["pass_value"])
        assert not _passes_guard(row, row["isolated_fail_value"])
        vector = dict(registry["passing_whole_vector"])
        vector.update(registry["isolated_failure_overrides"][row["metric"]])
        failed = [candidate["metric"] for candidate in rows if not _passes_guard(candidate, vector[candidate["metric"]])]
        assert failed == [row["metric"]]

    manifest, generated, imported = _boundary_manifest()
    assert payload["boundary_manifest"] == manifest
    assert payload["discovered_generator_outputs_sha256"] == generated
    assert payload["discovered_direct_import_paths"] == imported
    manifest_by_path = {row["path"]: row for row in manifest}
    assert set().union(*CLAIM_OWNER_PATHS.values()) <= set(manifest_by_path)
    assert PUBLIC_AND_UI_TRANSITS <= set(manifest_by_path)
    assert set(imported) <= set(manifest_by_path)
    assert set(generated) <= set(manifest_by_path)
    for required in (
        "src/crazyswarm_app/api/runtime.py",
        "src/crazyswarm_app/campaign/api_models.py",
        "src/crazyswarm_app/campaign/execution.py",
        "src/crazyswarm_app/campaign/perception.py",
        "src/crazyswarm_app/campaign/scenario.py",
        "src/crazyswarm_app/safety/supervisor.py",
        "src/crazyswarm_app/simulation/sensors.py",
    ):
        assert required in manifest_by_path
    for relative, expected in generated.items():
        assert _sha256(ROOT / relative) == expected, relative
    assert all(row["classifications"] for row in manifest)
    for relative, expected in RUN_EVIDENCE_SHA256.items():
        assert _sha256(ROOT / relative) == expected, relative
    for relative in NEW_PATHS:
        assert not (ROOT / relative).exists(), relative


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", nargs="?", type=Path)
    args = parser.parse_args()
    payload = build_payload()
    check(payload)
    if args.artifact is not None:
        assert json.loads(args.artifact.read_text()) == payload
    print(json.dumps(payload, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
