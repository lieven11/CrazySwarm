from __future__ import annotations

import heapq
import math
import time
from collections.abc import Sequence
from enum import StrEnum
from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import Region3D
from crazyswarm_app.domain.models import ContractModel, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class GoalCorridorDisposition(StrEnum):
    SELECTED = "SELECTED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    NO_SOLUTION = "NO_SOLUTION"


class GoalCorridorSearchResult(ContractModel):
    schema_version: Literal[1] = 1
    planner_id: Literal["bounded-goal-corridor-a-star-v1"] = (
        "bounded-goal-corridor-a-star-v1"
    )
    disposition: GoalCorridorDisposition
    cell_size_m: float = Field(default=0.05, gt=0.0, le=0.05)
    expansion_limit: int = Field(ge=1, le=8192)
    wall_budget_s: float = Field(ge=0.0, le=0.5)
    expanded_state_count: int = Field(ge=0)
    path_points_m: tuple[Vector3, ...]
    path_length_m: float = Field(ge=0.0)
    integrated_absolute_heading_change_rad: float = Field(ge=0.0)
    minimum_center_clearance_m: float = Field(ge=0.0)
    obstacle_geometry_sha256: SHA256
    result_sha256: SHA256

    @model_validator(mode="after")
    def identity_and_disposition_match(self) -> GoalCorridorSearchResult:
        if (self.disposition is GoalCorridorDisposition.SELECTED) != bool(
            self.path_points_m
        ):
            raise ValueError("only a selected corridor may contain path points")
        if not math.isclose(self.cell_size_m, 0.05, abs_tol=1e-12):
            raise ValueError("goal-corridor cell size must be exactly 0.05 m")
        payload = self.model_dump(mode="python", exclude={"result_sha256"})
        if self.result_sha256 != canonical_sha256(payload):
            raise ValueError("goal-corridor result hash mismatch")
        return self


_EIGHT_ADJACENT: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
    (0, -1),
    (1, -1),
)

GridState = tuple[int, int, int]
GridCost = tuple[float, float, float]


def search_goal_corridor(
    *,
    start_m: Vector3,
    goal_m: Vector3,
    flight_volume: Region3D,
    obstacles: Sequence[Region3D],
    inflation_m: float,
    boundary_horizontal_margin_m: float,
    expansion_limit: int = 8192,
    wall_budget_s: float = 0.5,
    neighbor_primitives: Sequence[tuple[int, int]] = _EIGHT_ADJACENT,
) -> GoalCorridorSearchResult:
    """Search one deterministic 2D free-space corridor from current state to goal.

    Obstacle identity and caller enumeration never participate in ordering. Geometry,
    canonical grid state, and the frozen eight-neighbor primitive family are the only
    search inputs.
    """

    if not 1 <= expansion_limit <= 8192:
        raise ValueError("goal-corridor expansion limit must be in 1..8192")
    if not 0.0 <= wall_budget_s <= 0.5:
        raise ValueError("goal-corridor wall budget must be in [0, 0.5]")
    if len(neighbor_primitives) != len(_EIGHT_ADJACENT) or set(
        neighbor_primitives
    ) != set(_EIGHT_ADJACENT):
        raise ValueError("goal-corridor search requires exactly eight adjacent cells")
    primitives = _EIGHT_ADJACENT
    if not flight_volume.contains(start_m) or not flight_volume.contains(goal_m):
        raise ValueError("goal-corridor endpoints must be inside the flight volume")
    if inflation_m < 0.0 or boundary_horizontal_margin_m < 0.0:
        raise ValueError("goal-corridor protection margins cannot be negative")

    started = time.monotonic()
    cell_size_m = 0.05
    origin_x = flight_volume.minimum_m.x
    origin_y = flight_volume.minimum_m.y

    def index_for(value: float, origin: float) -> int:
        return math.floor((value - origin) / cell_size_m + 0.5)

    def point_for(ix: int, iy: int) -> Vector3:
        return Vector3(
            x=round(origin_x + ix * cell_size_m, 10),
            y=round(origin_y + iy * cell_size_m, 10),
            z=start_m.z,
        )

    start_xy = (index_for(start_m.x, origin_x), index_for(start_m.y, origin_y))
    goal_xy = (index_for(goal_m.x, origin_x), index_for(goal_m.y, origin_y))
    canonical_obstacles = tuple(
        sorted(
            obstacles,
            key=lambda item: (
                item.minimum_m.x,
                item.minimum_m.y,
                item.minimum_m.z,
                item.maximum_m.x,
                item.maximum_m.y,
                item.maximum_m.z,
            ),
        )
    )
    free_cache: dict[tuple[int, int], bool] = {}
    edge_cache: dict[tuple[int, int, int, int], tuple[bool, float]] = {}

    def free(ix: int, iy: int) -> bool:
        key = (ix, iy)
        cached = free_cache.get(key)
        if cached is not None:
            return cached
        x = origin_x + ix * cell_size_m
        y = origin_y + iy * cell_size_m
        admitted = not (
            x < flight_volume.minimum_m.x + boundary_horizontal_margin_m
            or x > flight_volume.maximum_m.x - boundary_horizontal_margin_m
            or y < flight_volume.minimum_m.y + boundary_horizontal_margin_m
            or y > flight_volume.maximum_m.y - boundary_horizontal_margin_m
        ) and all(
            _distance_to_region_xy_values(x, y, region) + 1e-12 >= inflation_m
            for region in canonical_obstacles
        )
        free_cache[key] = admitted
        return admitted

    def edge_clearance(ix: int, iy: int, next_ix: int, next_iy: int) -> tuple[bool, float]:
        key = (ix, iy, next_ix, next_iy)
        cached = edge_cache.get(key)
        if cached is not None:
            return cached
        before = point_for(ix, iy)
        after = point_for(next_ix, next_iy)
        length_m = math.hypot(after.x - before.x, after.y - before.y)
        count = max(1, math.ceil(length_m / 0.01))
        minimum = 1_000_000.0
        admitted = True
        for step in range(count + 1):
            fraction = step / count
            x = before.x + (after.x - before.x) * fraction
            y = before.y + (after.y - before.y) * fraction
            if (
                x < flight_volume.minimum_m.x + boundary_horizontal_margin_m
                or x > flight_volume.maximum_m.x - boundary_horizontal_margin_m
                or y < flight_volume.minimum_m.y + boundary_horizontal_margin_m
                or y > flight_volume.maximum_m.y - boundary_horizontal_margin_m
            ):
                admitted = False
                break
            for region in canonical_obstacles:
                clearance = _distance_to_region_xy_values(x, y, region)
                minimum = min(minimum, clearance)
                if clearance + 1e-12 < inflation_m:
                    admitted = False
                    break
            if not admitted:
                break
        result = (admitted, minimum)
        edge_cache[key] = result
        edge_cache[(next_ix, next_iy, ix, iy)] = result
        return result

    if wall_budget_s == 0.0:
        return _result(
            GoalCorridorDisposition.BUDGET_EXHAUSTED,
            expansion_limit,
            wall_budget_s,
            0,
            (),
            canonical_obstacles,
            (goal_xy[0] - start_xy[0], goal_xy[1] - start_xy[1]),
        )
    if not free(*start_xy) or not free(*goal_xy):
        return _result(
            GoalCorridorDisposition.NO_SOLUTION,
            expansion_limit,
            wall_budget_s,
            0,
            (),
            canonical_obstacles,
            (goal_xy[0] - start_xy[0], goal_xy[1] - start_xy[1]),
        )

    direct_heading = (goal_xy[0] - start_xy[0], goal_xy[1] - start_xy[1])
    start_heading = min(
        range(len(primitives)),
        key=lambda index: (
            _absolute_heading_change(primitives[index], direct_heading),
            primitives[index],
        ),
    )
    start_state: GridState = (start_xy[0], start_xy[1], start_heading)
    best: dict[GridState, GridCost] = {start_state: (0.0, 0.0, 0.0)}
    parent: dict[GridState, GridState] = {}
    frontier: list[tuple[float, float, float, float, GridState]] = []
    heapq.heappush(
        frontier,
        (
            _heuristic(start_xy, goal_xy, cell_size_m),
            0.0,
            0.0,
            best[start_state][2],
            start_state,
        ),
    )
    expanded: set[GridState] = set()
    best_goal: GridState | None = None
    budget_exhausted = False

    while frontier:
        if time.monotonic() - started >= wall_budget_s:
            budget_exhausted = True
            break
        (
            _estimated_length,
            queued_distance,
            queued_turn,
            queued_negative_clearance,
            state,
        ) = heapq.heappop(frontier)
        if state in expanded:
            continue
        current_cost = best[state]
        if (
            (queued_distance, queued_turn, queued_negative_clearance) != current_cost
        ):
            continue
        if state[:2] == goal_xy:
            best_goal = state
            break
        if len(expanded) >= expansion_limit:
            budget_exhausted = True
            break
        expanded.add(state)

        for heading, (dx, dy) in enumerate(primitives):
            next_xy = (state[0] + dx, state[1] + dy)
            if not free(*next_xy):
                continue
            if dx and dy and (
                not free(state[0] + dx, state[1])
                or not free(state[0], state[1] + dy)
            ):
                continue
            edge_admitted, edge_minimum_clearance = edge_clearance(
                state[0], state[1], next_xy[0], next_xy[1]
            )
            if not edge_admitted:
                continue
            next_state: GridState = (next_xy[0], next_xy[1], heading)
            step_length = cell_size_m * (math.sqrt(2.0) if dx and dy else 1.0)
            heading_change = _absolute_heading_change(primitives[state[2]], (dx, dy))
            next_cost: GridCost = (
                round(current_cost[0] + step_length, 12),
                round(current_cost[1] + heading_change, 12),
                round(min(current_cost[2], -edge_minimum_clearance), 12),
            )
            if next_cost >= best.get(next_state, (math.inf, math.inf, math.inf)):
                continue
            best[next_state] = next_cost
            parent[next_state] = state
            heapq.heappush(
                frontier,
                (
                    round(
                        next_cost[0] + _heuristic(next_xy, goal_xy, cell_size_m),
                        12,
                    ),
                    next_cost[0],
                    next_cost[1],
                    next_cost[2],
                    next_state,
                ),
            )

    if best_goal is None:
        return _result(
            (
                GoalCorridorDisposition.BUDGET_EXHAUSTED
                if budget_exhausted
                else GoalCorridorDisposition.NO_SOLUTION
            ),
            expansion_limit,
            wall_budget_s,
            len(expanded),
            (),
            canonical_obstacles,
            direct_heading,
        )
    states = [best_goal]
    while states[-1] != start_state:
        states.append(parent[states[-1]])
    states.reverse()
    grid_points = tuple(point_for(state[0], state[1]) for state in states)
    points = _deduplicate_points((start_m, *grid_points, goal_m))
    selected = _result(
        GoalCorridorDisposition.SELECTED,
        expansion_limit,
        wall_budget_s,
        len(expanded),
        points,
        canonical_obstacles,
        direct_heading,
    )
    if time.monotonic() - started >= wall_budget_s:
        return _result(
            GoalCorridorDisposition.BUDGET_EXHAUSTED,
            expansion_limit,
            wall_budget_s,
            len(expanded),
            (),
            canonical_obstacles,
            direct_heading,
        )
    return selected


def simplify_corridor(points: Sequence[Vector3]) -> tuple[Vector3, ...]:
    """Remove only collinear grid samples; preserve every actual turn."""

    if len(points) <= 2:
        return tuple(points)
    output = [points[0]]
    for before, current, after in zip(points, points[1:], points[2:], strict=False):
        first = (current.x - before.x, current.y - before.y)
        second = (after.x - current.x, after.y - current.y)
        cross = first[0] * second[1] - first[1] * second[0]
        same_direction = first[0] * second[0] + first[1] * second[1] > 0.0
        if abs(cross) > 1e-12 or not same_direction:
            output.append(current)
    output.append(points[-1])
    return _deduplicate_points(tuple(output))


def _result(
    disposition: GoalCorridorDisposition,
    expansion_limit: int,
    wall_budget_s: float,
    expanded_state_count: int,
    points: tuple[Vector3, ...],
    obstacles: Sequence[Region3D],
    initial_heading_xy: tuple[int, int],
) -> GoalCorridorSearchResult:
    path_length = sum(
        (_distance(first, second) for first, second in pairwise(points)),
        0.0,
    )
    integrated_turn = sum(
        (
            _absolute_heading_change(
                (current.x - before.x, current.y - before.y),
                (after.x - current.x, after.y - current.y),
            )
            for before, current, after in zip(
                points,
                points[1:],
                points[2:],
                strict=False,
            )
        ),
        0.0,
    )
    if len(points) >= 2:
        integrated_turn += _absolute_heading_change(
            initial_heading_xy,
            (points[1].x - points[0].x, points[1].y - points[0].y),
        )
    minimum_clearance = min(
        (_clearance(point, obstacles) for point in points),
        default=1_000_000.0,
    )
    payload = {
        "schema_version": 1,
        "planner_id": "bounded-goal-corridor-a-star-v1",
        "disposition": disposition,
        "cell_size_m": 0.05,
        "expansion_limit": expansion_limit,
        "wall_budget_s": float(wall_budget_s),
        "expanded_state_count": expanded_state_count,
        "path_points_m": points,
        "path_length_m": path_length,
        "integrated_absolute_heading_change_rad": integrated_turn,
        "minimum_center_clearance_m": minimum_clearance,
        "obstacle_geometry_sha256": canonical_sha256(
            tuple(
                (
                    region.minimum_m,
                    region.maximum_m,
                )
                for region in obstacles
            )
        ),
    }
    return GoalCorridorSearchResult(
        **payload,
        result_sha256=canonical_sha256(payload),
    )


def _heuristic(first: tuple[int, int], second: tuple[int, int], cell_size_m: float) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1]) * cell_size_m


def _absolute_heading_change(
    first: tuple[int | float, int | float],
    second: tuple[int | float, int | float],
) -> float:
    first_heading = math.atan2(float(first[1]), float(first[0]))
    second_heading = math.atan2(float(second[1]), float(second[0]))
    delta = (second_heading - first_heading + math.pi) % (2.0 * math.pi) - math.pi
    return abs(delta)


def _clearance(point: Vector3, obstacles: Sequence[Region3D]) -> float:
    return min(
        (_distance_to_region_xy(point, obstacle) for obstacle in obstacles),
        default=1_000_000.0,
    )


def _distance_to_region_xy(point: Vector3, region: Region3D) -> float:
    return _distance_to_region_xy_values(point.x, point.y, region)


def _distance_to_region_xy_values(x: float, y: float, region: Region3D) -> float:
    dx = max(region.minimum_m.x - x, 0.0, x - region.maximum_m.x)
    dy = max(region.minimum_m.y - y, 0.0, y - region.maximum_m.y)
    return math.hypot(dx, dy)


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2
        + (first.y - second.y) ** 2
        + (first.z - second.z) ** 2
    )


def _deduplicate_points(points: Sequence[Vector3]) -> tuple[Vector3, ...]:
    output: list[Vector3] = []
    for point in points:
        if not output or _distance(output[-1], point) > 1e-12:
            output.append(point)
    return tuple(output)
