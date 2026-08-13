from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.geometry import (
    ClearanceDisposition,
    SolidGeometry,
    StructuredWorld,
    TraversableGeometry,
    assess_contact,
    certify_candidate_routes,
    structured_world_from_case,
    validate_structured_world,
)
from crazyswarm_app.campaign.models import Region3D
from crazyswarm_app.campaign.planner import _direct_routes
from crazyswarm_app.campaign.submissions import (
    ClearancePolicy,
    resolve_planning_submission,
)
from crazyswarm_app.domain.models import Vector3


@pytest.fixture(scope="module")
def catalog() -> CampaignCatalog:
    value = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    value.discover()
    return value


def _region(
    region_id: str,
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
) -> Region3D:
    return Region3D(
        region_id=region_id,
        minimum_m=Vector3(x=minimum[0], y=minimum[1], z=minimum[2]),
        maximum_m=Vector3(x=maximum[0], y=maximum[1], z=maximum[2]),
    )


def test_contact_and_protected_clearance_are_different_policy_layers() -> None:
    policy = ClearancePolicy(
        required_pairwise_center_separation_m=0.8,
        contact_allowed_role_ids=("Alpha",),
        contact_target_ids=("landing-pad",),
    )

    protected_breach = assess_contact(
        role_id="Alpha",
        target_id="landing-pad",
        signed_nominal_clearance_m=0.04,
        policy=policy,
    )
    authorized_contact = assess_contact(
        role_id="Alpha",
        target_id="landing-pad",
        signed_nominal_clearance_m=-0.001,
        policy=policy,
    )
    prohibited_contact = assess_contact(
        role_id="Beta",
        target_id="landing-pad",
        signed_nominal_clearance_m=-0.001,
        policy=policy,
    )

    assert protected_breach.disposition is ClearanceDisposition.PROTECTED_CLEARANCE_BREACH
    assert authorized_contact.disposition is ClearanceDisposition.PHYSICAL_CONTACT_AUTHORIZED
    assert prohibited_contact.disposition is ClearanceDisposition.PHYSICAL_CONTACT_PROHIBITED


def test_world_rejects_solid_free_space_contradiction_and_small_passage() -> None:
    volume = _region("volume", (-2.0, -2.0, 0.0), (2.0, 2.0, 2.0))
    solid = SolidGeometry(
        solid_id="wall",
        bounds=_region("wall", (-0.2, -1.0, 0.0), (0.2, 1.0, 2.0)),
    )
    passage = TraversableGeometry(
        passage_id="slot",
        bounds=_region("slot", (-0.1, -1.0, 0.5), (0.1, 1.0, 0.65)),
    )
    world = StructuredWorld(
        flight_volume=volume,
        solids=(solid,),
        traversable_passages=(passage,),
        world_sha256="0" * 64,
    )

    report = validate_structured_world(
        world,
        ClearancePolicy(required_pairwise_center_separation_m=0.8),
    )

    assert not report.valid
    assert "SOLID_FREE_SPACE_CONTRADICTION:wall:slot" in report.contradictions
    assert "PASSAGE_TOO_SMALL:slot" in report.contradictions
    assert not report.passage_capacities[0].passable


def test_continuous_verifier_catches_head_on_crossing_between_samples(
    catalog: CampaignCatalog,
) -> None:
    case = catalog.get("2d.head_on_conflict.canonical_nominal")
    submission = resolve_planning_submission(
        case,
        "constraint_directed.head_on.same_path",
    )
    routes = _direct_routes(case)

    certificate = certify_candidate_routes(case, submission, "1" * 64, routes)

    assert not certificate.passed
    assert certificate.minimum_pairwise_nominal_clearance_m < 0.0
    assert "PAIRWISE_PROTECTED_CLEARANCE_VIOLATION" in certificate.violations
    assert certificate.certificate_sha256 != "0" * 64


def test_case_world_conversion_preserves_named_solids(catalog: CampaignCatalog) -> None:
    case = catalog.get("2d.bottleneck.canonical_nominal")
    world = structured_world_from_case(case)

    assert {solid.solid_id for solid in world.solids} == {
        region.region_id
        for region in case.semantics.environment_constraints.keep_out_regions
    }
