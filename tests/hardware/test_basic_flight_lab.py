from __future__ import annotations

import asyncio
import csv
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.hardware import basic_flight_lab as basic_flight_lab_module
from crazyswarm_app.hardware.acrobatics_lab import (
    ACROBATICS_CLUSTER_ID,
    SINGLE_ROLL_MOTION_ID,
)
from crazyswarm_app.hardware.basic_flight_lab import (
    CHECKPOINT_SHAPE_MAX_CENTER_RADIUS_M,
    CHECKPOINT_SHAPE_MAX_SPEED_M_S,
    CHECKPOINT_SHAPE_SIDE_M,
    PHYSICAL_BASIC_FLIGHT_MOTION_IDS,
    PHYSICAL_FLIGHT_MOTION_IDS,
    BasicFlightLabRunRequest,
    BasicFlightLabService,
    MotorBenchStartRequest,
    MotorBenchStopRequest,
    MotorBenchUpdateRequest,
    PhysicalBasicFlightRunRequest,
    _contained_flight_commands,
)
from crazyswarm_app.hardware.observation_twin import PhysicalCommandTarget
from crazyswarm_app.simulation.world import load_scenario
from crazyswarm_app.vehicles.crazyflie import CrazyflieVehicle
from crazyswarm_app.vehicles.crazyflie_link import CrazyflieRawSample
from tests.hardware.test_crazyflie_adapter import URI, FakeCrazyflieLink


@pytest.mark.asyncio
async def test_commissioning_baseline_runs_privately_and_retains_learning_data(
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
    artifact = tmp_path / "learning" / "basic-flight.jsonl"
    service = BasicFlightLabService(runtime, artifact_path=artifact)

    result = await service.run(BasicFlightLabRunRequest())

    assert result.status == "COMPLETED"
    assert result.execution_backend == "FAST_SIM"
    assert result.qualification_claim == "NONE"
    assert result.learning_sample.final_state == "READY"
    assert result.learning_sample.landing_contact_observed is True
    assert result.learning_sample.maximum_altitude_m <= 0.5
    assert (
        result.learning_sample.battery_end_percent <= result.learning_sample.battery_start_percent
    )
    assert [step.status for step in result.steps if step.step_id == "motors-30"] == ["MODELED_ONLY"]
    assert artifact.read_text(encoding="utf-8").count("\n") == 1
    assert "twin-lab-fast-sim" not in runtime.vehicles


@pytest.mark.asyncio
async def test_catalog_separates_learning_signals_from_qualification(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )

    catalog = BasicFlightLabService(runtime).catalog()

    assert catalog.cluster_name == "Basic flight"
    assert catalog.qualification_claim == "NONE"
    assert {motion.major_mission for motion in catalog.motions} >= {
        "Ground readiness",
        "First liftoff",
        "Hover stability",
        "Move and return",
        "Land elsewhere",
        "Checkpoint shapes",
        "Continuous path",
        "Heading",
        "Shape flight",
        "Recovery",
    }
    assert catalog.motions[0].physical_execution == "OPERATOR_GATED"
    assert {
        motion.motion_id
        for motion in catalog.motions
        if motion.physical_execution == "OPERATOR_GATED"
    } == PHYSICAL_BASIC_FLIGHT_MOTION_IDS
    assert all(
        "battery start/minimum/end" in motion.learning_signals
        for motion in catalog.motions
        if motion.cluster_id == "basic-flight"
    )
    tuning = next(
        cluster
        for cluster in catalog.clusters
        if cluster.cluster_id == "controller-characterization-tuning"
    )
    assert tuning.state == "READY"
    assert catalog.controller_tuning_fixture is not None
    assert catalog.controller_tuning_fixture.state == "AWAITING_MEASUREMENTS"
    assert catalog.controller_tuning_fixture.implemented_flights_available is True
    assert [cluster.cluster_id for cluster in catalog.clusters] == [
        "basic-flight",
        "controller-characterization-tuning",
        ACROBATICS_CLUSTER_ID,
    ]
    acrobatics = catalog.clusters[-1]
    acrobatics_motion = next(
        motion for motion in catalog.motions if motion.motion_id == SINGLE_ROLL_MOTION_ID
    )
    assert acrobatics.cluster_name == "Cushioned acrobatics"
    assert acrobatics.state == "READY"
    assert acrobatics_motion.catalog_visibility is True
    assert acrobatics_motion.physical_execution == "OPERATOR_GATED"
    assert acrobatics_motion.implementation_state == "READY"
    assert acrobatics_motion.block_reason is None
    assert acrobatics_motion.steps[0].title == "Start and hover at 50 cm"
    assert "±0.50 m" in acrobatics_motion.steps[2].containment
    assert "motor-cut setpoint" in acrobatics_motion.steps[-2].containment


def test_physical_curriculum_stays_inside_low_slow_containment() -> None:
    for motion_id in PHYSICAL_FLIGHT_MOTION_IDS:
        if motion_id.startswith("tuning-"):
            continue
        x_m = 0.0
        y_m = 0.0
        for _, payload in _contained_flight_commands(
            motion_id,
            commissioning_hover_duration_s=30.0,
        ):
            if not isinstance(payload, MoveRelativeCommand):
                continue
            x_m += payload.x_m  # type: ignore[union-attr]
            y_m += payload.y_m  # type: ignore[union-attr]
            distance_m = (payload.x_m**2 + payload.y_m**2) ** 0.5  # type: ignore[union-attr]
            if motion_id in {
                "l-shape-stops-40cm",
                "square-stops-40cm",
                "triangle-stops-40cm",
            }:
                assert distance_m <= CHECKPOINT_SHAPE_SIDE_M + 1e-6
                maximum_center_radius_m = CHECKPOINT_SHAPE_MAX_CENTER_RADIUS_M
            else:
                assert distance_m <= 0.20 + 1e-6
                maximum_center_radius_m = 0.20
            assert (  # type: ignore[union-attr]
                distance_m / payload.duration_s <= CHECKPOINT_SHAPE_MAX_SPEED_M_S + 1e-6
            )
            assert (x_m**2 + y_m**2) ** 0.5 <= maximum_center_radius_m + 1e-6
            assert payload.z_m == 0.0  # type: ignore[union-attr]
            assert payload.yaw_rad == 0.0  # type: ignore[union-attr]


def test_checkpoint_shapes_are_centered_larger_and_return_home() -> None:
    for motion_id in (
        "l-shape-stops-40cm",
        "square-stops-40cm",
        "triangle-stops-40cm",
    ):
        x_m = 0.0
        y_m = 0.0
        move_distances: list[float] = []
        positions: list[tuple[float, float]] = [(x_m, y_m)]
        for _, payload in _contained_flight_commands(
            motion_id,
            commissioning_hover_duration_s=30.0,
        ):
            if not isinstance(payload, MoveRelativeCommand):
                continue
            x_m += payload.x_m  # type: ignore[union-attr]
            y_m += payload.y_m  # type: ignore[union-attr]
            move_distances.append(
                (payload.x_m**2 + payload.y_m**2) ** 0.5  # type: ignore[union-attr]
            )
            positions.append((x_m, y_m))

        assert max(move_distances) == pytest.approx(CHECKPOINT_SHAPE_SIDE_M)
        assert max((x**2 + y**2) ** 0.5 for x, y in positions) <= (
            CHECKPOINT_SHAPE_MAX_CENTER_RADIUS_M + 1e-6
        )
        assert x_m == pytest.approx(0.0)
        assert y_m == pytest.approx(0.0)


def test_checkpoint_shape_catalog_copy_names_40_cm_geometry() -> None:
    motions = {
        motion.motion_id: motion
        for motion in basic_flight_lab_module.basic_flight_catalog().motions
    }

    assert motions["l-shape-stops"].variant == "L-shape · 0.10 m legs"
    assert motions["square-stops"].variant == "Square · 0.10 m sides"
    assert motions["triangle-stops"].variant == "Triangle · 0.10 m sides"
    assert motions["l-shape-stops-40cm"].variant == "L-shape · 0.40 m legs"
    assert motions["square-stops-40cm"].variant == "Square · 0.40 m sides"
    assert motions["triangle-stops-40cm"].variant == "Triangle · 0.40 m sides"


@pytest.mark.asyncio
async def test_horizontal_task_waits_for_measured_takeoff_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowCaptureLink(FakeCrazyflieLink):
        capture_pending = False
        first_move_started_at: tuple[float, float] | None = None

        def takeoff(self, height_m: float, duration_s: float, yaw_rad: float | None) -> None:
            super().takeoff(height_m, duration_s, yaw_rad)
            self.values["stateEstimate.z"] = 0.14
            self.values["stateEstimate.vz"] = 0.20
            self.capture_pending = True

        def read_sample(self) -> CrazyflieRawSample:
            self.timestamp_ms += 100
            if self.capture_pending:
                next_height_m = min(0.30, self.values["stateEstimate.z"] + 0.04)
                self.values["stateEstimate.z"] = next_height_m
                self.values["stateEstimate.vz"] = 0.04 if next_height_m < 0.30 else 0.0
                if next_height_m >= 0.30:
                    self.capture_pending = False
            return super().read_sample()

        def go_to_relative(
            self,
            x_m: float,
            y_m: float,
            z_m: float,
            yaw_rad: float,
            duration_s: float,
        ) -> None:
            if self.first_move_started_at is None:
                self.first_move_started_at = (
                    self.values["stateEstimate.z"],
                    self.values["stateEstimate.vz"],
                )
            super().go_to_relative(x_m, y_m, z_m, yaw_rad, duration_s)

    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = SlowCaptureLink(high_level_enabled="0")

    async def skip_command_duration(
        vehicle: object, _duration_s: float, **_kwargs: object
    ) -> None:
        await vehicle.snapshot()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        skip_command_duration,
    )
    result = await BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
    ).run_physical(
        PhysicalBasicFlightRunRequest(motion_id="forward-10cm-return"),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    assert result.status == "COMPLETED"
    assert link.first_move_started_at == pytest.approx((0.30, 0.0))
    assert any(step.step_id == "takeoff-capture" for step in result.steps)


@pytest.mark.asyncio
async def test_airborne_stability_guard_uses_existing_failure_abort_and_land_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FloorContactDuringHoverLink(FakeCrazyflieLink):
        def hold_position(self, duration_s: float) -> None:
            super().hold_position(duration_s)
            self.values["stateEstimate.z"] = 0.02
            self.values["range.zrange"] = 20.0

    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = FloorContactDuringHoverLink(high_level_enabled="0")
    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.AIRBORNE_GUARD_FLOOR_PERSISTENCE_S",
        0.0,
    )

    async def sample_once(
        vehicle: CrazyflieVehicle,
        _duration_s: float,
        *,
        stability_guard: object | None = None,
    ) -> None:
        sample = await vehicle.snapshot()
        if stability_guard is not None:
            stability_guard.observe(sample)  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        sample_once,
    )
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        physical_hover_duration_s=0.01,
    )

    with pytest.raises(CrazySwarmError) as rejected:
        await service.run_physical(
            PhysicalBasicFlightRunRequest(motion_id="commissioning-baseline"),
            target=PhysicalCommandTarget(
                selected_uri=URI,
                vehicle_label="Test Crazyflie",
                observed_identity_sha256="a" * 64,
            ),
            operator_id="test-operator",
        )

    assert rejected.value.code is ErrorCode.PREFLIGHT_FAILED
    assert rejected.value.details["trigger"] == "near_floor"
    assert [item[0] for item in link.commands].count("land") == 1
    assert link.bitfield & (1 << 4) == 0


@pytest.mark.asyncio
async def test_physical_play_normalizes_grounded_armed_state_before_flight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = FakeCrazyflieLink(high_level_enabled="0")
    link.bitfield = (1 << 0) | (1 << 1)

    async def skip_command_duration(
        vehicle: object, _duration_s: float, **_kwargs: object
    ) -> None:
        await vehicle.snapshot()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        skip_command_duration,
    )
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        physical_hover_duration_s=0.01,
    )

    started = await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(motion_id="commissioning-baseline"),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )
    assert started.state == "STARTING"
    for _ in range(200):
        terminal = await service.physical_flight_status()
        if not terminal.stop_required:
            break
        await asyncio.sleep(0.01)

    assert terminal.state == "COMPLETED", terminal.detail
    assert terminal.result is not None
    assert terminal.result.status == "COMPLETED"
    assert [command[0] for command in link.commands] == [
        "arm",
        "arm",
        "takeoff",
        "hold",
        "land",
        "arm",
    ]
    assert link.commands[0] == ("arm", False)
    assert link.commands[1] == ("arm", True)
    assert link.commands[-1] == ("arm", False)
    assert link.estimator_reset_calls == 1
    assert link.disconnect_calls == 1


@pytest.mark.asyncio
async def test_physical_play_accepts_firmware_auto_armed_ground_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = FakeCrazyflieLink(high_level_enabled="0")
    link.bitfield = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3)

    async def skip_command_duration(
        vehicle: object, _duration_s: float, **_kwargs: object
    ) -> None:
        await vehicle.snapshot()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        skip_command_duration,
    )
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        physical_hover_duration_s=0.01,
    )

    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(motion_id="commissioning-baseline"),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )
    for _ in range(200):
        terminal = await service.physical_flight_status()
        if not terminal.stop_required:
            break
        await asyncio.sleep(0.01)

    assert terminal.state == "COMPLETED", terminal.detail
    assert terminal.stop_required is False
    assert [command[0] for command in link.commands] == [
        "takeoff",
        "hold",
        "land",
    ]
    assert all(command != ("arm", False) for command in link.commands)
    assert terminal.command_evidence[0]["command_kind"] == "takeoff"
    assert terminal.command_evidence[-1]["command_kind"] == "land"


@pytest.mark.asyncio
async def test_auto_armed_observer_clears_stale_abort_marker(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    marker = config.cache_directory / "physical-flight-operation.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "operation_id": "failed-auto-arm-normalization",
                "motion_id": "commissioning-baseline",
                "selected_uri": URI,
                "vehicle_label": "Test Crazyflie",
                "observed_identity_sha256": "a" * 64,
                "operator_id": "test-operator",
                "started_at_utc": datetime.now(UTC).isoformat(),
                "state": "FAILED",
                "stop_required": True,
                "detail": "preflight disarm was not retained",
                "command_evidence": [{"command_kind": "disarm", "phase": "OUTCOME_UNKNOWN"}],
            }
        ),
        encoding="utf-8",
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    service = BasicFlightLabService(runtime)

    recovered = await service.reconcile_physical_flight_stop(
        observation_current=True,
        armed=True,
        flying=False,
        auto_arming=True,
    )

    assert recovered.state == "ABORTED"
    assert recovered.stop_required is False
    assert "grounded and not flying" in (recovered.detail or "")
    assert json.loads(marker.read_text(encoding="utf-8"))["stop_required"] is False


@pytest.mark.asyncio
async def test_offset_landing_runs_selected_physical_plan_with_fake_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = FakeCrazyflieLink(high_level_enabled="0")

    async def skip_command_duration(
        vehicle: object, _duration_s: float, **_kwargs: object
    ) -> None:
        await vehicle.snapshot()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        skip_command_duration,
    )
    service = BasicFlightLabService(runtime, physical_link_factory=lambda: link)

    result = await service.run_physical(
        PhysicalBasicFlightRunRequest(motion_id="land-forward-10cm"),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    assert result.motion_id == "land-forward-10cm"
    assert [command[0] for command in link.commands] == [
        "arm",
        "takeoff",
        "move",
        "hold",
        "land",
        "arm",
    ]
    assert link.commands[2] == ("move", 0.10, 0.0, 0.0, 0.0, 1.0)
    assert link.values["stateEstimate.x"] == pytest.approx(0.10)
    assert link.estimator_reset_calls == 1
    assert link.commands[-1] == ("arm", False)


@pytest.mark.asyncio
async def test_contained_flight_provider_uses_preconnected_observer_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = FakeCrazyflieLink(high_level_enabled="0")
    observer = CrazyflieVehicle(
        vehicle_id="observer",
        selected_uri=URI,
        link=link,
        observation_only=True,
    )
    await observer.connect()

    async def provide_vehicle(
        vehicle_id: str,
        _target: PhysicalCommandTarget,
    ) -> CrazyflieVehicle:
        return observer.borrow_connected_command_adapter(vehicle_id=vehicle_id)

    async def skip_command_duration(
        vehicle: object, _duration_s: float, **_kwargs: object
    ) -> None:
        await vehicle.snapshot()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        skip_command_duration,
    )
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: pytest.fail("a second physical link was opened"),
        physical_vehicle_provider=provide_vehicle,
    )

    result = await service.run_physical(
        PhysicalBasicFlightRunRequest(motion_id="land-forward-10cm"),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    assert result.status == "COMPLETED"
    assert link.connect_calls == [URI]
    assert link.disconnect_calls == 0
    assert (await observer.snapshot()).telemetry.flying is False
    await observer.disconnect()
    assert link.disconnect_calls == 1


@pytest.mark.asyncio
async def test_every_catalog_motion_has_an_executable_fast_sim_rehearsal(
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
    service = BasicFlightLabService(runtime)

    basic_motions = [
        motion for motion in service.catalog().motions if motion.cluster_id == "basic-flight"
    ]
    results = [
        await service.run(BasicFlightLabRunRequest(motion_id=motion.motion_id))
        for motion in basic_motions
    ]

    assert all(result.status == "COMPLETED" for result in results)
    assert all(result.learning_sample.maximum_altitude_m <= 0.5 for result in results)
    assert {result.motion_id for result in results} == {
        motion.motion_id for motion in basic_motions
    }


@pytest.mark.asyncio
async def test_contained_physical_run_treats_battery_and_range_as_learning_data(
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
    link = FakeCrazyflieLink(high_level_enabled="0")
    link.values["range.zrange"] = 250.0
    link.values["pm.batteryLevel"] = 10.0
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        physical_hover_duration_s=0.05,
    )
    request = PhysicalBasicFlightRunRequest()

    result = await service.run_physical(
        request,
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    assert result.execution_backend == "REAL_CRAZYFLIE"
    assert result.evidence_class == "MEASURED_REAL"
    assert result.qualification_claim == "NONE"
    assert [command[0] for command in link.commands] == [
        "arm",
        "takeoff",
        "hold",
        "land",
        "arm",
    ]
    assert link.commands[-1] == ("arm", False)
    assert link.estimator_reset_calls == 1
    assert link.disconnect_calls == 1
    telemetry_path = Path(result.artifact_path)
    assert telemetry_path.is_file()
    with telemetry_path.open(encoding="utf-8", newline="") as telemetry_file:
        rows = list(csv.DictReader(telemetry_file))
    assert len(rows) == result.telemetry_row_count
    assert len(rows) >= 10
    assert {row["operating_mode"] for row in rows} == {"LIVE"}
    assert {row["source_clock_id"] for row in rows} == {"crazyflie-firmware"}
    assert {row["ground_truth_x_m"] for row in rows} == {""}
    assert len(result.telemetry_csv_sha256 or "") == 64


@pytest.mark.asyncio
async def test_scheduled_physical_flight_returns_immediately_and_global_abort_lands(
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
    link = FakeCrazyflieLink(high_level_enabled="0")
    terminal = AsyncMock()
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        physical_hover_duration_s=5.0,
        physical_flight_terminal_callback=terminal,
    )

    started = await asyncio.wait_for(
        service.start_physical_flight(
            PhysicalBasicFlightRunRequest(),
            target=PhysicalCommandTarget(
                selected_uri=URI,
                vehicle_label="Test Crazyflie",
                observed_identity_sha256="a" * 64,
            ),
            operator_id="test-operator",
        ),
        timeout=0.1,
    )

    assert started.state == "STARTING"
    assert started.stop_required is True
    for _ in range(100):
        if (await service.physical_flight_status()).state == "RUNNING":
            break
        await asyncio.sleep(0.01)
    assert (await service.physical_flight_status()).state == "RUNNING"

    aborted = await service.abort_physical_flight()

    assert aborted.state == "ABORTED", aborted.detail
    assert aborted.stop_required is False
    assert any(command[0] == "land" for command in link.commands)
    assert link.commands[-1] == ("arm", False)
    terminal.assert_awaited_once()


@pytest.mark.asyncio
async def test_cushioned_acrobatics_waits_at_50_cm_for_one_flip_then_lands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = FakeCrazyflieLink(high_level_enabled="0")

    async def skip_command_duration(
        vehicle: object, _duration_s: float, **_kwargs: object
    ) -> None:
        await vehicle.snapshot()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        skip_command_duration,
    )
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        acrobatics_trigger_timeout_s=1.0,
        acrobatics_recovery_duration_s=0.01,
    )

    started = await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(motion_id=SINGLE_ROLL_MOTION_ID),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )
    assert started.state == "STARTING"

    for _ in range(200):
        hovering = await service.physical_flight_status()
        if hovering.state == "HOVERING_READY":
            break
        await asyncio.sleep(0.01)
    assert hovering.state == "HOVERING_READY", hovering.detail
    assert hovering.available_action == "FLIP"
    assert ("takeoff", 0.5, 2.0, None) in link.commands
    assert not any(command[0] == "body-rate-thrust" for command in link.commands)

    flipping = await service.request_acrobatics_flip()
    assert flipping.state == "FLIPPING"
    assert flipping.available_action is None
    assert (await service.request_acrobatics_flip()).state == "FLIPPING"

    for _ in range(200):
        terminal = await service.physical_flight_status()
        if not terminal.stop_required:
            break
        await asyncio.sleep(0.01)
    assert terminal.state == "COMPLETED", terminal.detail
    assert terminal.result is not None
    assert terminal.result.learning_sample.maximum_altitude_m == pytest.approx(0.5)
    assert [command[0] for command in link.commands].count("body-rate-thrust") == 1
    assert [command[0] for command in link.commands][-2:] == ["land", "arm"]


@pytest.mark.asyncio
async def test_abort_during_flip_releases_rate_stream_before_one_landing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingRollLink(FakeCrazyflieLink):
        def __init__(self) -> None:
            super().__init__(high_level_enabled="0")
            self.roll_started = threading.Event()
            self.release_roll = threading.Event()

        def stream_body_rate_thrust(self, setpoints, sample_period_s):  # type: ignore[no-untyped-def]
            self.commands.append(("body-rate-thrust", setpoints, sample_period_s))
            self.roll_started.set()
            if not self.release_roll.wait(timeout=1.0):
                raise RuntimeError("test roll did not receive cancellation")

        def cancel_body_rate_thrust(self) -> None:
            self.commands.append(("body-rate-cancel",))
            self.release_roll.set()

    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = BlockingRollLink()

    async def skip_command_duration(
        vehicle: object, _duration_s: float, **_kwargs: object
    ) -> None:
        await vehicle.snapshot()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        skip_command_duration,
    )
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        acrobatics_trigger_timeout_s=1.0,
        acrobatics_recovery_duration_s=0.01,
    )
    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(motion_id=SINGLE_ROLL_MOTION_ID),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )
    for _ in range(200):
        if (await service.physical_flight_status()).state == "HOVERING_READY":
            break
        await asyncio.sleep(0.01)
    await service.request_acrobatics_flip()
    for _ in range(200):
        if link.roll_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert link.roll_started.is_set()

    aborted = await service.abort_physical_flight()

    assert aborted.state == "ABORTED"
    command_names = [command[0] for command in link.commands]
    assert command_names.count("body-rate-thrust") == 1
    assert command_names.count("body-rate-cancel") == 1
    assert command_names.count("land") == 1
    assert command_names.index("body-rate-cancel") < command_names.index("land")


@pytest.mark.asyncio
async def test_abort_request_acknowledges_before_landing_completes(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = FakeCrazyflieLink(high_level_enabled="0")
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        physical_hover_duration_s=5.0,
    )
    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )
    for _ in range(100):
        if (await service.physical_flight_status()).state == "RUNNING":
            break
        await asyncio.sleep(0.01)

    acknowledged = await asyncio.wait_for(
        service.request_physical_flight_abort(),
        timeout=0.1,
    )

    assert acknowledged.state == "ABORTING"
    assert acknowledged.stop_required is True
    terminal = await service.physical_flight_status()
    for _ in range(500):
        terminal = await service.physical_flight_status()
        if not terminal.stop_required:
            break
        await asyncio.sleep(0.01)
    assert terminal.state == "ABORTED"
    assert terminal.stop_required is False


@pytest.mark.asyncio
async def test_abort_while_play_is_connecting_cancels_without_recovery_link(
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
    created_links: list[FakeCrazyflieLink] = []

    def link_factory() -> FakeCrazyflieLink:
        link = FakeCrazyflieLink(high_level_enabled="0")
        created_links.append(link)
        return link

    service = BasicFlightLabService(runtime, physical_link_factory=link_factory)
    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    acknowledged = await service.request_physical_flight_abort()
    assert acknowledged.state == "ABORTING"
    for _ in range(200):
        terminal = await service.physical_flight_status()
        if not terminal.stop_required:
            break
        await asyncio.sleep(0.01)

    assert terminal.state == "ABORTED"
    assert terminal.stop_required is False
    assert len(created_links) == 1
    assert created_links[0].commands == []


@pytest.mark.asyncio
async def test_connection_failure_before_any_command_does_not_invent_active_flight(
    tmp_path: Path,
) -> None:
    class ConnectionFailureLink(FakeCrazyflieLink):
        def connect(self, selected_uri: str):  # type: ignore[no-untyped-def]
            del selected_uri
            raise RuntimeError("radio unavailable")

    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: ConnectionFailureLink(high_level_enabled="0"),
    )
    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    for _ in range(200):
        terminal = await service.physical_flight_status()
        if terminal.state == "FAILED":
            break
        await asyncio.sleep(0.01)

    assert terminal.state == "FAILED"
    assert terminal.stop_required is False
    assert terminal.command_evidence == ()
    assert "did not start" in (terminal.detail or "")

    later_outage = await service.reconcile_physical_flight_stop(
        observation_current=False,
        armed=None,
        flying=None,
        fallback_target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
    )
    assert later_outage.state == "FAILED"
    assert later_outage.stop_required is False


@pytest.mark.asyncio
async def test_post_connect_failure_before_any_command_does_not_require_abort(
    tmp_path: Path,
) -> None:
    class PostConnectTelemetryFailureLink(FakeCrazyflieLink):
        def __init__(self) -> None:
            super().__init__(high_level_enabled="0")
            self.read_count = 0

        def read_sample(self):  # type: ignore[no-untyped-def]
            self.read_count += 1
            if self.read_count > 1:
                raise RuntimeError("supervisor stream disappeared")
            return super().read_sample()

    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = PostConnectTelemetryFailureLink()
    service = BasicFlightLabService(runtime, physical_link_factory=lambda: link)
    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    for _ in range(200):
        terminal = await service.physical_flight_status()
        if terminal.state == "FAILED":
            break
        await asyncio.sleep(0.01)

    assert terminal.state == "FAILED"
    assert terminal.stop_required is False
    assert terminal.command_evidence == ()
    assert "did not start" in (terminal.detail or "")


@pytest.mark.asyncio
async def test_observer_outage_does_not_invent_an_active_physical_flight(
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
    service = BasicFlightLabService(runtime)

    status = await service.reconcile_physical_flight_stop(
        observation_current=False,
        armed=None,
        flying=None,
        fallback_target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
    )

    assert status.state == "IDLE"
    assert status.stop_required is False
    assert not (config.cache_directory / "physical-flight-operation.json").exists()


@pytest.mark.asyncio
async def test_legacy_observer_recovery_marker_is_ignored(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    marker = config.cache_directory / "physical-flight-operation.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "operation_id": "observer-recovery-legacy",
                "motion_id": "commissioning-baseline",
                "selected_uri": URI,
                "vehicle_label": "Test Crazyflie",
                "observed_identity_sha256": "a" * 64,
                "operator_id": "observer-state-recovery",
                "started_at_utc": datetime.now(UTC).isoformat(),
                "state": "STOP_UNCONFIRMED",
                "stop_required": True,
            }
        ),
        encoding="utf-8",
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )

    status = await BasicFlightLabService(runtime).physical_flight_status()

    assert status.state == "IDLE"
    assert status.stop_required is False


@pytest.mark.asyncio
async def test_recovered_observer_ground_state_clears_unconfirmed_abort(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = FakeCrazyflieLink(high_level_enabled="0")

    def fail_land(_height_m: float, _duration_s: float) -> None:
        raise RuntimeError("radio acknowledgement disappeared")

    link.land = fail_land  # type: ignore[method-assign]
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        physical_hover_duration_s=5.0,
    )
    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )
    for _ in range(500):
        running = await service.physical_flight_status()
        if running.state == "RUNNING":
            break
        await asyncio.sleep(0.01)
    assert running.state == "RUNNING"
    failed = await service.abort_physical_flight()
    assert failed.state == "FAILED"
    assert failed.stop_required is True
    assert failed.failure_details is not None
    assert failed.command_evidence[-1]["phase"] == "OUTCOME_UNKNOWN"
    assert failed.command_evidence[-1]["failure"]["details"]["automatic_retry_safe"] is False

    reconciled = await service.reconcile_physical_flight_stop(
        observation_current=True,
        armed=False,
        flying=False,
    )

    assert reconciled.state == "ABORTED"
    assert reconciled.stop_required is False
    assert "confirmed" in (reconciled.detail or "")

    later_outage = await service.reconcile_physical_flight_stop(
        observation_current=False,
        armed=None,
        flying=None,
        fallback_target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
    )

    assert later_outage.state == "ABORTED"
    assert later_outage.stop_required is False


@pytest.mark.asyncio
async def test_abort_reconnects_after_active_link_loss_and_confirms_stop(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    active_link = FakeCrazyflieLink(high_level_enabled="0")

    def lose_active_link(_height_m: float, _duration_s: float) -> None:
        active_link.connected = False
        raise RuntimeError("radio link disappeared during abort")

    active_link.land = lose_active_link  # type: ignore[method-assign]
    recovery_link = FakeCrazyflieLink(high_level_enabled="0")
    recovery_link.bitfield |= (1 << 1) | (1 << 4)
    links = iter((active_link, recovery_link))
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: next(links),
        physical_hover_duration_s=5.0,
    )
    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )
    for _ in range(100):
        if (await service.physical_flight_status()).state == "RUNNING":
            break
        await asyncio.sleep(0.01)

    aborted = await service.abort_physical_flight()

    assert aborted.state == "ABORTED"
    assert aborted.stop_required is False
    assert recovery_link.connect_calls == [URI]
    assert [command[0] for command in recovery_link.commands] == ["land", "arm"]
    assert "OUTCOME_UNKNOWN" in [item["phase"] for item in aborted.command_evidence]
    assert [item["phase"] for item in aborted.command_evidence[-2:]] == [
        "COMPLETED",
        "COMPLETED",
    ]


@pytest.mark.asyncio
async def test_preflight_supervisor_failure_does_not_open_abort_recovery(
    tmp_path: Path,
) -> None:
    class UnknownSupervisorLink(FakeCrazyflieLink):
        def read_sample(self):  # type: ignore[no-untyped-def]
            sample = super().read_sample()
            return sample.__class__(
                source_timestamp_ms=sample.source_timestamp_ms,
                received_at_monotonic_s=sample.received_at_monotonic_s,
                values=sample.values,
                supervisor_bitfield=None,
                link_quality_percent=sample.link_quality_percent,
                link_latency_ms=sample.link_latency_ms,
                connected=sample.connected,
            )

    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    initial_link = UnknownSupervisorLink(high_level_enabled="0")
    recovery_link = FakeCrazyflieLink(high_level_enabled="0")
    recovery_link.bitfield |= 1 << 1
    links = iter((initial_link, recovery_link))
    service = BasicFlightLabService(runtime, physical_link_factory=lambda: next(links))
    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )
    for _ in range(100):
        if (await service.physical_flight_status()).state == "FAILED":
            break
        await asyncio.sleep(0.01)

    failed = await service.abort_physical_flight()

    assert failed.state == "FAILED"
    assert failed.stop_required is False
    assert failed.command_evidence == ()
    assert recovery_link.connect_calls == []
    assert recovery_link.commands == []


@pytest.mark.asyncio
async def test_process_restart_restores_uncertain_flight_and_abort_reconnects_exact_uri(
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
    marker = config.cache_directory / "physical-flight-operation.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "operation_id": "interrupted-flight",
                "motion_id": "commissioning-baseline",
                "selected_uri": URI,
                "vehicle_label": "Test Crazyflie",
                "observed_identity_sha256": "a" * 64,
                "operator_id": "test-operator",
                "started_at_utc": datetime.now(UTC).isoformat(),
                "state": "RUNNING",
                "stop_required": True,
                "detail": "Physical drone action running",
                "command_evidence": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    recovery_link = FakeCrazyflieLink(high_level_enabled="0")
    recovery_link.bitfield |= (1 << 1) | (1 << 4)
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: recovery_link,
    )

    restored = await service.physical_flight_status()
    assert restored.state == "STOP_UNCONFIRMED"
    assert restored.stop_required is True

    aborted = await service.abort_physical_flight()

    assert aborted.state == "ABORTED"
    assert aborted.stop_required is False
    assert recovery_link.connect_calls == [URI]
    assert [command[0] for command in recovery_link.commands] == ["land", "arm"]
    assert [item["phase"] for item in aborted.command_evidence] == [
        "COMPLETED",
        "COMPLETED",
    ]
    persisted = json.loads(marker.read_text(encoding="utf-8"))
    assert persisted["state"] == "ABORTED"
    assert persisted["stop_required"] is False

    restarted = BasicFlightLabService(runtime)
    terminal = await restarted.physical_flight_status()
    assert terminal.state == "ABORTED"
    assert terminal.stop_required is False


@pytest.mark.asyncio
async def test_ground_readiness_physically_arms_observes_and_disarms(
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
    link = FakeCrazyflieLink(high_level_enabled="0")
    link.values.pop("range.zrange", None)
    live_samples = []
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        physical_arm_duration_s=0.05,
        physical_telemetry_callback=live_samples.append,
    )

    result = await service.run_physical(
        PhysicalBasicFlightRunRequest(motion_id="arm-disarm"),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    assert result.status == "COMPLETED"
    assert result.motion_id == "arm-disarm"
    assert [command[0] for command in link.commands] == ["arm", "arm"]
    assert link.commands == [("arm", True), ("arm", False)]
    assert link.estimator_reset_calls == 0
    assert (result.telemetry_row_count or 0) >= 5
    assert len(live_samples) == result.telemetry_row_count
    assert all(sample.telemetry.imu is not None for sample in live_samples)
    assert all(sample.telemetry.ranges is not None for sample in live_samples)


@pytest.mark.asyncio
async def test_physical_readiness_resets_estimator_without_sending_commands(
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
    link = FakeCrazyflieLink(high_level_enabled="0")
    link.values.pop("range.zrange", None)
    service = BasicFlightLabService(runtime, physical_link_factory=lambda: link)

    readiness = await service.assess_physical_readiness(
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        )
    )

    assert readiness.ready is True
    assert readiness.floor_distance_m is None
    assert readiness.physical_commands_sent is False
    assert link.commands == []
    assert link.estimator_reset_calls == 1


@pytest.mark.asyncio
async def test_live_motor_bench_updates_measured_pwm_and_retains_csv(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    link = FakeCrazyflieLink(high_level_enabled="0")
    link.bitfield |= (1 << 5) | (1 << 7)
    live_samples = []
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        physical_telemetry_callback=live_samples.append,
    )
    target = PhysicalCommandTarget(
        selected_uri=URI,
        vehicle_label="Test Crazyflie",
        observed_identity_sha256="a" * 64,
    )

    active = await service.start_motor_bench(
        MotorBenchStartRequest(
            motor_selection="all",
            props_removed_confirmed=True,
            physically_restrained_confirmed=True,
        ),
        target=target,
        operator_id="test-operator",
    )
    updated = await service.update_motor_bench(
        MotorBenchUpdateRequest(session_id=active.session_id, output_percent=70.0)
    )
    await service.update_motor_bench(
        MotorBenchUpdateRequest(session_id=active.session_id, output_percent=70.0)
    )
    await asyncio.sleep(0.15)
    stopped = await service.stop_motor_bench(MotorBenchStopRequest(session_id=active.session_id))

    assert link.crash_recovery_calls == 0
    assert updated.output_percent == 70.0
    assert stopped.status == "STOPPED"
    assert stopped.output_percent == 0.0
    assert stopped.measured_pwm_percent == pytest.approx((70.0, 70.0, 70.0, 70.0))
    assert stopped.telemetry_row_count >= 3
    assert stopped.telemetry_artifact_path is not None
    assert Path(stopped.telemetry_artifact_path).is_file()
    assert stopped.motor_csv_path is not None
    assert Path(stopped.motor_csv_path).is_file()
    assert len(stopped.motor_csv_sha256 or "") == 64
    assert link.commands.count(("motor-power", "all", 70.0)) == 1
    assert ("motor-watchdog",) in link.commands
    assert link.commands[-1] == ("motor-bench-stop",)
    assert stopped.firmware_watchdog_armed is True
    assert stopped.reboot_required is True
    assert len(live_samples) == stopped.telemetry_row_count
    assert all(sample.telemetry.imu is not None for sample in live_samples)
    assert all(sample.telemetry.ranges is not None for sample in live_samples)
    restarted_service = BasicFlightLabService(runtime)
    restarted_status = await restarted_service.motor_actuation_status()
    assert restarted_status.state == "IDLE"
    assert restarted_status.reboot_required is True


@pytest.mark.asyncio
async def test_motor_bench_heartbeat_loss_fails_closed_and_releases_radio(
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
    link = FakeCrazyflieLink(high_level_enabled="0")
    link.bitfield |= (1 << 5) | (1 << 7)
    release_radio = AsyncMock(return_value=object())
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        motor_watchdog_timeout_s=0.05,
        motor_bench_terminal_callback=release_radio,
    )
    target = PhysicalCommandTarget(
        selected_uri=URI,
        vehicle_label="Test Crazyflie",
        observed_identity_sha256="a" * 64,
    )

    active = await service.start_motor_bench(
        MotorBenchStartRequest(
            motor_selection="all",
            props_removed_confirmed=True,
            physically_restrained_confirmed=True,
        ),
        target=target,
        operator_id="test-operator",
    )
    await service.update_motor_bench(
        MotorBenchUpdateRequest(session_id=active.session_id, output_percent=35.0)
    )

    await asyncio.sleep(0.25)

    release_radio.assert_awaited_once()
    assert link.commands[-1] == ("motor-bench-stop",)
    assert link.motor_selection is None
    assert link.disconnect_calls == 1
    with pytest.raises(RuntimeError, match="motor bench session is not active"):
        await service.update_motor_bench(
            MotorBenchUpdateRequest(session_id=active.session_id, output_percent=35.0)
        )


@pytest.mark.asyncio
async def test_motor_bench_graceful_shutdown_fails_closed_and_releases_radio(
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
    link = FakeCrazyflieLink(high_level_enabled="0")
    link.bitfield |= (1 << 5) | (1 << 7)
    release_radio = AsyncMock(return_value=object())
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: link,
        motor_bench_terminal_callback=release_radio,
    )
    target = PhysicalCommandTarget(
        selected_uri=URI,
        vehicle_label="Test Crazyflie",
        observed_identity_sha256="a" * 64,
    )
    active = await service.start_motor_bench(
        MotorBenchStartRequest(
            motor_selection="all",
            props_removed_confirmed=True,
            physically_restrained_confirmed=True,
        ),
        target=target,
        operator_id="test-operator",
    )
    await service.update_motor_bench(
        MotorBenchUpdateRequest(session_id=active.session_id, output_percent=35.0)
    )

    await service.shutdown()

    release_radio.assert_awaited_once()
    assert link.commands[-1] == ("motor-bench-stop",)
    assert link.disconnect_calls == 1


@pytest.mark.asyncio
async def test_motor_bench_crash_marker_recovers_output_without_original_session(
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
    active_link = FakeCrazyflieLink(high_level_enabled="0")
    service = BasicFlightLabService(runtime, physical_link_factory=lambda: active_link)
    target = PhysicalCommandTarget(
        selected_uri=URI,
        vehicle_label="Test Crazyflie",
        observed_identity_sha256="a" * 64,
    )
    active = await service.start_motor_bench(
        MotorBenchStartRequest(
            motor_selection="all",
            props_removed_confirmed=True,
            physically_restrained_confirmed=True,
        ),
        target=target,
        operator_id="test-operator",
    )
    await service.update_motor_bench(
        MotorBenchUpdateRequest(session_id=active.session_id, output_percent=35.0)
    )
    assert ("motor-watchdog",) in active_link.commands

    # Simulate a hard process loss: the monitor disappears without running any
    # Python cleanup, while the durable marker and firmware parameters remain.
    assert service._motor_session is not None
    monitor = service._motor_session.monitor_task
    assert monitor is not None
    monitor.cancel()
    await asyncio.gather(monitor, return_exceptions=True)

    recovery_link = FakeCrazyflieLink(high_level_enabled="0")
    recovered_service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: recovery_link,
    )
    uncertain = await recovered_service.motor_actuation_status()
    assert uncertain.state == "POSSIBLY_ACTIVE"
    assert uncertain.stop_required is True
    assert uncertain.commanded_output_percent == 35.0
    assert uncertain.measured_output_active is None

    recovered = await recovered_service.recover_stale_motor_output(fallback_target=target)

    assert recovered.state == "IDLE"
    assert recovered.stop_required is False
    assert recovered.measured_output_active is False
    assert recovered.reboot_required is True
    assert recovery_link.commands[-1] == ("motor-bench-stop",)
    assert recovery_link.disconnect_calls == 1
    assert not (config.cache_directory / "motor-bench-actuation.json").exists()


@pytest.mark.asyncio
async def test_fresh_unlocked_supervisor_clears_power_cycle_marker(tmp_path: Path) -> None:
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    marker = config.cache_directory / "motor-bench-reboot-required"
    marker.parent.mkdir(parents=True)
    marker.touch()
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    service = BasicFlightLabService(runtime)

    stale = await service.reconcile_motor_reboot_required(
        observation_current=False,
        faults=(),
    )
    assert stale.reboot_required is True
    assert marker.exists()

    locked = await service.reconcile_motor_reboot_required(
        observation_current=True,
        faults=("SUPERVISOR_LOCKED",),
    )
    assert locked.reboot_required is True
    assert marker.exists()

    cleared = await service.reconcile_motor_reboot_required(
        observation_current=True,
        faults=(),
    )
    assert cleared.reboot_required is False
    assert not marker.exists()


@pytest.mark.asyncio
async def test_global_motor_stop_retains_uncertainty_when_zero_cannot_be_confirmed(
    tmp_path: Path,
) -> None:
    class StopFailureLink(FakeCrazyflieLink):
        def end_motor_power_override(self) -> None:
            raise RuntimeError("radio write failed")

    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    target = PhysicalCommandTarget(
        selected_uri=URI,
        vehicle_label="Test Crazyflie",
        observed_identity_sha256="a" * 64,
    )
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: StopFailureLink(high_level_enabled="0"),
    )

    status = await service.stop_all_motor_output(fallback_target=target)

    assert status.state == "STOP_FAILED"
    assert status.stop_required is True
    assert status.measured_output_active is None
    assert "radio write failed" in (status.detail or "")
    assert (config.cache_directory / "motor-bench-actuation.json").exists()


@pytest.mark.asyncio
async def test_global_motor_stop_bounds_a_stalled_radio_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowStopLink(FakeCrazyflieLink):
        def end_motor_power_override(self) -> None:
            time.sleep(0.2)
            super().end_motor_power_override()

    monkeypatch.setattr(basic_flight_lab_module, "MOTOR_STOP_IO_TIMEOUT_S", 0.05)
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    runtime = create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )
    target = PhysicalCommandTarget(
        selected_uri=URI,
        vehicle_label="Test Crazyflie",
        observed_identity_sha256="a" * 64,
    )
    service = BasicFlightLabService(
        runtime,
        physical_link_factory=lambda: SlowStopLink(high_level_enabled="0"),
    )

    started_at = time.monotonic()
    status = await service.stop_all_motor_output(fallback_target=target)

    assert time.monotonic() - started_at < 0.15
    assert status.state == "STOP_FAILED"
    assert status.stop_required is True
    assert "could not be confirmed" in (status.detail or "")
