from __future__ import annotations

import asyncio
import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.hardware.basic_flight_lab import (
    BasicFlightLabService,
    PhysicalBasicFlightRunRequest,
)
from crazyswarm_app.hardware.controller_tuning_lab import (
    CONTROLLER_TUNING_FLIGHT_MOTION_IDS,
    CONTROLLER_TUNING_RAW_MOTION_IDS,
    DEFAULT_CONTROLLER_TUNING_FIXTURE_PATH,
    ControllerTuningFixtureDefinition,
    FixturePose,
    controller_tuning_fixture_status,
    controller_tuning_flight_commands,
    fit_range_pose,
    fixture_heading_to_model_yaw_rad,
    load_controller_tuning_fixture,
    predict_fixture_ranges,
)
from crazyswarm_app.hardware.observation_twin import PhysicalCommandTarget
from crazyswarm_app.simulation.world import load_scenario
from crazyswarm_app.vehicles.crazyflie_link import CrazyflieConnectionMetadata
from tests.hardware.test_crazyflie_adapter import URI, FakeCrazyflieLink


def _fixture_payload() -> dict[str, object]:
    stations = [
        ("START", 1.0, 1.0, 0.03),
        ("CENTER", 1.0, 1.0, 0.30),
        ("X_POSITIVE", 1.30, 1.0, 0.30),
        ("X_NEGATIVE", 0.70, 1.0, 0.30),
        ("Y_POSITIVE", 1.0, 1.30, 0.30),
        ("Y_NEGATIVE", 1.0, 0.70, 0.30),
        ("HEIGHT_LOW", 1.0, 1.0, 0.20),
        ("HEIGHT_HIGH", 1.0, 1.0, 0.40),
        ("HOLDOUT_ONE", 1.20, 1.20, 0.30),
        ("HOLDOUT_TWO", 0.80, 0.80, 0.30),
    ]
    mounts = [
        ("front", 0.012, 0.0, 0.0, 1.0, 0.0, 0.0),
        ("back", -0.012, 0.0, 0.0, -1.0, 0.0, 0.0),
        ("left", 0.0, 0.012, 0.0, 0.0, 1.0, 0.0),
        ("right", 0.0, -0.012, 0.0, 0.0, -1.0, 0.0),
    ]
    return {
        "schema_version": 1,
        "fixture_id": "test-controller-box",
        "fixture_version": "1.0",
        "survey_status": "SURVEYED",
        "survey_date": "2026-08-23",
        "survey_frame": {
            "origin": "CLOSEST_INNER_CORNER",
            "positive_x_axis": "SHORT_SIDE",
            "positive_y_axis": "LONG_SIDE",
            "positive_z_axis": "UP",
        },
        "dimensions": {"inside_x_m": 2.0, "inside_y_m": 2.0, "wall_height_m": 1.2},
        "positive_x_wall_label": "A",
        "positive_y_wall_label": "B",
        "nominal_hover_height_m": 0.30,
        "safety_clearance_m": 0.20,
        "floor_markers": [
            {
                "marker_id": marker_id,
                "x_m": x_m,
                "y_m": y_m,
                "coordinate_source": "SCAN_DERIVED",
            }
            for marker_id, x_m, y_m in (
                ("A", 0.30, 0.30),
                ("B", 0.40, 1.10),
                ("C", 0.80, 0.80),
                ("D", 0.70, 0.20),
                ("E", 0.60, 0.67),
            )
        ],
        "marker_distances": [],
        "stations": [
            {"station_id": station_id, "x_m": x, "y_m": y, "z_m": z, "yaw_deg": 0.0}
            for station_id, x, y, z in stations
        ],
        "sensor_mounts": [
            {
                "sensor_id": sensor_id,
                "origin_x_m": ox,
                "origin_y_m": oy,
                "origin_z_m": oz,
                "direction_x": dx,
                "direction_y": dy,
                "direction_z": dz,
            }
            for sensor_id, ox, oy, oz, dx, dy, dz in mounts
        ],
        "wall_material": "braced board",
        "wall_finish": "matte light gray",
        "floor_texture_id": "test-floor-v1",
        "lighting_configuration": "fixed diffuse lamps",
    }


def _write_fixture(path: Path) -> ControllerTuningFixtureDefinition:
    path.write_text(json.dumps(_fixture_payload()), encoding="utf-8")
    return ControllerTuningFixtureDefinition.model_validate(_fixture_payload())


def _runtime(tmp_path: Path):
    config = load_config(Path("config/app.yaml")).model_copy(
        update={"cache_directory": tmp_path / "cache"}
    )
    return create_runtime(
        config,
        load_scenario(Path("config/worlds/one_drone.yaml")),
        evidence_path=tmp_path / "evidence.sqlite3",
    )


def test_draft_fixture_exposes_a_to_e_and_keeps_f_to_h_raw(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    catalog = BasicFlightLabService(runtime).catalog()
    tuning = [
        motion
        for motion in catalog.motions
        if motion.cluster_id == "controller-characterization-tuning"
    ]

    assert {motion.major_mission[0] for motion in tuning} == set("ABCDEFGH")
    mission_a = [motion for motion in tuning if motion.major_mission.startswith("A ·")]
    assert [motion.variant for motion in mission_a] == list("ABCDE")
    assert {motion.placement_marker for motion in mission_a} == set("ABCDE")
    assert all(motion.motion == "Observe baseline" for motion in mission_a)
    assert all(motion.implementation_state == "READY" for motion in mission_a)
    mission_b = [motion for motion in tuning if motion.major_mission.startswith("B ·")]
    assert [motion.variant for motion in mission_b] == list("ABCDE")
    assert all(motion.implementation_state == "READY" for motion in mission_b)
    assert all(motion.block_reason is None for motion in mission_b)
    assert all(
        motion.implementation_state == "READY"
        for motion in tuning
        if motion.motion_id.startswith("tuning-c-")
    )
    assert {motion.motion_id for motion in tuning if motion.implementation_state == "RAW"} == set(
        CONTROLLER_TUNING_RAW_MOTION_IDS
    )
    assert all(
        not motion.steps and motion.physical_execution == "NOT_ENABLED"
        for motion in tuning
        if motion.motion_id in CONTROLLER_TUNING_RAW_MOTION_IDS
    )
    for letter in "ABCDE":
        variants = {
            motion.variant
            for motion in tuning
            if motion.major_mission.startswith(f"{letter} ·")
        }
        assert variants == set("ABCDE")


def test_default_fixture_records_corner_frame_and_trilaterated_marker_e() -> None:
    fixture = load_controller_tuning_fixture(DEFAULT_CONTROLLER_TUNING_FIXTURE_PATH)
    status = controller_tuning_fixture_status(fixture)
    markers = {marker.marker_id: marker for marker in fixture.floor_markers}
    distances = {
        frozenset((item.first_marker_id, item.second_marker_id)): item.distance_m
        for item in fixture.marker_distances
    }

    assert fixture.survey_frame.origin == "CLOSEST_INNER_CORNER"
    assert fixture.survey_frame.positive_x_axis == "SHORT_SIDE"
    assert fixture.survey_frame.positive_y_axis == "LONG_SIDE"
    assert fixture.placement_baseline.center_reference == ("DRONE_CENTER_OVER_SELECTED_FLOOR_X")
    assert fixture.placement_baseline.heading_zero == "FRONT_TOWARD_POSITIVE_Y"
    assert fixture.placement_baseline.heading_positive_90 == "FRONT_TOWARD_POSITIVE_X"
    assert fixture.placement_baseline.active_range_sensors == (
        "front",
        "back",
        "left",
        "right",
    )
    assert fixture.placement_baseline.excluded_range_sensors == ("up", "down")
    assert set(markers) == set("ABCDE")
    assert (markers["E"].x_m, markers["E"].y_m) == pytest.approx((0.603, 0.665))
    assert markers["E"].coordinate_source == "DISTANCE_TRILATERATED"
    assert distances == {
        frozenset(("E", "C")): pytest.approx(0.268),
        frozenset(("E", "B")): pytest.approx(0.441),
        frozenset(("E", "A")): pytest.approx(0.502),
    }
    residuals = [
        abs(
            (
                (markers["E"].x_m - markers[anchor].x_m) ** 2
                + (markers["E"].y_m - markers[anchor].y_m) ** 2
            )
            ** 0.5
            - distances[frozenset(("E", anchor))]
        )
        for anchor in "ABC"
    ]
    assert max(residuals) < 0.006
    mounts = {mount.sensor_id: mount for mount in fixture.sensor_mounts}
    assert set(mounts) == {"front", "back", "left", "right"}
    assert mounts["front"].origin_x_m == pytest.approx(0.012)
    assert mounts["back"].origin_x_m == pytest.approx(-0.012)
    assert mounts["left"].origin_y_m == pytest.approx(0.012)
    assert mounts["right"].origin_y_m == pytest.approx(-0.012)
    assert status.missing_fields == (
        "dimensions.wall_height_m",
        "safety_clearance_m",
    )
    assert status.implemented_flights_available is True
    assert status.detail == (
        "Controller-characterization metadata is still missing: wall height, wall safety "
        "clearance (including the drone envelope). Implemented flights remain "
        "operator-selectable."
    )


def test_fixture_heading_convention_is_clockwise_from_positive_y() -> None:
    assert fixture_heading_to_model_yaw_rad(0.0) == pytest.approx(math.pi / 2.0)
    assert fixture_heading_to_model_yaw_rad(45.0) == pytest.approx(math.pi / 4.0)
    assert fixture_heading_to_model_yaw_rad(90.0) == pytest.approx(0.0)


def test_completed_fixture_exposes_bounded_a_to_e_plans(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture = _write_fixture(fixture_path)
    status = controller_tuning_fixture_status(fixture, artifact_path=fixture_path)

    assert status.state == "READY"
    assert status.implemented_flights_available is True
    for motion_id in CONTROLLER_TUNING_FLIGHT_MOTION_IDS:
        commands = controller_tuning_flight_commands(motion_id, fixture)
        x_m = 0.0
        y_m = 0.0
        yaw_rad = 0.0
        for _, payload in commands:
            if not isinstance(payload, MoveRelativeCommand):
                continue
            x_m += payload.x_m
            y_m += payload.y_m
            yaw_rad += payload.yaw_rad
            horizontal_m = (payload.x_m**2 + payload.y_m**2) ** 0.5
            assert horizontal_m / payload.duration_s <= 0.10 + 1e-9
            assert (x_m**2 + y_m**2) ** 0.5 <= 0.30 + 1e-6
        assert x_m == pytest.approx(0.0)
        assert y_m == pytest.approx(0.0)
        assert yaw_rad == pytest.approx(0.0)


def test_fixture_ray_model_and_local_pose_fit_use_measured_geometry() -> None:
    fixture = ControllerTuningFixtureDefinition.model_validate(_fixture_payload())
    center = FixturePose(
        x_m=1.0,
        y_m=1.0,
        z_m=0.30,
        yaw_rad=fixture_heading_to_model_yaw_rad(0.0),
    )
    predicted = predict_fixture_ranges(fixture, center)

    assert predicted == pytest.approx(
        {
            "front": 0.988,
            "back": 0.988,
            "left": 0.988,
            "right": 0.988,
        }
    )
    displaced = FixturePose(
        x_m=1.20,
        y_m=0.90,
        z_m=0.30,
        yaw_rad=fixture_heading_to_model_yaw_rad(0.0),
    )
    measured = {
        key: value
        for key, value in predict_fixture_ranges(fixture, displaced).items()
        if value is not None
    }
    fit = fit_range_pose(fixture, measured, center)

    assert fit.residual_rms_m < 0.02
    assert fit.pose.x_m == pytest.approx(1.20, abs=0.02)
    assert fit.pose.y_m == pytest.approx(0.90, abs=0.02)


@pytest.mark.asyncio
async def test_draft_fixture_does_not_gate_an_implemented_flight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = FakeCrazyflieLink(high_level_enabled="0")

    async def skip_command_duration(
        vehicle: object, _duration_s: float, **_kwargs: object
    ) -> None:
        await vehicle.snapshot()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        skip_command_duration,
    )
    result = await BasicFlightLabService(
        _runtime(tmp_path),
        physical_link_factory=lambda: link,
    ).run_physical(
        PhysicalBasicFlightRunRequest(
            motion_id="tuning-b-center-hover",
            station_id="A",
            target_height_m=0.20,
        ),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    assert result.status == "COMPLETED"
    assert [command[0] for command in link.commands] == [
        "arm",
        "takeoff",
        "hold",
        "land",
        "arm",
    ]


@pytest.mark.asyncio
async def test_floor_baseline_records_without_sending_a_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = FakeCrazyflieLink(high_level_enabled="0")
    monkeypatch.setattr(
        "crazyswarm_app.hardware.basic_flight_lab.controller_tuning_observation_duration_s",
        lambda _motion_id: 0.01,
    )
    result = await BasicFlightLabService(
        _runtime(tmp_path),
        physical_link_factory=lambda: link,
    ).run_physical(
        PhysicalBasicFlightRunRequest(
            motion_id="tuning-a-station-a",
            station_id="A",
            heading_deg=45.0,
        ),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    assert result.status == "COMPLETED"
    assert result.motion_id == "tuning-a-station-a"
    assert link.commands == []
    assert [step.step_id for step in result.steps] == ["place", "observe"]
    assert result.controller_tuning_range_summary is not None
    assert result.controller_tuning_range_summary.model_status == "RAW_ONLY"
    assert result.controller_tuning_preparation is not None
    assert result.controller_tuning_preparation.station_id == "A"
    assert result.controller_tuning_preparation.heading_deg == pytest.approx(45.0)


@pytest.mark.asyncio
async def test_running_fixture_observation_stops_without_a_flight_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = FakeCrazyflieLink(high_level_enabled="0")
    monkeypatch.setattr(
        "crazyswarm_app.hardware.basic_flight_lab.controller_tuning_observation_duration_s",
        lambda _motion_id: 5.0,
    )
    service = BasicFlightLabService(
        _runtime(tmp_path),
        physical_link_factory=lambda: link,
    )
    await service.start_physical_flight(
        PhysicalBasicFlightRunRequest(
            motion_id="tuning-a-station-a",
            station_id="A",
        ),
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
    stopped = await service.abort_physical_flight(reason="stop fixture observation")
    assert stopped.state == "ABORTED"
    assert stopped.stop_required is False
    assert link.commands == []


@pytest.mark.asyncio
async def test_default_pid_vertical_baseline_uses_completed_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_path = tmp_path / "fixture.json"
    _write_fixture(fixture_path)
    link = FakeCrazyflieLink(high_level_enabled="0")

    async def skip_command_duration(
        vehicle: object, _duration_s: float, **_kwargs: object
    ) -> None:
        await vehicle.snapshot()  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "crazyswarm_app.vehicles.crazyflie.CrazyflieVehicle._wait_duration_and_refresh",
        skip_command_duration,
    )
    result = await BasicFlightLabService(
        _runtime(tmp_path),
        physical_link_factory=lambda: link,
        controller_tuning_fixture_path=fixture_path,
    ).run_physical(
        PhysicalBasicFlightRunRequest(
            motion_id="tuning-b-center-hover",
            station_id="C",
            heading_deg=45.0,
            target_height_m=0.30,
        ),
        target=PhysicalCommandTarget(
            selected_uri=URI,
            vehicle_label="Test Crazyflie",
            observed_identity_sha256="a" * 64,
        ),
        operator_id="test-operator",
    )

    assert result.status == "COMPLETED"
    assert result.controller_tuning_range_summary is not None
    assert result.controller_tuning_range_summary.model_status == "EVALUATED"
    assert result.controller_tuning_preparation is not None
    assert result.controller_tuning_preparation.station_id == "C"
    assert result.controller_tuning_preparation.heading_deg == pytest.approx(45.0)
    assert [command[0] for command in link.commands] == [
        "arm",
        "takeoff",
        "hold",
        "land",
        "arm",
    ]


@pytest.mark.asyncio
async def test_flight_rejects_a_non_pid_controller_before_takeoff(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    _write_fixture(fixture_path)

    class NonPidLink(FakeCrazyflieLink):
        def connect(self, selected_uri: str) -> CrazyflieConnectionMetadata:
            metadata = super().connect(selected_uri)
            return replace(
                metadata,
                observed_parameters={
                    **metadata.observed_parameters,
                    "stabilizer.controller": "2",
                },
            )

    link = NonPidLink(high_level_enabled="0")
    service = BasicFlightLabService(
        _runtime(tmp_path),
        physical_link_factory=lambda: link,
        controller_tuning_fixture_path=fixture_path,
    )

    with pytest.raises(RuntimeError, match="default PID controller"):
        await service.run_physical(
            PhysicalBasicFlightRunRequest(
                motion_id="tuning-b-center-hover",
                station_id="A",
            ),
            target=PhysicalCommandTarget(
                selected_uri=URI,
                vehicle_label="Test Crazyflie",
                observed_identity_sha256="a" * 64,
            ),
            operator_id="test-operator",
        )

    assert link.commands == []
