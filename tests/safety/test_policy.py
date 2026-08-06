from __future__ import annotations

import pytest

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.safety.policy import FlightVolume, SafetyPolicy, SafetyPolicyOverride


def test_policy_can_only_be_tightened() -> None:
    policy = SafetyPolicy()
    tightened = policy.tighten(
        SafetyPolicyOverride(
            max_altitude_m=0.8,
            minimum_takeoff_battery_percent=40.0,
            flight_volume=FlightVolume(
                minimum_m=Vector3(x=-1.0, y=-1.0, z=0.0),
                maximum_m=Vector3(x=1.0, y=1.0, z=0.8),
            ),
        )
    )
    assert tightened.max_altitude_m == 0.8
    assert tightened.minimum_takeoff_battery_percent == 40.0


@pytest.mark.parametrize(
    "override",
    [
        SafetyPolicyOverride(max_altitude_m=1.2),
        SafetyPolicyOverride(minimum_link_quality_percent=50.0),
        SafetyPolicyOverride(
            flight_volume=FlightVolume(
                minimum_m=Vector3(x=-3.0, y=-1.0, z=0.0),
                maximum_m=Vector3(x=1.0, y=1.0, z=0.8),
            )
        ),
    ],
)
def test_policy_rejects_relaxation(override: SafetyPolicyOverride) -> None:
    with pytest.raises(ValueError, match="relax"):
        SafetyPolicy().tighten(override)
