from crazyswarm_app.campaign.models import MotionQualityContract, RouteNodeMode
from crazyswarm_app.campaign.route_horizon import compile_route_horizon
from crazyswarm_app.domain.models import Vector3


def test_normalization_removes_only_collinear_sampling_knots() -> None:
    horizon = compile_route_horizon(
        (
            Vector3(),
            Vector3(x=0.2),
            Vector3(x=0.4),
            Vector3(x=0.4, y=0.2),
        ),
        (
            RouteNodeMode.CAPTURE,
            RouteNodeMode.FLY_THROUGH,
            RouteNodeMode.FLY_THROUGH,
            RouteNodeMode.CAPTURE,
        ),
        MotionQualityContract(target_speed_m_s=0.3),
        maximum_speed_m_s=0.6,
        maximum_acceleration_m_s2=1.0,
    )
    assert len(horizon.nodes) == 3
    assert horizon.nodes[0].authored_indices == (0, 1)
    assert horizon.nodes[1].position_m == Vector3(x=0.4)


def test_repeated_coordinate_remains_distinct_path_state() -> None:
    crossing = Vector3(x=0.2, y=0.2)
    horizon = compile_route_horizon(
        (
            Vector3(),
            crossing,
            Vector3(x=0.4),
            crossing,
            Vector3(y=0.4),
        ),
        (RouteNodeMode.CAPTURE, *(RouteNodeMode.FLY_THROUGH,) * 3, RouteNodeMode.CAPTURE),
        MotionQualityContract(target_speed_m_s=0.25),
        maximum_speed_m_s=0.6,
        maximum_acceleration_m_s2=1.0,
    )
    repeated = [node for node in horizon.nodes if node.position_m == crossing]
    assert len(repeated) == 2
    assert all(node.repeated_coordinate for node in repeated)
    assert repeated[0].path_state_index != repeated[1].path_state_index
