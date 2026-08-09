from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from crazyswarm_app.isaac.scene import load_isaac_scene
from crazyswarm_app.isaac.transport import TlsGatewayEndpoint
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.vehicles.isaac import IsaacSimVehicle

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.live_isaac
@pytest.mark.asyncio
async def test_live_headless_gateway_launch_ready_snapshot_stop(
    live_isaac_environment: Mapping[str, str],
) -> None:
    """Manual closeout fixture; normally skipped until WP-01 supplies a qualified host."""

    scene = load_isaac_scene(
        ROOT / "config" / "isaac" / "minimal-one-vehicle-scene-v1.json",
        vehicle_parameters=SimulationConfig().vehicle_parameters(),
    )
    endpoint = TlsGatewayEndpoint(
        host=live_isaac_environment["CRAZYSWARM_LIVE_ISAAC_HOST"],
        port=int(live_isaac_environment["CRAZYSWARM_LIVE_ISAAC_PORT"]),
        server_name=live_isaac_environment["CRAZYSWARM_LIVE_ISAAC_SERVER_NAME"],
        ca_certificate=Path(live_isaac_environment["CRAZYSWARM_LIVE_ISAAC_CA_CERTIFICATE"]),
    )
    vehicle = IsaacSimVehicle(
        scene=scene,
        endpoint=endpoint,
        authentication_token=live_isaac_environment["CRAZYSWARM_ISAAC_GATEWAY_TOKEN"],
    )
    await vehicle.connect()
    sample = await vehicle.snapshot()
    assert sample.vehicle_id == "cf01"
    assert sample.telemetry.position_m is not None
    stepped = await vehicle.manual_step(steps=1)
    assert stepped.source_timestamp_s > sample.source_timestamp_s
    await vehicle.disconnect()
