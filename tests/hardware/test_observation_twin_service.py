from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import CoordinateFrame, EulerAttitude, Vector3, VehicleState
from crazyswarm_app.domain.telemetry import (
    ImuReading,
    RadioFailureKind,
    RadioTransportDiagnostics,
    RangeReadings,
    TelemetryEnvelope,
    VehicleTelemetry,
)
from crazyswarm_app.hardware.observation_twin import (
    ObservationProvenance,
    ObservationTwinService,
    ObservationTwinState,
    PhysicalTwinBindingRequest,
)
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.world import load_scenario
from crazyswarm_app.twin.ingestion import default_twin_channels
from crazyswarm_app.twin.models import (
    TwinAvailability,
    TwinSessionStatus,
    TwinSourceClass,
    TwinStreamSide,
)
from crazyswarm_app.vehicles.crazyflie_link import (
    CrazyflieConnectionMetadata,
    CrazyflieRawSample,
)

URI = "radio://0/80/2M/E7E7E7E701"  # Exact test binding; never discovered.


class ObservationLink:
    def __init__(self) -> None:
        self.connected = False
        self.connect_calls = 0
        self.timestamp_ms = 42_000
        self.commands: list[str] = []
        self.disconnect_calls = 0
        self.scan_calls = 0
        self.observation_reads = 0
        self.command_state_reads = 0
        self.restart_observation_logs_calls = 0
        self.position_x_m = 0.0
        self.radio_transport: RadioTransportDiagnostics | None = None

    def discover(self) -> tuple[str, ...]:
        self.scan_calls += 1
        raise AssertionError("observation binding must never scan")

    def connect(self, selected_uri: str) -> CrazyflieConnectionMetadata:
        self.connect_calls += 1
        self.connected = True
        # Deliberately flight-unqualified: observation must still be possible.
        return CrazyflieConnectionMetadata(
            selected_uri=selected_uri,
            connected_uri=selected_uri,
            protocol_version=11,
            firmware_version="unqualified-test-build",
            deck_parameters={"deck.bcFlow2": 0, "deck.bcMultiranger": 0},
            observed_parameters={},
            available_log_variables=frozenset({"pm.vbat"}),
        )

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def read_sample(self) -> CrazyflieRawSample:
        self.command_state_reads += 1
        return self._sample()

    def read_observation_sample(self) -> CrazyflieRawSample:
        self.observation_reads += 1
        return self._sample()

    def restart_observation_logs(self) -> None:
        self.restart_observation_logs_calls += 1

    def _sample(self) -> CrazyflieRawSample:
        self.timestamp_ms += 100
        return CrazyflieRawSample(
            source_timestamp_ms=self.timestamp_ms,
            received_at_monotonic_s=time.monotonic(),
            values={
                "stateEstimate.x": self.position_x_m,
                "stateEstimate.y": 0.0,
                "stateEstimate.z": 0.0,
                "pm.vbat": 4.05,
                "pm.batteryLevel": 82.0,
            },
            connected=self.connected,
            link_quality_percent=91.0,
            radio_transport=self.radio_transport,
        )

    def request_arm(self, armed: bool) -> None:
        self.commands.append("arm")

    def takeoff(self, height_m: float, duration_s: float, yaw_rad: float | None) -> None:
        self.commands.append("takeoff")

    def land(self, height_m: float, duration_s: float) -> None:
        self.commands.append("land")

    def go_to_relative(
        self, x_m: float, y_m: float, z_m: float, yaw_rad: float, duration_s: float
    ) -> None:
        self.commands.append("move")

    def hold_position(self, duration_s: float) -> None:
        self.commands.append("hold")

    def emergency_stop(self) -> None:
        self.commands.append("emergency")


class UnavailableObservationLink(ObservationLink):
    def connect(self, selected_uri: str) -> CrazyflieConnectionMetadata:
        del selected_uri
        raise OSError("No such USB device")


class QualifiedObservationLink(ObservationLink):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_observation = False

    def connect(self, selected_uri: str) -> CrazyflieConnectionMetadata:
        self.connect_calls += 1
        self.connected = True
        return CrazyflieConnectionMetadata(
            selected_uri=selected_uri,
            connected_uri=selected_uri,
            protocol_version=12,
            firmware_version="qualified-test-build",
            deck_parameters={"deck.bcFlow2": 1, "deck.bcMultiranger": 1},
            observed_parameters={
                "stabilizer.controller": "1",
                "stabilizer.estimator": "2",
            },
            available_log_variables=frozenset({"pm.vbat", "supervisor.info"}),
        )

    def read_observation_sample(self) -> CrazyflieRawSample:
        if self.fail_next_observation:
            self.fail_next_observation = False
            raise OSError("retained telemetry stream stopped")
        return super().read_observation_sample()


def service(
    tmp_path: Path,
    link: ObservationLink | None = None,
) -> tuple[ObservationTwinService, ObservationLink, object]:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    scenario = load_scenario(Path("config/worlds/one_drone.yaml"))
    scenario = scenario.model_copy(
        update={
            "simulation": scenario.simulation.model_copy(
                update={"clock_mode": ClockMode.ACCELERATED}
            )
        }
    )
    runtime = create_runtime(config, scenario, evidence_path=tmp_path / "evidence.sqlite3")
    link = link or ObservationLink()
    return (
        ObservationTwinService(
            runtime,
            binding_path=tmp_path / "binding.json",
            link_factory=lambda: link,
        ),
        link,
        runtime,
    )


@pytest.mark.asyncio
async def test_connection_error_preserves_the_underlying_radio_reason(
    tmp_path: Path,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    observer = ObservationTwinService(
        runtime,
        binding_path=tmp_path / "binding.json",
        link_factory=UnavailableObservationLink,
    )
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )

    status = await observer.connect()

    assert status.state is ObservationTwinState.ERROR
    assert status.last_error_code == "RADIO_UNAVAILABLE"
    assert status.last_error_message is not None
    assert "No such USB device" in status.last_error_message


@pytest.mark.asyncio
async def test_first_connection_captures_identity_and_pairs_without_commands(
    tmp_path: Path,
) -> None:
    observer, link, runtime = service(tmp_path)
    configured = await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )
    assert configured.state is ObservationTwinState.DISCONNECTED
    assert configured.redacted_uri is not None and URI not in configured.redacted_uri

    paired = await observer.connect()
    assert paired.state is ObservationTwinState.PAIRED
    assert paired.connection_nonce is None
    assert paired.observed_identity_sha256
    assert "PROTOCOL_UNQUALIFIED" in paired.command_readiness_issues
    assert "MISSING_DECK_BCFLOW2" in paired.command_readiness_issues
    assert link.commands == []
    assert link.scan_calls == 0
    assert not any(key.startswith("physical-observer-") for key in runtime.vehicles)

    assert paired.state is ObservationTwinState.PAIRED
    assert paired.provenance is ObservationProvenance.TEST
    assert paired.test_only is True
    assert paired.observed_source_class is TwinSourceClass.TEST
    assert paired.predicted_source_class is TwinSourceClass.TEST
    assert paired.sample_count == 2 * len(default_twin_channels())
    assert paired.observed is not None
    assert paired.predicted is not None
    binding_id = (paired.observed_identity_sha256 or "")[:16]
    assert paired.observed.vehicle_id == f"physical:{binding_id}"
    assert paired.predicted.vehicle_id == f"fast-sim:{binding_id}"
    assert paired.observed.freshness == "CURRENT"
    assert paired.observed.position_availability == "INCOMPATIBLE"
    assert paired.observed.battery_availability == "AVAILABLE"
    assert link.observation_reads >= 2
    assert link.command_state_reads == 0
    assert link.commands == []

    assert paired.session_id is not None
    timeline = runtime.twins.timeline(paired.session_id)
    assert len(timeline.samples) == 2 * len(default_twin_channels())
    expected_channels = {item.channel_id for item in default_twin_channels()}
    assert len(expected_channels) == 29
    assert "transport.radio" in expected_channels
    for side in TwinStreamSide:
        assert {
            sample.channel_id for sample in timeline.samples if sample.side is side
        } == expected_channels
    observed_battery = next(
        sample
        for sample in timeline.samples
        if sample.side is TwinStreamSide.OBSERVED and sample.channel_id == "battery.voltage"
    )
    assert observed_battery.source_clock_id == "test-fixture"
    assert observed_battery.raw_source_timestamp_s == pytest.approx(42.2)
    assert observed_battery.source_timestamp_s == pytest.approx(0.0)
    assert observed_battery.availability is TwinAvailability.AVAILABLE
    predicted_battery = next(
        sample
        for sample in timeline.samples
        if sample.side is TwinStreamSide.PREDICTED and sample.channel_id == "battery.voltage"
    )
    assert predicted_battery.source_clock_id == "test-fixture"
    battery_residual = next(
        residual for residual in timeline.residuals if residual.channel_id == "battery.voltage"
    )
    assert isinstance(observed_battery.value, float)
    assert isinstance(predicted_battery.value, float)
    assert battery_residual.value == pytest.approx(observed_battery.value - predicted_battery.value)
    assert all(
        sample.value is None for sample in timeline.samples if sample.channel_id == "pose.position"
    )
    assert all(
        sample.availability is TwinAvailability.INCOMPATIBLE
        and sample.source_frame == "home"
        for sample in timeline.samples
        if sample.channel_id == "pose.position"
    )
    observed_missing = [
        sample
        for sample in timeline.samples
        if sample.side is TwinStreamSide.OBSERVED
        and sample.channel_id.startswith("motor.")
    ]
    assert len(observed_missing) == 12
    assert all(
        sample.availability is TwinAvailability.MISSING and sample.value is None
        for sample in observed_missing
    )
    await observer.disconnect()
    assert link.commands == []


@pytest.mark.asyncio
async def test_home_frame_offset_outside_sim_world_does_not_block_observation(
    tmp_path: Path,
) -> None:
    observer, link, _runtime = service(tmp_path)
    link.position_x_m = 25.0
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Offset Crazyflie",
            confirm_exact_uri=True,
        )
    )
    paired = await observer.connect()

    assert paired.state is ObservationTwinState.PAIRED
    assert paired.observed is not None
    assert paired.predicted is not None
    assert paired.observed.position_m is not None
    assert paired.predicted.position_m is not None
    assert paired.observed.position_m.x == pytest.approx(25.0)
    assert paired.predicted.position_m.x == pytest.approx(0.0, abs=0.01)
    assert paired.observed.position_availability == "INCOMPATIBLE"
    assert paired.predicted.position_availability == "INCOMPATIBLE"
    await observer.shutdown()


@pytest.mark.asyncio
async def test_changed_identity_fails_closed_without_replacing_saved_binding(
    tmp_path: Path,
) -> None:
    observer, _link, runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )
    binding_path = tmp_path / "binding.json"
    payload = json.loads(binding_path.read_text(encoding="utf-8"))
    payload["confirmed_identity_sha256"] = "0" * 64
    binding_path.write_text(json.dumps(payload), encoding="utf-8")

    reloaded_link = ObservationLink()
    reloaded = ObservationTwinService(
        runtime,
        binding_path=binding_path,
        link_factory=lambda: reloaded_link,
    )
    assert reloaded.status().state is ObservationTwinState.DISCONNECTED
    rejected = await reloaded.connect()
    assert rejected.state is ObservationTwinState.ERROR
    assert rejected.last_error_code == "IDENTITY_MISMATCH"
    assert rejected.last_error_message == (
        "connected drone identity does not match the saved observer binding"
    )
    assert rejected.observed_identity_sha256 != "0" * 64
    persisted = json.loads(binding_path.read_text(encoding="utf-8"))
    assert persisted["confirmed_identity_sha256"] == "0" * 64
    assert reloaded_link.connected is False
    assert runtime.twins.list_sessions(include_test=True) == ()
    await reloaded.shutdown()
    assert reloaded_link.commands == []


@pytest.mark.asyncio
async def test_reconnect_after_stream_failure_starts_fresh_counters_and_clocks(
    tmp_path: Path,
) -> None:
    observer, link, _runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )
    paired = await observer.connect()
    assert paired.paired_cycle_count == 1

    link.connected = False
    for _ in range(50):
        if observer.status().state is ObservationTwinState.ERROR:
            break
        await asyncio.sleep(0.01)
    assert observer.status().state is ObservationTwinState.ERROR

    reconnected = await observer.connect()

    assert reconnected.state is ObservationTwinState.PAIRED
    assert reconnected.paired_cycle_count == 1
    assert reconnected.sample_count == 2 * len(default_twin_channels())
    assert reconnected.observed is not None
    assert reconnected.observed.alignment_epoch == 1
    await observer.shutdown()


@pytest.mark.asyncio
async def test_first_ingestion_failure_rolls_back_both_private_adapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, link, runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )
    def fail_ingestion(_: object) -> None:
        raise RuntimeError("injected ingestion failure")

    monkeypatch.setattr(runtime.twins, "ingest", fail_ingestion)
    status = await observer.connect()
    assert status.state is ObservationTwinState.ERROR
    assert status.last_error_code == "IDENTITY_OR_TELEMETRY_INVALID"
    assert status.last_error_message == "injected ingestion failure"
    assert link.connected is False
    assert link.commands == []
    assert not any(key.startswith("physical-observer-") for key in runtime.vehicles)
    assert not any(key.startswith("predicted-observer-") for key in runtime.vehicles)
    failed = runtime.twins.list_sessions(include_test=True)
    assert len(failed) == 1
    assert failed[0].status is TwinSessionStatus.FAILED


@pytest.mark.asyncio
async def test_session_channel_registration_failure_leaves_only_failed_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, link, runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )
    assert runtime.twins.ingestion is not None

    def fail_registration(*_: object) -> None:
        raise RuntimeError("injected channel registration failure")

    monkeypatch.setattr(runtime.twins.ingestion, "register_channels", fail_registration)
    status = await observer.connect()
    sessions = runtime.twins.list_sessions(include_test=True)
    assert len(sessions) == 1
    assert sessions[0].status is TwinSessionStatus.FAILED
    assert status.state is ObservationTwinState.ERROR
    assert status.last_error_message == "injected channel registration failure"
    assert status.session_id is None
    assert link.connected is False


@pytest.mark.asyncio
async def test_second_ticks_clock_reset_and_reconnect_are_bounded_and_truthful(
    tmp_path: Path,
) -> None:
    observer, link, runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    # The firmware clock is unrelated to Fast Sim and may reboot.  Preserve the
    # raw reset/epoch while the mapped session timeline remains monotonic.
    link.timestamp_ms = 0
    await asyncio_sleep(0.24)
    status = observer.status()
    records_per_pair = 2 * len(default_twin_channels())
    assert status.sample_count in {2 * records_per_pair, 3 * records_per_pair}
    assert status.session_id is not None
    timeline = runtime.twins.timeline(status.session_id)
    observed = [
        sample
        for sample in timeline.samples
        if sample.side is TwinStreamSide.OBSERVED and sample.channel_id == "battery.voltage"
    ]
    assert len(observed) in {2, 3}
    assert observed[0].source_epoch == 1
    assert observed[1].source_epoch == 2
    assert observed[1].raw_source_timestamp_s < observed[0].raw_source_timestamp_s
    assert all(
        later.source_timestamp_s - earlier.source_timestamp_s >= 0.099
        for earlier, later in pairwise(observed)
    )
    reset_start = min(
        sample.source_timestamp_s for sample in observed if sample.source_epoch == 2
    )
    reset_residual = next(
        residual
        for residual in timeline.residuals
        if residual.channel_id == "battery.voltage"
        and residual.observed_sample_sha256
        == next(sample.sample_sha256 for sample in observed if sample.source_epoch == 2)
    )
    predicted_match = next(
        sample
        for sample in timeline.samples
        if sample.sample_sha256 == reset_residual.predicted_sample_sha256
    )
    assert predicted_match.source_timestamp_s >= reset_start
    first_session = status.session_id
    await observer.disconnect()

    # Confirmed exact binding auto-pairs on a later connection, but gets a fresh
    # session and remains visibly test-only.
    reconnected = await observer.connect()
    assert reconnected.state is ObservationTwinState.PAIRED
    assert reconnected.session_id != first_session
    assert reconnected.test_only is True
    assert link.commands == []
    await observer.shutdown()


def test_ten_hz_guard_rejects_an_eleventh_batch_in_one_window(tmp_path: Path) -> None:
    observer, _link, _runtime = service(tmp_path)
    observer._batch_admission_times_s.clear()
    for index in range(10):
        observer._admit_batch(100.0 + index * 0.09)
    with pytest.raises(CrazySwarmError, match="10 Hz"):
        observer._admit_batch(100.9)
    observer._admit_batch(101.01)


def test_evidence_schedule_remains_below_ten_hz_guard_over_time(tmp_path: Path) -> None:
    observer, _link, _runtime = service(tmp_path)
    observer._batch_admission_times_s.clear()
    for index in range(500):
        observer._admit_batch(100.0 + index * observer.EVIDENCE_PERIOD_S)


@pytest.mark.asyncio
async def test_live_observation_runs_faster_than_retained_pairing(tmp_path: Path) -> None:
    observer, _link, _runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )
    paired = await observer.connect()
    initial_live_sequence = observer.live_frame().live_sequence
    initial_pair_sequence = paired.paired_cycle_count

    await asyncio.sleep(0.24)

    live_delta = observer.live_frame().live_sequence - initial_live_sequence
    pair_delta = observer.status().paired_cycle_count - initial_pair_sequence
    assert live_delta >= 4
    assert pair_delta >= 1
    assert live_delta > pair_delta
    assert observer.status().sample_count == (
        observer.status().paired_cycle_count * 2 * len(default_twin_channels())
    )
    await observer.shutdown()


@pytest.mark.asyncio
async def test_live_status_exposes_literal_four_motor_pwm_percentages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, link, runtime = service(tmp_path)
    original_sample = link._sample

    def sample_with_motors() -> CrazyflieRawSample:
        sample = original_sample()
        values = {
            **sample.values,
            "motor.m1": 0.4125 * 65_535.0,
            "motor.m2": 0.425 * 65_535.0,
            "motor.m3": 0.4375 * 65_535.0,
            "motor.m4": 0.45 * 65_535.0,
        }
        return replace(sample, values=values)

    monkeypatch.setattr(link, "_sample", sample_with_motors)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Motor telemetry Crazyflie",
            confirm_exact_uri=True,
        )
    )
    paired = await observer.connect()

    assert paired.observed is not None
    assert paired.observed.motor_pwm_percent == pytest.approx((41.25, 42.5, 43.75, 45.0))
    assert paired.observed.family_availability["motors"] is TwinAvailability.AVAILABLE
    assert paired.session_id is not None
    retained = runtime.twins.timeline(
        paired.session_id,
        channel_ids=("motor.m1.pwm", "motor.m2.pwm", "motor.m3.pwm", "motor.m4.pwm"),
    )
    observed_pwm = {
        sample.channel_id: sample.value
        for sample in retained.samples
        if sample.side is TwinStreamSide.OBSERVED
    }
    assert observed_pwm == pytest.approx(
        {
            "motor.m1.pwm": 41.25,
            "motor.m2.pwm": 42.5,
            "motor.m3.pwm": 43.75,
            "motor.m4.pwm": 45.0,
        }
    )
    await observer.shutdown()


@pytest.mark.asyncio
async def test_retained_observation_does_not_burst_past_its_ten_hz_guard(
    tmp_path: Path,
) -> None:
    observer, _link, _runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()

    # Run beyond the accumulated-jitter failure seen on a real observer link.
    await asyncio.sleep(2.5)

    status = observer.status()
    assert status.state is ObservationTwinState.PAIRED
    assert status.last_error_code is None
    assert status.paired_cycle_count > 1
    await observer.shutdown()


@pytest.mark.asyncio
async def test_async_stream_failure_closes_link_predictor_and_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, link, runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Lab Crazyflie",
            confirm_exact_uri=True,
        )
    )
    paired = await observer.connect()
    assert paired.session_id is not None

    def fail_stream() -> object:
        raise RuntimeError("injected asynchronous telemetry failure")

    monkeypatch.setattr(link, "read_observation_sample", fail_stream)
    await asyncio_sleep(0.14)
    failed = observer.status()
    assert failed.state is ObservationTwinState.ERROR
    assert failed.last_error_code == "TELEMETRY_STREAM_FAILED"
    assert failed.last_error_message is not None
    assert "injected asynchronous telemetry failure" in failed.last_error_message
    assert failed.observed is None
    assert failed.predicted is None
    assert link.connected is False
    assert runtime.twins.session(
        paired.session_id, include_test=True
    ).status is TwinSessionStatus.FAILED
    assert observer._predicted is None


@pytest.mark.asyncio
async def test_confirmed_observer_auto_connects_after_service_restart(
    tmp_path: Path,
) -> None:
    observer, _link, runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Restart Crazyflie",
            confirm_exact_uri=True,
        )
    )
    paired = await observer.connect()
    assert paired.auto_connect_enabled is True
    await observer.shutdown()

    restarted_link = ObservationLink()
    restarted = ObservationTwinService(
        runtime,
        binding_path=tmp_path / "binding.json",
        link_factory=lambda: restarted_link,
    )
    assert restarted.status().state is ObservationTwinState.DISCONNECTED
    assert restarted.status().auto_connect_enabled is True

    await restarted.start()
    await wait_for_observer_state(restarted, ObservationTwinState.PAIRED)

    assert restarted_link.connected is True
    assert restarted.status().observed_identity_sha256 == paired.observed_identity_sha256
    await restarted.shutdown()


@pytest.mark.asyncio
async def test_saved_uri_without_identity_finishes_pairing_after_service_restart(
    tmp_path: Path,
) -> None:
    observer, _link, runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Migrated Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.shutdown()

    binding_path = tmp_path / "binding.json"
    before = json.loads(binding_path.read_text(encoding="utf-8"))
    assert before["confirmed_identity_sha256"] is None

    restarted_link = ObservationLink()
    restarted = ObservationTwinService(
        runtime,
        binding_path=binding_path,
        link_factory=lambda: restarted_link,
    )
    assert restarted.status().auto_connect_enabled is True
    await restarted.start()
    await wait_for_observer_state(restarted, ObservationTwinState.PAIRED)

    after = json.loads(binding_path.read_text(encoding="utf-8"))
    assert after["confirmed_identity_sha256"] == restarted.status().observed_identity_sha256
    assert restarted_link.commands == []
    await restarted.shutdown()


@pytest.mark.asyncio
async def test_physical_action_suspends_and_resumes_enabled_observer(
    tmp_path: Path,
) -> None:
    observer, link, _runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Suspended Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()

    suspended = await observer.suspend(
        reason="Motor bench owns the radio",
        owner="operator-test",
    )
    assert suspended.state is ObservationTwinState.SUSPENDED
    assert suspended.auto_connect_enabled is True
    assert suspended.suspension_reason == "Motor bench owns the radio"
    assert suspended.suspension_owner == "operator-test"
    assert suspended.suspended_at_utc is not None
    assert link.connected is False

    resumed = await observer.resume()
    assert resumed.state is ObservationTwinState.PAIRED
    assert resumed.auto_connect_enabled is True
    assert resumed.suspension_reason is None
    assert resumed.suspension_owner is None
    assert link.connected is True
    await observer.shutdown()


@pytest.mark.asyncio
async def test_physical_flight_borrows_and_returns_one_persistent_link(
    tmp_path: Path,
) -> None:
    qualified_link = QualifiedObservationLink()
    observer, link, _runtime = service(tmp_path, qualified_link)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Persistent Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()

    await observer.suspend(
        reason="Physical mission owns the radio",
        owner="operator-test",
        retain_connection=True,
    )
    repeated = await observer.suspend(
        reason="Abort and land owns the radio",
        owner="operator-abort",
    )
    assert repeated.suspension_reason == "Physical mission owns the radio"
    assert repeated.suspension_owner == "operator-test"
    assert link.disconnect_calls == 0
    borrowed = await observer.borrow_command_vehicle(
        vehicle_id="basic-flight:test",
        selected_uri=URI,
    )
    assert borrowed.connected is True
    await borrowed.snapshot()
    await borrowed.disconnect()
    resumed = await observer.resume()

    assert resumed.state is ObservationTwinState.PAIRED
    assert link.connected is True
    assert link.connect_calls == 1
    assert link.disconnect_calls == 0

    await observer.shutdown()
    assert link.disconnect_calls == 1


@pytest.mark.asyncio
async def test_stale_retained_link_reconnects_once_before_command_borrow(
    tmp_path: Path,
) -> None:
    qualified_link = QualifiedObservationLink()
    observer, link, _runtime = service(tmp_path, qualified_link)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Recoverable Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    await observer.suspend(
        reason="Physical mission owns the radio",
        owner="operator-test",
        retain_connection=True,
    )
    qualified_link.fail_next_observation = True

    borrowed = await observer.borrow_command_vehicle(
        vehicle_id="basic-flight:test",
        selected_uri=URI,
    )

    assert borrowed.connected is True
    assert link.connect_calls == 2
    assert link.disconnect_calls == 1
    await borrowed.disconnect()
    assert (await observer.resume()).state is ObservationTwinState.PAIRED
    await observer.shutdown()


@pytest.mark.asyncio
async def test_suspended_observer_publishes_telemetry_from_the_operation_link(
    tmp_path: Path,
) -> None:
    observer, _link, _runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Mission Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    await observer.suspend(reason="Physical mission owns the radio", owner="operator-test")
    sample = TelemetryEnvelope(
        vehicle_id="basic-flight:test",
        sequence=7,
        source_timestamp_s=12.5,
        received_timestamp_s=max(12.5, time.monotonic()),
        source_clock_id="crazyflie-firmware",
        source_clock_epoch=2,
        telemetry=VehicleTelemetry(
            state=VehicleState.FLYING,
            armed=True,
            flying=True,
            frame=CoordinateFrame.HOME,
            attitude=EulerAttitude(roll_rad=0.1, pitch_rad=-0.2, yaw_rad=0.3),
            imu=ImuReading(
                acceleration_body_m_s2=Vector3(x=0.0, y=0.1, z=9.8),
                angular_velocity_body_rad_s=Vector3(x=0.01, y=0.02, z=0.03),
            ),
            ranges=RangeReadings(front_m=0.4, down_m=0.3),
            battery_voltage_v=3.9,
        ),
    )

    observer.accept_operation_sample(sample)

    status = observer.status()
    frame = await anext(observer.live_stream())
    assert status.state is ObservationTwinState.SUSPENDED
    assert status.telemetry_owner == "PHYSICAL_OPERATION"
    assert status.operation_sample_count == 1
    assert status.observed is not None
    assert status.observed.vehicle_id == "basic-flight:test"
    assert status.observed.freshness == "CURRENT"
    assert status.observed.imu == sample.telemetry.imu
    assert status.observed.ranges == sample.telemetry.ranges
    assert frame.telemetry_owner == "PHYSICAL_OPERATION"
    assert frame.operation_sample_count == 1
    assert frame.observed == status.observed
    await observer.shutdown()


@pytest.mark.asyncio
async def test_enabled_observer_recovers_from_stream_failure_without_click(
    tmp_path: Path,
) -> None:
    observer, link, _runtime = service(tmp_path)
    observer.AUTO_RECONNECT_DELAYS_S = (0.01,)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Recovering Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    await observer.start()
    initial_disconnect_calls = link.disconnect_calls

    link.connected = False
    for _ in range(100):
        if (
            observer.status().state is ObservationTwinState.PAIRED
            and link.connected
            and link.disconnect_calls > initial_disconnect_calls
        ):
            break
        await asyncio.sleep(0.01)

    assert observer.status().state is ObservationTwinState.PAIRED
    assert link.connected is True
    assert link.disconnect_calls > initial_disconnect_calls
    await observer.shutdown()


@pytest.mark.asyncio
async def test_stream_failure_observes_backoff_before_reconnecting(
    tmp_path: Path,
) -> None:
    observer, link, _runtime = service(tmp_path)
    observer.AUTO_RECONNECT_DELAYS_S = (0.2,)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Backoff Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    await observer.start()

    link.connected = False
    await wait_for_observer_state(observer, ObservationTwinState.ERROR)
    failure = observer.status()
    assert failure.last_error_code == "TELEMETRY_STREAM_FAILED"
    await asyncio.sleep(0.05)
    assert observer.status().state is ObservationTwinState.ERROR

    await wait_for_observer_state(observer, ObservationTwinState.PAIRED, attempts=100)
    await observer.shutdown()


@pytest.mark.asyncio
async def test_stale_idle_telemetry_keeps_transport_open_and_recovers_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, link, _runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Persistent Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    initial_connect_calls = link.connect_calls
    initial_disconnect_calls = link.disconnect_calls
    initial_live_sequence = observer.live_frame().live_sequence
    real_sample = link._sample
    stale = True

    def stale_then_current_sample() -> CrazyflieRawSample:
        sample = real_sample()
        if not stale:
            return sample
        return replace(
            sample,
            received_at_monotonic_s=time.monotonic() - 2.0,
        )

    monkeypatch.setattr(link, "_sample", stale_then_current_sample)
    observer._last_live_received_monotonic_s = time.monotonic() - 2.0
    await asyncio.sleep(0.08)

    stalled = observer.status()
    assert stalled.state is ObservationTwinState.PAIRED
    assert stalled.observed is not None
    assert stalled.observed.freshness == "STALE"
    assert link.connected is True
    assert link.connect_calls == initial_connect_calls
    assert link.disconnect_calls == initial_disconnect_calls

    stale = False
    for _ in range(30):
        if observer.live_frame().live_sequence > initial_live_sequence:
            break
        await asyncio.sleep(0.01)

    recovered = observer.status()
    assert recovered.state is ObservationTwinState.PAIRED
    assert recovered.observed is not None
    assert recovered.observed.freshness == "CURRENT"
    assert link.connect_calls == initial_connect_calls
    assert link.disconnect_calls == initial_disconnect_calls
    await observer.shutdown()


@pytest.mark.asyncio
async def test_rf_fade_gets_extended_grace_and_recovers_without_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, link, _runtime = service(tmp_path)
    observer.STALE_RECONNECT_S = 0.04
    observer.RF_FADE_RECONNECT_S = 0.20
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Obscured Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    initial_connect_calls = link.connect_calls
    initial_disconnect_calls = link.disconnect_calls
    link.radio_transport = RadioTransportDiagnostics(
        connection_epoch=1,
        state="DEGRADED",
        failure_kind=RadioFailureKind.RF_ACK_LOSS,
        acked_packet_count=60_000,
        lost_packet_count=200,
        packet_loss_percent=40.0,
        consecutive_lost_packet_count=200,
        maximum_consecutive_lost_packet_count=200,
        last_ack_age_ms=1_200.0,
    )
    real_sample = link._sample
    stale = True

    def obscured_then_current_sample() -> CrazyflieRawSample:
        sample = real_sample()
        if not stale:
            return sample
        return replace(sample, received_at_monotonic_s=time.monotonic() - 2.0)

    monkeypatch.setattr(link, "_sample", obscured_then_current_sample)
    observer._last_live_received_monotonic_s = time.monotonic() - 2.0
    await asyncio.sleep(0.10)

    assert observer.status().state is ObservationTwinState.PAIRED
    assert link.connect_calls == initial_connect_calls
    assert link.disconnect_calls == initial_disconnect_calls

    stale = False
    link.radio_transport = RadioTransportDiagnostics(
        connection_epoch=1,
        state="HEALTHY",
        acked_packet_count=60_001,
        lost_packet_count=200,
        packet_loss_percent=0.0,
        maximum_consecutive_lost_packet_count=200,
        last_ack_age_ms=0.0,
    )
    await asyncio.sleep(0.08)

    recovered = observer.status()
    assert recovered.state is ObservationTwinState.PAIRED
    assert recovered.observed is not None
    assert recovered.observed.freshness == "CURRENT"
    assert link.connect_calls == initial_connect_calls
    assert link.disconnect_calls == initial_disconnect_calls
    assert link.restart_observation_logs_calls == 0
    await observer.shutdown()


@pytest.mark.asyncio
async def test_healthy_radio_stale_logs_restart_without_reconnecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, link, _runtime = service(tmp_path)
    observer.STALE_RECONNECT_S = 0.05
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Log-repair Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    real_sample = link._sample

    def stale_until_log_restart() -> CrazyflieRawSample:
        sample = real_sample()
        if link.restart_observation_logs_calls > 0:
            return sample
        return replace(sample, received_at_monotonic_s=time.monotonic() - 2.0)

    monkeypatch.setattr(link, "_sample", stale_until_log_restart)
    observer._last_live_received_monotonic_s = time.monotonic() - 2.0
    await observer.start()
    for _ in range(100):
        status = observer.status()
        if (
            link.restart_observation_logs_calls == 1
            and status.state is ObservationTwinState.PAIRED
            and status.observed is not None
            and status.observed.freshness == "CURRENT"
        ):
            break
        await asyncio.sleep(0.01)

    recovered = observer.status()
    assert recovered.state is ObservationTwinState.PAIRED
    assert recovered.observed is not None
    assert recovered.observed.freshness == "CURRENT"
    assert recovered.last_failure_kind is RadioFailureKind.TELEMETRY_STALE
    assert link.restart_observation_logs_calls == 1
    assert link.connect_calls == 1
    assert link.disconnect_calls == 0
    await observer.shutdown()


@pytest.mark.asyncio
async def test_log_repair_that_immediately_restalls_escalates_to_one_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, link, _runtime = service(tmp_path)
    observer.STALE_RECONNECT_S = 0.03
    observer.LOG_REPAIR_STABILITY_RESET_S = 1.0
    observer.AUTO_RECONNECT_DELAYS_S = (0.01,)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Restalling Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    real_sample = link._sample
    fresh_samples_after_repair = 0

    def stale_again_after_one_repaired_sample() -> CrazyflieRawSample:
        nonlocal fresh_samples_after_repair
        sample = real_sample()
        if link.connect_calls > 1:
            return sample
        if link.restart_observation_logs_calls == 0:
            return replace(sample, received_at_monotonic_s=time.monotonic() - 2.0)
        if fresh_samples_after_repair == 0:
            fresh_samples_after_repair += 1
            return sample
        return replace(sample, received_at_monotonic_s=time.monotonic() - 2.0)

    monkeypatch.setattr(link, "_sample", stale_again_after_one_repaired_sample)
    observer._last_live_received_monotonic_s = time.monotonic() - 2.0
    await observer.start()
    for _ in range(150):
        status = observer.status()
        if link.connect_calls == 2 and status.state is ObservationTwinState.PAIRED:
            break
        await asyncio.sleep(0.01)

    assert observer.status().state is ObservationTwinState.PAIRED
    assert link.restart_observation_logs_calls == 1
    assert link.connect_calls == 2
    assert link.disconnect_calls == 1
    await observer.shutdown()


@pytest.mark.asyncio
async def test_prolonged_stale_observation_reconnects_without_manual_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, link, _runtime = service(tmp_path)
    observer.STALE_RECONNECT_S = 0.05
    observer.AUTO_RECONNECT_DELAYS_S = (0.01,)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Self-healing Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    real_sample = link._sample
    stale_first_connection = True

    def stale_until_reconnected() -> CrazyflieRawSample:
        sample = real_sample()
        if not stale_first_connection or link.connect_calls > 1:
            return sample
        return replace(
            sample,
            received_at_monotonic_s=time.monotonic() - 2.0,
        )

    monkeypatch.setattr(link, "_sample", stale_until_reconnected)
    await observer.start()
    for _ in range(100):
        status = observer.status()
        if (
            link.connect_calls > 1
            and status.state is ObservationTwinState.PAIRED
            and status.observed is not None
        ):
            break
        await asyncio.sleep(0.01)

    assert observer.status().state is ObservationTwinState.PAIRED
    assert link.restart_observation_logs_calls == 1
    assert link.connect_calls == 2
    assert link.disconnect_calls == 1
    assert observer.status().observed is not None
    assert observer.status().observed.freshness == "CURRENT"
    await observer.shutdown()


@pytest.mark.asyncio
async def test_observer_freshness_uses_the_configured_telemetry_timeout(
    tmp_path: Path,
) -> None:
    observer, _link, _runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Freshness Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()

    observer._last_live_received_monotonic_s = time.monotonic() - 0.2
    assert observer.status().observed is not None
    assert observer.status().observed.freshness == "CURRENT"
    observer._last_live_received_monotonic_s = time.monotonic() - 1.1
    assert observer.status().observed is not None
    assert observer.status().observed.freshness == "STALE"
    await observer.shutdown()


@pytest.mark.asyncio
async def test_explicit_disconnect_pauses_only_until_service_restart(
    tmp_path: Path,
) -> None:
    observer, link, runtime = service(tmp_path)
    await observer.configure(
        PhysicalTwinBindingRequest(
            selected_uri=URI,
            vehicle_label="Disabled Crazyflie",
            confirm_exact_uri=True,
        )
    )
    await observer.connect()
    await observer.start()

    disconnected = await observer.disconnect()
    await asyncio.sleep(0.03)

    assert disconnected.state is ObservationTwinState.DISCONNECTED
    assert disconnected.auto_connect_enabled is False
    assert observer.status().state is ObservationTwinState.DISCONNECTED
    assert link.connected is False
    await observer.shutdown()

    binding_path = tmp_path / "binding.json"
    persisted = json.loads(binding_path.read_text(encoding="utf-8"))
    assert persisted["auto_connect_enabled"] is True
    # Simulate the sticky-disabled binding written by an older release.
    persisted["auto_connect_enabled"] = False
    binding_path.write_text(json.dumps(persisted), encoding="utf-8")

    restarted_link = ObservationLink()
    restarted = ObservationTwinService(
        runtime,
        binding_path=binding_path,
        link_factory=lambda: restarted_link,
    )
    assert restarted.status().auto_connect_enabled is True
    await restarted.start()
    await wait_for_observer_state(restarted, ObservationTwinState.PAIRED)
    assert restarted_link.connected is True
    await restarted.shutdown()


async def wait_for_observer_state(
    observer: ObservationTwinService,
    expected: ObservationTwinState,
    *,
    attempts: int = 100,
) -> None:
    for _ in range(attempts):
        if observer.status().state is expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"observer did not reach {expected}; current state is {observer.status().state}"
    )


async def asyncio_sleep(duration_s: float) -> None:
    # Small wrapper keeps this test's only wall-clock wait explicit and bounded.
    import asyncio

    await asyncio.sleep(duration_s)


def test_corrupt_binding_fails_closed_without_constructing_a_link(tmp_path: Path) -> None:
    observer, link, runtime = service(tmp_path)
    binding = tmp_path / "binding.json"
    binding.write_text("{not-json", encoding="utf-8")
    observer = ObservationTwinService(
        runtime,
        binding_path=binding,
        link_factory=lambda: link,
    )
    status = observer.status()
    assert status.state is ObservationTwinState.CONFIGURATION_INVALID
    assert status.configured is False
    assert status.last_error_code == "CONFIGURATION_INVALID"
    assert link.connected is False
    assert link.commands == []
