#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from crazyswarm_app.isaac.scaffold import QUALIFICATION, render_minimal_usda
from crazyswarm_app.isaac.scene import load_isaac_scene
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.physics import PhysicsModelConfig

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate WP03/WP04 OpenUSD scaffolding without running Isaac Sim."
    )
    parser.add_argument(
        "--scene",
        type=Path,
        default=ROOT / "config" / "isaac" / "minimal-one-vehicle-scene-v1.json",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=ROOT / "assets" / "isaac",
    )
    arguments = parser.parse_args()
    parameters = SimulationConfig(physics=PhysicsModelConfig.legacy_v1()).vehicle_parameters()
    scene = load_isaac_scene(arguments.scene.resolve(), vehicle_parameters=parameters)
    arguments.output_directory.mkdir(parents=True, exist_ok=True)
    outputs = {
        "primitive_drone_empty_scene": arguments.output_directory
        / "crazyflie-primitive-empty-scene-v1.usda",
        "primitive_drone_minimal_room": arguments.output_directory
        / "crazyflie-primitive-minimal-room-v1.usda",
    }
    outputs["primitive_drone_empty_scene"].write_text(
        render_minimal_usda(scene, parameters, include_environment=False),
        encoding="utf-8",
    )
    outputs["primitive_drone_minimal_room"].write_text(
        render_minimal_usda(scene, parameters, include_environment=True),
        encoding="utf-8",
    )
    artifacts = {
        name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in outputs.items()
    }
    manifest = {
        "schema_version": 1,
        "manifest_id": "isaac-wp03-wp04-configured-unqualified-v1",
        "qualification": QUALIFICATION,
        "physical_model_authorized": False,
        "digital_twin_enabled": False,
        "isaac_runtime_result": "NOT_RUN",
        "scene_id": scene.scene_id,
        "scene_configuration_sha256": scene.sha256,
        "parameter_set_id": parameters.parameter_set_id,
        "parameter_configuration_sha256": parameters.sha256,
        "maximum_vehicles": 1,
        "artifacts": artifacts,
    }
    manifest_path = arguments.output_directory / "scaffold-manifest-v1.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
