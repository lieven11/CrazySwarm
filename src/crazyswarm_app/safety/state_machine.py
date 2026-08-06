from __future__ import annotations

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import VehicleState

ALLOWED_TRANSITIONS: dict[VehicleState, frozenset[VehicleState]] = {
    VehicleState.DISCONNECTED: frozenset({VehicleState.CONNECTING}),
    VehicleState.CONNECTING: frozenset(
        {VehicleState.READY, VehicleState.DISCONNECTED, VehicleState.FAULT}
    ),
    VehicleState.READY: frozenset(
        {
            VehicleState.ARMING,
            VehicleState.TAKING_OFF,
            VehicleState.DISCONNECTED,
            VehicleState.FAULT,
            VehicleState.EMERGENCY,
        }
    ),
    VehicleState.ARMING: frozenset(
        {VehicleState.READY, VehicleState.FAULT, VehicleState.EMERGENCY}
    ),
    VehicleState.TAKING_OFF: frozenset(
        {
            VehicleState.FLYING,
            VehicleState.LANDING,
            VehicleState.ABORTING,
            VehicleState.FAULT,
            VehicleState.EMERGENCY,
        }
    ),
    VehicleState.FLYING: frozenset(
        {
            VehicleState.RETURNING,
            VehicleState.LANDING,
            VehicleState.ABORTING,
            VehicleState.FAULT,
            VehicleState.EMERGENCY,
        }
    ),
    VehicleState.RETURNING: frozenset(
        {
            VehicleState.FLYING,
            VehicleState.LANDING,
            VehicleState.ABORTING,
            VehicleState.FAULT,
            VehicleState.EMERGENCY,
        }
    ),
    VehicleState.LANDING: frozenset(
        {VehicleState.READY, VehicleState.FAULT, VehicleState.EMERGENCY}
    ),
    VehicleState.ABORTING: frozenset(
        {
            VehicleState.LANDING,
            VehicleState.READY,
            VehicleState.FAULT,
            VehicleState.EMERGENCY,
        }
    ),
    VehicleState.FAULT: frozenset(
        {VehicleState.READY, VehicleState.DISCONNECTED, VehicleState.EMERGENCY}
    ),
    VehicleState.EMERGENCY: frozenset({VehicleState.DISCONNECTED}),
}


def can_transition(current: VehicleState, target: VehicleState) -> bool:
    return current is target or target in ALLOWED_TRANSITIONS[current]


def require_transition(current: VehicleState, target: VehicleState) -> None:
    if not can_transition(current, target):
        raise CrazySwarmError(
            ErrorCode.INVALID_STATE,
            f"transition {current.value} -> {target.value} is not permitted",
        )
