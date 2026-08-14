from pathlib import Path

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import MotionQualityMetric, MotionSpeedLaw, motion_contract_for
from crazyswarm_app.campaign.planner import BoundedJointPlanner
from crazyswarm_app.campaign.submissions import (
    motion_contract_for_execution_profile,
    resolve_submission,
)
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.simulation import canonical_sha256


def test_motion_contract_reaches_plan_and_trajectory_authority() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.continuous_waypoint_sequence.canonical_nominal")
    plan = BoundedJointPlanner().plan(case)
    assert plan.selected is not None
    trajectories = generate_smooth_trajectories(case, plan.selected)
    contract = motion_contract_for(case)
    assert plan.motion_quality_contract == contract
    assert trajectories.motion_quality_contract == contract
    assert plan.motion_quality_contract_sha256 == canonical_sha256(contract)
    assert trajectories.motion_quality_contract_sha256 == canonical_sha256(contract)


def test_selected_smooth_profile_reaches_plan_and_trajectory_authority() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("1d.continuous_waypoint_sequence.canonical_nominal")
    profile = resolve_submission(case, "waypoint.smoothness_first")
    contract = motion_contract_for_execution_profile(case, profile)

    plan = BoundedJointPlanner().plan(case, profile)
    assert plan.selected is not None
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=profile,
    )

    assert contract.speed_law is MotionSpeedLaw.CONSTANT
    assert contract.target_speed_m_s == profile.parameters.target_path_speed_m_s
    assert contract.objective_order[0] is MotionQualityMetric.JERK
    assert (
        contract.maximum_electrical_energy_used_j
        == motion_contract_for(case).maximum_electrical_energy_used_j
    )
    assert plan.motion_quality_contract == contract
    assert trajectories.motion_quality_contract == contract
    assert plan.motion_quality_contract_sha256 == canonical_sha256(contract)
    assert trajectories.motion_quality_contract_sha256 == canonical_sha256(contract)
