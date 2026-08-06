from __future__ import annotations

from crazyswarm_app.domain.models import OperatingMode, VehicleState
from crazyswarm_app.domain.telemetry import TelemetryEnvelope, VehicleTelemetry
from crazyswarm_app.observability.bridge import EvidenceBridge
from crazyswarm_app.observability.bus import TelemetryBus
from crazyswarm_app.observability.events import EvidenceKind


def telemetry(sequence: int, timestamp_s: float) -> TelemetryEnvelope:
    return TelemetryEnvelope(
        vehicle_id="sim01",
        sequence=sequence,
        source_timestamp_s=timestamp_s,
        received_timestamp_s=timestamp_s,
        telemetry=VehicleTelemetry(state=VehicleState.READY),
    )


def test_bounded_subscriber_overflow_is_visible_and_nonblocking() -> None:
    bus = TelemetryBus()
    bridge = EvidenceBridge(bus)
    slow = bus.subscribe(buffer_size=4)
    for sequence in range(1000):
        bridge.telemetry_received(telemetry(sequence, sequence * 0.01))
    assert slow.queue.qsize() == 4
    assert slow.dropped_events == 996
    assert bus.stats.published_events == 1000
    assert bus.stats.dropped_events == 996


def test_subscriber_rate_control_does_not_change_bus_acquisition_rate() -> None:
    bus = TelemetryBus()
    bridge = EvidenceBridge(bus, mode_provider=lambda: OperatingMode.SIM)
    limited = bus.subscribe(
        buffer_size=100,
        max_telemetry_rate_hz=10.0,
        kinds=frozenset({EvidenceKind.TELEMETRY}),
    )
    full_rate = bus.subscribe(buffer_size=100)
    for sequence in range(20):
        bridge.telemetry_received(telemetry(sequence, sequence * 0.02))
    assert full_rate.queue.qsize() == 20
    assert limited.queue.qsize() == 4
    assert bus.stats.published_events == 20


def test_operator_action_is_a_typed_auditable_event() -> None:
    bus = TelemetryBus()
    bridge = EvidenceBridge(bus)
    subscription = bus.subscribe(buffer_size=2)
    bridge.operator_action(
        vehicle_id="sim01",
        client_id="client-1",
        request_id="request-1",
        action="select_vehicle",
    )
    event = subscription.get_nowait()
    assert event.kind is EvidenceKind.OPERATOR_ACTION
    assert event.run_id.startswith("system-")
    assert event.source == "operator"


def test_system_run_identity_is_unique_per_bridge() -> None:
    first_bus = TelemetryBus()
    second_bus = TelemetryBus()
    first_subscription = first_bus.subscribe(buffer_size=1)
    second_subscription = second_bus.subscribe(buffer_size=1)
    EvidenceBridge(first_bus).telemetry_received(telemetry(1, 0.1))
    EvidenceBridge(second_bus).telemetry_received(telemetry(1, 0.1))
    assert first_subscription.get_nowait().run_id != second_subscription.get_nowait().run_id


def test_multi_vehicle_fanout_handles_expected_rates_without_recorder_loss() -> None:
    bus = TelemetryBus()
    bridge = EvidenceBridge(bus)
    recorder_feed = bus.subscribe(buffer_size=20_000)
    ui_feed = bus.subscribe(buffer_size=64, max_telemetry_rate_hz=20.0)
    for sequence in range(5000):
        vehicle_id = f"sim{sequence % 3 + 1:02d}"
        sample = telemetry(sequence, sequence * 0.005).model_copy(update={"vehicle_id": vehicle_id})
        bridge.telemetry_received(sample)
    assert recorder_feed.queue.qsize() == 5000
    assert recorder_feed.dropped_events == 0
    assert ui_feed.queue.qsize() <= 64
    assert bus.stats.published_events == 5000
