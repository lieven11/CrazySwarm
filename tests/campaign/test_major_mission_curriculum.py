from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import Region3D
from crazyswarm_app.campaign.planner import BoundedJointPlanner, PlanningStatus
from crazyswarm_app.campaign.submissions import (
    MotionPreparationRequest,
    motion_preparation_limits_for_case,
    resolve_planning_package,
)
from crazyswarm_app.domain.models import Vector3

ROOT = Path("missions/campaigns/sim/cases")
CURRICULUM = Path("missions/campaigns/sim/curriculum/1d-major-missions-v1.yaml")
TWO_DRONE_CURRICULUM = Path("missions/campaigns/sim/curriculum/2d-conflict-missions-v1.yaml")


@pytest.fixture(scope="module")
def catalog() -> CampaignCatalog:
    value = CampaignCatalog(ROOT)
    value.discover()
    return value


def test_major_mission_registry_has_exact_five_group_twelve_case_coverage(
    catalog: CampaignCatalog,
) -> None:
    curriculum = catalog.major_mission_curriculum()
    assert curriculum.curriculum_id == "1d-major-missions-v1"
    assert tuple(group.label for group in curriculum.groups) == (
        "Flight",
        "Target",
        "Level path",
        "3D path",
        "Shape",
    )
    executable = tuple(
        variant.case_id
        for group in curriculum.groups
        for variant in group.variants
        if variant.status.value == "EXECUTABLE"
    )
    assert len(executable) == len(set(executable)) == 12
    wind = tuple(
        variant
        for group in curriculum.groups
        for variant in group.variants
        if variant.status.value == "PLANNED_NOT_EXECUTABLE"
    )
    assert len(wind) == 1
    assert wind[0].label == "Wind shift"
    assert wind[0].disabled_reason


def test_major_mission_registry_is_independent_of_catalog_source_order(
    catalog: CampaignCatalog,
) -> None:
    expected = catalog.major_mission_curriculum()
    catalog._entries = dict(reversed(tuple(catalog._entries.items())))
    assert catalog.major_mission_curriculum() == expected


def test_major_mission_registry_rejects_a_renamed_unknown_case(
    catalog: CampaignCatalog,
    tmp_path: Path,
) -> None:
    raw = yaml.safe_load(CURRICULUM.read_text(encoding="utf-8"))
    raw["groups"][0]["variants"][0]["case_id"] = "1d.takeoff_hover_land.renamed"
    changed = tmp_path / "curriculum.yaml"
    changed.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="coverage mismatch"):
        catalog.major_mission_curriculum(changed)


def test_two_drone_registry_has_distinct_five_group_full_case_coverage(
    catalog: CampaignCatalog,
) -> None:
    curriculum = catalog.two_drone_mission_curriculum()
    assert tuple(group.label for group in curriculum.groups) == (
        "Crossing",
        "Traffic",
        "Merge",
        "Coordination",
        "Recovery",
    )
    registered = tuple(variant.case_id for group in curriculum.groups for variant in group.variants)
    discovered = {
        case.case_id
        for case in catalog.cases()
        if case.environment.value == "SIMULATION" and case.drone_count == 2
    }
    assert len(registered) == len(set(registered)) == 18
    assert set(registered) == discovered

    crossing = next(group for group in curriculum.groups if group.label == "Crossing")
    assert {variant.case_id for variant in crossing.variants} == {
        "2d.perpendicular_crossing.nominal_equal_priority",
        "2d.unequal_priority.canonical_nominal",
        "2d.no_hover_crossing.canonical_nominal",
        "2d.constrained_border_height.canonical_nominal",
    }


def test_two_drone_registry_is_independent_of_catalog_source_order(
    catalog: CampaignCatalog,
) -> None:
    expected = catalog.two_drone_mission_curriculum()
    catalog._entries = dict(reversed(tuple(catalog._entries.items())))
    assert catalog.two_drone_mission_curriculum() == expected


def test_two_drone_registry_rejects_duplicate_or_unknown_case(
    catalog: CampaignCatalog,
    tmp_path: Path,
) -> None:
    raw = yaml.safe_load(TWO_DRONE_CURRICULUM.read_text(encoding="utf-8"))
    raw["groups"][1]["variants"][0]["case_id"] = raw["groups"][0]["variants"][0]["case_id"]
    changed = tmp_path / "2d-curriculum.yaml"
    changed.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly once"):
        catalog.two_drone_mission_curriculum(changed)


@pytest.mark.parametrize(
    "case_id",
    (
        "1d.takeoff_hover_land.canonical_nominal",
        "1d.curved_route.canonical_nominal",
        "1d.planar_shape_loop.figure_eight",
    ),
)
def test_plain_motion_controls_retain_requests_and_cap_hard_bounds(
    catalog: CampaignCatalog,
    case_id: str,
) -> None:
    case = catalog.get(case_id)
    low = resolve_planning_package(
        case,
        motion_preparation_request=MotionPreparationRequest(balance=0),
    ).motion_preparation
    middle = resolve_planning_package(
        case,
        motion_preparation_request=MotionPreparationRequest(balance=50),
    ).motion_preparation
    high = resolve_planning_package(
        case,
        motion_preparation_request=MotionPreparationRequest(
            balance=100,
            speed_m_s=0.5,
            accuracy_m=100.0,
            smoothness=0,
        ),
    ).motion_preparation
    assert low is not None and middle is not None and high is not None
    low_controls = {item.label: item for item in low.controls}
    middle_controls = {item.label: item for item in middle.controls}
    high_controls = {item.label: item for item in high.controls}
    assert low_controls["Speed"].resolved_value <= middle_controls["Speed"].resolved_value
    assert middle_controls["Speed"].resolved_value <= high_controls["Speed"].resolved_value
    assert low_controls["Accuracy"].resolved_value <= middle_controls["Accuracy"].resolved_value
    assert middle_controls["Accuracy"].resolved_value <= high_controls["Accuracy"].resolved_value
    assert high_controls["Accuracy"].requested_value == 100.0
    motion_limits = motion_preparation_limits_for_case(case)
    assert high_controls["Accuracy"].resolved_value == pytest.approx(motion_limits.accuracy_max_m)
    assert high_controls["Accuracy"].binding_safety_cap == (
        f"{motion_limits.accuracy_binding} {motion_limits.accuracy_max_m:.3f} m"
    )
    assert (
        high.motion_quality_contract.maximum_path_tube_error_m
        == high_controls["Accuracy"].resolved_value
    )


def test_fly_through_accuracy_can_span_the_room_while_multi_goal_stays_checkpoint_bound(
    catalog: CampaignCatalog,
) -> None:
    continuous = motion_preparation_limits_for_case(
        catalog.get("1d.continuous_waypoint_sequence.canonical_nominal")
    )
    curved = motion_preparation_limits_for_case(catalog.get("1d.curved_route.canonical_nominal"))
    spatial = motion_preparation_limits_for_case(
        catalog.get("1d.altitude_transition.canonical_nominal")
    )
    multi_goal = motion_preparation_limits_for_case(
        catalog.get("1d.static_multi_goal_sequence.canonical_nominal")
    )

    for limits in (continuous, curved, spatial):
        assert limits.accuracy_max_m > 4.0
        assert limits.accuracy_binding == "flight-volume route span"
    assert multi_goal.accuracy_max_m == pytest.approx(0.08)
    assert multi_goal.accuracy_binding == "mission goal tolerance"

    flow_package = resolve_planning_package(
        catalog.get("1d.continuous_waypoint_sequence.canonical_nominal"),
        motion_preparation_request=MotionPreparationRequest(balance=100),
    )
    assert flow_package.motion_preparation is not None
    flow_accuracy = next(
        control
        for control in flow_package.motion_preparation.controls
        if control.label == "Accuracy"
    )
    assert flow_accuracy.resolved_value == pytest.approx(continuous.accuracy_max_m)


def test_hundred_metre_accuracy_never_authorizes_an_obstacle_intersection(
    catalog: CampaignCatalog,
) -> None:
    source = catalog.get("1d.curved_route.canonical_nominal")
    assert source.semantics is not None
    obstacle = Region3D(
        region_id="global-shortcut-blocker",
        minimum_m=Vector3(x=0.55, y=0.31, z=0.25),
        maximum_m=Vector3(x=0.65, y=0.41, z=0.55),
    )
    constrained = source.model_copy(
        update={
            "case_id": "1d.curved_route.hundred-metre-obstacle-boundary",
            "parent_case_sha256": source.case_sha256,
            "semantics": source.semantics.model_copy(
                update={
                    "environment_constraints": (
                        source.semantics.environment_constraints.model_copy(
                            update={"keep_out_regions": (obstacle,)}
                        )
                    )
                }
            ),
        }
    )
    package = resolve_planning_package(
        constrained,
        motion_preparation_request=MotionPreparationRequest(
            balance=100,
            accuracy_m=100.0,
            smoothness=0,
        ),
    )
    plan = BoundedJointPlanner().plan(
        constrained,
        package.execution_profile,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
    )

    # The direct start-to-goal shortcut crosses the obstacle at x=.6, y=.36,
    # but Accuracy remains a soft route preference. The independent solid oracle
    # must still certify every selected trajectory against the immutable obstacle.
    assert obstacle.minimum_m.y <= 0.36 <= obstacle.maximum_m.y
    assert plan.status is PlanningStatus.READY
    assert plan.feasibility_certificate is not None
    assert plan.feasibility_certificate.passed
    assert plan.feasibility_certificate.minimum_solid_protected_clearance_m >= 0.0


def test_plain_motion_accuracy_falls_back_to_goal_region_dimensions(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("three_drone_multi_conflict")
    assert case.semantics is None
    preparation = resolve_planning_package(
        case,
        motion_preparation_request=MotionPreparationRequest(accuracy_m=100.0),
    ).motion_preparation

    assert preparation is not None
    accuracy = next(item for item in preparation.controls if item.label == "Accuracy")
    assert accuracy.resolved_value == pytest.approx(0.05)
    assert accuracy.binding_safety_cap == "mission goal dimensions 0.050 m"
