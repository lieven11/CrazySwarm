from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.simulation import VehicleParameterSchema, canonical_sha256
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.isaac.launcher import LaunchReadiness, inspect_headless_launch
from crazyswarm_app.isaac.protocol import (
    GATEWAY_PROTOCOL_VERSION,
    GatewayCapabilities,
    GatewayResponse,
)
from crazyswarm_app.isaac.scene import IsaacSceneSpecification, load_isaac_scene
from crazyswarm_app.isaac.transport import LocalProcessEndpoint, ManagedProcessTransport
from crazyswarm_app.missions.models import MissionStatus
from crazyswarm_app.missions.registry import MissionRegistry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.missions.script import ScriptMission, parse_python_mission
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.physics import PhysicsModelConfig
from crazyswarm_app.vehicles.isaac import IsaacSimVehicle

ROOT = Path(__file__).resolve().parents[2]
SCENE_PATH = ROOT / "config" / "isaac" / "minimal-one-vehicle-scene-v1.json"
WORKER = ROOT / "src" / "crazyswarm_app" / "vehicles" / "_mock_isaac_gateway.py"


def legacy_v1_parameters() -> VehicleParameterSchema:
    return SimulationConfig(physics=PhysicsModelConfig.legacy_v1()).vehicle_parameters()


def scene() -> IsaacSceneSpecification:
    return load_isaac_scene(
        SCENE_PATH,
        vehicle_parameters=legacy_v1_parameters(),
    )


def vehicle() -> IsaacSimVehicle:
    endpoint = LocalProcessEndpoint(
        argv=(sys.executable, "-I", str(WORKER)),
        working_directory=ROOT,
        request_timeout_s=1.0,
        shutdown_timeout_s=0.5,
    )
    return IsaacSimVehicle(scene=scene(), endpoint=endpoint)


def test_minimal_scene_is_same_source_hash_pinned_and_unqualified() -> None:
    specification = scene()
    shared = legacy_v1_parameters()
    assert specification.qualification == "CONFIGURED_UNQUALIFIED"
    assert specification.vehicles[0].parameter_source == "CONFIGURED_UNQUALIFIED"
    assert specification.vehicles[0].parameter_configuration_sha256 == shared.sha256
    assert specification.runtime.maximum_vehicles == 1
    assert specification.runtime.headless
    assert not specification.runtime.renderer_enabled
    assert not specification.physical_model_authorized
    assert not specification.digital_twin_enabled
    gateway_contract = json.loads(
        (ROOT / "config" / "isaac" / "gateway-contract-v1.json").read_text(encoding="utf-8")
    )
    assert gateway_contract["protocol_version"] == GATEWAY_PROTOCOL_VERSION
    assert gateway_contract["authority"] == "SIMULATION_ONLY"
    assert gateway_contract["transports"]["unsecured_tcp"] == "UNSUPPORTED"


def test_scene_rejects_shared_parameter_drift() -> None:
    changed = legacy_v1_parameters().model_copy(update={"base_mass_kg": 0.04})
    with pytest.raises(ValueError, match="parameter hash mismatch"):
        load_isaac_scene(SCENE_PATH, vehicle_parameters=changed)


def test_protocol_rejects_physical_or_digital_twin_capability() -> None:
    with pytest.raises(ValidationError):
        GatewayCapabilities(
            authority="PHYSICAL",
            commands=frozenset(),
            vehicle_capabilities=frozenset(),
            signals=frozenset(),
        )
    with pytest.raises(ValidationError):
        GatewayCapabilities(
            commands=frozenset(),
            vehicle_capabilities=frozenset(),
            signals=frozenset(),
            digital_twin_enabled=True,
        )


def test_gateway_golden_connect_response_is_strict() -> None:
    capabilities = GatewayCapabilities(
        commands=frozenset({"arm"}),
        vehicle_capabilities=frozenset(),
        signals=frozenset({"position"}),
    )
    response = GatewayResponse(
        request_id=1,
        operation="connect",
        ok=True,
        vehicle_id="cf01",
        gateway_instance_id="fixture-gateway",
        session_id="fixture-session",
        model_id="crazyflie-6dof",
        model_version="1.0.0",
        frame="home",
        capabilities=capabilities,
    )
    assert response.protocol_version == GATEWAY_PROTOCOL_VERSION
    assert canonical_sha256(response) == canonical_sha256(
        response.model_dump(mode="json", exclude_none=False)
    )
    malformed = response.model_dump(mode="json") | {"unexpected": True}
    with pytest.raises(ValidationError):
        GatewayResponse.model_validate(malformed)


@pytest.mark.asyncio
async def test_real_isaac_vehicle_class_runs_exact_qf01_through_mock_process() -> None:
    mission_path = ROOT / "missions" / "qualification" / "hover_30s.py"
    record = parse_python_mission(
        filename=mission_path.name,
        name=mission_path.stem,
        source=mission_path.read_text(encoding="utf-8"),
    )
    registry = MissionRegistry()
    registry.register(ScriptMission(record))
    selected = vehicle()
    supervisor = SafetySupervisor()
    supervisor.register_vehicle(selected)
    result = await MissionRunner(supervisor, registry).run(
        record.mission_id,
        selected.identity.vehicle_id,
        mission_run_id="isaac-qf01-contract-run",
    )
    assert result.status is MissionStatus.SUCCEEDED
    assert result.mission_source_sha256 == (
        "fd00838a0fe5beb13e6fc52c39555b9e284b4da5951207f510844dca904c36dc"
    )
    assert result.run_identity_sha256 is not None
    assert result.backend_role == "ISAAC_SIM"
    assert result.authority_class == "SIMULATION"


@pytest.mark.asyncio
async def test_process_loss_is_explicit_and_transport_has_bounded_diagnostics() -> None:
    selected = vehicle()
    await selected.connect()
    transport = selected._transport
    assert isinstance(transport, ManagedProcessTransport)
    await transport.force_terminate()
    with pytest.raises(CrazySwarmError) as lost:
        await selected.snapshot()
    assert lost.value.code is ErrorCode.LINK_LOST
    assert lost.value.details["automatic_retry_safe"] is False
    assert len(transport.stderr_tail) <= 100
    await selected.disconnect()


@pytest.mark.asyncio
async def test_bad_process_authentication_fails_closed_and_stops_child() -> None:
    selected = vehicle()
    transport = selected._transport
    assert isinstance(transport, ManagedProcessTransport)
    transport.endpoint.environment["CRAZYSWARM_ISAAC_GATEWAY_TOKEN"] = "x" * 32
    with pytest.raises(CrazySwarmError) as rejected:
        await selected.connect()
    assert rejected.value.code is ErrorCode.INVALID_COMMAND
    assert transport.process is None


@pytest.mark.asyncio
async def test_telemetry_queue_overflow_is_bounded_and_counted() -> None:
    selected = vehicle()
    stream = cast(AsyncGenerator[TelemetryEnvelope, None], selected.telemetry_stream())
    pending = asyncio.create_task(anext(stream))
    await selected.connect()
    await pending
    for _ in range(105):
        await selected.snapshot()
    assert selected.telemetry_dropped_total == 5
    health = await selected.refresh_gateway_health()
    assert health.telemetry_dropped_total == 5
    await stream.aclose()
    await selected.disconnect()


@pytest.mark.asyncio
async def test_manual_fixed_step_and_clock_reset_are_explicit() -> None:
    selected = vehicle()
    await selected.connect()
    before = await selected.snapshot()
    stepped = await selected.manual_step(steps=3)
    assert stepped.source_timestamp_s == pytest.approx(before.source_timestamp_s + 0.03)
    assert stepped.source_clock_epoch == before.source_clock_epoch
    reset = await selected.reset_source_clock()
    assert reset.source_timestamp_s == 0.0
    assert reset.source_clock_epoch == before.source_clock_epoch + 1
    await selected.disconnect()


def test_headless_launcher_waits_without_host_and_builds_no_shell_plan(tmp_path: Path) -> None:
    waiting = inspect_headless_launch(SCENE_PATH, environment={})
    assert waiting.status is LaunchReadiness.WAITING_FOR_COMPATIBLE_LOCAL_OR_CLOUD_HOST
    assert waiting.argv is None
    executable = tmp_path / "isaac-python"
    entrypoint = tmp_path / "gateway.py"
    profile = tmp_path / "host.json"
    executable.write_text("", encoding="utf-8")
    entrypoint.write_text("", encoding="utf-8")
    profile.write_text(
        json.dumps(
            {
                "classification": "MEASURED_HOST_EVIDENCE",
                "decision": "GO_MINIMAL_EXPERIMENT",
                "compatible": True,
                "headless_gateway_authorized": True,
                "checker_status": "PASSED",
                "isaac_runtime_version": "pinned-test-version",
                "driver_version": "pinned-test-driver",
                "ros_distribution": "pinned-test-ros",
                "middleware": "pinned-test-middleware",
            }
        ),
        encoding="utf-8",
    )
    ready = inspect_headless_launch(
        SCENE_PATH,
        environment={
            "CRAZYSWARM_ISAAC_SIM_EXECUTABLE": str(executable),
            "CRAZYSWARM_ISAAC_GATEWAY_ENTRYPOINT": str(entrypoint),
            "CRAZYSWARM_ISAAC_HOST_PROFILE": str(profile),
            "CRAZYSWARM_ISAAC_RUNTIME_VERSION": "pinned-test-version",
            "CRAZYSWARM_ISAAC_GATEWAY_TOKEN": "s" * 32,
        },
    )
    assert ready.status is LaunchReadiness.READY_FOR_EXPLICIT_LIVE_LAUNCH
    assert ready.argv is not None
    assert ready.argv[0] == str(executable)
    assert ready.argv[1] == str(entrypoint)
    assert ready.argv[2:] == (
        "--headless",
        "--scene",
        str(SCENE_PATH),
        "--gateway-protocol",
        GATEWAY_PROTOCOL_VERSION,
    )
    deferred = inspect_headless_launch(
        SCENE_PATH,
        environment={
            "CRAZYSWARM_ISAAC_SIM_EXECUTABLE": str(executable),
            "CRAZYSWARM_ISAAC_GATEWAY_ENTRYPOINT": str(entrypoint),
            "CRAZYSWARM_ISAAC_HOST_PROFILE": str(
                ROOT / "config" / "isaac" / "victus-reported-host-profile-v1.json"
            ),
            "CRAZYSWARM_ISAAC_RUNTIME_VERSION": "6.0.1",
            "CRAZYSWARM_ISAAC_GATEWAY_TOKEN": "s" * 32,
        },
    )
    assert deferred.status is LaunchReadiness.WAITING_FOR_COMPATIBLE_LOCAL_OR_CLOUD_HOST
    assert deferred.argv is None
    assert "host profile decision is not GO_MINIMAL_EXPERIMENT" in deferred.issues
    assert "host profile is not measured host evidence" in deferred.issues
