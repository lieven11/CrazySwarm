import json
from pathlib import Path

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.ingestion import default_twin_channels
from crazyswarm_app.twin.models import (
    TwinAvailability,
    TwinQuality,
    TwinSourceClass,
    TwinStreamSample,
    TwinStreamSide,
)
from crazyswarm_app.twin.physical_handoff import (
    REQUIRED_PROPS_OFF_CHANNELS,
    PhysicalTwinHandoffRequest,
    assess_physical_twin_handoff,
)


def test_physical_handoff_is_fail_closed_and_entirely_not_run() -> None:
    payload = json.loads(
        Path("config/qualification/reality-physical-plan-v1.json").read_text(
            encoding="utf-8"
        )
    )
    handoff = payload["digital_twin_handoff"]
    assert handoff["authorization"] == "NOT_AUTHORIZED"
    assert handoff["radio_discovery"] == "NOT_RUN"
    assert handoff["props_on_operation"] == "NOT_RUN"
    assert handoff["real_takeoff"] == "NOT_RUN"
    assert all(stage["status"] == "NOT_RUN" for stage in handoff["stages"])
    assert all(stage["requires_operator_phrase"] for stage in handoff["stages"])
    assert {
        "disconnect",
        "stale telemetry",
        "bad units",
        "bad frame",
        "partial required sensors",
        "simulated data labeled as real",
        "unacknowledged supervisor fallback",
    } == set(handoff["fail_closed_conditions"])


def _request(**updates: object) -> PhysicalTwinHandoffRequest:
    definitions = tuple(
        item
        for item in default_twin_channels()
        if item.channel_id in REQUIRED_PROPS_OFF_CHANNELS
    )
    samples = []
    for sequence, definition in enumerate(definitions, start=1):
        value: float | str | Vector3 = 1.0
        if definition.value_kind == "VECTOR3":
            value = Vector3()
        elif definition.value_kind == "IDENTIFIER":
            value = "retained"
        samples.append(
            TwinStreamSample.create(
                sample_id=f"physical-{sequence}",
                session_id="physical-session",
                side=TwinStreamSide.OBSERVED,
                vehicle_id="real-alpha",
                channel_id=definition.channel_id,
                sequence=1,
                source_timestamp_s=9.9,
                received_timestamp_s=10.0,
                availability=TwinAvailability.AVAILABLE,
                quality=TwinQuality.GOOD,
                unit=definition.unit,
                frame=definition.frame,
                value=value,
                raw_payload_sha256=canonical_sha256([definition.channel_id, value]),
            )
        )
    payload = {
        "session_id": "physical-session",
        "connected": True,
        "observed_source_class": TwinSourceClass.MEASURED_REAL,
        "now_received_s": 10.1,
        "channels": definitions,
        "latest_samples": tuple(samples),
        **updates,
    }
    return PhysicalTwinHandoffRequest(**payload)


def test_physical_handoff_schema_is_ready_but_execution_remains_not_run() -> None:
    assessment = assess_physical_twin_handoff(_request())
    assert assessment.readiness == "READY_FOR_SEPARATE_OPERATOR_AUTHORIZATION"
    assert assessment.execution_status == "NOT_RUN"
    assert assessment.command_issued is False


def test_disconnect_stale_partial_and_simulated_source_fail_closed() -> None:
    disconnected = assess_physical_twin_handoff(_request(connected=False))
    assert "DISCONNECTED" in disconnected.blockers
    stale = assess_physical_twin_handoff(_request(now_received_s=10.4))
    assert any(item.startswith("STALE.") for item in stale.blockers)
    partial_request = _request()
    partial = assess_physical_twin_handoff(
        partial_request.model_copy(
            update={"latest_samples": partial_request.latest_samples[:-1]}
        )
    )
    assert "PARTIAL_REQUIRED_SENSORS" in partial.blockers
    modeled = assess_physical_twin_handoff(
        _request(observed_source_class=TwinSourceClass.SIMULATED_MODEL)
    )
    assert "SOURCE_NOT_MEASURED_REAL" in modeled.blockers


def test_bad_unit_and_frame_are_named_without_issuing_a_command() -> None:
    request = _request()
    original = request.latest_samples[0]
    payload = original.model_dump(mode="python", exclude={"sample_sha256"})
    payload.update({"unit": "feet", "frame": "unknown"})
    changed = TwinStreamSample(
        **payload,
        sample_sha256=canonical_sha256(payload),
    )
    assessment = assess_physical_twin_handoff(
        request.model_copy(
            update={"latest_samples": (changed, *request.latest_samples[1:])}
        )
    )
    assert any(item.startswith("BAD_UNIT.") for item in assessment.blockers)
    assert any(item.startswith("BAD_FRAME.") for item in assessment.blockers)
    assert assessment.execution_status == "NOT_RUN"
    assert assessment.command_issued is False
