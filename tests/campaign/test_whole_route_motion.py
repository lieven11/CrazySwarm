from pathlib import Path

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.planner import BoundedJointPlanner, PlanningStatus
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories


def test_figure_eight_is_one_continuous_route_with_two_crossover_states() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.planar_shape_loop.figure_eight")
    plan = BoundedJointPlanner().plan(case)
    assert plan.status is PlanningStatus.READY
    assert plan.selected is not None
    trajectories = generate_smooth_trajectories(case, plan.selected)
    trajectory = trajectories.trajectories[0]
    crossing = case.drones[0].goal_sequence[0].center_m
    crossing_points = [
        point for point in trajectory.points if point.position_m == crossing
    ]
    assert len(crossing_points) >= 2
    assert all(
        (point.velocity_m_s.x**2 + point.velocity_m_s.y**2 + point.velocity_m_s.z**2)
        ** 0.5
        > 0.0
        for point in crossing_points[1:]
    )
    assert case.motion_contract_for("Alpha").minimum_continuous_knot_speed_ratio == 0.95
    assert trajectories.audits[0].generated_unintended_stop_count == 0
