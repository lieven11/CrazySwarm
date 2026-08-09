#!/usr/bin/env python3
"""Run the deterministic WP-01-04 two-drone Fast Sim/mock-Isaac comparison."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    FleetSessionIdentity,
    MissionArtifact,
    load_versioned_contract,
)
from crazyswarm_app.fleet.backends import software_backend_factory
from crazyswarm_app.fleet.coordinator import FleetCoordinator, FleetResult
from crazyswarm_app.fleet.preparation import FleetPreparation
from crazyswarm_app.missions.registry import default_registry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.safety.supervisor import SafetySupervisor

ROOT = Path(__file__).resolve().parents[1]
FLEET_CONFIG = ROOT / "config" / "fleet"


async def run_backend(
    deployment: DeploymentManifest,
    mission: MissionArtifact,
    binding_path: Path,
) -> tuple[FleetResult, tuple[dict[str, str], ...]]:
    binding = load_versioned_contract(binding_path, BackendBindingProfile)
    supervisor = SafetySupervisor()
    preparation = FleetPreparation(
        execution_session_id="qualification-session-v1",
        deployment=deployment,
        binding=binding,
        supervisor=supervisor,
    )
    preparation.initialize_backend(software_backend_factory(deployment, binding))
    try:
        await preparation.connect_all()
        await preparation.start_observation()
        preflight = await preparation.run_preflight()
        if not preflight.approved:
            raise RuntimeError(f"fleet preflight failed: {preflight.failed_vehicle_ids}")
        identity = FleetSessionIdentity.create(
            fleet_session_id="qualification-session-v1",
            fleet_run_id="qualification-run-v1",
            backend=binding.backend,
            mission=mission,
            deployment=deployment,
            binding=binding,
            model_id="software-fleet-foundation",
            scenario_id=deployment.deployment_id,
            initial_state={
                member.vehicle_id: member.home.model_dump(mode="json")
                for member in deployment.fleet
            },
        )
        coordinator = FleetCoordinator(
            identity=identity,
            deployment=deployment,
            preparation=preparation,
            supervisor=supervisor,
            mission_runner=MissionRunner(supervisor, default_registry()),
        )
        assignments = {
            task.task_id: deployment.fleet[index].vehicle_id
            for index, task in enumerate(deployment.tasks)
        }
        result = await coordinator.run(assignments)
        return result, preparation.normalized_trace()
    finally:
        await preparation.disconnect_all_safe()


async def main() -> int:
    deployment = load_versioned_contract(
        FLEET_CONFIG / "two-drone-deployment-v1.yaml", DeploymentManifest
    )
    registry = default_registry()
    mission_metadata = registry.metadata("hover")
    if mission_metadata.source_sha256 is None:
        raise RuntimeError("built-in mission artifact has no source identity")
    mission = MissionArtifact(
        mission_id=mission_metadata.mission_id,
        mission_version=mission_metadata.mission_version,
        source_sha256=mission_metadata.source_sha256,
    )
    fast, fast_preparation = await run_backend(
        deployment,
        mission,
        FLEET_CONFIG / "fast-sim-two-drone-binding-v1.yaml",
    )
    mock, mock_preparation = await run_backend(
        deployment,
        mission,
        FLEET_CONFIG / "mock-isaac-two-drone-binding-v1.yaml",
    )
    equivalent = (
        fast_preparation == mock_preparation
        and fast.normalized_trace == mock.normalized_trace
        and fast.normalized_outcome_sha256 == mock.normalized_outcome_sha256
    )
    report = {
        "schema_version": 1,
        "qualification": "WP-01-04_TWO_DRONE_SOFTWARE_FOUNDATION",
        "deployment_sha256": deployment.sha256,
        "mission_sha256": mission.sha256,
        "fast_sim_status": fast.status.value,
        "mock_isaac_status": mock.status.value,
        "normalized_outcome_sha256": fast.normalized_outcome_sha256,
        "equivalent": equivalent,
        "live_isaac_qualification": "NOT_RUN",
        "physical_qualification": "NOT_RUN",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if equivalent else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
