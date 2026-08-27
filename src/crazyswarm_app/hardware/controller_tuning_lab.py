from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.commands import CommandPayload, HoverCommand, MoveRelativeCommand
from crazyswarm_app.domain.models import ContractModel, CoordinateFrame
from crazyswarm_app.domain.telemetry import RangeStatus, TelemetryEnvelope

DEFAULT_CONTROLLER_TUNING_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "fixtures" / "controller-tuning-box-v1.json"
)

ControllerTuningMotionId = Literal[
    "tuning-a-floor-start",
    "tuning-a-raised-center",
    "tuning-a-station-a",
    "tuning-a-station-b",
    "tuning-a-station-c",
    "tuning-a-station-d",
    "tuning-a-station-e",
    "tuning-a-yaw-minus-45",
    "tuning-a-yaw-minus-30",
    "tuning-a-yaw-minus-15",
    "tuning-a-yaw-zero",
    "tuning-a-yaw-plus-15",
    "tuning-a-yaw-plus-30",
    "tuning-a-yaw-plus-45",
    "tuning-a-height-low",
    "tuning-a-height-nominal",
    "tuning-a-height-high",
    "tuning-a-holdout-one",
    "tuning-a-holdout-two",
    "tuning-b-center-hover",
    "tuning-c-x-plus-05",
    "tuning-c-x-minus-05",
    "tuning-c-y-plus-05",
    "tuning-c-y-minus-05",
    "tuning-c-x-plus-15",
    "tuning-c-x-minus-15",
    "tuning-c-y-plus-15",
    "tuning-c-y-minus-15",
    "tuning-c-x-plus-30",
    "tuning-c-x-minus-30",
    "tuning-c-y-plus-30",
    "tuning-c-y-minus-30",
    "tuning-d-yaw-zero",
    "tuning-d-yaw-plus-15",
    "tuning-d-yaw-minus-15",
    "tuning-d-yaw-plus-30",
    "tuning-d-yaw-minus-30",
    "tuning-d-slow-sweep",
    "tuning-d-off-center",
    "tuning-e-slow-x",
    "tuning-e-stress-x",
    "tuning-e-hold-x-positive",
    "tuning-e-hold-x-negative",
    "tuning-e-hold-y-positive",
    "tuning-e-hold-y-negative",
    "tuning-f-controller-comparison",
    "tuning-g-gain-refinement",
    "tuning-h-robustness-confirmation",
]
FixtureMarkerId = Literal["A", "B", "C", "D", "E"]

CONTROLLER_TUNING_OBSERVATION_MOTION_IDS: tuple[ControllerTuningMotionId, ...] = (
    "tuning-a-station-a",
    "tuning-a-station-b",
    "tuning-a-station-c",
    "tuning-a-station-d",
    "tuning-a-station-e",
)

CONTROLLER_TUNING_FLIGHT_MOTION_IDS: tuple[ControllerTuningMotionId, ...] = (
    "tuning-b-center-hover",
    "tuning-c-x-plus-05",
    "tuning-c-x-minus-05",
    "tuning-c-y-plus-05",
    "tuning-c-y-minus-05",
    "tuning-c-x-plus-15",
    "tuning-c-x-minus-15",
    "tuning-c-y-plus-15",
    "tuning-c-y-minus-15",
    "tuning-c-x-plus-30",
    "tuning-c-x-minus-30",
    "tuning-c-y-plus-30",
    "tuning-c-y-minus-30",
    "tuning-d-yaw-zero",
    "tuning-d-yaw-plus-15",
    "tuning-d-yaw-minus-15",
    "tuning-d-yaw-plus-30",
    "tuning-d-yaw-minus-30",
    "tuning-d-slow-sweep",
    "tuning-d-off-center",
    "tuning-e-slow-x",
    "tuning-e-stress-x",
    "tuning-e-hold-x-positive",
    "tuning-e-hold-x-negative",
    "tuning-e-hold-y-positive",
    "tuning-e-hold-y-negative",
)

CONTROLLER_TUNING_RAW_MOTION_IDS: tuple[ControllerTuningMotionId, ...] = (
    "tuning-f-controller-comparison",
    "tuning-g-gain-refinement",
    "tuning-h-robustness-confirmation",
)

CONTROLLER_TUNING_PHYSICAL_MOTION_IDS = frozenset(
    (*CONTROLLER_TUNING_OBSERVATION_MOTION_IDS, *CONTROLLER_TUNING_FLIGHT_MOTION_IDS)
)


class FixtureDimensions(ContractModel):
    inside_x_m: float | None = Field(default=None, gt=0.0)
    inside_y_m: float | None = Field(default=None, gt=0.0)
    wall_height_m: float | None = Field(default=None, gt=0.0)


class FixtureStation(ContractModel):
    station_id: str = Field(min_length=1, max_length=80)
    x_m: float | None = None
    y_m: float | None = None
    z_m: float | None = Field(default=None, ge=0.0)
    yaw_deg: float | None = Field(default=None, ge=-180.0, le=180.0)
    placement_uncertainty_m: float | None = Field(default=None, ge=0.0)
    yaw_uncertainty_deg: float | None = Field(default=None, ge=0.0)


class FixtureSurveyFrame(ContractModel):
    origin: Literal["CLOSEST_INNER_CORNER"] = "CLOSEST_INNER_CORNER"
    positive_x_axis: Literal["SHORT_SIDE"] = "SHORT_SIDE"
    positive_y_axis: Literal["LONG_SIDE"] = "LONG_SIDE"
    positive_z_axis: Literal["UP"] = "UP"


class FixtureFloorMarker(ContractModel):
    marker_id: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z][A-Z0-9_-]*$")
    x_m: float = Field(ge=0.0)
    y_m: float = Field(ge=0.0)
    coordinate_source: Literal["SCAN_DERIVED", "DISTANCE_TRILATERATED"]
    coordinate_uncertainty_m: float | None = Field(default=None, ge=0.0)
    fit_residual_rms_m: float | None = Field(default=None, ge=0.0)


class FixtureMarkerDistance(ContractModel):
    first_marker_id: str = Field(min_length=1, max_length=20)
    second_marker_id: str = Field(min_length=1, max_length=20)
    distance_m: float = Field(gt=0.0)


class FixturePlacementBaseline(ContractModel):
    center_reference: Literal["DRONE_CENTER_OVER_SELECTED_FLOOR_X"] = (
        "DRONE_CENTER_OVER_SELECTED_FLOOR_X"
    )
    heading_zero: Literal["FRONT_TOWARD_POSITIVE_Y"] = "FRONT_TOWARD_POSITIVE_Y"
    heading_positive_90: Literal["FRONT_TOWARD_POSITIVE_X"] = "FRONT_TOWARD_POSITIVE_X"
    positive_heading_direction: Literal["FROM_POSITIVE_Y_TOWARD_POSITIVE_X"] = (
        "FROM_POSITIVE_Y_TOWARD_POSITIVE_X"
    )
    body_positive_x_axis: Literal["FRONT"] = "FRONT"
    body_positive_y_axis: Literal["LEFT"] = "LEFT"
    body_positive_z_axis: Literal["UP"] = "UP"
    active_range_sensors: tuple[
        Literal["front"], Literal["back"], Literal["left"], Literal["right"]
    ] = ("front", "back", "left", "right")
    excluded_range_sensors: tuple[Literal["up"], Literal["down"]] = ("up", "down")


class FixtureSensorMount(ContractModel):
    sensor_id: Literal["front", "back", "left", "right"]
    origin_x_m: float | None = None
    origin_y_m: float | None = None
    origin_z_m: float | None = None
    direction_x: float | None = None
    direction_y: float | None = None
    direction_z: float | None = None
    position_uncertainty_m: float | None = Field(default=None, ge=0.0)
    angular_uncertainty_deg: float | None = Field(default=None, ge=0.0)


class ControllerTuningFixtureDefinition(ContractModel):
    schema_version: Literal[1] = 1
    fixture_id: str = Field(min_length=1, max_length=100)
    fixture_version: str = Field(min_length=1, max_length=40)
    survey_status: Literal["AWAITING_MEASUREMENTS", "SURVEYED"] = "AWAITING_MEASUREMENTS"
    survey_date: str | None = None
    survey_frame: FixtureSurveyFrame = Field(default_factory=FixtureSurveyFrame)
    placement_baseline: FixturePlacementBaseline = Field(default_factory=FixturePlacementBaseline)
    dimensions: FixtureDimensions = Field(default_factory=FixtureDimensions)
    positive_x_wall_label: str | None = None
    positive_y_wall_label: str | None = None
    nominal_hover_height_m: float | None = Field(default=None, gt=0.0, le=0.50)
    safety_clearance_m: float | None = Field(default=None, gt=0.0)
    floor_markers: tuple[FixtureFloorMarker, ...] = ()
    marker_distances: tuple[FixtureMarkerDistance, ...] = ()
    stations: tuple[FixtureStation, ...] = ()
    sensor_mounts: tuple[FixtureSensorMount, ...] = ()
    wall_material: str | None = None
    wall_finish: str | None = None
    floor_texture_id: str | None = None
    lighting_configuration: str | None = None
    environmental_notes: str | None = None

    @model_validator(mode="after")
    def marker_geometry_is_consistent(self) -> ControllerTuningFixtureDefinition:
        marker_ids = tuple(marker.marker_id for marker in self.floor_markers)
        if len(marker_ids) != len(set(marker_ids)):
            raise ValueError("fixture floor marker IDs must be unique")
        known_markers = set(marker_ids)
        distance_pairs: set[frozenset[str]] = set()
        for measurement in self.marker_distances:
            if measurement.first_marker_id == measurement.second_marker_id:
                raise ValueError("fixture marker distance endpoints must differ")
            if {
                measurement.first_marker_id,
                measurement.second_marker_id,
            } - known_markers:
                raise ValueError("fixture marker distances must reference configured markers")
            pair = frozenset((measurement.first_marker_id, measurement.second_marker_id))
            if pair in distance_pairs:
                raise ValueError("fixture marker distance pairs must be unique")
            distance_pairs.add(pair)
        return self


class ControllerTuningFixtureStatus(ContractModel):
    fixture_id: str
    fixture_version: str
    artifact_path: str
    state: Literal["AWAITING_MEASUREMENTS", "READY", "INVALID"]
    implemented_flights_available: bool
    missing_fields: tuple[str, ...] = ()
    detail: str


class FixturePose(ContractModel):
    x_m: float
    y_m: float
    z_m: float
    roll_rad: float = 0.0
    pitch_rad: float = 0.0
    yaw_rad: float = 0.0


class RangeFitResult(ContractModel):
    pose: FixturePose
    residual_rms_m: float = Field(ge=0.0)
    valid_sensor_count: int = Field(ge=0, le=4)
    continuity_constrained: Literal[True] = True


class ControllerTuningRangeSummary(ContractModel):
    fixture_id: str
    fixture_version: str
    model_status: Literal["EVALUATED", "RAW_ONLY"]
    prediction_source: Literal["CONFIGURED_PLACEMENT", "ESTIMATOR_POSE", "UNAVAILABLE"]
    valid_range_value_count: int = Field(default=0, ge=0)
    pose_prediction_residual_rms_m: float | None = Field(default=None, ge=0.0)
    opposing_range_sum_residual_rms_m: float | None = Field(default=None, ge=0.0)
    fitted_pose_sample_count: int = Field(default=0, ge=0)
    estimator_to_range_xy_rms_m: float | None = Field(default=None, ge=0.0)
    continuity_constrained: Literal[True] = True
    qualification_claim: Literal["NONE"] = "NONE"
    detail: str


@dataclass(frozen=True, slots=True)
class TuningStepSpec:
    step_id: str
    title: str
    behavior: str
    containment: str


@dataclass(frozen=True, slots=True)
class TuningMotionSpec:
    motion_id: ControllerTuningMotionId
    major_mission: str
    variant: str
    placement_marker: FixtureMarkerId | None
    motion: str
    summary: str
    physical_scope: Literal["FIXTURE_OBSERVATION", "CONTAINED_FLIGHT"]
    physical_execution: Literal["NOT_ENABLED", "OPERATOR_GATED"]
    implementation_state: Literal["READY", "SETUP_REQUIRED", "RAW"]
    block_reason: str | None
    steps: tuple[TuningStepSpec, ...]
    learning_signals: tuple[str, ...]


def load_controller_tuning_fixture(
    path: Path = DEFAULT_CONTROLLER_TUNING_FIXTURE_PATH,
) -> ControllerTuningFixtureDefinition:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ControllerTuningFixtureDefinition.model_validate(payload)


def controller_tuning_fixture_status(
    fixture: ControllerTuningFixtureDefinition,
    *,
    artifact_path: Path = DEFAULT_CONTROLLER_TUNING_FIXTURE_PATH,
) -> ControllerTuningFixtureStatus:
    missing: list[str] = []
    invalid: list[str] = []
    dimensions = fixture.dimensions
    for name, value in (
        ("dimensions.inside_x_m", dimensions.inside_x_m),
        ("dimensions.inside_y_m", dimensions.inside_y_m),
        ("dimensions.wall_height_m", dimensions.wall_height_m),
        ("safety_clearance_m", fixture.safety_clearance_m),
        ("wall_material", fixture.wall_material),
    ):
        if value is None or value == "":
            missing.append(name)
    markers = {marker.marker_id: marker for marker in fixture.floor_markers}
    for marker_id in "ABCDE":
        if marker_id not in markers:
            missing.append(f"floor_markers.{marker_id}")
    mounts = {mount.sensor_id: mount for mount in fixture.sensor_mounts}
    for sensor_id in ("front", "back", "left", "right"):
        mount = mounts.get(sensor_id)
        if mount is None:
            missing.append(f"sensor_mounts.{sensor_id}")
            continue
        values = (
            mount.origin_x_m,
            mount.origin_y_m,
            mount.origin_z_m,
            mount.direction_x,
            mount.direction_y,
            mount.direction_z,
        )
        if any(value is None for value in values):
            missing.append(f"sensor_mounts.{sensor_id}.geometry")
        elif not math.isclose(
            math.sqrt(sum(float(value) ** 2 for value in values[3:])),
            1.0,
            abs_tol=1e-3,
        ):
            missing.append(f"sensor_mounts.{sensor_id}.unit_direction")
    if (
        dimensions.inside_x_m is not None
        and dimensions.inside_y_m is not None
        and dimensions.wall_height_m is not None
        and fixture.safety_clearance_m is not None
    ):
        minimum_x_m = fixture.safety_clearance_m
        minimum_y_m = fixture.safety_clearance_m
        maximum_x_m = dimensions.inside_x_m - fixture.safety_clearance_m
        maximum_y_m = dimensions.inside_y_m - fixture.safety_clearance_m
        maximum_z_m = dimensions.wall_height_m - fixture.safety_clearance_m
        if (
            min(
                maximum_x_m - minimum_x_m,
                maximum_y_m - minimum_y_m,
                maximum_z_m,
            )
            <= 0.0
        ):
            invalid.append("safety_clearance_m")
        for station in fixture.stations:
            if (
                station.x_m is not None
                and station.y_m is not None
                and station.z_m is not None
                and (
                    station.x_m < minimum_x_m - 1e-9
                    or station.x_m > maximum_x_m + 1e-9
                    or station.y_m < minimum_y_m - 1e-9
                    or station.y_m > maximum_y_m + 1e-9
                    or station.z_m > maximum_z_m + 1e-9
                )
            ):
                invalid.append(f"stations.{station.station_id}.outside_working_volume")
        center = next(
            (station for station in fixture.stations if station.station_id == "CENTER"),
            None,
        )
        if center is not None and (
            center.x_m is not None
            and center.y_m is not None
            and (
                not math.isclose(center.x_m, dimensions.inside_x_m / 2.0, abs_tol=1e-6)
                or not math.isclose(center.y_m, dimensions.inside_y_m / 2.0, abs_tol=1e-6)
            )
        ):
            invalid.append("stations.CENTER.must_match_fixture_center")
        for marker in fixture.floor_markers:
            if (
                marker.x_m < minimum_x_m - 1e-9
                or marker.x_m > maximum_x_m + 1e-9
                or marker.y_m < minimum_y_m - 1e-9
                or marker.y_m > maximum_y_m + 1e-9
            ):
                invalid.append(f"floor_markers.{marker.marker_id}.outside_working_volume")
        if fixture.nominal_hover_height_m is not None and (
            fixture.nominal_hover_height_m > maximum_z_m + 1e-9
        ):
            invalid.append("nominal_hover_height_m.outside_working_volume")
    if invalid:
        return ControllerTuningFixtureStatus(
            fixture_id=fixture.fixture_id,
            fixture_version=fixture.fixture_version,
            artifact_path=str(artifact_path),
            state="INVALID",
            implemented_flights_available=True,
            missing_fields=tuple(dict.fromkeys(invalid)),
            detail=(
                "Fixture geometry is internally inconsistent for characterization analysis. "
                "Implemented flights remain operator-selectable."
            ),
        )
    if missing:
        field_labels = {
            "dimensions.inside_x_m": "inside short-side length",
            "dimensions.inside_y_m": "inside long-side length",
            "dimensions.wall_height_m": "wall height",
            "safety_clearance_m": "wall safety clearance (including the drone envelope)",
            "wall_material": "wall material",
        }
        labels = [field_labels.get(field, field.replace("_", " ")) for field in missing]
        return ControllerTuningFixtureStatus(
            fixture_id=fixture.fixture_id,
            fixture_version=fixture.fixture_version,
            artifact_path=str(artifact_path),
            state="AWAITING_MEASUREMENTS",
            implemented_flights_available=True,
            missing_fields=tuple(dict.fromkeys(missing)),
            detail=(
                "Controller-characterization metadata is still missing: "
                f"{', '.join(labels)}. Implemented flights remain operator-selectable."
            ),
        )
    if fixture.survey_status != "SURVEYED":
        return ControllerTuningFixtureStatus(
            fixture_id=fixture.fixture_id,
            fixture_version=fixture.fixture_version,
            artifact_path=str(artifact_path),
            state="AWAITING_MEASUREMENTS",
            implemented_flights_available=True,
            missing_fields=("survey_status",),
            detail=(
                "The fixture survey is not marked surveyed. This is characterization "
                "metadata, not a flight unlock."
            ),
        )
    return ControllerTuningFixtureStatus(
        fixture_id=fixture.fixture_id,
        fixture_version=fixture.fixture_version,
        artifact_path=str(artifact_path),
        state="READY",
        implemented_flights_available=True,
        detail="The fixture characterization metadata is complete.",
    )


def load_controller_tuning_fixture_status(
    path: Path = DEFAULT_CONTROLLER_TUNING_FIXTURE_PATH,
) -> tuple[ControllerTuningFixtureDefinition | None, ControllerTuningFixtureStatus]:
    try:
        fixture = load_controller_tuning_fixture(path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return None, ControllerTuningFixtureStatus(
            fixture_id="controller-tuning-box",
            fixture_version="unavailable",
            artifact_path=str(path),
            state="INVALID",
            implemented_flights_available=False,
            missing_fields=("fixture_artifact",),
            detail=f"Fixture artifact is unavailable or invalid: {error}",
        )
    return fixture, controller_tuning_fixture_status(fixture, artifact_path=path)


def controller_tuning_motion_block_reason(
    motion_id: str,
    fixture: ControllerTuningFixtureDefinition | None,
    status: ControllerTuningFixtureStatus,
) -> str | None:
    if motion_id in CONTROLLER_TUNING_RAW_MOTION_IDS:
        return "Raw future stage; no executable workflow is attached yet."
    if motion_id == "tuning-a-floor-start":
        return None
    if motion_id.startswith("tuning-a-station-"):
        if fixture is None or status.state == "INVALID":
            return status.detail
        marker_id = motion_id.rsplit("-", 1)[-1].upper()
        if marker_id not in {marker.marker_id for marker in fixture.floor_markers}:
            return f"Floor marker {marker_id} is unavailable in the fixture artifact."
        return None
    if motion_id in CONTROLLER_TUNING_OBSERVATION_MOTION_IDS:
        return None
    if fixture is None:
        return status.detail
    required_station_id = {
        "tuning-d-off-center": "X_POSITIVE",
        "tuning-e-hold-x-positive": "X_POSITIVE",
        "tuning-e-hold-x-negative": "X_NEGATIVE",
        "tuning-e-hold-y-positive": "Y_POSITIVE",
        "tuning-e-hold-y-negative": "Y_NEGATIVE",
    }.get(motion_id)
    if required_station_id is not None:
        stations = {station.station_id: station for station in fixture.stations}
        incomplete = [
            station_id
            for station_id in ("CENTER", required_station_id)
            if (
                (station := stations.get(station_id)) is None
                or station.x_m is None
                or station.y_m is None
            )
        ]
        if incomplete:
            return (
                "This command needs configured relative target geometry for "
                f"{', '.join(incomplete)}."
            )
    return None


def controller_tuning_flight_commands(
    motion_id: str,
    fixture: ControllerTuningFixtureDefinition,
) -> tuple[tuple[str, CommandPayload], ...]:
    if motion_id == "tuning-b-center-hover":
        return (("center-hover", HoverCommand(duration_s=25.0)),)

    transition = _transition_vector_for_motion(motion_id)
    if transition is not None:
        x_m, y_m, amplitude = transition
        duration_s = max(1.0, amplitude / 0.05)
        return (
            ("outbound", _move(x_m=x_m, y_m=y_m, duration_s=duration_s)),
            ("offset-hold", HoverCommand(duration_s=5.0)),
            ("return-center", _move(x_m=-x_m, y_m=-y_m, duration_s=duration_s)),
            ("center-hold", HoverCommand(duration_s=5.0)),
        )

    yaw_deg = {
        "tuning-d-yaw-plus-15": 15.0,
        "tuning-d-yaw-minus-15": -15.0,
        "tuning-d-yaw-plus-30": 30.0,
        "tuning-d-yaw-minus-30": -30.0,
    }.get(motion_id)
    if motion_id == "tuning-d-yaw-zero":
        return (("yaw-zero-hold", HoverCommand(duration_s=10.0)),)
    if yaw_deg is not None:
        yaw_rad = math.radians(yaw_deg)
        duration_s = max(2.0, abs(yaw_deg) / 10.0)
        return (
            ("yaw-out", _move(yaw_rad=yaw_rad, duration_s=duration_s)),
            ("yaw-hold", HoverCommand(duration_s=8.0)),
            ("yaw-return", _move(yaw_rad=-yaw_rad, duration_s=duration_s)),
            ("heading-hold", HoverCommand(duration_s=5.0)),
        )
    if motion_id == "tuning-d-slow-sweep":
        return (
            ("sweep-plus-30", _move(yaw_rad=math.radians(30.0), duration_s=6.0)),
            ("sweep-minus-30", _move(yaw_rad=math.radians(-60.0), duration_s=12.0)),
            ("sweep-return", _move(yaw_rad=math.radians(30.0), duration_s=6.0)),
            ("heading-hold", HoverCommand(duration_s=5.0)),
        )
    if motion_id == "tuning-d-off-center":
        x_m, y_m = _station_delta_from_center(fixture, "X_POSITIVE")
        return (
            ("move-off-center", _move(x_m=x_m, y_m=y_m, duration_s=_duration(x_m, y_m, 0.05))),
            ("off-center-hold", HoverCommand(duration_s=5.0)),
            ("yaw-plus-30", _move(yaw_rad=math.radians(30.0), duration_s=6.0)),
            ("yaw-hold", HoverCommand(duration_s=8.0)),
            ("yaw-return", _move(yaw_rad=math.radians(-30.0), duration_s=6.0)),
            ("return-center", _move(x_m=-x_m, y_m=-y_m, duration_s=_duration(x_m, y_m, 0.05))),
        )
    if motion_id in {"tuning-e-slow-x", "tuning-e-stress-x"}:
        speed_m_s = 0.05 if motion_id == "tuning-e-slow-x" else 0.10
        return (
            ("outbound", _move(x_m=0.30, duration_s=0.30 / speed_m_s)),
            ("offset-hold", HoverCommand(duration_s=8.0)),
            ("return-center", _move(x_m=-0.30, duration_s=0.30 / speed_m_s)),
            ("center-hold", HoverCommand(duration_s=5.0)),
        )
    station_id = {
        "tuning-e-hold-x-positive": "X_POSITIVE",
        "tuning-e-hold-x-negative": "X_NEGATIVE",
        "tuning-e-hold-y-positive": "Y_POSITIVE",
        "tuning-e-hold-y-negative": "Y_NEGATIVE",
    }.get(motion_id)
    if station_id is not None:
        x_m, y_m = _station_delta_from_center(fixture, station_id)
        return (
            ("move-to-station", _move(x_m=x_m, y_m=y_m, duration_s=_duration(x_m, y_m, 0.05))),
            ("station-hold", HoverCommand(duration_s=12.0)),
            ("return-center", _move(x_m=-x_m, y_m=-y_m, duration_s=_duration(x_m, y_m, 0.05))),
            ("center-hold", HoverCommand(duration_s=5.0)),
        )
    raise ValueError(f"motion is not an implemented controller-tuning flight: {motion_id}")


def controller_tuning_observation_duration_s(motion_id: str) -> float:
    if motion_id == "tuning-a-floor-start":
        return 45.0
    if motion_id == "tuning-a-raised-center":
        return 60.0
    if motion_id in {
        "tuning-a-yaw-minus-45",
        "tuning-a-yaw-minus-30",
        "tuning-a-yaw-minus-15",
        "tuning-a-yaw-zero",
        "tuning-a-yaw-plus-15",
        "tuning-a-yaw-plus-30",
        "tuning-a-yaw-plus-45",
    }:
        return 20.0
    return 30.0


def predict_fixture_ranges(
    fixture: ControllerTuningFixtureDefinition,
    pose: FixturePose,
) -> dict[str, float | None]:
    """Predict central-ray intersections with the four bounded vertical walls."""

    dimensions = fixture.dimensions
    if (
        dimensions.inside_x_m is None
        or dimensions.inside_y_m is None
        or dimensions.wall_height_m is None
    ):
        raise ValueError("fixture dimensions are incomplete")
    rotation = _rotation_matrix(pose.roll_rad, pose.pitch_rad, pose.yaw_rad)
    result: dict[str, float | None] = {}
    for mount in fixture.sensor_mounts:
        origin_values = (mount.origin_x_m, mount.origin_y_m, mount.origin_z_m)
        direction_values = (mount.direction_x, mount.direction_y, mount.direction_z)
        if any(value is None for value in (*origin_values, *direction_values)):
            result[mount.sensor_id] = None
            continue
        origin_offset = _matvec(rotation, tuple(float(value) for value in origin_values))
        direction = _matvec(rotation, tuple(float(value) for value in direction_values))
        origin = (
            pose.x_m + origin_offset[0],
            pose.y_m + origin_offset[1],
            pose.z_m + origin_offset[2],
        )
        candidates: list[float] = []
        for axis, plane in (
            (0, dimensions.inside_x_m),
            (0, 0.0),
            (1, dimensions.inside_y_m),
            (1, 0.0),
        ):
            component = direction[axis]
            if abs(component) <= 1e-9:
                continue
            distance = (plane - origin[axis]) / component
            if distance <= 0.0:
                continue
            intersection = tuple(origin[index] + distance * direction[index] for index in range(3))
            if (
                -1e-9 <= intersection[0] <= dimensions.inside_x_m + 1e-9
                and -1e-9 <= intersection[1] <= dimensions.inside_y_m + 1e-9
                and -1e-9 <= intersection[2] <= dimensions.wall_height_m + 1e-9
            ):
                candidates.append(distance)
        result[mount.sensor_id] = min(candidates) if candidates else None
    return result


def fit_range_pose(
    fixture: ControllerTuningFixtureDefinition,
    measured_ranges_m: dict[str, float],
    initial_pose: FixturePose,
) -> RangeFitResult:
    """Fit x/y/yaw locally while retaining continuity from a known initial pose."""

    if len(measured_ranges_m) < 3:
        return RangeFitResult(
            pose=initial_pose,
            residual_rms_m=float("inf"),
            valid_sensor_count=len(measured_ranges_m),
        )
    dimensions = fixture.dimensions
    if dimensions.inside_x_m is None or dimensions.inside_y_m is None:
        raise ValueError("fixture dimensions are incomplete")
    clearance = fixture.safety_clearance_m or 0.0
    minimum_x = clearance
    maximum_x = dimensions.inside_x_m - clearance
    minimum_y = clearance
    maximum_y = dimensions.inside_y_m - clearance

    def score(candidate: FixturePose) -> float:
        predicted = predict_fixture_ranges(fixture, candidate)
        residuals = [
            measured - predicted[sensor_id]
            for sensor_id, measured in measured_ranges_m.items()
            if predicted.get(sensor_id) is not None
        ]
        return (
            math.sqrt(sum(value * value for value in residuals) / len(residuals))
            if residuals
            else float("inf")
        )

    best = initial_pose
    best_score = score(best)
    for xy_step_m, yaw_step_deg in ((0.08, 6.0), (0.025, 2.0), (0.008, 0.5)):
        anchor = best
        for x_index in range(-2, 3):
            for y_index in range(-2, 3):
                for yaw_index in range(-2, 3):
                    candidate = anchor.model_copy(
                        update={
                            "x_m": max(minimum_x, min(maximum_x, anchor.x_m + x_index * xy_step_m)),
                            "y_m": max(minimum_y, min(maximum_y, anchor.y_m + y_index * xy_step_m)),
                            "yaw_rad": anchor.yaw_rad + math.radians(yaw_index * yaw_step_deg),
                        }
                    )
                    candidate_score = score(candidate)
                    if candidate_score < best_score:
                        best = candidate
                        best_score = candidate_score
    return RangeFitResult(
        pose=best,
        residual_rms_m=best_score,
        valid_sensor_count=len(measured_ranges_m),
    )


def summarize_controller_tuning_ranges(
    fixture: ControllerTuningFixtureDefinition,
    motion_id: str,
    samples: Sequence[TelemetryEnvelope],
    *,
    station_id: FixtureMarkerId | None = None,
    heading_deg: float = 0.0,
    target_height_m: float | None = None,
) -> ControllerTuningRangeSummary:
    dimensions = fixture.dimensions
    geometry_available = (
        dimensions.inside_x_m is not None
        and dimensions.inside_y_m is not None
        and dimensions.wall_height_m is not None
        and {mount.sensor_id for mount in fixture.sensor_mounts}
        == {"front", "back", "left", "right"}
    )
    if not geometry_available:
        return ControllerTuningRangeSummary(
            fixture_id=fixture.fixture_id,
            fixture_version=fixture.fixture_version,
            model_status="RAW_ONLY",
            prediction_source="UNAVAILABLE",
            valid_range_value_count=sum(
                value is not None
                for sample in samples
                if sample.telemetry.ranges is not None
                for value in (
                    sample.telemetry.ranges.front_m,
                    sample.telemetry.ranges.back_m,
                    sample.telemetry.ranges.left_m,
                    sample.telemetry.ranges.right_m,
                )
            ),
            detail="Raw ranges retained; measured fixture or ranger geometry is incomplete.",
        )
    estimator_residuals: list[float] = []
    opposing_residuals: list[float] = []
    fitted_xy_errors: list[float] = []
    valid_value_count = 0
    fitted_count = 0
    fitting_stride = max(1, len(samples) // 80)
    fixed_pose = _observation_pose(
        fixture,
        motion_id,
        station_id=station_id,
        heading_deg=heading_deg,
        target_height_m=target_height_m,
    )
    for sample_index, sample in enumerate(samples):
        telemetry = sample.telemetry
        ranges = telemetry.ranges
        attitude = telemetry.attitude
        position = telemetry.position_m
        if ranges is None:
            continue
        measured = {
            sensor_id: value
            for sensor_id, value in (
                ("front", ranges.front_m),
                ("back", ranges.back_m),
                ("left", ranges.left_m),
                ("right", ranges.right_m),
            )
            if value is not None
            and ranges.statuses.get(sensor_id, RangeStatus.VALID) == RangeStatus.VALID
        }
        valid_value_count += len(measured)
        pose = fixed_pose
        if (
            pose is None
            and motion_id not in CONTROLLER_TUNING_OBSERVATION_MOTION_IDS
            and position is not None
            and attitude is not None
        ):
            marker = next(
                (item for item in fixture.floor_markers if item.marker_id == station_id),
                None,
            )
            center = _required_station(fixture, "CENTER") if marker is None else None
            base_x_m = float(marker.x_m) if marker is not None else float(center.x_m)
            base_y_m = float(marker.y_m) if marker is not None else float(center.y_m)
            pose = FixturePose(
                x_m=base_x_m + position.x,
                y_m=base_y_m + position.y,
                z_m=position.z,
                roll_rad=attitude.roll_rad,
                pitch_rad=attitude.pitch_rad,
                yaw_rad=(
                    fixture_heading_to_model_yaw_rad(heading_deg) + attitude.yaw_rad
                ),
            )
        if pose is None:
            continue
        predicted = predict_fixture_ranges(fixture, pose)
        estimator_residuals.extend(
            measured[sensor_id] - predicted[sensor_id]
            for sensor_id in measured
            if predicted.get(sensor_id) is not None
        )
        for first, second in (("front", "back"), ("left", "right")):
            if (
                first in measured
                and second in measured
                and predicted.get(first) is not None
                and predicted.get(second) is not None
            ):
                opposing_residuals.append(
                    measured[first]
                    + measured[second]
                    - float(predicted[first])
                    - float(predicted[second])
                )
        if sample_index % fitting_stride == 0 and len(measured) >= 3:
            fit = fit_range_pose(fixture, measured, pose)
            if math.isfinite(fit.residual_rms_m):
                fitted_count += 1
                fitted_xy_errors.append(
                    math.hypot(fit.pose.x_m - pose.x_m, fit.pose.y_m - pose.y_m)
                )

    evaluated = bool(estimator_residuals)
    return ControllerTuningRangeSummary(
        fixture_id=fixture.fixture_id,
        fixture_version=fixture.fixture_version,
        model_status="EVALUATED" if evaluated else "RAW_ONLY",
        prediction_source=(
            "CONFIGURED_PLACEMENT"
            if fixed_pose is not None
            else "ESTIMATOR_POSE"
            if evaluated
            else "UNAVAILABLE"
        ),
        valid_range_value_count=valid_value_count,
        pose_prediction_residual_rms_m=_rms(estimator_residuals),
        opposing_range_sum_residual_rms_m=_rms(opposing_residuals),
        fitted_pose_sample_count=fitted_count,
        estimator_to_range_xy_rms_m=_rms(fitted_xy_errors),
        detail=(
            "Central-ray fixture residuals and continuity-constrained range-derived "
            "poses evaluated."
            if evaluated
            else "Raw ranges retained; the configured pose or valid ranger values were unavailable."
        ),
    )


def controller_tuning_specs(
    fixture: ControllerTuningFixtureDefinition | None,
    status: ControllerTuningFixtureStatus,
) -> tuple[TuningMotionSpec, ...]:
    range_signals = (
        "raw front/back/left/right ranges and validity",
        "source and receive timestamps",
        "estimator position and attitude",
        "opposing-range consistency",
        "fixture/model residuals when survey geometry is available",
    )
    flight_signals = (
        *range_signals,
        "command target and controller response",
        "rise, overshoot, settling, and steady-state error",
        "cross-axis, altitude, and yaw coupling",
        "battery, attitude, body rate, and motor activity",
    )

    def step(step_id: str, title: str, behavior: str, containment: str) -> TuningStepSpec:
        return TuningStepSpec(step_id, title, behavior, containment)

    def observation(
        motion_id: ControllerTuningMotionId,
        marker_id: FixtureMarkerId,
    ) -> TuningMotionSpec:
        block = controller_tuning_motion_block_reason(motion_id, fixture, status)
        summary = (
            f"Center the drone over floor marker {marker_id}, set the typed fixture "
            "heading, and retain one motors-off range baseline."
        )
        return TuningMotionSpec(
            motion_id=motion_id,
            major_mission="A · Fixture & sensor baseline",
            variant=marker_id,
            placement_marker=marker_id,
            motion="Observe baseline",
            summary=summary,
            physical_scope="FIXTURE_OBSERVATION",
            physical_execution="OPERATOR_GATED",
            implementation_state="READY" if block is None else "SETUP_REQUIRED",
            block_reason=block,
            steps=(
                step(
                    "place",
                    f"Place at marker {marker_id}",
                    summary,
                    "Motors off; center the drone over the marked X.",
                ),
                step(
                    "observe",
                    f"Record for {controller_tuning_observation_duration_s(motion_id):g} s",
                    "Keep motors off and retain every measured range sample.",
                    "No flight or motor command is issued.",
                ),
            ),
            learning_signals=range_signals,
        )

    specs: list[TuningMotionSpec] = []
    for marker_id in ("A", "B", "C", "D", "E"):
        motion_id = f"tuning-a-station-{marker_id.lower()}"
        specs.append(
            observation(
                motion_id,  # type: ignore[arg-type]
                marker_id,
            )
        )

    def flight(
        motion_id: ControllerTuningMotionId,
        major: str,
        marker_id: FixtureMarkerId,
        title: str,
        summary: str,
        task_steps: tuple[TuningStepSpec, ...],
    ) -> TuningMotionSpec:
        block = controller_tuning_motion_block_reason(motion_id, fixture, status)
        return TuningMotionSpec(
            motion_id=motion_id,
            major_mission=major,
            variant=marker_id,
            placement_marker=marker_id,
            motion=title,
            summary=summary,
            physical_scope="CONTAINED_FLIGHT",
            physical_execution="OPERATOR_GATED",
            implementation_state="READY" if block is None else "SETUP_REQUIRED",
            block_reason=block,
            steps=(
                step(
                    "takeoff",
                    "Take off",
                    "Reset the estimator and capture the configured hover height.",
                    "Contained fixture only.",
                ),
                *task_steps,
                step(
                    "land",
                    "Land",
                    "Land, confirm grounded state, and disarm.",
                    "One run per operator action.",
                ),
            ),
            learning_signals=flight_signals,
        )

    for marker_id in ("A", "B", "C", "D", "E"):
        specs.append(
            flight(
                "tuning-b-center-hover",
                "B · Default-PID vertical baseline",
                marker_id,
                "Take off, hover, and land",
                f"Run one default-PID hover repetition from marker {marker_id}.",
                (
                    step(
                        "center-hover",
                        "Hold for 25 s",
                        "Keep fixed heading and altitude.",
                        "No horizontal command.",
                    ),
                ),
            )
        )
    for amplitude_cm in (5, 15, 30):
        amplitude_m = amplitude_cm / 100.0
        for axis, suffix, direction in (
            ("X", "x-plus", "+X"),
            ("X", "x-minus", "-X"),
            ("Y", "y-plus", "+Y"),
            ("Y", "y-minus", "-Y"),
        ):
            motion_id = f"tuning-c-{suffix}-{amplitude_cm:02d}"
            for marker_id in ("A", "B", "C", "D", "E"):
                specs.append(
                    flight(
                        motion_id,  # type: ignore[arg-type]
                        "C · XY hold & bounded transitions",
                        marker_id,
                        f"HOME {direction} {amplitude_cm} cm and return",
                        f"Measure one {amplitude_m:.2f} m HOME {axis}-axis step and "
                        "return response.",
                        (
                            step(
                                "outbound",
                                f"Step HOME {direction} {amplitude_cm} cm",
                                "Use the logged bounded profile.",
                                "The selected implemented amplitude runs directly.",
                            ),
                            step(
                                "offset-hold",
                                "Hold offset",
                                "Measure steady-state error.",
                                "Keep height and heading fixed.",
                            ),
                            step(
                                "return-center",
                                "Return to start",
                                "Reverse the same displacement.",
                                "Record settling and cross-axis motion.",
                            ),
                        ),
                    )
                )
    for motion_id, _variant, title in (
        ("tuning-d-yaw-zero", "Center holds", "Hold 0° heading"),
        ("tuning-d-yaw-plus-15", "Center holds", "Hold +15° and return"),
        ("tuning-d-yaw-minus-15", "Center holds", "Hold -15° and return"),
        ("tuning-d-yaw-plus-30", "Center holds", "Hold +30° and return"),
        ("tuning-d-yaw-minus-30", "Center holds", "Hold -30° and return"),
        ("tuning-d-slow-sweep", "Slow sweep", "Sweep -30° to +30° and return"),
        ("tuning-d-off-center", "Off-center", "Repeat +30° at the +X station"),
    ):
        for marker_id in ("A", "B", "C", "D", "E"):
            specs.append(
                flight(
                    motion_id,
                    "D · Yaw geometry & coupling",
                    marker_id,
                    title,
                    "Compare measured ranger curves with heading telemetry without treating "
                    "wall ranges as an inner-loop yaw reference.",
                    (
                        step(
                            "yaw-profile",
                            "Run yaw profile",
                            title,
                            "Slow bounded heading motion only.",
                        ),
                    ),
                )
            )
    for motion_id, _variant, title, summary in (
        (
            "tuning-e-slow-x",
            "Speed profiles",
            "Slow 30 cm X transition",
            "Use the margin-rich 0.05 m/s profile.",
        ),
        (
            "tuning-e-stress-x",
            "Speed profiles",
            "Higher-stress 30 cm X transition",
            "Use the bounded 0.10 m/s profile.",
        ),
        (
            "tuning-e-hold-x-positive",
            "Cardinal holds",
            "Hold +X station",
            "Move to and hold the configured +X station.",
        ),
        (
            "tuning-e-hold-x-negative",
            "Cardinal holds",
            "Hold -X station",
            "Move to and hold the configured -X station.",
        ),
        (
            "tuning-e-hold-y-positive",
            "Cardinal holds",
            "Hold +Y station",
            "Move to and hold the configured +Y station.",
        ),
        (
            "tuning-e-hold-y-negative",
            "Cardinal holds",
            "Hold -Y station",
            "Move to and hold the configured -Y station.",
        ),
    ):
        for marker_id in ("A", "B", "C", "D", "E"):
            specs.append(
                flight(
                    motion_id,
                    "E · Speed & position dependence",
                    marker_id,
                    title,
                    summary,
                    (
                        step(
                            "profile",
                            "Run bounded profile",
                            summary,
                            "Return to the selected start before landing.",
                        ),
                    ),
                )
            )
    for motion_id, major, summary in (
        (
            "tuning-f-controller-comparison",
            "F · Controller comparison",
            "Compare frozen PID with one mass-configured candidate.",
        ),
        (
            "tuning-g-gain-refinement",
            "G · Bounded gain refinement",
            "Tune one bounded gain family only after diagnosis.",
        ),
        (
            "tuning-h-robustness-confirmation",
            "H · Robustness confirmation",
            "Confirm the selected candidate across position and battery conditions.",
        ),
    ):
        specs.append(
            TuningMotionSpec(
                motion_id=motion_id,
                major_mission=major,
                variant="Raw",
                placement_marker=None,
                motion="Raw stage",
                summary=summary,
                physical_scope="CONTAINED_FLIGHT",
                physical_execution="NOT_ENABLED",
                implementation_state="RAW",
                block_reason="Raw future stage; no executable workflow is attached yet.",
                steps=(),
                learning_signals=(),
            )
        )
    return tuple(specs)


def _move(
    *,
    x_m: float = 0.0,
    y_m: float = 0.0,
    yaw_rad: float = 0.0,
    duration_s: float,
) -> MoveRelativeCommand:
    return MoveRelativeCommand(
        x_m=x_m,
        y_m=y_m,
        yaw_rad=yaw_rad,
        duration_s=duration_s,
        frame=CoordinateFrame.HOME,
    )


def _duration(x_m: float, y_m: float, speed_m_s: float) -> float:
    return max(1.0, math.hypot(x_m, y_m) / speed_m_s)


def _required_station(
    fixture: ControllerTuningFixtureDefinition,
    station_id: str,
) -> FixtureStation:
    station = next((item for item in fixture.stations if item.station_id == station_id), None)
    if station is None or station.x_m is None or station.y_m is None:
        raise ValueError(f"fixture station {station_id} is unavailable")
    return station


def _station_delta_from_center(
    fixture: ControllerTuningFixtureDefinition,
    station_id: str,
) -> tuple[float, float]:
    center = _required_station(fixture, "CENTER")
    station = _required_station(fixture, station_id)
    return (
        float(station.x_m) - float(center.x_m),
        float(station.y_m) - float(center.y_m),
    )


def _xy_amplitude_for_motion(motion_id: str) -> float | None:
    if not motion_id.startswith("tuning-c-"):
        return None
    suffix = motion_id.rsplit("-", 1)[-1]
    return {"05": 0.05, "15": 0.15, "30": 0.30}.get(suffix)


def _transition_vector_for_motion(motion_id: str) -> tuple[float, float, float] | None:
    amplitude = _xy_amplitude_for_motion(motion_id)
    if amplitude is None:
        return None
    if "x-plus" in motion_id:
        return amplitude, 0.0, amplitude
    if "x-minus" in motion_id:
        return -amplitude, 0.0, amplitude
    if "y-plus" in motion_id:
        return 0.0, amplitude, amplitude
    if "y-minus" in motion_id:
        return 0.0, -amplitude, amplitude
    raise ValueError(f"controller-tuning transition direction is invalid: {motion_id}")


def _observation_pose(
    fixture: ControllerTuningFixtureDefinition,
    motion_id: str,
    *,
    station_id: FixtureMarkerId | None = None,
    heading_deg: float = 0.0,
    target_height_m: float | None = None,
) -> FixturePose | None:
    legacy_station_id = {
        "tuning-a-floor-start": "START",
        "tuning-a-raised-center": "CENTER",
        "tuning-a-height-low": "HEIGHT_LOW",
        "tuning-a-height-nominal": "CENTER",
        "tuning-a-height-high": "HEIGHT_HIGH",
        "tuning-a-holdout-one": "HOLDOUT_ONE",
        "tuning-a-holdout-two": "HOLDOUT_TWO",
    }.get(motion_id)
    marker_id = (
        station_id
        if motion_id.startswith("tuning-a-station-")
        else None
    ) or {f"tuning-a-station-{marker.lower()}": marker for marker in "ABCDE"}.get(
        motion_id
    )
    yaw_deg = {
        "tuning-a-yaw-minus-45": -45.0,
        "tuning-a-yaw-minus-30": -30.0,
        "tuning-a-yaw-minus-15": -15.0,
        "tuning-a-yaw-zero": 0.0,
        "tuning-a-yaw-plus-15": 15.0,
        "tuning-a-yaw-plus-30": 30.0,
        "tuning-a-yaw-plus-45": 45.0,
    }.get(motion_id)
    if yaw_deg is not None:
        legacy_station_id = "CENTER"
    if marker_id is not None:
        marker = next(
            (item for item in fixture.floor_markers if item.marker_id == marker_id),
            None,
        )
        if marker is None or target_height_m is None:
            return None
        return FixturePose(
            x_m=marker.x_m,
            y_m=marker.y_m,
            z_m=target_height_m,
            yaw_rad=fixture_heading_to_model_yaw_rad(heading_deg),
        )
    if legacy_station_id is None:
        return None
    station = next(
        (item for item in fixture.stations if item.station_id == legacy_station_id),
        None,
    )
    if station is None or station.x_m is None or station.y_m is None or station.z_m is None:
        return None
    return FixturePose(
        x_m=station.x_m,
        y_m=station.y_m,
        z_m=station.z_m,
        yaw_rad=fixture_heading_to_model_yaw_rad(
            yaw_deg if yaw_deg is not None else station.yaw_deg or 0.0
        ),
    )


def fixture_heading_to_model_yaw_rad(heading_deg: float) -> float:
    """Convert clockwise-from-+Y fixture headings to the model's CCW-from-+X yaw."""

    return math.radians(90.0 - heading_deg)


def _rotation_matrix(
    roll_rad: float,
    pitch_rad: float,
    yaw_rad: float,
) -> tuple[tuple[float, float, float], ...]:
    cr, sr = math.cos(roll_rad), math.sin(roll_rad)
    cp, sp = math.cos(pitch_rad), math.sin(pitch_rad)
    cy, sy = math.cos(yaw_rad), math.sin(yaw_rad)
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )


def _matvec(
    matrix: tuple[tuple[float, float, float], ...],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(sum(row[index] * vector[index] for index in range(3)) for row in matrix)  # type: ignore[return-value]


def _rms(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return math.sqrt(sum(value * value for value in values) / len(values))
