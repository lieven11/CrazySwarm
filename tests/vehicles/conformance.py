from __future__ import annotations

from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.domain.models import VehicleCapability, VehicleState
from crazyswarm_app.safety.supervisor import SafetySupervisor
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


async def assert_flight_vehicle_conformance(vehicle: Vehicle) -> None:
    """Mission-level contract shared by Fast Sim and the Isaac gateway mock."""

    supervisor = SafetySupervisor()
    supervisor.register_vehicle(vehicle)
    vehicle_id = vehicle.identity.vehicle_id
    owner = "conformance"
    await supervisor.connect(vehicle_id)
    supervisor.claim_control(vehicle_id, owner)
    report = await supervisor.preflight(
        vehicle_id,
        owner,
        required_capabilities=frozenset(
            {
                VehicleCapability.ARMING,
                VehicleCapability.RELATIVE_POSITIONING,
                VehicleCapability.HIGH_LEVEL_COMMANDS,
                VehicleCapability.RANGE_SENSING,
                VehicleCapability.EMERGENCY_STOP,
            }
        ),
    )
    assert report.approved
    await supervisor.arm(vehicle_id, owner, report.report_id)
    await supervisor.takeoff(vehicle_id, owner, height_m=0.3, duration_s=2.0)
    await supervisor.hover(vehicle_id, owner, 0.1)
    await supervisor.move_relative(
        vehicle_id,
        owner,
        MoveRelativeCommand(x_m=0.1, duration_s=1.0),
    )
    observation, _ = await supervisor.observe(vehicle_id, owner, timeout_s=0.5)
    assert observation.telemetry.position_m is not None
    assert observation.telemetry.ranges is not None
    await supervisor.land(vehicle_id, owner, duration_s=2.0)
    await supervisor.release_control(vehicle_id, owner)
    await supervisor.disconnect(vehicle_id)
    assert supervisor.session(vehicle_id).state is VehicleState.DISCONNECTED
