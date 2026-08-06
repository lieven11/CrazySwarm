from __future__ import annotations

from crazyswarm_app.domain.models import VehicleState
from crazyswarm_app.vehicles.base import Vehicle


async def assert_vehicle_conformance(vehicle: Vehicle) -> None:
    """Backend-neutral minimum exercised by FastSim and future adapter test doubles."""

    assert vehicle.identity.vehicle_id
    assert vehicle.identity.adapter
    vehicle.contract_manifest.require(frozenset())
    await vehicle.connect()
    snapshot = await vehicle.snapshot()
    assert snapshot.vehicle_id == vehicle.identity.vehicle_id
    assert snapshot.received_timestamp_s >= snapshot.source_timestamp_s
    assert snapshot.telemetry.state in {VehicleState.READY, VehicleState.CONNECTING}
    await vehicle.disconnect()
