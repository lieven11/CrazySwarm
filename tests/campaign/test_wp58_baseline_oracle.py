import json
from pathlib import Path


def test_predraft_comparisons_require_every_declared_metric() -> None:
    payload = json.loads(
        Path(
            "missions/campaigns/sim/qualification/wp57-61-predraft-1d-evidence-v1.json"
        ).read_text(encoding="utf-8")
    )
    comparisons = payload["design_set_audit"]["comparisons"]
    assert comparisons
    for comparison in comparisons:
        assert comparison["same_case"] is True
        assert comparison["same_clock_mode"] is True
        assert comparison["missing_run_ids"] == []
        assert comparison["missing_metrics_by_run_id"] == {}
        assert set(comparison["metrics"]) == set(comparison["metric_dispositions"])
        assert comparison["passed"] is True


def test_terminal_peak_comparator_has_literal_source_values() -> None:
    payload = json.loads(
        Path(
            "missions/campaigns/sim/qualification/wp57-61-predraft-1d-evidence-v1.json"
        ).read_text(encoding="utf-8")
    )
    terminal = next(
        item
        for item in payload["design_set_audit"]["comparisons"]
        if "terminal_secondary_speed_peak_count" in item["metrics"]
    )
    assert all(
        values["terminal_secondary_speed_peak_count"] is not None
        for values in terminal["metric_values_by_run_id"].values()
    )
