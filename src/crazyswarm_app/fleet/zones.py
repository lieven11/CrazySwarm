from __future__ import annotations

import math
from enum import StrEnum
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.fleet.artifacts import DeploymentTaskDefinition, ZoneDefinition


class ZoneActionKind(StrEnum):
    TAKEOFF = "TAKEOFF"
    MOVE_TO = "MOVE_TO"
    HOLD = "HOLD"
    LAND = "LAND"


class ZoneObstacle(ContractModel):
    obstacle_id: Identifier
    minimum_m: Vector3
    maximum_m: Vector3


class ZoneAction(ContractModel):
    kind: ZoneActionKind
    target_m: Vector3 | None = None
    duration_s: float = Field(gt=0.0)


class ZoneTaskPlan(ContractModel):
    schema_version: Literal[1] = 1
    task_id: Identifier
    zone_id: Identifier
    actions: tuple[ZoneAction, ...]
    waypoints_m: tuple[Vector3, ...]
    obstacle_aware: bool
    path_length_m: float = Field(ge=0.0)
    estimated_duration_s: float = Field(gt=0.0)
    estimated_energy_percent: float = Field(gt=0.0)
    plan_sha256: SHA256


class ZoneTaskPlanner:
    """Deterministic backend-neutral decomposition for bounded box obstacles."""

    def __init__(
        self,
        *,
        cruise_speed_m_s: float = 0.4,
        safety_margin_m: float = 0.2,
        transit_energy_percent_per_m: float = 1.0,
    ) -> None:
        if cruise_speed_m_s <= 0.0 or safety_margin_m <= 0.0:
            raise ValueError("zone planner parameters must be positive")
        self.cruise_speed_m_s = cruise_speed_m_s
        self.safety_margin_m = safety_margin_m
        self.transit_energy_percent_per_m = transit_energy_percent_per_m

    def plan(
        self,
        task: DeploymentTaskDefinition,
        zone: ZoneDefinition,
        *,
        start_m: Vector3,
        obstacles: tuple[ZoneObstacle, ...] = (),
        flight_height_m: float = 0.3,
    ) -> ZoneTaskPlan:
        if task.zone_id != zone.zone_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "task and zone do not match")
        target = zone.geometry.center_m.model_copy(
            update={"z": max(flight_height_m, zone.geometry.center_m.z)}
        )
        start = start_m.model_copy(update={"z": target.z})
        waypoints: list[Vector3] = [start]
        cursor = start
        obstacle_aware = False
        for obstacle in sorted(obstacles, key=lambda item: item.obstacle_id):
            if not _segment_intersects_box_xy(cursor, target, obstacle, target.z):
                continue
            obstacle_aware = True
            lower_y = obstacle.minimum_m.y - self.safety_margin_m
            upper_y = obstacle.maximum_m.y + self.safety_margin_m
            candidates = (
                (
                    Vector3(x=cursor.x, y=lower_y, z=target.z),
                    Vector3(x=target.x, y=lower_y, z=target.z),
                ),
                (
                    Vector3(x=cursor.x, y=upper_y, z=target.z),
                    Vector3(x=target.x, y=upper_y, z=target.z),
                ),
            )
            selected = min(
                candidates,
                key=lambda pair: (
                    _path_length((cursor, *pair, target)),
                    pair[0].y,
                ),
            )
            waypoints.extend(selected)
            cursor = selected[-1]
        waypoints.append(target)
        compact = tuple(
            point
            for index, point in enumerate(waypoints)
            if index == 0 or point != waypoints[index - 1]
        )
        if any(
            _inside_expanded_box(point, obstacle, 0.0)
            for point in compact
            for obstacle in obstacles
        ):
            raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, "planned waypoint is obstructed")
        path_length = _path_length(compact)
        transit_duration = path_length / self.cruise_speed_m_s
        hold_duration = max(0.1, task.estimated_duration_s - transit_duration - 4.0)
        actions = (
            ZoneAction(kind=ZoneActionKind.TAKEOFF, target_m=compact[0], duration_s=2.0),
            *(
                ZoneAction(
                    kind=ZoneActionKind.MOVE_TO,
                    target_m=point,
                    duration_s=max(
                        0.1,
                        _distance(compact[index - 1], point) / self.cruise_speed_m_s,
                    ),
                )
                for index, point in enumerate(compact[1:], start=1)
            ),
            ZoneAction(kind=ZoneActionKind.HOLD, target_m=target, duration_s=hold_duration),
            ZoneAction(kind=ZoneActionKind.LAND, duration_s=2.0),
        )
        duration = sum(item.duration_s for item in actions)
        energy = max(
            0.01,
            task.estimated_energy_percent + path_length * self.transit_energy_percent_per_m,
        )
        normalized = {
            "task_id": task.task_id,
            "zone_id": zone.zone_id,
            "waypoints": [item.model_dump(mode="json") for item in compact],
            "actions": [item.model_dump(mode="json") for item in actions],
            "obstacle_aware": obstacle_aware,
            "path_length_m": round(path_length, 9),
            "estimated_duration_s": round(duration, 9),
            "estimated_energy_percent": round(energy, 9),
        }
        return ZoneTaskPlan(
            task_id=task.task_id,
            zone_id=zone.zone_id,
            actions=actions,
            waypoints_m=compact,
            obstacle_aware=obstacle_aware,
            path_length_m=path_length,
            estimated_duration_s=duration,
            estimated_energy_percent=energy,
            plan_sha256=canonical_sha256(normalized),
        )


def _segment_intersects_box_xy(
    start: Vector3,
    end: Vector3,
    obstacle: ZoneObstacle,
    height_m: float,
) -> bool:
    if not (obstacle.minimum_m.z <= height_m <= obstacle.maximum_m.z):
        return False
    steps = 200
    for index in range(steps + 1):
        ratio = index / steps
        point = Vector3(
            x=start.x + (end.x - start.x) * ratio,
            y=start.y + (end.y - start.y) * ratio,
            z=height_m,
        )
        if _inside_expanded_box(point, obstacle, 0.0):
            return True
    return False


def _inside_expanded_box(point: Vector3, obstacle: ZoneObstacle, margin_m: float) -> bool:
    return (
        obstacle.minimum_m.x - margin_m <= point.x <= obstacle.maximum_m.x + margin_m
        and obstacle.minimum_m.y - margin_m <= point.y <= obstacle.maximum_m.y + margin_m
        and obstacle.minimum_m.z <= point.z <= obstacle.maximum_m.z
    )


def _path_length(points: tuple[Vector3, ...]) -> float:
    return sum(_distance(points[index - 1], point) for index, point in enumerate(points[1:], 1))


def _distance(first: Vector3, second: Vector3) -> float:
    return math.sqrt(
        (first.x - second.x) ** 2 + (first.y - second.y) ** 2 + (first.z - second.z) ** 2
    )
