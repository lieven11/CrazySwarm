from __future__ import annotations

import hashlib
import json
from pathlib import Path

from crazyswarm_app.domain.simulation import VehicleParameterSchema
from crazyswarm_app.isaac.host_qualification import (
    CompatibilityCheckerEvidence,
    CompatibilityCheckerStatus,
    HostGateDecision,
    HostMeasurementClass,
    evaluate_isaac_host,
    load_host_inventory,
    load_official_requirements,
)
from crazyswarm_app.isaac.scaffold import render_minimal_usda
from crazyswarm_app.isaac.scene import load_isaac_scene
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.physics import PhysicsModelConfig

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = ROOT / "config" / "isaac" / "official-requirements-6.0.1-v1.json"
REPORTED_PATH = ROOT / "config" / "isaac" / "victus-reported-precheck-v1.json"
SCENE_PATH = ROOT / "config" / "isaac" / "minimal-one-vehicle-scene-v1.json"
ASSET_DIRECTORY = ROOT / "assets" / "isaac"


def _legacy_parameters() -> VehicleParameterSchema:
    return SimulationConfig(physics=PhysicsModelConfig.legacy_v1()).vehicle_parameters()


def test_reported_victus_precheck_defers_before_install() -> None:
    requirements = load_official_requirements(REQUIREMENTS_PATH)
    inventory = load_host_inventory(REPORTED_PATH)
    report = evaluate_isaac_host(inventory, requirements)

    assert report.classification == "REPORTED_PRECHECK_NOT_LIVE_EVIDENCE"
    assert report.decision is HostGateDecision.DEFER_RESOURCE_LIMIT
    assert not report.compatible
    assert not report.headless_gateway_authorized
    assert report.isaac_runtime_version == "NOT_PINNED_RESOURCE_GATE_NOT_GO"
    failed = {finding.check for finding in report.findings if not finding.passed}
    assert {"SYSTEM_RAM_BYTES", "VRAM_BYTES", "OFFICIAL_COMPATIBILITY_CHECKER"} <= failed


def test_go_requires_measured_host_and_passing_official_checker() -> None:
    requirements = load_official_requirements(REQUIREMENTS_PATH)
    inventory = load_host_inventory(REPORTED_PATH).model_copy(
        update={
            "measurement_class": HostMeasurementClass.MEASURED_HOST,
            "physical_cpu_cores": 8,
            "system_ram_bytes": requirements.minimum_system_ram_bytes,
            "gpu": requirements.minimum_gpu,
            "vram_bytes": requirements.minimum_vram_bytes,
            "driver_version": requirements.tested_windows_driver,
            "free_storage_bytes": requirements.minimum_free_storage_bytes,
            "official_checker": CompatibilityCheckerEvidence(
                status=CompatibilityCheckerStatus.PASSED,
                package_version="6.0.1",
                command="isaac-sim.compatibility_check.bat --/app/quitAfter=10 --no-window",
                exit_code=0,
                report_path="C:/evidence/isaac-checker.log",
            ),
        }
    )

    report = evaluate_isaac_host(inventory, requirements)
    assert report.decision is HostGateDecision.GO_MINIMAL_EXPERIMENT
    assert report.compatible
    assert report.headless_gateway_authorized

    waiting = inventory.model_copy(update={"official_checker": CompatibilityCheckerEvidence()})
    assert (
        evaluate_isaac_host(waiting, requirements).decision
        is HostGateDecision.WAITING_FOR_MEASURED_HOST_AND_CHECKER
    )


def test_usd_scaffold_is_single_vehicle_unqualified_and_bounded() -> None:
    parameters = _legacy_parameters()
    scene = load_isaac_scene(SCENE_PATH, vehicle_parameters=parameters)
    empty_stage = render_minimal_usda(scene, parameters, include_environment=False)
    room_stage = render_minimal_usda(scene, parameters, include_environment=True)

    assert empty_stage.count('def Xform "cf01"') == 1
    assert empty_stage.count('def Cylinder "Rotor_') == 4
    assert empty_stage.count('custom string crazyswarm:signal = "') == 8
    assert 'def Scope "Environment"' not in empty_stage
    assert 'def Scope "Environment"' in room_stage
    assert room_stage.count("CONFIGURED_UNQUALIFIED") >= 10
    assert "custom bool crazyswarm:physicalModelAuthorized = false" in room_stage
    assert "custom bool crazyswarm:digitalTwinEnabled = false" in room_stage
    assert "Camera" not in room_stage
    assert "RTX" not in room_stage


def test_generated_scaffold_manifest_remains_not_run_and_hashes_match() -> None:
    manifest = json.loads((ASSET_DIRECTORY / "scaffold-manifest-v1.json").read_text())
    assert manifest["qualification"] == "CONFIGURED_UNQUALIFIED"
    assert manifest["isaac_runtime_result"] == "NOT_RUN"
    assert manifest["maximum_vehicles"] == 1
    assert not manifest["physical_model_authorized"]
    assert not manifest["digital_twin_enabled"]

    parameters = _legacy_parameters()
    scene = load_isaac_scene(SCENE_PATH, vehicle_parameters=parameters)
    expected = {
        "primitive_drone_empty_scene": render_minimal_usda(
            scene, parameters, include_environment=False
        ),
        "primitive_drone_minimal_room": render_minimal_usda(
            scene, parameters, include_environment=True
        ),
    }
    for name, rendered in expected.items():
        path = ROOT / manifest["artifacts"][name]["path"]
        assert path.read_text(encoding="utf-8") == rendered
        assert (
            hashlib.sha256(path.read_bytes()).hexdigest() == manifest["artifacts"][name]["sha256"]
        )
