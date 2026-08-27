from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from crazyswarm_app.domain.commands import (
    AcknowledgementStatus,
    CommandAcknowledgement,
    CommandKind,
)
from crazyswarm_app.domain.models import CoordinateFrame, Vector3, VehicleState
from crazyswarm_app.domain.simulation import (
    CANONICAL_FRAME_CONVENTION,
    COMMAND_SEMANTICS,
    AdapterContractManifest,
    QuaternionValue,
    SignalObservation,
    SignalPresence,
    SignalSpecification,
    SignalValidity,
    SimulationRunIdentity,
    SourceClass,
    TimeContext,
    canonical_sha256,
    inverse_rotate_vector,
    rotate_vector,
)
from crazyswarm_app.domain.telemetry import TelemetryEnvelope, VehicleTelemetry
from crazyswarm_app.simulation.models import SimulationConfig


def assert_vector(actual: Vector3, expected: Vector3, *, absolute: float = 1e-12) -> None:
    assert actual.x == pytest.approx(expected.x, abs=absolute)
    assert actual.y == pytest.approx(expected.y, abs=absolute)
    assert actual.z == pytest.approx(expected.z, abs=absolute)


def axis_angle(axis: Vector3, angle_rad: float) -> QuaternionValue:
    norm = math.sqrt(axis.x**2 + axis.y**2 + axis.z**2)
    scale = math.sin(angle_rad / 2.0) / norm
    return QuaternionValue(
        w=math.cos(angle_rad / 2.0),
        x=axis.x * scale,
        y=axis.y * scale,
        z=axis.z * scale,
    )


@pytest.mark.parametrize(
    ("quaternion", "vector", "expected"),
    [
        (
            QuaternionValue(w=1.0, x=0.0, y=0.0, z=0.0),
            Vector3(x=1.0, y=2.0, z=3.0),
            Vector3(x=1.0, y=2.0, z=3.0),
        ),
        (axis_angle(Vector3(z=1.0), math.pi / 2.0), Vector3(x=1.0), Vector3(y=1.0)),
    ],
)
def test_golden_zero_and_ninety_degree_frame_transforms(
    quaternion: QuaternionValue,
    vector: Vector3,
    expected: Vector3,
) -> None:
    assert_vector(rotate_vector(quaternion, vector), expected)


def test_arbitrary_attitude_transform_round_trip() -> None:
    quaternion = axis_angle(Vector3(x=1.0, y=2.0, z=3.0), 0.73)
    original = Vector3(x=0.41, y=-1.2, z=2.7)
    assert_vector(inverse_rotate_vector(quaternion, rotate_vector(quaternion, original)), original)
    assert {item.frame for item in CANONICAL_FRAME_CONVENTION.frames} == set(CoordinateFrame)


def test_vehicle_parameter_and_signal_schema_round_trip_hashes_are_deterministic() -> None:
    config = SimulationConfig()
    parameters = config.vehicle_parameters()
    restored = type(parameters).model_validate_json(parameters.model_dump_json())
    assert restored == parameters
    assert restored.sha256 == parameters.sha256
    assert parameters.total_mass_kg == config.physics.total_mass_kg
    assert [rotor.rotation_direction for rotor in parameters.rotors] == ["CCW", "CW", "CCW", "CW"]
    assert {sensor.signal for sensor in parameters.sensors} == {
        "imu",
        "optical-flow",
        "range-rays",
        "position-estimate",
    }

    specifications = config.signal_specifications()
    assert canonical_sha256(specifications) == canonical_sha256(
        tuple(type(item).model_validate_json(item.model_dump_json()) for item in specifications)
    )
    unsupported = next(item for item in specifications if item.signal_id == "physical-radio-rssi")
    assert unsupported.presence is SignalPresence.UNSUPPORTED
    assert unsupported.noise_std is None


def test_absent_zero_invalid_unavailable_and_stale_remain_distinct() -> None:
    absent = VehicleTelemetry(state=VehicleState.READY)
    explicit_zero = VehicleTelemetry(
        state=VehicleState.READY,
        position_m=Vector3(),
        frame=CoordinateFrame.HOME,
        position_is_estimate=True,
        battery_percent=0.0,
        battery_voltage_v=0.0,
    )
    assert absent.position_m is None
    assert absent.battery_percent is None
    assert explicit_zero.position_m == Vector3()
    assert explicit_zero.battery_percent == 0.0

    unavailable = SignalObservation(
        signal_id="position",
        validity=SignalValidity.UNAVAILABLE,
        source_class=SourceClass.SIMULATED_MODEL,
        source_id="fast-sim",
        unit="m",
        frame=CoordinateFrame.HOME,
        source_timestamp_s=None,
    )
    invalid = unavailable.model_copy(
        update={"validity": SignalValidity.INVALID, "source_timestamp_s": 1.0}
    )
    stale = unavailable.model_copy(
        update={"validity": SignalValidity.STALE, "source_timestamp_s": 0.5, "value": Vector3()}
    )
    assert unavailable.value is None
    assert invalid.validity is SignalValidity.INVALID
    assert stale.validity is SignalValidity.STALE and stale.value == Vector3()
    with pytest.raises(ValidationError, match="cannot carry a value"):
        SignalObservation.model_validate(unavailable.model_dump() | {"value": 0.0})


def test_signal_contract_rejects_wrong_frame_provenance_and_unsupported_output() -> None:
    specification = SignalSpecification(
        signal_id="position",
        unit="m",
        frame=CoordinateFrame.HOME,
        source_class=SourceClass.SIMULATED_MODEL,
        presence=SignalPresence.REQUIRED,
        nominal_sample_rate_hz=100.0,
        nominal_latency_s=0.01,
        noise_std=0.001,
        bias=0.0,
        minimum=None,
        maximum=None,
        clipping="NONE",
        dropout_probability=0.0,
    )
    observation = SignalObservation(
        signal_id="position",
        validity=SignalValidity.VALID,
        source_class=SourceClass.SIMULATED_MODEL,
        source_id="fast-sim",
        model_id="crazyflie-6dof",
        model_version="1.0.0",
        unit="m",
        frame=CoordinateFrame.HOME,
        source_timestamp_s=1.0,
        value=Vector3(),
    )
    specification.validate_observation(observation)
    with pytest.raises(ValueError, match="frame mismatch"):
        specification.validate_observation(
            observation.model_copy(update={"frame": CoordinateFrame.SENSOR})
        )
    with pytest.raises(ValueError, match="provenance mismatch"):
        specification.validate_observation(
            observation.model_copy(update={"source_class": SourceClass.MEASURED_REAL})
        )


def test_time_contract_separates_all_clocks_and_allows_explicit_epoch_reset() -> None:
    context = TimeContext(
        simulation_time_s=4.0,
        source_time_s=4.0,
        receive_time_s=4.03,
        wall_time_utc="2026-08-06T16:30:00+02:00",
        replay_time_s=12.5,
        source_clock_id="fast-sim-sim01",
        source_clock_epoch=2,
    )
    assert (
        len(
            {
                context.simulation_time_s,
                context.receive_time_s,
                context.replay_time_s,
                context.wall_time_utc,
            }
        )
        == 4
    )

    before_reset = TelemetryEnvelope(
        vehicle_id="sim01",
        sequence=50,
        source_timestamp_s=9.0,
        received_timestamp_s=9.01,
        source_clock_id="fast-sim-sim01",
        source_clock_epoch=0,
        telemetry=VehicleTelemetry(state=VehicleState.READY),
    )
    after_reset = before_reset.model_copy(
        update={
            "sequence": 0,
            "source_timestamp_s": 0.0,
            "received_timestamp_s": 0.01,
            "source_clock_epoch": 1,
        }
    )
    assert after_reset.sequence < before_reset.sequence
    assert after_reset.source_clock_epoch > before_reset.source_clock_epoch
    with pytest.raises(ValidationError, match="cannot precede"):
        TimeContext(
            source_time_s=2.0,
            receive_time_s=1.0,
            wall_time_utc="2026-08-06T16:30:00+02:00",
            source_clock_id="clock",
        )


def test_command_semantics_and_run_identity_are_backend_neutral_and_stable() -> None:
    assert {item.command for item in COMMAND_SEMANTICS} == set(CommandKind)
    move = next(item for item in COMMAND_SEMANTICS if item.command is CommandKind.MOVE_RELATIVE)
    assert move.allowed_frames == frozenset({CoordinateFrame.HOME, CoordinateFrame.BODY})

    digest = "a" * 64
    identity = SimulationRunIdentity(
        mission_source_sha256=digest,
        model_id="crazyflie-6dof",
        model_version="1.0.0",
        model_configuration_sha256="b" * 64,
        scenario_id="room-v1",
        scenario_configuration_sha256="c" * 64,
        initial_state_sha256="d" * 64,
        seed=7,
        fixed_step_s=0.01,
    )
    assert (
        SimulationRunIdentity.model_validate_json(identity.model_dump_json()).sha256
        == identity.sha256
    )

    manifest = AdapterContractManifest(
        adapter_id="isaac-mock",
        supported_capabilities=frozenset(),
        supported_signals=frozenset(),
        supported_model_ids=frozenset({"isaac-crazyflie"}),
    )
    with pytest.raises(ValueError, match="model unsupported"):
        manifest.require(frozenset(), model_id="crazyflie-6dof")


def test_acknowledgement_completion_and_rejection_semantics_fail_closed() -> None:
    with pytest.raises(ValidationError, match="completion timestamp"):
        CommandAcknowledgement(
            vehicle_id="sim01",
            command_id="cmd-1",
            status=AcknowledgementStatus.COMPLETED,
            received_at_monotonic_s=1.0,
        )
    with pytest.raises(ValidationError, match="cannot precede"):
        CommandAcknowledgement(
            vehicle_id="sim01",
            command_id="cmd-2",
            status=AcknowledgementStatus.COMPLETED,
            received_at_monotonic_s=2.0,
            completed_at_monotonic_s=1.0,
        )
    with pytest.raises(ValidationError, match="reason code"):
        CommandAcknowledgement(
            vehicle_id="sim01",
            command_id="cmd-3",
            status=AcknowledgementStatus.REJECTED,
            received_at_monotonic_s=1.0,
        )
    with pytest.raises(ValidationError, match="complete clock identity"):
        CommandAcknowledgement(
            vehicle_id="sim01",
            command_id="cmd-4",
            status=AcknowledgementStatus.COMPLETED,
            received_at_monotonic_s=1.0,
            completed_at_monotonic_s=2.0,
            received_at_source_s=1.25,
        )
    acknowledged = CommandAcknowledgement(
        vehicle_id="sim01",
        command_id="cmd-5",
        status=AcknowledgementStatus.COMPLETED,
        received_at_monotonic_s=1.0,
        completed_at_monotonic_s=2.0,
        received_at_source_s=1.25,
        completed_at_source_s=2.25,
        source_clock_id="fast-sim-sim01",
        source_clock_epoch=3,
    )
    assert acknowledged.received_at_source_s == 1.25
