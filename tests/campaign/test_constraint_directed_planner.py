from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import PlannerStrategy
from crazyswarm_app.campaign.planner import (
    BoundedJointPlanner,
    PlanningStatus,
    SearchDisposition,
)
from crazyswarm_app.campaign.submissions import resolve_planning_submission


@pytest.fixture(scope="module")
def catalog() -> CampaignCatalog:
    value = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    value.discover()
    return value


@pytest.mark.parametrize(
    ("case_id", "submission_id", "expected_strategy"),
    [
        (
            "2d.bottleneck.canonical_nominal",
            "constraint_directed.bottleneck.simultaneous_vertical",
            PlannerStrategy.VERTICAL_LAYER,
        ),
        (
            "2d.head_on_conflict.canonical_nominal",
            "constraint_directed.head_on.same_path",
            PlannerStrategy.HORIZONTAL_DETOUR,
        ),
        (
            "2d.merge.canonical_nominal",
            "constraint_directed.merge.flexible_geometry",
            PlannerStrategy.HORIZONTAL_DETOUR,
        ),
    ],
)
def test_constraint_directed_cases_select_independently_certified_plan(
    catalog: CampaignCatalog,
    case_id: str,
    submission_id: str,
    expected_strategy: PlannerStrategy,
) -> None:
    case = catalog.get(case_id)
    submission = resolve_planning_submission(case, submission_id)

    result = BoundedJointPlanner().plan(case, planning_submission=submission)

    assert result.status is PlanningStatus.READY
    assert result.search_disposition is SearchDisposition.SELECTED
    assert result.bounded_search_complete
    assert result.selected is not None
    assert result.selected.strategy is expected_strategy
    assert result.feasibility_certificate is not None
    assert result.feasibility_certificate.passed
    assert result.feasibility_certificate.candidate_sha256 == result.selected_candidate_sha256
    assert result.representative_candidate_sha256s[0] == result.selected_candidate_sha256


def test_budget_exhaustion_has_no_execution_authority_or_feasibility_claim(
    catalog: CampaignCatalog,
) -> None:
    source = catalog.get("2d.merge.canonical_nominal")
    case = source.model_copy(
        update={
            "case_id": "2d.merge.planning-budget-regression",
            "search": source.search.model_copy(update={"planning_budget_s": 0.000001}),
        }
    )

    result = BoundedJointPlanner().plan(case)

    assert result.status is PlanningStatus.BLOCKED
    assert result.search_disposition is SearchDisposition.BUDGET_EXHAUSTED
    assert not result.bounded_search_complete
    assert result.selected is None
    assert result.feasibility_certificate is None
    assert result.optimality_claim == "no feasibility or optimality claim"


def test_continuous_release_boundary_is_generated_for_timing_authority(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("2d.merge.canonical_nominal")

    result = BoundedJointPlanner().plan(case)

    continuous = tuple(
        candidate
        for candidate in result.retained_candidates
        if candidate.generator_id == "continuous-ground-release-v1"
    )
    assert continuous
    assert all(candidate.parameters["solver"] == "BRACKETED_BISECTION" for candidate in continuous)
