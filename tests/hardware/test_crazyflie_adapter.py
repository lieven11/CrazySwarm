from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from crazyswarm_app.domain.commands import (
    ArmCommand,
    CommandEnvelope,
    MoveRelativeCommand,
    TakeoffCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    AuthorityClass,
    BackendRole,
    CommandSource,
    CoordinateFrame,
    OperatingMode,
    VehicleCapability,
)
from crazyswarm_app.hardware.models import CommandPermit, PermitScope
from crazyswarm_app.vehicles.crazyflie import CrazyflieVehicle
from crazyswarm_app.vehicles.crazyflie_link import (
    CrazyflieConnectionMetadata,
    CrazyflieRawSample,
)
from tests.vehicles.conformance import assert_vehicle_conformance

URI = "radio://0/80/2M/E7E7E7E701"
SHA = "a" * 64


class FakeCrazyflieLink:
    def __init__(
        self,
        *,
        flow: int = 1,
        multiranger: int = 1,
        high_level_enabled: str = "1",
    ) -> None:
        self.connect_calls: list[str] = []
        self.disconnect_calls = 0
        self.commands: list[tuple[object, ...]] = []
        self.flow = flow
        self.multiranger = multiranger
        self.high_level_enabled = high_level_enabled
        self.connected = False
        self.bitfield = 1 << 0
        self.timestamp_ms = 1_000
        self.fail_next_move = False
        self.values = {
            "stateEstimate.x": 0.0,
            "stateEstimate.y": 0.0,
            "stateEstimate.z": 0.0,
            "stateEstimate.vx": 0.0,
            "stateEstimate.vy": 0.0,
            "stateEstimate.vz": 0.0,
            "stabilizer.roll": 0.0,
            "stabilizer.pitch": 0.0,
            "stabilizer.yaw": 90.0,
            "stateEstimate.qw": 1.0,
            "stateEstimate.qx": 0.0,
            "stateEstimate.qy": 0.0,
            "stateEstimate.qz": 0.0,
            "kalman.varPX": 0.001,
            "kalman.varPY": 0.002,
            "kalman.varPZ": 0.003,
            "range.front": 500.0,
            "range.back": 5_000.0,
            "range.left": 600.0,
            "range.right": 700.0,
            "range.up": 800.0,
            "range.zrange": 300.0,
            "pm.vbat": 4.0,
            "pm.batteryLevel": 80.0,
            "motion.squal": 204.0,
            "acc.x": 0.0,
            "acc.y": 0.0,
            "acc.z": 1.0,
            "gyro.x": 0.0,
            "gyro.y": 0.0,
            "gyro.z": 0.0,
        }

    def connect(self, selected_uri: str) -> CrazyflieConnectionMetadata:
        self.connect_calls.append(selected_uri)
        self.connected = True
        return CrazyflieConnectionMetadata(
            selected_uri=selected_uri,
            connected_uri=selected_uri,
            protocol_version=12,
            firmware_version="2026.06",
            deck_parameters={
                "deck.bcFlow2": self.flow,
                "deck.bcMultiranger": self.multiranger,
            },
            observed_parameters={
                "commander.enHighLevel": self.high_level_enabled,
                "stabilizer.controller": "1",
                "stabilizer.estimator": "2",
            },
            available_log_variables=frozenset(self.values),
        )

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def read_sample(self) -> CrazyflieRawSample:
        return CrazyflieRawSample(
            source_timestamp_ms=self.timestamp_ms,
            received_at_monotonic_s=time.monotonic(),
            values=dict(self.values),
            supervisor_bitfield=self.bitfield,
            link_quality_percent=90.0,
            link_latency_ms=4.0,
            connected=self.connected,
        )

    def request_arm(self, armed: bool) -> None:
        self.commands.append(("arm", armed))
        if armed:
            self.bitfield |= 1 << 1
        else:
            self.bitfield &= ~(1 << 1)

    def takeoff(self, height_m: float, duration_s: float, yaw_rad: float | None) -> None:
        self.commands.append(("takeoff", height_m, duration_s, yaw_rad))
        self.bitfield |= (1 << 1) | (1 << 4)
        self.values["stateEstimate.z"] = height_m

    def land(self, height_m: float, duration_s: float) -> None:
        self.commands.append(("land", height_m, duration_s))
        self.bitfield &= ~(1 << 4)
        self.values["stateEstimate.z"] = height_m

    def go_to_relative(
        self,
        x_m: float,
        y_m: float,
        z_m: float,
        yaw_rad: float,
        duration_s: float,
    ) -> None:
        self.commands.append(("move", x_m, y_m, z_m, yaw_rad, duration_s))
        if self.fail_next_move:
            raise RuntimeError("radio acknowledgement disappeared")
        self.values["stateEstimate.x"] += x_m
        self.values["stateEstimate.y"] += y_m
        self.values["stateEstimate.z"] += z_m

    def hold_position(self, duration_s: float) -> None:
        self.commands.append(("hold", duration_s))

    def emergency_stop(self) -> None:
        self.commands.append(("emergency",))
        self.bitfield &= ~((1 << 1) | (1 << 4))


def vehicle(link: FakeCrazyflieLink | None = None) -> CrazyflieVehicle:
    return CrazyflieVehicle(vehicle_id="cf01", selected_uri=URI, link=link or FakeCrazyflieLink())


def permit(scope: PermitScope) -> CommandPermit:
    now = datetime.now(UTC)
    return CommandPermit(
        permit_id=f"permit-{scope.value.lower()}",
        vehicle_id="cf01",
        selected_uri=URI,
        operator_id="operator",
        scope=scope,
        issued_at_utc=now,
        expires_at_utc=now + timedelta(minutes=5),
        operator_present=True,
        props_removed=scope is PermitScope.PROPS_OFF_BENCH,
        physically_restrained=True,
        flight_entry_record_id=("flight-entry" if scope is PermitScope.CONTAINED_FLIGHT else None),
        flight_entry_evidence_sha256=(SHA if scope is PermitScope.CONTAINED_FLIGHT else None),
    )


def command(payload: object, command_id: str = "cmd-1") -> CommandEnvelope:
    return CommandEnvelope(
        vehicle_id="cf01",
        command_id=command_id,
        issued_at_monotonic_s=time.monotonic(),
        source=CommandSource.TEST,
        mode=OperatingMode.LIVE,
        payload=payload,
    )


def test_construction_is_inert_and_declares_physical_authority() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    assert link.connect_calls == []
    assert adapter.backend_profile.role is BackendRole.REAL_CRAZYFLIE
    assert adapter.backend_profile.authority is AuthorityClass.PHYSICAL
    assert VehicleCapability.RELATIVE_POSITIONING not in adapter.capabilities.features


@pytest.mark.asyncio
async def test_observation_conformance_measures_decks_and_never_arms() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    await assert_vehicle_conformance(adapter)
    assert link.connect_calls == [URI]
    assert not any(item[0] == "arm" for item in link.commands)


@pytest.mark.asyncio
async def test_missing_required_deck_fails_closed_and_disconnects() -> None:
    link = FakeCrazyflieLink(multiranger=0)
    adapter = vehicle(link)
    with pytest.raises(CrazySwarmError) as rejected:
        await adapter.connect()
    assert rejected.value.code is ErrorCode.PREFLIGHT_FAILED
    assert rejected.value.details == {"missing_deck_parameters": ["deck.bcMultiranger"]}
    assert link.disconnect_calls == 1


@pytest.mark.asyncio
async def test_disabled_high_level_commander_fails_before_command_authority() -> None:
    link = FakeCrazyflieLink(high_level_enabled="0")
    adapter = vehicle(link)
    with pytest.raises(CrazySwarmError) as rejected:
        await adapter.connect()
    assert rejected.value.code is ErrorCode.PREFLIGHT_FAILED
    assert rejected.value.details == {"commander.enHighLevel": "0"}
    assert link.commands == []
    assert link.disconnect_calls == 1


@pytest.mark.asyncio
async def test_commands_require_permit_and_bench_scope_cannot_fly() -> None:
    adapter = vehicle()
    await adapter.connect()
    with pytest.raises(CrazySwarmError) as no_permit:
        await adapter.execute(command(ArmCommand()))
    assert no_permit.value.code is ErrorCode.MODE_NOT_AUTHORIZED
    adapter.install_command_permit(permit(PermitScope.PROPS_OFF_BENCH))
    await adapter.execute(command(ArmCommand(), "arm-bench"))
    with pytest.raises(CrazySwarmError) as flight_rejected:
        await adapter.execute(command(TakeoffCommand(height_m=0.2, duration_s=0.01)))
    assert flight_rejected.value.code is ErrorCode.MODE_NOT_AUTHORIZED
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_body_move_uses_latest_measured_yaw_and_preserves_home_mapping() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    await adapter.connect()
    adapter.install_command_permit(permit(PermitScope.CONTAINED_FLIGHT))
    await adapter.execute(
        command(
            MoveRelativeCommand(
                x_m=0.2,
                duration_s=0.01,
                frame=CoordinateFrame.BODY,
            ),
            "move-body",
        )
    )
    mapped = link.commands[-1]
    assert mapped[0] == "move"
    assert mapped[1] == pytest.approx(0.0, abs=1e-9)
    assert mapped[2] == pytest.approx(0.2)
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_real_telemetry_units_validity_and_unsupported_fields_are_explicit() -> None:
    adapter = vehicle()
    await adapter.connect()
    sample = await adapter.snapshot()
    telemetry = sample.telemetry
    assert telemetry.ground_truth_position_m is None
    assert telemetry.motors is None
    assert telemetry.ranges is not None
    assert telemetry.ranges.front_m == pytest.approx(0.5)
    assert telemetry.ranges.back_m is None
    assert telemetry.ranges.statuses["back"].value == "NO_HIT"
    assert telemetry.imu is not None
    assert telemetry.imu.acceleration_body_m_s2.z == pytest.approx(9.80665)
    assert telemetry.estimator is not None
    assert telemetry.estimator.position_variance_m2 is not None
    assert telemetry.transport is not None
    assert telemetry.transport.source_class == "MEASURED_REAL"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_lost_command_acknowledgement_is_unknown_and_never_retry_safe() -> None:
    link = FakeCrazyflieLink()
    adapter = vehicle(link)
    await adapter.connect()
    adapter.install_command_permit(permit(PermitScope.CONTAINED_FLIGHT))
    link.fail_next_move = True
    with pytest.raises(CrazySwarmError) as unknown:
        await adapter.execute(
            command(MoveRelativeCommand(x_m=0.1, duration_s=0.01), "unknown-move")
        )
    assert unknown.value.code is ErrorCode.LINK_LOST
    assert unknown.value.details["command_outcome"] == "UNKNOWN_OUTCOME"
    assert unknown.value.details["automatic_retry_safe"] is False
    assert len([item for item in link.commands if item[0] == "move"]) == 1
    await adapter.disconnect()


def test_invalid_or_implicit_radio_uri_is_rejected_before_driver_access() -> None:
    with pytest.raises(ValueError, match="full explicit"):
        CrazyflieVehicle(
            vehicle_id="cf01",
            selected_uri="radio://0/80/2M",
            link=FakeCrazyflieLink(),
        )
