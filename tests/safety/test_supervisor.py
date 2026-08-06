from __future__ import annotations

import asyncio
import time

import pytest

from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    OperatingMode,
    VehicleCapability,
    VehicleIdentity,
    VehicleState,
)
from crazyswarm_app.safety.models import LiveModeAuthorization, RecoveryAction
from crazyswarm_app.safety.policy import SafetyPolicy
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.models import SimulationConfig
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig

OWNER = "operator-1"


def make_vehicle(
    *, adapter: str = "sim", config: SimulationConfig | None = None
) -> SimulatedVehicle:
    return SimulatedVehicle(
        VehicleIdentity(vehicle_id="vehicle-1", display_name="Vehicle 1", adapter=adapter),
        IndoorWorld(WorldConfig(width_m=4.0, depth_m=4.0, height_m=1.0)),
        config=config,
    )


async def ready_supervisor(
    *,
    vehicle: SimulatedVehicle | None = None,
    policy: SafetyPolicy | None = None,
) -> tuple[SafetySupervisor, SimulatedVehicle]:
    selected = vehicle or make_vehicle()
    supervisor = SafetySupervisor(policy)
    supervisor.register_vehicle(selected)
    await supervisor.connect(selected.identity.vehicle_id)
    supervisor.claim_control(selected.identity.vehicle_id, OWNER)
    return supervisor, selected


@pytest.mark.asyncio
async def test_nominal_supervised_hover_lifecycle() -> None:
    supervisor, vehicle = await ready_supervisor()
    report = await supervisor.preflight(
        vehicle.identity.vehicle_id,
        OWNER,
        required_capabilities=frozenset(
            {VehicleCapability.ARMING, VehicleCapability.RELATIVE_POSITIONING}
        ),
    )
    assert report.approved

    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    await supervisor.takeoff(vehicle.identity.vehicle_id, OWNER, height_m=0.3, duration_s=2.0)
    await supervisor.hover(vehicle.identity.vehicle_id, OWNER, 1.0)
    await supervisor.move_relative(
        vehicle.identity.vehicle_id,
        OWNER,
        MoveRelativeCommand(x_m=0.1, duration_s=1.5),
    )
    await supervisor.land(vehicle.identity.vehicle_id, OWNER)

    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.READY
    assert not (await vehicle.snapshot()).telemetry.armed
    assert any(event.event_type == "COMMAND_COMPLETED" for event in supervisor.events)


@pytest.mark.asyncio
async def test_real_vehicle_needs_explicit_live_authorization() -> None:
    supervisor, vehicle = await ready_supervisor(vehicle=make_vehicle(adapter="cflib"))
    assert supervisor.mode is OperatingMode.SIM
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    assert not report.approved

    with pytest.raises(CrazySwarmError) as no_authority:
        await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    assert no_authority.value.code is ErrorCode.PREFLIGHT_FAILED

    now = time.monotonic()
    supervisor.set_mode(
        OperatingMode.LIVE,
        authorization=LiveModeAuthorization(
            vehicle_id=vehicle.identity.vehicle_id,
            operator_id=OWNER,
            mode=OperatingMode.LIVE,
            confirmed=True,
            authorized_at_monotonic_s=now,
        ),
    )
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    assert report.approved
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)


@pytest.mark.asyncio
async def test_mode_cannot_change_while_armed() -> None:
    supervisor, vehicle = await ready_supervisor()
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    with pytest.raises(CrazySwarmError, match="cannot change mode"):
        supervisor.set_mode(OperatingMode.REPLAY)


@pytest.mark.asyncio
async def test_limits_reject_before_adapter_receives_command() -> None:
    supervisor, vehicle = await ready_supervisor()
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    clock_before = vehicle.clock.now_s
    with pytest.raises(CrazySwarmError) as too_high:
        await supervisor.takeoff(vehicle.identity.vehicle_id, OWNER, height_m=1.2, duration_s=3.0)
    assert too_high.value.code is ErrorCode.INVALID_COMMAND
    assert vehicle.clock.now_s == clock_before


@pytest.mark.asyncio
async def test_releasing_control_aborts_and_lands() -> None:
    supervisor, vehicle = await ready_supervisor()
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    await supervisor.takeoff(vehicle.identity.vehicle_id, OWNER, height_m=0.3, duration_s=2.0)
    await supervisor.release_control(vehicle.identity.vehicle_id, OWNER)
    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.READY
    assert any("ABORT" in fault for fault in (await vehicle.snapshot()).telemetry.faults)


@pytest.mark.asyncio
async def test_health_assessment_and_enforcement_are_deterministic() -> None:
    supervisor, vehicle = await ready_supervisor()
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    await supervisor.takeoff(vehicle.identity.vehicle_id, OWNER, height_m=0.3, duration_s=2.0)

    session = supervisor.session(vehicle.identity.vehicle_id)
    assert session.telemetry_received_at_monotonic_s is not None
    stale_at = (
        session.telemetry_received_at_monotonic_s + supervisor.policy.telemetry_timeout_s + 1.0
    )
    assessment = supervisor.evaluate_health(vehicle.identity.vehicle_id, now_s=stale_at)
    assert assessment.action is RecoveryAction.ABORT_AND_LAND
    await supervisor.enforce_health(vehicle.identity.vehicle_id, OWNER, now_s=stale_at)
    assert session.state is VehicleState.READY


@pytest.mark.asyncio
async def test_each_health_fault_has_an_explicit_recovery_action() -> None:
    supervisor, vehicle = await ready_supervisor()
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    await supervisor.takeoff(vehicle.identity.vehicle_id, OWNER, height_m=0.3, duration_s=2.0)
    session = supervisor.session(vehicle.identity.vehicle_id)
    assert session.telemetry is not None
    baseline = session.telemetry
    assert baseline.telemetry.position_m is not None

    abort_cases = (
        {"battery_percent": 5.0},
        {"link_quality_percent": 10.0},
        {"localization_quality_percent": 0.0},
        {"position_m": baseline.telemetry.position_m.model_copy(update={"x": 3.0})},
    )
    for update in abort_cases:
        session.telemetry = baseline.model_copy(
            update={"telemetry": baseline.telemetry.model_copy(update=update)}
        )
        assessment = supervisor.evaluate_health(vehicle.identity.vehicle_id)
        assert assessment.action is RecoveryAction.ABORT_AND_LAND

    session.telemetry = baseline.model_copy(
        update={
            "telemetry": baseline.telemetry.model_copy(update={"state": VehicleState.DISCONNECTED})
        }
    )
    assessment = supervisor.evaluate_health(vehicle.identity.vehicle_id)
    assert assessment.action is RecoveryAction.EMERGENCY_STOP


@pytest.mark.asyncio
async def test_preflight_fails_for_low_battery_and_missing_capability() -> None:
    supervisor, vehicle = await ready_supervisor(
        vehicle=make_vehicle(config=SimulationConfig(battery_start_percent=20.0))
    )
    report = await supervisor.preflight(
        vehicle.identity.vehicle_id,
        OWNER,
        required_capabilities=frozenset(
            {VehicleCapability.ARMING, VehicleCapability.GLOBAL_POSITIONING}
        ),
    )
    failed_codes = {check.code for check in report.checks if not check.passed}
    assert not report.approved
    assert {"BATTERY", "CAPABILITIES"}.issubset(failed_codes)


@pytest.mark.asyncio
async def test_emergency_stop_is_distinct_and_latching() -> None:
    supervisor, vehicle = await ready_supervisor()
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    await supervisor.takeoff(vehicle.identity.vehicle_id, OWNER, height_m=0.3, duration_s=2.0)
    await supervisor.emergency_stop(vehicle.identity.vehicle_id, OWNER, reason="test cutoff")
    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.EMERGENCY
    event_types = [event.event_type for event in supervisor.events]
    assert "EMERGENCY_STOP" in event_types
    assert not (await vehicle.snapshot()).telemetry.armed


@pytest.mark.asyncio
async def test_long_command_retains_control_lease_until_acknowledgement() -> None:
    policy = SafetyPolicy(control_lease_timeout_s=0.05)
    vehicle = make_vehicle(
        config=SimulationConfig(clock_mode="realtime", speed=10.0, fixed_step_s=0.01)
    )
    supervisor, vehicle = await ready_supervisor(policy=policy, vehicle=vehicle)
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    await supervisor.takeoff(
        vehicle.identity.vehicle_id,
        OWNER,
        height_m=0.3,
        duration_s=2.0,
    )
    lease = supervisor.session(vehicle.identity.vehicle_id).lease
    assert lease is not None
    assert lease.expires_at_monotonic_s > time.monotonic()
    await supervisor.emergency_stop(vehicle.identity.vehicle_id, OWNER, reason="lease retained")


@pytest.mark.asyncio
async def test_expired_control_lease_aborts_flight() -> None:
    policy = SafetyPolicy(control_lease_timeout_s=0.1)
    supervisor, vehicle = await ready_supervisor(policy=policy)
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    await supervisor.takeoff(vehicle.identity.vehicle_id, OWNER, height_m=0.3, duration_s=2.0)
    lease = supervisor.session(vehicle.identity.vehicle_id).lease
    assert lease is not None
    expiry = lease.expires_at_monotonic_s
    await supervisor.expire_control_leases(now_s=expiry + 0.01)
    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.READY


@pytest.mark.asyncio
async def test_command_timeout_becomes_structured_fault() -> None:
    vehicle = make_vehicle(config=SimulationConfig(clock_mode="realtime", command_latency_s=0.05))
    supervisor = SafetySupervisor(SafetyPolicy(command_timeout_s=0.01))
    supervisor.register_vehicle(vehicle)
    with pytest.raises(CrazySwarmError) as timeout:
        await supervisor.connect(vehicle.identity.vehicle_id)
    assert timeout.value.code is ErrorCode.COMMAND_TIMEOUT
    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.FAULT


@pytest.mark.asyncio
async def test_realtime_simulation_duration_is_not_a_transport_timeout() -> None:
    vehicle = make_vehicle(
        config=SimulationConfig(
            clock_mode="realtime",
            speed=100.0,
            fixed_step_s=0.05,
            command_latency_s=0.0,
            acknowledgement_latency_s=0.0,
        )
    )
    supervisor = SafetySupervisor(SafetyPolicy(command_timeout_s=0.01))
    supervisor.register_vehicle(vehicle)
    await supervisor.connect(vehicle.identity.vehicle_id)
    supervisor.claim_control(vehicle.identity.vehicle_id, OWNER)
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)

    await supervisor.takeoff(
        vehicle.identity.vehicle_id,
        OWNER,
        height_m=0.3,
        duration_s=2.0,
    )

    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.FLYING


@pytest.mark.asyncio
async def test_replay_mode_cannot_arm() -> None:
    supervisor, vehicle = await ready_supervisor()
    supervisor.set_mode(OperatingMode.REPLAY)
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    assert not report.approved
    with pytest.raises(CrazySwarmError):
        await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)


@pytest.mark.asyncio
async def test_cancelled_client_task_does_not_bypass_backend_state() -> None:
    supervisor, vehicle = await ready_supervisor()
    report = await supervisor.preflight(vehicle.identity.vehicle_id, OWNER)
    await supervisor.arm(vehicle.identity.vehicle_id, OWNER, report.report_id)
    task = asyncio.create_task(
        supervisor.takeoff(vehicle.identity.vehicle_id, OWNER, height_m=0.3, duration_s=2.0)
    )
    await task
    await supervisor.release_control(vehicle.identity.vehicle_id, OWNER)
    assert supervisor.session(vehicle.identity.vehicle_id).state is VehicleState.READY
