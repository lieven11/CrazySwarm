from __future__ import annotations

import json
from pathlib import Path

import pytest

from crazyswarm_app.campaign.analyzer import analyze_execution
from crazyswarm_app.campaign.catalog import CampaignCatalog

REVIEWED_BOTTLENECK_RUN = Path(
    "run-files/"
    "20260811T165412Z_Campaign_2d.bottleneck.canonical_nominal_"
    "campaign-run-c89c7b645810ffc542a2"
)


def test_reviewed_bottleneck_preserves_raw_processed_disagreement_and_role_targets() -> None:
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    catalog.discover()
    case = catalog.get("2d.bottleneck.canonical_nominal")
    manifest = json.loads((REVIEWED_BOTTLENECK_RUN / "manifest.json").read_text())
    bundle_path = next(REVIEWED_BOTTLENECK_RUN.glob("*execution-bundle-v1.json"))
    csv_path = next(REVIEWED_BOTTLENECK_RUN.glob("*telemetry-v1.csv"))
    analysis = analyze_execution(
        case=case,
        manifest=manifest,
        bundle=json.loads(bundle_path.read_text()),
        csv_bytes=csv_path.read_bytes(),
    )

    beta = next(vehicle for vehicle in analysis.vehicles if vehicle.vehicle_id == "Beta")
    gate = beta.kinematics_gate_reconciliation
    assert gate.raw_vertical_speed_peak_m_s == pytest.approx(0.740979, abs=1e-6)
    assert gate.processed_vertical_speed_peak_m_s == pytest.approx(0.01169, abs=1e-4)
    assert gate.raw_gate_passed is False
    assert gate.processed_gate_passed is True
    assert gate.gate_disagreement is True

    drones_by_role = {drone.role_id: drone for drone in case.drones}
    for landing in analysis.landing:
        assert landing.accepted_landing_center_m == drones_by_role[
            landing.vehicle_id
        ].landing_region.center_m
        assert landing.coordinate_conversion_chain
