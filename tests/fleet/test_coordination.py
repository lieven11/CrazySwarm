import pytest

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.fleet.coordination import assess_leader_follower


def test_global_frame_leader_follower_setpoint_and_errors_are_backend_neutral() -> None:
    assessment = assess_leader_follower(
        leader_position_m=Vector3(x=0.5, y=-0.25, z=0.3),
        follower_position_m=Vector3(x=0.55, y=0.8, z=0.3),
        expected_offset_m=Vector3(y=1.1),
        leader_velocity_m_s=Vector3(x=0.2),
        follower_velocity_m_s=Vector3(x=0.2, y=0.01),
    )

    assert assessment.expected_follower_position_m.x == pytest.approx(0.5)
    assert assessment.expected_follower_position_m.y == pytest.approx(0.85)
    assert assessment.expected_follower_position_m.z == pytest.approx(0.3)
    assert assessment.observed_offset_m.x == pytest.approx(0.05)
    assert assessment.observed_offset_m.y == pytest.approx(1.05)
    assert assessment.observed_offset_m.z == pytest.approx(0.0)
    assert assessment.relative_velocity_m_s.x == pytest.approx(0.0)
    assert assessment.relative_velocity_m_s.y == pytest.approx(0.01)
    assert assessment.relative_velocity_m_s.z == pytest.approx(0.0)
    assert assessment.tracking_error_m == pytest.approx(2**0.5 * 0.05)
    assert assessment.speed_error_m_s == pytest.approx(0.01)
    assert assessment.separation_m == pytest.approx((0.05**2 + 1.05**2) ** 0.5)
