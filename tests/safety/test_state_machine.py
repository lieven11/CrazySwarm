from __future__ import annotations

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import VehicleState
from crazyswarm_app.safety.state_machine import (
    ALLOWED_TRANSITIONS,
    can_transition,
    require_transition,
)


@pytest.mark.parametrize("current", list(VehicleState))
@pytest.mark.parametrize("target", list(VehicleState))
def test_every_state_pair_is_explicit(current: VehicleState, target: VehicleState) -> None:
    expected = current is target or target in ALLOWED_TRANSITIONS[current]
    assert can_transition(current, target) is expected
    if expected:
        require_transition(current, target)
    else:
        with pytest.raises(CrazySwarmError):
            require_transition(current, target)
