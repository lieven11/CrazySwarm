from __future__ import annotations

import time

import pytest

from crazyswarm_app.domain.models import CoordinateFrame, Vector3
from crazyswarm_app.twin.coordinator import TwinCoordinator
from crazyswarm_app.twin.models import (
    CanonicalMissionIntent,
    TwinInitialState,
    TwinObservation,
    TwinSessionConfig,
    TwinSourceClass,
    TwinValidity,
)


def session_config(*, test_only: bool = False) -> TwinSessionConfig:
    observed_source = TwinSourceClass.TEST if test_only else TwinSourceClass.MEASURED_REAL
    simulated_source = TwinSourceClass.TEST if test_only else TwinSourceClass.SIMULATED_MODEL
    return TwinSessionConfig(
        observed_vehicle_id="real-1",
        simulated_vehicle_id="sim-1",
        mission_id="hover",
        mission_version="1.0.0",
        mission_source_sha256="a" * 64,
        physics_model_id="crazyflie-6dof",
        physics_model_version="1.0.0",
        physics_configuration_sha256="b" * 64,
        observed_initial_state=TwinInitialState(
            source_class=observed_source,
            source_id="observed-start",
            frame=CoordinateFrame.WORLD,
            position_m=Vector3(),
        ),
        simulated_initial_state=TwinInitialState(
            source_class=simulated_source,
            source_id="model-start",
            frame=CoordinateFrame.WORLD,
            position_m=Vector3(),
        ),
        ground_truth_available=False,
        test_only=test_only,
    )


@pytest.mark.asyncio
async def test_same_intent_has_independent_acknowledgements_and_failure() -> None:
    coordinator = TwinCoordinator()
    session = coordinator.create_session(session_config(test_only=True))
    received: list[str] = []

    async def observed(intent: CanonicalMissionIntent) -> str:
        received.append(intent.intent_id)
        return "observed accepted"

    async def simulated(intent: CanonicalMissionIntent) -> None:
        received.append(intent.intent_id)
        raise RuntimeError("model unavailable")

    intent = CanonicalMissionIntent(
        intent_id="intent-1",
        mission_id="hover",
        mission_version="1.0.0",
        mission_source_sha256="a" * 64,
        physics_model_id="crazyflie-6dof",
        physics_model_version="1.0.0",
        physics_configuration_sha256="b" * 64,
        parameters={"height_m": 0.3},
        issued_at_monotonic_s=time.monotonic(),
    )
    observed_ack, simulated_ack = await coordinator.route_intent(
        session.session_id,
        intent,
        observed_executor=observed,
        simulated_executor=simulated,
    )
    assert received == ["intent-1", "intent-1"]
    assert observed_ack.accepted is True
    assert simulated_ack.accepted is False
    assert "model unavailable" in (simulated_ack.message or "")


def test_residuals_preserve_source_clocks_and_separate_latency() -> None:
    coordinator = TwinCoordinator()
    session = coordinator.create_session(session_config())
    observed = TwinObservation(
        vehicle_id="real-1",
        source_class=TwinSourceClass.MEASURED_REAL,
        source_id="lighthouse",
        source_timestamp_s=10.0,
        received_timestamp_s=10.03,
        frame=CoordinateFrame.WORLD,
        position_m=Vector3(x=1.0, z=0.3),
        velocity_m_s=Vector3(x=0.2),
        yaw_rad=0.2,
        battery_percent=90.0,
    )
    simulated = TwinObservation(
        vehicle_id="sim-1",
        source_class=TwinSourceClass.SIMULATED_MODEL,
        source_id="crazyflie-6dof-v1",
        source_timestamp_s=10.05,
        received_timestamp_s=10.06,
        frame=CoordinateFrame.WORLD,
        position_m=Vector3(z=0.2),
        velocity_m_s=Vector3(x=0.1),
        yaw_rad=0.1,
        battery_percent=91.5,
    )
    deviation = coordinator.add_observations(session.session_id, observed, simulated)
    assert deviation.validity is TwinValidity.VALID
    assert deviation.observed_source_timestamp_s == 10.0
    assert deviation.simulated_source_timestamp_s == 10.05
    assert deviation.observed_latency_ms == pytest.approx(30.0)
    assert deviation.simulated_latency_ms == pytest.approx(10.0)
    assert deviation.position_m == pytest.approx((1.0**2 + 0.1**2) ** 0.5)
    assert deviation.altitude_m == pytest.approx(0.1)
    assert deviation.battery_percent == pytest.approx(1.5)
    assert deviation.ground_truth_available is False

    report = coordinator.report(session.session_id)
    assert report.valid_sample_count == 1
    calibration = coordinator.calibrate(
        session.session_id,
        base_model_id="crazyflie-6dof",
        base_model_version="1.0.0",
    )
    assert calibration.model_version.startswith("1.0.0+")
    assert calibration.base_model_version == "1.0.0"


def test_missing_or_incompatible_data_produces_no_residual() -> None:
    coordinator = TwinCoordinator()
    session = coordinator.create_session(session_config())
    observed = TwinObservation(
        vehicle_id="real-1",
        source_class=TwinSourceClass.MEASURED_REAL,
        source_id="flow",
        source_timestamp_s=1.0,
        received_timestamp_s=1.01,
        frame=CoordinateFrame.HOME,
    )
    simulated = TwinObservation(
        vehicle_id="sim-1",
        source_class=TwinSourceClass.SIMULATED_MODEL,
        source_id="model",
        source_timestamp_s=1.0,
        received_timestamp_s=1.01,
        frame=CoordinateFrame.WORLD,
        position_m=Vector3(),
    )
    deviation = coordinator.add_observations(session.session_id, observed, simulated)
    assert deviation.validity is TwinValidity.INCOMPATIBLE
    assert deviation.position_m is None
    assert coordinator.report(session.session_id).valid_sample_count == 0


def test_test_sessions_are_excluded_from_operator_results() -> None:
    coordinator = TwinCoordinator()
    session = coordinator.create_session(session_config(test_only=True))
    assert coordinator.list_sessions() == ()
    assert coordinator.list_sessions(include_test=True) == (session,)
