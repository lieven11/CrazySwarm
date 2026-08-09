import pytest

from crazyswarm_app.fleet.metrics import FleetMetricKind, FleetMetricsCollector


def test_metrics_are_derived_from_semantic_events_and_hash_stably() -> None:
    collector = FleetMetricsCollector(
        started_at_s=0.0,
        required_coverage_roles=2,
        warning_separation_m=0.75,
        critical_separation_m=0.5,
    )
    for task_id in ("zone-a", "zone-b"):
        collector.record(
            FleetMetricKind.TASK_DECLARED,
            timestamp_s=0.0,
            correlation_id=task_id,
        )
        collector.record(
            FleetMetricKind.TASK_ASSIGNED,
            timestamp_s=0.2,
            correlation_id=task_id,
        )
        collector.record(
            FleetMetricKind.LEASE_ISSUED,
            timestamp_s=0.25,
            correlation_id=task_id,
        )
    for kind, timestamp in (
        (FleetMetricKind.HANDOVER_DECISION, 10.0),
        (FleetMetricKind.REPLACEMENT_LAUNCHED, 11.0),
        (FleetMetricKind.TAKEOVER_CONFIRMED, 13.0),
        (FleetMetricKind.OUTGOING_RELEASED, 14.0),
        (FleetMetricKind.HANDOVER_COMPLETED, 15.0),
    ):
        collector.record(kind, timestamp_s=timestamp, correlation_id="handover-a")
    collector.record(
        FleetMetricKind.COVERAGE_GAP_STARTED,
        timestamp_s=12.0,
        correlation_id="zone-a-gap",
    )
    collector.record(
        FleetMetricKind.COVERAGE_GAP_ENDED,
        timestamp_s=13.0,
        correlation_id="zone-a-gap",
    )
    for distance in (1.4, 0.7, 0.4):
        collector.record(
            FleetMetricKind.SEPARATION_OBSERVED,
            timestamp_s=16.0,
            correlation_id="cf01-cf03",
            value=distance,
        )
    collector.record(
        FleetMetricKind.ENERGY_MARGIN,
        timestamp_s=10.0,
        correlation_id="handover-a",
        vehicle_id="cf03",
        value=41.0,
        details={"stage": "decision"},
    )
    for kind, timestamp in (
        (FleetMetricKind.DOCK_QUEUED, 15.0),
        (FleetMetricKind.DOCK_ATTEMPT, 17.0),
        (FleetMetricKind.DOCK_CHARGING, 20.0),
        (FleetMetricKind.DOCK_READY, 80.0),
    ):
        collector.record(kind, timestamp_s=timestamp, correlation_id="dock-cf01")
    for kind, timestamp in (
        (FleetMetricKind.FAULT_DETECTED, 9.0),
        (FleetMetricKind.RECOVERY_COMMAND, 9.1),
        (FleetMetricKind.STABILIZED, 9.5),
        (FleetMetricKind.REASSIGNED, 13.0),
    ):
        collector.record(kind, timestamp_s=timestamp, correlation_id="fault-low-battery")
    collector.record(
        FleetMetricKind.DROP_COUNT,
        timestamp_s=80.0,
        correlation_id="telemetry-cf01",
        count=2,
    )
    for timestamp in (0.0, 0.05, 0.1):
        collector.record(
            FleetMetricKind.TELEMETRY_SAMPLE,
            timestamp_s=timestamp,
            correlation_id="telemetry-cf01",
            vehicle_id="cf01",
        )
    collector.record(
        FleetMetricKind.POSITION_QUALITY,
        timestamp_s=0.05,
        correlation_id="position-cf01",
        vehicle_id="cf01",
        value=98.0,
    )
    collector.record(
        FleetMetricKind.COMMAND_SENT,
        timestamp_s=20.0,
        correlation_id="command-one",
    )
    collector.record(
        FleetMetricKind.COMMAND_ACKNOWLEDGED,
        timestamp_s=20.025,
        correlation_id="command-one",
    )

    report = collector.report(ended_at_s=100.0)
    assert report.coverage_gap_duration_s == 1.0
    assert report.coverage_gap_percent == 0.5
    assert report.mission_availability_percent == 99.5
    assert report.minimum_separation_m == 0.4
    assert report.warning_separation_violations == 1
    assert report.critical_separation_violations == 1
    assert report.handovers[0].total_handover_s == 5.0
    assert report.docks[0].modeled_charge_time_s == 60.0
    assert report.faults[0].detection_to_reassignment_s == 4.0
    assert report.drop_counts == {"telemetry-cf01": 2}
    assert report.telemetry_update_rate_hz == {"cf01": 20.0}
    assert report.command_latency_ms["command-one"] == pytest.approx(25.0)
    assert report.mean_position_quality_percent == {"cf01": 98.0}
    assert (
        report.normalized_metrics_sha256
        == collector.report(ended_at_s=100.0).normalized_metrics_sha256
    )
