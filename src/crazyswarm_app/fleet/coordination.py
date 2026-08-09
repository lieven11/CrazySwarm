from __future__ import annotations

import math
from dataclasses import dataclass

from crazyswarm_app.domain.models import Vector3


@dataclass(frozen=True, slots=True)
class LeaderFollowerAssessment:
    """Backend-neutral formation setpoint and tracking-error evaluation."""

    expected_follower_position_m: Vector3
    observed_offset_m: Vector3
    relative_velocity_m_s: Vector3
    tracking_error_m: float
    speed_error_m_s: float
    separation_m: float


def assess_leader_follower(
    *,
    leader_position_m: Vector3,
    follower_position_m: Vector3,
    expected_offset_m: Vector3,
    leader_velocity_m_s: Vector3 | None,
    follower_velocity_m_s: Vector3 | None,
) -> LeaderFollowerAssessment:
    """Evaluate one global-frame follower setpoint without accessing an adapter."""

    expected_follower_position = _add(leader_position_m, expected_offset_m)
    observed_offset = _subtract(follower_position_m, leader_position_m)
    relative_velocity = _subtract(
        follower_velocity_m_s or Vector3(),
        leader_velocity_m_s or Vector3(),
    )
    return LeaderFollowerAssessment(
        expected_follower_position_m=expected_follower_position,
        observed_offset_m=observed_offset,
        relative_velocity_m_s=relative_velocity,
        tracking_error_m=_distance(follower_position_m, expected_follower_position),
        speed_error_m_s=_length(relative_velocity),
        separation_m=_distance(leader_position_m, follower_position_m),
    )


def _add(first: Vector3, second: Vector3) -> Vector3:
    return Vector3(
        x=first.x + second.x,
        y=first.y + second.y,
        z=first.z + second.z,
    )


def _subtract(first: Vector3, second: Vector3) -> Vector3:
    return Vector3(
        x=first.x - second.x,
        y=first.y - second.y,
        z=first.z - second.z,
    )


def _length(value: Vector3) -> float:
    return math.sqrt(value.x**2 + value.y**2 + value.z**2)


def _distance(first: Vector3, second: Vector3) -> float:
    return _length(_subtract(first, second))
