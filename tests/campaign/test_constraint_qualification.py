import json
from pathlib import Path

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.qualification import run_constraint_directed_qualification


def test_constraint_directed_causal_matrix_and_retained_artifact_are_current() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()

    report = run_constraint_directed_qualification(catalog)
    retained = json.loads(
        Path(
            "missions/campaigns/sim/qualification/constraint-directed-planning-v1.json"
        ).read_text(encoding="utf-8")
    )

    assert report.passed
    assert len(report.rows) == 9
    assert len(report.geometry_rows) == 6
    assert len(report.dynamic_rows) == 4
    assert all(
        row.passed
        for row in (*report.rows, *report.geometry_rows, *report.dynamic_rows)
    )
    assert retained == report.model_dump(mode="json")

    by_id = {row.row_id: row for row in report.rows}
    assert by_id["bottleneck.simultaneous-vertical"].selected_strategy == "VERTICAL_LAYER"
    assert by_id["bottleneck.simultaneous-no-vertical"].actual_status == "BLOCKED"
    assert by_id["head-on.open-ceiling-vertical"].selected_strategy == "VERTICAL_LAYER"
    assert by_id["merge.flexible-geometry"].selected_strategy == "HORIZONTAL_DETOUR"
    dynamic_by_id = {row.row_id: row for row in report.dynamic_rows}
    object_row = dynamic_by_id["dynamic.obstacle-atomic-cutover"]
    assert object_row.committed_route_count == 2
    assert object_row.qualification_scope == (
        "REAL_CHANGED_WORLD_PLAN_PLUS_COORDINATOR_COMMIT"
    )
    assert object_row.proposal_sha256 is not None
    assert object_row.replacement_world_sha256 is not None
    assert len(object_row.feasibility_certificate_sha256s) == 2
    assert dynamic_by_id["dynamic.peer-atomic-cutover"].committed_route_count == 2
    assert dynamic_by_id["dynamic.peer-atomic-cutover"].qualification_scope == (
        "COORDINATOR_TRANSACTION_ONLY"
    )
    assert (
        dynamic_by_id["dynamic.obstacle-late-fallback"].actual_disposition
        == "BLOCKED_REACTION_HORIZON"
    )
    assert (
        dynamic_by_id["dynamic.peer-partial-ack-zero-commit"].committed_route_count
        == 0
    )
