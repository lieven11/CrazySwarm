from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import math
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field

from crazyswarm_app.api.runtime import ApplicationRuntime
from crazyswarm_app.domain.commands import (
    AbortCommand,
    AcknowledgementStatus,
    ArmCommand,
    BodyRateThrustCommand,
    CommandEnvelope,
    CommandPayload,
    DisarmCommand,
    EmergencyStopCommand,
    HoverCommand,
    LandCommand,
    MoveRelativeCommand,
    TakeoffCommand,
)
from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import (
    CommandSource,
    ContractModel,
    CoordinateFrame,
    OperatingMode,
    Vector3,
    VehicleIdentity,
)
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.domain.telemetry import TelemetryEnvelope
from crazyswarm_app.hardware.acrobatics_lab import (
    ACROBATICS_CLUSTER_ID,
    ACROBATICS_HOVER_HEIGHT_M,
    ACROBATICS_MAX_ABS_XY_M,
    ACROBATICS_RECOVERY_DURATION_S,
    ACROBATICS_TRIGGER_TIMEOUT_S,
    BOOST_DURATION_S,
    REFERENCE_PEAK_RATE_DEG_S,
    REFERENCE_ROTATION_DEG,
    REFERENCE_THRUST_PERCENT,
    SAMPLE_PERIOD_S,
    SINGLE_ROLL_MOTION_ID,
    single_roll_rate_thrust_command,
)
from crazyswarm_app.hardware.controller_tuning_lab import (
    CONTROLLER_TUNING_FLIGHT_MOTION_IDS,
    CONTROLLER_TUNING_OBSERVATION_MOTION_IDS,
    CONTROLLER_TUNING_PHYSICAL_MOTION_IDS,
    DEFAULT_CONTROLLER_TUNING_FIXTURE_PATH,
    ControllerTuningFixtureDefinition,
    ControllerTuningFixtureStatus,
    ControllerTuningRangeSummary,
    FixtureMarkerId,
    controller_tuning_flight_commands,
    controller_tuning_motion_block_reason,
    controller_tuning_observation_duration_s,
    controller_tuning_specs,
    load_controller_tuning_fixture_status,
    summarize_controller_tuning_ranges,
)
from crazyswarm_app.hardware.models import CommandPermit, PermitScope
from crazyswarm_app.hardware.observation_twin import PhysicalCommandTarget
from crazyswarm_app.missions.models import (
    MissionPhase,
    MissionResult,
    MissionRunSnapshot,
    MissionStatus,
)
from crazyswarm_app.observability.events import (
    EvidenceEvent,
    EvidenceKind,
    MissionResultPayload,
    MissionStartedPayload,
    TelemetryPayload,
)
from crazyswarm_app.simulation.clock import ClockMode
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld
from crazyswarm_app.vehicles._cflib_link import CflibCrazyflieLink
from crazyswarm_app.vehicles.crazyflie import CrazyflieVehicle
from crazyswarm_app.vehicles.crazyflie_link import CrazyflieLink

PhysicalVehicleProvider = Callable[
    [str, PhysicalCommandTarget],
    Awaitable[CrazyflieVehicle],
]


class BasicFlightLabStep(ContractModel):
    step_id: str
    title: str
    behavior: str
    containment: str


class BasicFlightLabMotion(ContractModel):
    motion_id: str
    cluster_id: str = "basic-flight"
    major_mission: str
    variant: str
    placement_marker: FixtureMarkerId | None = None
    motion: str
    summary: str
    physical_scope: Literal["PROPS_OFF_BENCH", "FIXTURE_OBSERVATION", "CONTAINED_FLIGHT"]
    physical_execution: Literal["NOT_ENABLED", "OPERATOR_GATED"] = "NOT_ENABLED"
    catalog_visibility: bool = False
    implementation_state: Literal["READY", "SETUP_REQUIRED", "RAW"] = "READY"
    block_reason: str | None = None
    steps: tuple[BasicFlightLabStep, ...]
    learning_signals: tuple[str, ...]


class BasicFlightLabCluster(ContractModel):
    cluster_id: str
    cluster_name: str
    purpose: str
    state: Literal["READY", "SETUP_REQUIRED"] = "READY"
    detail: str | None = None


class BasicFlightLabCatalog(ContractModel):
    schema_version: Literal[1] = 1
    cluster_id: Literal["basic-flight"] = "basic-flight"
    cluster_name: Literal["Basic flight"] = "Basic flight"
    purpose: str
    qualification_claim: Literal["NONE"] = "NONE"
    clusters: tuple[BasicFlightLabCluster, ...] = ()
    controller_tuning_fixture: ControllerTuningFixtureStatus | None = None
    motions: tuple[BasicFlightLabMotion, ...]


class BasicFlightLabRunRequest(ContractModel):
    motion_id: str = Field(default="commissioning-baseline", min_length=1, max_length=80)


PhysicalBasicFlightMotionId = Literal[
    "commissioning-baseline",
    "arm-disarm",
    "hover-12s",
    "forward-10cm-return",
    "left-10cm-return",
    "right-10cm-return",
    "forward-20cm-return",
    "land-forward-10cm",
    "land-forward-20cm",
    "land-diagonal-20cm",
    "l-shape-stops",
    "square-stops",
    "triangle-stops",
    "l-shape-stops-40cm",
    "square-stops-40cm",
    "triangle-stops-40cm",
    "straight-out-back-continuous",
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
    "acro-single-roll",
]

PHYSICAL_FLIGHT_MOTION_IDS: tuple[PhysicalBasicFlightMotionId, ...] = (
    "commissioning-baseline",
    "hover-12s",
    "forward-10cm-return",
    "left-10cm-return",
    "right-10cm-return",
    "forward-20cm-return",
    "land-forward-10cm",
    "land-forward-20cm",
    "land-diagonal-20cm",
    "l-shape-stops-40cm",
    "square-stops-40cm",
    "triangle-stops-40cm",
    "straight-out-back-continuous",
    SINGLE_ROLL_MOTION_ID,
    *cast(tuple[PhysicalBasicFlightMotionId, ...], CONTROLLER_TUNING_FLIGHT_MOTION_IDS),
)
PHYSICAL_OBSERVATION_MOTION_IDS: tuple[PhysicalBasicFlightMotionId, ...] = cast(
    tuple[PhysicalBasicFlightMotionId, ...],
    CONTROLLER_TUNING_OBSERVATION_MOTION_IDS,
)
PHYSICAL_BASIC_FLIGHT_MOTION_IDS = frozenset(
    (*PHYSICAL_FLIGHT_MOTION_IDS, *PHYSICAL_OBSERVATION_MOTION_IDS, "arm-disarm")
)

CHECKPOINT_SHAPE_SIDE_M = 0.40
CHECKPOINT_SHAPE_HALF_SIDE_M = CHECKPOINT_SHAPE_SIDE_M / 2.0
CHECKPOINT_SHAPE_MAX_SPEED_M_S = 0.10
CHECKPOINT_SHAPE_MAX_CENTER_RADIUS_M = math.hypot(
    CHECKPOINT_SHAPE_HALF_SIDE_M,
    CHECKPOINT_SHAPE_HALF_SIDE_M,
)
TAKEOFF_CAPTURE_HEIGHT_M = 0.30
TAKEOFF_CAPTURE_TOLERANCE_M = 0.05
TAKEOFF_CAPTURE_MAX_VERTICAL_SPEED_M_S = 0.03
TAKEOFF_CAPTURE_CONSECUTIVE_SAMPLES = 3
TAKEOFF_CAPTURE_TIMEOUT_S = 4.0
CRAZYFLIE_DEFAULT_PID_CONTROLLER_VALUE = "1"
CRAZYFLIE_KALMAN_ESTIMATOR_VALUE = "2"


class PhysicalBasicFlightRunRequest(ContractModel):
    motion_id: PhysicalBasicFlightMotionId = "commissioning-baseline"
    station_id: FixtureMarkerId | None = None
    heading_deg: float = Field(default=0.0, ge=0.0, le=90.0)
    target_height_m: float | None = Field(default=None, ge=0.0, le=0.50)


class ControllerTuningRunPreparation(ContractModel):
    fixture_id: str
    fixture_version: str
    fixture_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    station_id: FixtureMarkerId
    heading_deg: float = Field(ge=0.0, le=90.0)
    target_height_m: float | None = Field(default=None, ge=0.0, le=0.50)


class PhysicalBasicFlightReadiness(ContractModel):
    schema_version: Literal[1] = 1
    ready: bool
    estimator_converged: bool
    battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    battery_voltage_v: float | None = Field(default=None, ge=0.0)
    floor_distance_m: float | None = Field(default=None, ge=0.0)
    faults: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    physical_commands_sent: Literal[False] = False


MotorSelection = Literal["all", "m1", "m2", "m3", "m4"]
MOTOR_STOP_IO_TIMEOUT_S = 2.0
MOTOR_RECOVERY_CONNECT_TIMEOUT_S = 4.0
FLIGHT_RECOVERY_CONNECT_TIMEOUT_S = 6.0
FLIGHT_RECOVERY_COMMAND_TIMEOUT_S = 6.0


class MotorBenchStartRequest(ContractModel):
    motor_selection: MotorSelection = "all"
    props_removed_confirmed: Literal[True]
    physically_restrained_confirmed: Literal[True]


class MotorBenchUpdateRequest(ContractModel):
    session_id: str = Field(min_length=1, max_length=100)
    output_percent: float = Field(ge=0.0, le=70.0)


class MotorBenchStopRequest(ContractModel):
    session_id: str = Field(min_length=1, max_length=100)


class MotorBenchSession(ContractModel):
    schema_version: Literal[1] = 1
    session_id: str
    status: Literal["ACTIVE", "STOPPED", "FAILED"]
    motor_selection: MotorSelection
    output_percent: float = Field(ge=0.0, le=70.0)
    measured_pwm_percent: tuple[float, float, float, float] | None = None
    maximum_output_percent: Literal[70] = 70
    watchdog_timeout_ms: Literal[750] = 750
    firmware_watchdog_armed: bool = False
    reboot_required: bool = False
    telemetry_row_count: int = Field(default=0, ge=0)
    telemetry_artifact_path: str | None = None
    motor_csv_path: str | None = None
    motor_csv_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    error: str | None = None


class MotorActuationStatus(ContractModel):
    """Backend-authoritative direct-PWM state, independent of the mission UI."""

    schema_version: Literal[1] = 1
    state: Literal["IDLE", "ACTIVE", "POSSIBLY_ACTIVE", "STOPPING", "STOP_FAILED"]
    stop_required: bool
    session_id: str | None = None
    motor_selection: MotorSelection | None = None
    commanded_output_percent: float | None = Field(default=None, ge=0.0, le=70.0)
    measured_pwm_percent: tuple[float, float, float, float] | None = None
    measured_output_active: bool | None = None
    firmware_watchdog_armed: bool = False
    reboot_required: bool = False
    detail: str | None = None


@dataclass(slots=True)
class _ActiveMotorBench:
    session_id: str
    motor_selection: MotorSelection
    selected_uri: str
    vehicle: CrazyflieVehicle
    started_at_utc: datetime
    started_at_monotonic_s: float
    output_percent: float = 0.0
    measured_pwm_percent: tuple[float, float, float, float] | None = None
    firmware_watchdog_armed: bool = False
    last_update_monotonic_s: float = field(default_factory=time.monotonic)
    records: list[dict[str, object]] = field(default_factory=list)
    monitor_task: asyncio.Task[None] | None = None
    status: Literal["ACTIVE", "STOPPED", "FAILED"] = "ACTIVE"
    telemetry_artifact_path: str | None = None
    motor_csv_path: str | None = None
    motor_csv_sha256: str | None = None
    error: str | None = None


class BasicFlightLabStepResult(ContractModel):
    step_id: str
    status: Literal["COMPLETED", "MODELED_ONLY"]
    detail: str


class BasicFlightLearningSample(ContractModel):
    battery_start_percent: float = Field(ge=0.0, le=100.0)
    battery_minimum_percent: float = Field(ge=0.0, le=100.0)
    battery_end_percent: float = Field(ge=0.0, le=100.0)
    battery_delta_percent: float = Field(ge=0.0)
    minimum_voltage_v: float | None = Field(default=None, ge=0.0)
    maximum_current_a: float | None = Field(default=None, ge=0.0)
    peak_motor_command_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    hover_rms_drift_m: float | None = Field(default=None, ge=0.0)
    maximum_altitude_m: float = Field(ge=0.0)
    landing_contact_observed: bool
    final_state: str


class BasicFlightLabRun(ContractModel):
    schema_version: Literal[1] = 1
    run_id: str
    motion_id: str
    status: Literal["COMPLETED", "FAILED"]
    execution_backend: Literal["FAST_SIM", "REAL_CRAZYFLIE"] = "FAST_SIM"
    evidence_class: Literal["SIMULATED_MODEL", "MEASURED_REAL"] = "SIMULATED_MODEL"
    learning_disposition: Literal["SIMULATOR_INPUT_CANDIDATE"] = "SIMULATOR_INPUT_CANDIDATE"
    qualification_claim: Literal["NONE"] = "NONE"
    started_at_utc: datetime
    completed_at_utc: datetime
    steps: tuple[BasicFlightLabStepResult, ...]
    learning_sample: BasicFlightLearningSample
    artifact_path: str
    telemetry_row_count: int | None = Field(default=None, ge=0)
    telemetry_csv_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    controller_tuning_range_summary: ControllerTuningRangeSummary | None = None
    controller_tuning_preparation: ControllerTuningRunPreparation | None = None


PhysicalFlightState = Literal[
    "IDLE",
    "STARTING",
    "RUNNING",
    "HOVERING_READY",
    "FLIPPING",
    "ABORTING",
    "STOP_UNCONFIRMED",
    "COMPLETED",
    "ABORTED",
    "FAILED",
]


class PhysicalFlightOperationStatus(ContractModel):
    """Global contained-flight state, independent of the initiating HTTP request."""

    schema_version: Literal[1] = 1
    state: PhysicalFlightState
    stop_required: bool
    operation_id: str | None = None
    motion_id: PhysicalBasicFlightMotionId | None = None
    started_at_utc: datetime | None = None
    detail: str | None = None
    result: BasicFlightLabRun | None = None
    failure_details: dict[str, Any] | None = None
    command_evidence: tuple[dict[str, Any], ...] = ()
    controller_tuning_preparation: ControllerTuningRunPreparation | None = None
    available_action: Literal["FLIP"] | None = None


@dataclass(slots=True)
class _ActivePhysicalFlight:
    operation_id: str
    request: PhysicalBasicFlightRunRequest
    target: PhysicalCommandTarget
    operator_id: str
    started_at_utc: datetime
    state: Literal[
        "STARTING",
        "RUNNING",
        "HOVERING_READY",
        "FLIPPING",
        "ABORTING",
        "STOP_UNCONFIRMED",
        "COMPLETED",
        "ABORTED",
        "FAILED",
    ] = "STARTING"
    detail: str = "Connecting to the physical drone"
    vehicle: CrazyflieVehicle | None = None
    permit: CommandPermit | None = None
    task: asyncio.Task[None] | None = None
    abort_task: asyncio.Task[PhysicalFlightOperationStatus] | None = None
    abort_requested: bool = False
    abort_complete: asyncio.Event = field(default_factory=asyncio.Event)
    flip_requested: asyncio.Event = field(default_factory=asyncio.Event)
    flip_triggered: bool = False
    hover_reference_m: Vector3 | None = None
    command_link_connected: bool = False
    stop_required: bool = True
    result: BasicFlightLabRun | None = None
    failure_details: dict[str, Any] | None = None
    command_evidence: list[dict[str, Any]] = field(default_factory=list)


def _step(step_id: str, title: str, behavior: str, containment: str) -> BasicFlightLabStep:
    return BasicFlightLabStep(
        step_id=step_id,
        title=title,
        behavior=behavior,
        containment=containment,
    )


def _move(
    *,
    x_m: float = 0.0,
    y_m: float = 0.0,
    duration_s: float = 1.0,
) -> MoveRelativeCommand:
    """Build a low-speed home-frame move used by the contained curriculum."""

    return MoveRelativeCommand(
        x_m=x_m,
        y_m=y_m,
        duration_s=duration_s,
        frame=CoordinateFrame.HOME,
    )


def _checkpoint_shape_move(
    *,
    x_m: float = 0.0,
    y_m: float = 0.0,
) -> MoveRelativeCommand:
    distance_m = math.hypot(x_m, y_m)
    if distance_m <= 0.0:
        raise ValueError("checkpoint shape move must have nonzero distance")
    return _move(
        x_m=x_m,
        y_m=y_m,
        duration_s=distance_m / CHECKPOINT_SHAPE_MAX_SPEED_M_S,
    )


def _contained_flight_commands(
    motion_id: PhysicalBasicFlightMotionId,
    *,
    commissioning_hover_duration_s: float,
    controller_tuning_fixture: ControllerTuningFixtureDefinition | None = None,
) -> tuple[tuple[str, CommandPayload], ...]:
    """Return the bounded in-flight portion between takeoff and landing."""

    if motion_id in CONTROLLER_TUNING_FLIGHT_MOTION_IDS:
        if controller_tuning_fixture is None:
            raise ValueError("controller-tuning fixture definition is required")
        return controller_tuning_flight_commands(motion_id, controller_tuning_fixture)

    plans: dict[str, tuple[tuple[str, CommandPayload], ...]] = {
        SINGLE_ROLL_MOTION_ID: (
            ("single-roll-rate-profile", single_roll_rate_thrust_command()),
        ),
        "commissioning-baseline": (
            ("hover-30s", HoverCommand(duration_s=commissioning_hover_duration_s)),
        ),
        "hover-12s": (("hover-12s", HoverCommand(duration_s=12.0)),),
        "forward-10cm-return": (
            ("forward-10cm", _move(x_m=0.10)),
            ("hold-forward", HoverCommand(duration_s=2.0)),
            ("return-home", _move(x_m=-0.10)),
        ),
        "left-10cm-return": (
            ("left-10cm", _move(y_m=0.10)),
            ("hold-left", HoverCommand(duration_s=2.0)),
            ("return-home", _move(y_m=-0.10)),
        ),
        "right-10cm-return": (
            ("right-10cm", _move(y_m=-0.10)),
            ("hold-right", HoverCommand(duration_s=2.0)),
            ("return-home", _move(y_m=0.10)),
        ),
        "forward-20cm-return": (
            ("forward-20cm", _move(x_m=0.20, duration_s=2.0)),
            ("hold-forward", HoverCommand(duration_s=2.0)),
            ("return-home", _move(x_m=-0.20, duration_s=2.0)),
        ),
        "land-forward-10cm": (
            ("forward-10cm", _move(x_m=0.10)),
            ("hold-landing-point", HoverCommand(duration_s=2.0)),
        ),
        "land-forward-20cm": (
            ("forward-20cm", _move(x_m=0.20, duration_s=2.0)),
            ("hold-landing-point", HoverCommand(duration_s=2.0)),
        ),
        "land-diagonal-20cm": (
            (
                "diagonal-20cm",
                _move(x_m=0.141421, y_m=0.141421, duration_s=2.0),
            ),
            ("hold-landing-point", HoverCommand(duration_s=2.0)),
        ),
        "l-shape-stops": (
            ("l-checkpoint-1", _move(x_m=0.10)),
            ("l-hold-1", HoverCommand(duration_s=2.0)),
            ("l-checkpoint-2", _move(y_m=0.10)),
            ("l-hold-2", HoverCommand(duration_s=2.0)),
            ("l-return-1", _move(y_m=-0.10)),
            ("l-return-hold", HoverCommand(duration_s=2.0)),
            ("l-return-home", _move(x_m=-0.10)),
        ),
        "square-stops": (
            ("square-1", _move(x_m=0.10)),
            ("square-hold-1", HoverCommand(duration_s=2.0)),
            ("square-2", _move(y_m=0.10)),
            ("square-hold-2", HoverCommand(duration_s=2.0)),
            ("square-3", _move(x_m=-0.10)),
            ("square-hold-3", HoverCommand(duration_s=2.0)),
            ("square-4", _move(y_m=-0.10)),
        ),
        "triangle-stops": (
            ("triangle-1", _move(x_m=0.10)),
            ("triangle-hold-1", HoverCommand(duration_s=2.0)),
            ("triangle-2", _move(x_m=-0.05, y_m=0.086603)),
            ("triangle-hold-2", HoverCommand(duration_s=2.0)),
            ("triangle-3", _move(x_m=-0.05, y_m=-0.086603)),
        ),
        "l-shape-stops-40cm": (
            (
                "l-entry",
                _checkpoint_shape_move(
                    x_m=-CHECKPOINT_SHAPE_HALF_SIDE_M,
                    y_m=-CHECKPOINT_SHAPE_HALF_SIDE_M,
                ),
            ),
            ("l-entry-hold", HoverCommand(duration_s=2.0)),
            ("l-checkpoint-1", _checkpoint_shape_move(x_m=CHECKPOINT_SHAPE_SIDE_M)),
            ("l-hold-1", HoverCommand(duration_s=2.0)),
            ("l-checkpoint-2", _checkpoint_shape_move(y_m=CHECKPOINT_SHAPE_SIDE_M)),
            ("l-hold-2", HoverCommand(duration_s=2.0)),
            ("l-return-1", _checkpoint_shape_move(y_m=-CHECKPOINT_SHAPE_SIDE_M)),
            ("l-return-hold", HoverCommand(duration_s=2.0)),
            ("l-return-home", _checkpoint_shape_move(x_m=-CHECKPOINT_SHAPE_SIDE_M)),
            ("l-return-home-hold", HoverCommand(duration_s=2.0)),
            (
                "l-exit",
                _checkpoint_shape_move(
                    x_m=CHECKPOINT_SHAPE_HALF_SIDE_M,
                    y_m=CHECKPOINT_SHAPE_HALF_SIDE_M,
                ),
            ),
        ),
        "square-stops-40cm": (
            (
                "square-entry",
                _checkpoint_shape_move(
                    x_m=-CHECKPOINT_SHAPE_HALF_SIDE_M,
                    y_m=-CHECKPOINT_SHAPE_HALF_SIDE_M,
                ),
            ),
            ("square-entry-hold", HoverCommand(duration_s=2.0)),
            ("square-1", _checkpoint_shape_move(x_m=CHECKPOINT_SHAPE_SIDE_M)),
            ("square-hold-1", HoverCommand(duration_s=2.0)),
            ("square-2", _checkpoint_shape_move(y_m=CHECKPOINT_SHAPE_SIDE_M)),
            ("square-hold-2", HoverCommand(duration_s=2.0)),
            ("square-3", _checkpoint_shape_move(x_m=-CHECKPOINT_SHAPE_SIDE_M)),
            ("square-hold-3", HoverCommand(duration_s=2.0)),
            ("square-4", _checkpoint_shape_move(y_m=-CHECKPOINT_SHAPE_SIDE_M)),
            ("square-hold-4", HoverCommand(duration_s=2.0)),
            (
                "square-exit",
                _checkpoint_shape_move(
                    x_m=CHECKPOINT_SHAPE_HALF_SIDE_M,
                    y_m=CHECKPOINT_SHAPE_HALF_SIDE_M,
                ),
            ),
        ),
        "triangle-stops-40cm": (
            (
                "triangle-entry",
                _checkpoint_shape_move(y_m=CHECKPOINT_SHAPE_SIDE_M / math.sqrt(3.0)),
            ),
            ("triangle-entry-hold", HoverCommand(duration_s=2.0)),
            (
                "triangle-1",
                _checkpoint_shape_move(
                    x_m=-CHECKPOINT_SHAPE_HALF_SIDE_M,
                    y_m=-CHECKPOINT_SHAPE_SIDE_M * math.sqrt(3.0) / 2.0,
                ),
            ),
            ("triangle-hold-1", HoverCommand(duration_s=2.0)),
            ("triangle-2", _checkpoint_shape_move(x_m=CHECKPOINT_SHAPE_SIDE_M)),
            ("triangle-hold-2", HoverCommand(duration_s=2.0)),
            (
                "triangle-3",
                _checkpoint_shape_move(
                    x_m=-CHECKPOINT_SHAPE_HALF_SIDE_M,
                    y_m=CHECKPOINT_SHAPE_SIDE_M * math.sqrt(3.0) / 2.0,
                ),
            ),
            ("triangle-hold-3", HoverCommand(duration_s=2.0)),
            (
                "triangle-exit",
                _checkpoint_shape_move(y_m=-CHECKPOINT_SHAPE_SIDE_M / math.sqrt(3.0)),
            ),
        ),
        "straight-out-back-continuous": (
            ("straight-out", _move(x_m=0.20, duration_s=2.0)),
            ("straight-back", _move(x_m=-0.20, duration_s=2.0)),
        ),
    }
    try:
        return plans[motion_id]
    except KeyError as error:
        raise ValueError(f"motion is not a contained flight: {motion_id}") from error


_GROUND_STEPS = (
    _step("arm", "Arm", "Arm, observe state, then disarm.", "Vehicle remains on the ground."),
    _step(
        "motors-30",
        "Motors at 30%",
        "Model an equal 30% command on all four motors.",
        "Props-off bench scope only; physical output is not enabled.",
    ),
)
_FLIGHT_START = (
    _step(
        "arm-for-flight",
        "Arm for flight",
        "Arm immediately before liftoff.",
        "Contained volume only.",
    ),
    _step("takeoff-30cm", "Take off to 0.30 m", "Climb over 2 seconds.", "Altitude limit 0.50 m."),
)
_FLIGHT_END = (
    _step(
        "land", "Land", "Descend to ground contact and cut motors.", "Landing at the takeoff point."
    ),
)


def basic_flight_catalog(
    *,
    controller_tuning_fixture_path: Path = DEFAULT_CONTROLLER_TUNING_FIXTURE_PATH,
) -> BasicFlightLabCatalog:
    common_signals = (
        "battery start/minimum/end",
        "battery voltage and current when available",
        "motor command envelope",
        "position and hover drift",
        "landing contact and final state",
    )
    motions = (
        BasicFlightLabMotion(
            motion_id="commissioning-baseline",
            major_mission="First liftoff",
            variant="30 cm · 30 s",
            motion="Arm → motor rehearsal → hover → land",
            summary="The first end-to-end behavior for a drone that has never flown.",
            physical_scope="CONTAINED_FLIGHT",
            physical_execution="OPERATOR_GATED",
            steps=(
                *_GROUND_STEPS,
                _step(
                    "disarm-after-bench",
                    "Disarm",
                    "Close the bench phase.",
                    "Motors commanded off.",
                ),
                *_FLIGHT_START,
                _step(
                    "hover-30s",
                    "Hover for 30 s",
                    "Hold the takeoff position.",
                    "No translation.",
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="arm-disarm",
            major_mission="Ground readiness",
            variant="State transition",
            motion="Arm and disarm",
            summary="Physically arm for three seconds, record telemetry, then disarm.",
            physical_scope="CONTAINED_FLIGHT",
            physical_execution="OPERATOR_GATED",
            steps=(
                _GROUND_STEPS[0],
                _step("disarm", "Disarm", "Return to the safe ground state.", "Motors off."),
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="hover-12s",
            major_mission="Hover stability",
            variant="30 cm · 12 s",
            motion="Take off → hover → land at home",
            summary="Hold 0.30 m for 12 seconds before landing at the takeoff point.",
            physical_scope="CONTAINED_FLIGHT",
            physical_execution="OPERATOR_GATED",
            steps=(
                *_FLIGHT_START,
                _step("hover-12s", "Hover for 12 s", "Hold position.", "No translation."),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        *tuple(
            BasicFlightLabMotion(
                motion_id=motion_id,
                major_mission="Move and return",
                variant=variant,
                motion=f"Take off → move {direction} → hold → return → land",
                summary=(
                    f"Move {distance:.2f} m {direction}, hold for two seconds, "
                    "return home, and land."
                ),
                physical_scope="CONTAINED_FLIGHT",
                physical_execution="OPERATOR_GATED",
                steps=(
                    *_FLIGHT_START,
                    _step(
                        f"{direction}-move",
                        f"Move {direction} {distance:.2f} m",
                        "Translate in the fixed takeoff frame.",
                        "Speed at most 0.10 m/s.",
                    ),
                    _step(
                        f"{direction}-hold",
                        "Hold for 2 s",
                        "Stop at the offset checkpoint.",
                        "No translation during the hold.",
                    ),
                    _step(
                        f"{direction}-return",
                        "Return home",
                        "Reverse the offset and settle above the takeoff point.",
                        "Land at home.",
                    ),
                    *_FLIGHT_END,
                ),
                learning_signals=common_signals,
            )
            for motion_id, variant, direction, distance in (
                ("forward-10cm-return", "Forward · 0.10 m", "forward", 0.10),
                ("left-10cm-return", "Left · 0.10 m", "left", 0.10),
                ("right-10cm-return", "Right · 0.10 m", "right", 0.10),
                ("forward-20cm-return", "Forward · 0.20 m", "forward", 0.20),
            )
        ),
        *tuple(
            BasicFlightLabMotion(
                motion_id=motion_id,
                major_mission="Land elsewhere",
                variant=variant,
                motion="Take off → move → hold → land at offset",
                summary=(
                    f"Fly to {destination}, hold for two seconds, and land there "
                    "instead of at home."
                ),
                physical_scope="CONTAINED_FLIGHT",
                physical_execution="OPERATOR_GATED",
                steps=(
                    *_FLIGHT_START,
                    _step(
                        "move-to-landing-point",
                        f"Move to {destination}",
                        "Translate in the fixed takeoff frame.",
                        "Remain within 0.20 m of home.",
                    ),
                    _step(
                        "hold-landing-point",
                        "Hold for 2 s",
                        "Settle above the new landing point.",
                        "No further horizontal motion.",
                    ),
                    _step(
                        "land",
                        "Land at the offset point",
                        "Descend vertically and cut motors.",
                        "The landing point is not the takeoff point.",
                    ),
                ),
                learning_signals=common_signals,
            )
            for motion_id, variant, destination in (
                ("land-forward-10cm", "Forward · 0.10 m", "0.10 m forward"),
                ("land-forward-20cm", "Forward · 0.20 m", "0.20 m forward"),
                ("land-diagonal-20cm", "Diagonal · 0.20 m", "0.20 m diagonally"),
            )
        ),
        BasicFlightLabMotion(
            motion_id="l-shape-stops",
            major_mission="Checkpoint shapes",
            variant="L-shape · 0.10 m legs",
            motion="L-shape with a stop at every checkpoint",
            summary="Fly a 0.10 m L-shape, retrace it, and land at home.",
            physical_scope="CONTAINED_FLIGHT",
            steps=(
                *_FLIGHT_START,
                _step("l-checkpoint-1", "Checkpoint 1", "Move 0.10 m forward.", "Hold 2 s."),
                _step("l-checkpoint-2", "Checkpoint 2", "Move 0.10 m left.", "Hold 2 s."),
                _step(
                    "l-return",
                    "Retrace to home",
                    "Reverse both legs.",
                    "Hold at the corner before returning.",
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="square-stops",
            major_mission="Checkpoint shapes",
            variant="Square · 0.10 m sides",
            motion="Square with a stop at every checkpoint",
            summary=(
                "Fly a square with four 0.10 m sides and a two-second hold "
                "at each corner, then land at home."
            ),
            physical_scope="CONTAINED_FLIGHT",
            steps=(
                *_FLIGHT_START,
                *tuple(
                    _step(
                        f"square-{index}",
                        f"Corner {index}",
                        "Fly one 0.10 m side.",
                        "Hold for 2 s at the corner.",
                    )
                    for index in range(1, 5)
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="triangle-stops",
            major_mission="Checkpoint shapes",
            variant="Triangle · 0.10 m sides",
            motion="Triangle with a stop at every checkpoint",
            summary=(
                "Fly a triangle with 0.10 m sides and a two-second hold at "
                "each corner, then land at home."
            ),
            physical_scope="CONTAINED_FLIGHT",
            steps=(
                *_FLIGHT_START,
                *tuple(
                    _step(
                        f"triangle-{index}",
                        f"Corner {index}",
                        "Fly one 0.10 m side.",
                        "Hold for 2 s at the corner.",
                    )
                    for index in range(1, 4)
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="l-shape-stops-40cm",
            major_mission="Checkpoint shapes",
            variant="L-shape · 0.40 m legs",
            motion="Centered L-shape with a stop at every checkpoint",
            summary="Fly a centered 0.40 m L-shape, retrace it, and land at home.",
            physical_scope="CONTAINED_FLIGHT",
            physical_execution="OPERATOR_GATED",
            steps=(
                *_FLIGHT_START,
                _step("l-entry", "Enter shape", "Move to the centered start.", "Hold 2 s."),
                _step("l-checkpoint-1", "Checkpoint 1", "Move 0.40 m forward.", "Hold 2 s."),
                _step("l-checkpoint-2", "Checkpoint 2", "Move 0.40 m left.", "Hold 2 s."),
                _step(
                    "l-return",
                    "Retrace to shape start",
                    "Reverse both legs.",
                    "Hold at the corner before returning.",
                ),
                _step("l-exit", "Return home", "Exit from the centered shape.", "Land at home."),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="square-stops-40cm",
            major_mission="Checkpoint shapes",
            variant="Square · 0.40 m sides",
            motion="Centered square with a stop at every checkpoint",
            summary=(
                "Fly a centered square with four 0.40 m sides and a two-second hold "
                "at each corner, then land at home."
            ),
            physical_scope="CONTAINED_FLIGHT",
            physical_execution="OPERATOR_GATED",
            steps=(
                *_FLIGHT_START,
                _step("square-entry", "Enter shape", "Move to the centered start.", "Hold 2 s."),
                *tuple(
                    _step(
                        f"square-{index}",
                        f"Corner {index}",
                        "Fly one 0.40 m side.",
                        "Hold for 2 s at the corner.",
                    )
                    for index in range(1, 5)
                ),
                _step(
                    "square-exit", "Return home", "Exit from the centered shape.", "Land at home."
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="triangle-stops-40cm",
            major_mission="Checkpoint shapes",
            variant="Triangle · 0.40 m sides",
            motion="Centered triangle with a stop at every checkpoint",
            summary=(
                "Fly a centered triangle with 0.40 m sides and a two-second hold at "
                "each corner, then land at home."
            ),
            physical_scope="CONTAINED_FLIGHT",
            physical_execution="OPERATOR_GATED",
            steps=(
                *_FLIGHT_START,
                _step("triangle-entry", "Enter shape", "Move to the centered start.", "Hold 2 s."),
                *tuple(
                    _step(
                        f"triangle-{index}",
                        f"Corner {index}",
                        "Fly one 0.40 m side.",
                        "Hold for 2 s at the corner.",
                    )
                    for index in range(1, 4)
                ),
                _step(
                    "triangle-exit", "Return home", "Exit from the centered shape.", "Land at home."
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="straight-out-back-continuous",
            major_mission="Continuous path",
            variant="Straight · 0.20 m out and back",
            motion="Straight out and back without checkpoint holds",
            summary="Fly 0.20 m out and return directly, then land at home.",
            physical_scope="CONTAINED_FLIGHT",
            physical_execution="OPERATOR_GATED",
            steps=(
                *_FLIGHT_START,
                _step(
                    "straight-out",
                    "Fly out 0.20 m",
                    "Move forward without a checkpoint dwell.",
                    "Speed at most 0.10 m/s.",
                ),
                _step(
                    "straight-back",
                    "Fly back 0.20 m",
                    "Reverse and return directly.",
                    "No authored hold at the far point.",
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="yaw-turn",
            major_mission="Heading",
            variant="90° out and back",
            motion="Yaw right and left",
            summary="Rotate in place and return to the entry heading.",
            physical_scope="CONTAINED_FLIGHT",
            steps=(
                *_FLIGHT_START,
                _step("yaw-right", "Yaw right 90°", "Rotate in place.", "No translation."),
                _step(
                    "yaw-left", "Yaw left 90°", "Return to the entry heading.", "No translation."
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="square",
            major_mission="Shape flight",
            variant="0.20 m sides",
            motion="Square and return",
            summary="Fly four canonical sides and exit at the exact entry point and heading.",
            physical_scope="CONTAINED_FLIGHT",
            steps=(
                *_FLIGHT_START,
                *tuple(
                    _step(
                        f"square-{index}",
                        f"Square side {index}",
                        "Translate 0.20 m.",
                        "Canonical clockwise phase.",
                    )
                    for index in range(1, 5)
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="circle",
            major_mission="Shape flight",
            variant="0.20 m diameter",
            motion="Circle and return",
            summary=(
                "Fly a clockwise 12-segment circle from a fixed start phase and return exactly."
            ),
            physical_scope="CONTAINED_FLIGHT",
            steps=(
                *_FLIGHT_START,
                _step(
                    "circle-entry",
                    "Enter circle",
                    "Move 0.10 m to the +x start phase.",
                    "Canonical connector from hover center.",
                ),
                _step(
                    "circle",
                    "Clockwise circle",
                    "12 canonical segments, radius 0.10 m.",
                    "Fixed +x entry and exit phase.",
                ),
                _step(
                    "circle-exit",
                    "Exit circle",
                    "Return 0.10 m to the hover center.",
                    "Exact reverse connector to landing point.",
                ),
                *_FLIGHT_END,
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="abort-to-land",
            major_mission="Recovery",
            variant="Abort from hover",
            motion="Abort and land",
            summary="Exercise the controlled abort path from a stable 0.30 m hover.",
            physical_scope="CONTAINED_FLIGHT",
            steps=(
                *_FLIGHT_START,
                _step(
                    "abort",
                    "Abort",
                    "Transition to controlled landing.",
                    "No further mission motion.",
                ),
            ),
            learning_signals=common_signals,
        ),
        BasicFlightLabMotion(
            motion_id="emergency-stop",
            major_mission="Recovery",
            variant="Motor cut in Fast Sim",
            motion="Emergency stop",
            summary=(
                "Exercise the latching emergency motor-cut model; never a routine physical test."
            ),
            physical_scope="CONTAINED_FLIGHT",
            steps=(
                *_FLIGHT_START,
                _step(
                    "emergency",
                    "Emergency stop",
                    "Cut modeled motor output immediately.",
                    "Fast Sim only; physical execution is disabled.",
                ),
            ),
            learning_signals=common_signals,
        ),
    )
    basic_motions = tuple(
        motion.model_copy(
            update={
                "catalog_visibility": motion.physical_execution == "OPERATOR_GATED",
            }
        )
        for motion in motions
    )
    fixture, fixture_status = load_controller_tuning_fixture_status(controller_tuning_fixture_path)
    tuning_motions = tuple(
        BasicFlightLabMotion(
            motion_id=spec.motion_id,
            cluster_id="controller-characterization-tuning",
            major_mission=spec.major_mission,
            variant=spec.variant,
            placement_marker=spec.placement_marker,
            motion=spec.motion,
            summary=spec.summary,
            physical_scope=spec.physical_scope,
            physical_execution=spec.physical_execution,
            catalog_visibility=True,
            implementation_state=spec.implementation_state,
            block_reason=spec.block_reason,
            steps=tuple(
                BasicFlightLabStep(
                    step_id=step.step_id,
                    title=step.title,
                    behavior=step.behavior,
                    containment=step.containment,
                )
                for step in spec.steps
            ),
            learning_signals=spec.learning_signals,
        )
        for spec in controller_tuning_specs(fixture, fixture_status)
    )
    single_roll = single_roll_rate_thrust_command()
    acrobatics_motions = (
        BasicFlightLabMotion(
            motion_id=SINGLE_ROLL_MOTION_ID,
            cluster_id=ACROBATICS_CLUSTER_ID,
            major_mission="Single flip",
            variant="Positive roll · 360°",
            motion="Hover → boost → fast roll → recover → land",
            summary=(
                "Exercise the onboard body-rate controller and motor mixer with one "
                "finite 360° roll profile; exact horizontal landing position is not a goal."
            ),
            physical_scope="CONTAINED_FLIGHT",
            physical_execution="OPERATOR_GATED",
            catalog_visibility=True,
            implementation_state="READY",
            steps=(
                _step(
                    "takeoff-recovery-height",
                    "Start and hover at 50 cm",
                    "Play takes off, captures 0.50 m, and holds for the operator.",
                    "The takeoff point becomes the HOME XY containment reference.",
                ),
                _step(
                    "wait-for-flip",
                    "Wait for the Flip action",
                    "Keep hovering until the mission-only Flip button is pressed once.",
                    "Abort and land remains available throughout the wait.",
                ),
                _step(
                    "collective-boost",
                    "Collective boost",
                    (
                        f"Stream zero body rate and {REFERENCE_THRUST_PERCENT:g}% collective "
                        f"for {BOOST_DURATION_S:.2f} s."
                    ),
                    "Measured X and Y must each remain within ±0.50 m of HOME.",
                ),
                _step(
                    "single-roll-rate-profile",
                    "One cubic roll-rate profile",
                    (
                        f"Stream {REFERENCE_ROTATION_DEG:g}° of positive roll at "
                        f"{1.0 / SAMPLE_PERIOD_S:.0f} Hz with a "
                        f"{REFERENCE_PEAK_RATE_DEG_S:g} deg/s continuous-profile limit."
                    ),
                    "The onboard rate PID and X mixer retain closed-loop motor authority; "
                    "crossing the XY box interrupts the stream and starts recovery.",
                ),
                _step(
                    "high-level-handoff",
                    "Recover stable hover",
                    (
                        "Send the terminal zero-rate sample, release manual-commander "
                        f"priority after {single_roll.duration_s:.2f} s, and return to HLC."
                    ),
                    "A motor-cut setpoint is never used for the handoff.",
                ),
                _step(
                    "land-over-cushion",
                    "Land over the cushion",
                    "Command a controlled landing after attitude recovery.",
                    "Landing position is observed, not used as the maneuver success target.",
                ),
            ),
            learning_signals=(
                "authored roll-rate and collective-thrust stream",
                "measured roll angle and gyro roll rate",
                "measured motor m1/m2/m3/m4 outputs",
                "vertical position and velocity",
                "commander handoff and supervisor state",
                "link timing and missed-deadline failures",
            ),
        ),
    )
    return BasicFlightLabCatalog(
        purpose=(
            "Build basic physical behavior and run bounded controller-characterization "
            "or cushioned-acrobatics learning missions without turning observations into "
            "qualification claims."
        ),
        clusters=(
            BasicFlightLabCluster(
                cluster_id="basic-flight",
                cluster_name="Basic flight",
                purpose=("Build basic behavior from ground state transitions to contained motion."),
            ),
            BasicFlightLabCluster(
                cluster_id="controller-characterization-tuning",
                cluster_name="Controller characterization & tuning",
                purpose=(
                    "Characterize the measured box fixture, default controller response, "
                    "range geometry, and bounded outer-loop behavior."
                ),
                state="READY" if fixture is not None else "SETUP_REQUIRED",
                detail=(
                    "Implemented missions are operator-selectable; incomplete fixture "
                    "characterization remains visible as advisory metadata."
                ),
            ),
            BasicFlightLabCluster(
                cluster_id=ACROBATICS_CLUSTER_ID,
                cluster_name="Cushioned acrobatics",
                purpose=(
                    "Learn the Crazyflie rate-controller and motor-mixer boundary with "
                    "short, finite aerobatic profiles."
                ),
                state="READY",
                detail="Play establishes a 50 cm hover; Flip then runs once and auto-lands.",
            ),
        ),
        controller_tuning_fixture=fixture_status,
        motions=(*basic_motions, *tuning_motions, *acrobatics_motions),
    )


class BasicFlightLabService:
    """Runs private rehearsals and archives physical telemetry for learning."""

    def __init__(
        self,
        runtime: ApplicationRuntime,
        *,
        artifact_path: Path | None = None,
        physical_link_factory: Callable[[], CrazyflieLink] | None = None,
        physical_vehicle_provider: PhysicalVehicleProvider | None = None,
        physical_hover_duration_s: float = 30.0,
        physical_arm_duration_s: float = 3.0,
        acrobatics_trigger_timeout_s: float = ACROBATICS_TRIGGER_TIMEOUT_S,
        acrobatics_recovery_duration_s: float = ACROBATICS_RECOVERY_DURATION_S,
        motor_watchdog_timeout_s: float = 0.75,
        motor_bench_terminal_callback: Callable[[], Awaitable[object]] | None = None,
        physical_flight_terminal_callback: Callable[[], Awaitable[object]] | None = None,
        physical_telemetry_callback: Callable[[TelemetryEnvelope], None] | None = None,
        controller_tuning_fixture_path: Path = DEFAULT_CONTROLLER_TUNING_FIXTURE_PATH,
    ) -> None:
        if physical_hover_duration_s <= 0.0:
            raise ValueError("physical_hover_duration_s must be positive")
        if physical_arm_duration_s <= 0.0:
            raise ValueError("physical_arm_duration_s must be positive")
        if acrobatics_trigger_timeout_s <= 0.0:
            raise ValueError("acrobatics_trigger_timeout_s must be positive")
        if acrobatics_recovery_duration_s < 0.0:
            raise ValueError("acrobatics_recovery_duration_s cannot be negative")
        if motor_watchdog_timeout_s <= 0.0:
            raise ValueError("motor_watchdog_timeout_s must be positive")
        self._runtime = runtime
        self._artifact_path = artifact_path or (
            runtime.config.cache_directory / "digital-twin-basic-flight-runs.jsonl"
        )
        self._lock = asyncio.Lock()
        self._physical_link_factory = physical_link_factory or (
            lambda: CflibCrazyflieLink(
                cache_directory=self._runtime.config.cache_directory / "cflib",
                enable_latency_pings=False,
            )
        )
        self._physical_vehicle_provider = physical_vehicle_provider
        self._physical_hover_duration_s = physical_hover_duration_s
        self._physical_arm_duration_s = physical_arm_duration_s
        self._acrobatics_trigger_timeout_s = acrobatics_trigger_timeout_s
        self._acrobatics_recovery_duration_s = acrobatics_recovery_duration_s
        self._motor_watchdog_timeout_s = motor_watchdog_timeout_s
        self._motor_bench_terminal_callback = motor_bench_terminal_callback
        self._physical_flight_terminal_callback = physical_flight_terminal_callback
        self._physical_telemetry_callback = physical_telemetry_callback
        self._controller_tuning_fixture_path = controller_tuning_fixture_path
        self._physical_flight_lock = asyncio.Lock()
        self._physical_flight_marker_path = (
            self._runtime.config.cache_directory / "physical-flight-operation.json"
        )
        self._physical_flight = self._load_physical_flight_marker()
        self._motor_lock = asyncio.Lock()
        self._motor_session: _ActiveMotorBench | None = None
        self._motor_marker_path = (
            self._runtime.config.cache_directory / "motor-bench-actuation.json"
        )
        self._motor_reboot_path = (
            self._runtime.config.cache_directory / "motor-bench-reboot-required"
        )
        self._motor_stop_in_progress = False
        self._motor_stop_error: str | None = None
        self._motor_reboot_required = self._motor_reboot_path.exists()

    def catalog(self) -> BasicFlightLabCatalog:
        return basic_flight_catalog(
            controller_tuning_fixture_path=self._controller_tuning_fixture_path
        )

    def _controller_tuning_fixture(
        self,
    ) -> tuple[ControllerTuningFixtureDefinition | None, ControllerTuningFixtureStatus]:
        return load_controller_tuning_fixture_status(self._controller_tuning_fixture_path)

    def _physical_motion_block_reason(self, motion_id: str) -> str | None:
        if motion_id not in CONTROLLER_TUNING_PHYSICAL_MOTION_IDS:
            return None
        fixture, status = self._controller_tuning_fixture()
        return controller_tuning_motion_block_reason(motion_id, fixture, status)

    def _controller_tuning_preparation(
        self,
        request: PhysicalBasicFlightRunRequest,
        fixture: ControllerTuningFixtureDefinition,
        *,
        resolved_height_m: float | None,
    ) -> ControllerTuningRunPreparation:
        if request.station_id is None:
            raise RuntimeError("Select floor marker A, B, C, D, or E before starting")
        return ControllerTuningRunPreparation(
            fixture_id=fixture.fixture_id,
            fixture_version=fixture.fixture_version,
            fixture_sha256=canonical_sha256(fixture.model_dump(mode="json")),
            station_id=request.station_id,
            heading_deg=request.heading_deg,
            target_height_m=resolved_height_m,
        )

    def _physical_request_block_reason(
        self,
        request: PhysicalBasicFlightRunRequest,
    ) -> str | None:
        block_reason = self._physical_motion_block_reason(request.motion_id)
        if block_reason is not None:
            return block_reason
        if request.motion_id not in CONTROLLER_TUNING_PHYSICAL_MOTION_IDS:
            return None
        fixture, status = self._controller_tuning_fixture()
        if fixture is None:
            return status.detail
        if request.station_id is None:
            return "Select floor marker A, B, C, D, or E before starting"
        markers = {marker.marker_id: marker for marker in fixture.floor_markers}
        if request.station_id not in markers:
            return f"Floor marker {request.station_id} is unavailable in the fixture artifact"
        encoded_station = (
            request.motion_id.rsplit("-", 1)[-1].upper()
            if request.motion_id.startswith("tuning-a-station-")
            else None
        )
        if encoded_station is not None and encoded_station != request.station_id:
            return (
                f"Mission A motion {request.motion_id} does not match selected marker "
                f"{request.station_id}"
            )
        resolved_height_m = request.target_height_m
        if request.motion_id in CONTROLLER_TUNING_FLIGHT_MOTION_IDS:
            resolved_height_m = resolved_height_m or fixture.nominal_hover_height_m
            if resolved_height_m is None:
                return "Select a flight height or complete the fixture nominal hover height"
        return None

    async def shutdown(self) -> None:
        """Fail closed and release an active physical bench during graceful shutdown."""

        async with self._physical_flight_lock:
            flight = self._physical_flight
            owns_live_flight = flight is not None and (
                flight.vehicle is not None or (flight.task is not None and not flight.task.done())
            )
        if owns_live_flight:
            await self.abort_physical_flight(reason="dashboard service stopped")

        async with self._motor_lock:
            session = self._motor_session
            if session is None:
                return
            session.status = "FAILED"
            session.error = "dashboard service stopped; motor output was set to zero"
            task = session.monitor_task
            session.monitor_task = None
            self._motor_session = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._finish_failed_motor_bench(session)

    async def motor_actuation_status(self) -> MotorActuationStatus:
        """Return direct-PWM truth even when the initiating browser state is gone."""

        async with self._motor_lock:
            return self._motor_actuation_status_locked()

    async def reconcile_motor_reboot_required(
        self,
        *,
        observation_current: bool,
        faults: Sequence[str],
    ) -> MotorActuationStatus:
        """Clear a watchdog reboot marker only from fresh unlocked firmware truth."""

        async with self._motor_lock:
            if (
                self._motor_reboot_required
                and observation_current
                and "SUPERVISOR_STATE_UNKNOWN" not in faults
                and "SUPERVISOR_LOCKED" not in faults
            ):
                self._clear_motor_reboot_required()
            return self._motor_actuation_status_locked()

    async def recover_stale_motor_output(
        self,
        *,
        fallback_target: PhysicalCommandTarget | None = None,
    ) -> MotorActuationStatus:
        """Clear an override left behind by a crashed or replaced API process."""

        if not self._motor_marker_path.exists():
            return await self.motor_actuation_status()
        return await self.stop_all_motor_output(fallback_target=fallback_target)

    async def stop_all_motor_output(
        self,
        *,
        fallback_target: PhysicalCommandTarget | None = None,
    ) -> MotorActuationStatus:
        """Idempotently clear direct PWM without requiring the original session ID."""

        async with self._motor_lock:
            self._motor_stop_in_progress = True
            self._motor_stop_error = None
            session = self._motor_session
            if session is not None:
                session.status = "STOPPED"
                task = session.monitor_task
                session.monitor_task = None
                self._motor_session = None
                if task is not None and task is not asyncio.current_task():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                await self._finish_motor_bench(session)
                self._motor_stop_in_progress = False
                return self._motor_actuation_status_locked()

            marker = self._read_motor_marker()
            selected_uri = (
                str(marker.get("selected_uri"))
                if marker is not None and isinstance(marker.get("selected_uri"), str)
                else fallback_target.selected_uri
                if fallback_target is not None
                else None
            )
            if selected_uri is None:
                self._motor_stop_in_progress = False
                self._motor_stop_error = "No configured physical drone is available for motor stop"
                return self._motor_actuation_status_locked()

            # Persist uncertainty before touching the radio. A process failure during
            # this recovery attempt must never turn an unknown output into IDLE.
            marker_selection = None if marker is None else marker.get("motor_selection")
            recovery_selection = cast(
                MotorSelection,
                marker_selection if marker_selection in {"all", "m1", "m2", "m3", "m4"} else "all",
            )
            marker_output = None if marker is None else marker.get("output_percent")
            recovery_output = (
                float(marker_output) if isinstance(marker_output, (int, float)) else 0.0
            )
            recovery_watchdog_armed = bool(
                marker is not None and marker.get("firmware_watchdog_armed", False)
            )
            self._motor_reboot_required = self._motor_reboot_required or recovery_watchdog_armed
            if recovery_watchdog_armed:
                self._mark_motor_reboot_required()
            self._write_motor_marker(
                session_id=(
                    str(marker.get("session_id"))
                    if marker is not None and isinstance(marker.get("session_id"), str)
                    else "global-motor-stop"
                ),
                selected_uri=selected_uri,
                motor_selection=recovery_selection,
                output_percent=recovery_output,
                firmware_watchdog_armed=recovery_watchdog_armed,
            )
            vehicle = CrazyflieVehicle(
                vehicle_id="motor-stop-recovery",
                selected_uri=selected_uri,
                link=self._physical_link_factory(),
                telemetry_listener=self._physical_telemetry_callback,
            )
            connected = False
            try:
                await asyncio.wait_for(
                    vehicle.connect(),
                    timeout=MOTOR_RECOVERY_CONNECT_TIMEOUT_S,
                )
                connected = True
                await asyncio.wait_for(
                    vehicle.end_motor_bench(),
                    timeout=MOTOR_STOP_IO_TIMEOUT_S,
                )
            except Exception as error:
                self._motor_stop_error = f"Motor stop could not be confirmed: {error}"
            finally:
                if connected:
                    with suppress(Exception):
                        await asyncio.wait_for(
                            vehicle.disconnect(),
                            timeout=MOTOR_STOP_IO_TIMEOUT_S,
                        )
                self._motor_stop_in_progress = False
            if self._motor_stop_error is None:
                self._clear_motor_marker()
            return self._motor_actuation_status_locked()

    async def run(self, request: BasicFlightLabRunRequest) -> BasicFlightLabRun:
        motion = next(
            (item for item in self.catalog().motions if item.motion_id == request.motion_id),
            None,
        )
        if motion is None:
            raise ValueError(f"unknown basic-flight motion: {request.motion_id}")
        if motion.cluster_id != "basic-flight":
            raise ValueError(
                f"{motion.cluster_id} missions have no validated Fast Sim vehicle model"
            )
        async with self._lock:
            result = await self._run_private_simulator(motion)
            self._artifact_path.parent.mkdir(parents=True, exist_ok=True)
            with self._artifact_path.open("a", encoding="utf-8") as artifact:
                artifact.write(result.model_dump_json() + "\n")
            return result

    async def run_physical(
        self,
        request: PhysicalBasicFlightRunRequest,
        *,
        target: PhysicalCommandTarget,
        operator_id: str,
        active_operation: _ActivePhysicalFlight | None = None,
    ) -> BasicFlightLabRun:
        block_reason = self._physical_request_block_reason(request)
        if block_reason is not None:
            raise RuntimeError(block_reason)
        async with self._lock:
            result = await self._run_contained_physical(
                request,
                target=target,
                operator_id=operator_id,
                active_operation=active_operation,
            )
            self._artifact_path.parent.mkdir(parents=True, exist_ok=True)
            with self._artifact_path.open("a", encoding="utf-8") as artifact:
                artifact.write(result.model_dump_json() + "\n")
        return result

    async def physical_flight_status(self) -> PhysicalFlightOperationStatus:
        async with self._physical_flight_lock:
            return self._physical_flight_status_locked()

    async def reconcile_physical_flight_stop(
        self,
        *,
        observation_current: bool,
        armed: bool | None,
        flying: bool | None,
        auto_arming: bool | None = None,
        fallback_target: PhysicalCommandTarget | None = None,
    ) -> PhysicalFlightOperationStatus:
        """Clear uncertainty only from current supervisor-confirmed ground state."""

        async with self._physical_flight_lock:
            safe_ground = self._supervisor_confirms_safe_ground(
                observation_current=observation_current,
                armed=armed,
                flying=flying,
                auto_arming=auto_arming,
            )
            operation = self._physical_flight
            if operation is not None and self._is_observer_recovery_operation(operation):
                # Older status polling invented a flight when an idle observer was
                # unavailable. That synthetic state never owned a command link and
                # must not keep presenting Abort and land as an active mission.
                self._physical_flight = None
                operation = None
            if (
                operation is not None
                and not operation.stop_required
                and operation.state not in {"ABORTED", "COMPLETED", "FAILED"}
                and fallback_target is not None
                and not safe_ground
            ):
                operation.state = "STOP_UNCONFIRMED"
                operation.stop_required = True
                operation.detail = (
                    "Current supervisor stop state is unavailable"
                    if armed is None and flying is None
                    else "Current supervisor state no longer confirms the drone is stopped"
                )
                self._write_physical_flight_marker(operation)
            if (
                operation is not None
                and operation.stop_required
                and operation.state in {"ABORTING", "STOP_UNCONFIRMED", "FAILED"}
                and safe_ground
            ):
                operation.state = "ABORTED"
                operation.stop_required = False
                operation.detail = (
                    "Recovered observer confirmed the physical drone is grounded and not flying"
                    if auto_arming
                    else (
                        "Recovered observer confirmed the physical drone is disarmed and not flying"
                    )
                )
                operation.failure_details = None
                self._write_physical_flight_marker(operation)
            return self._physical_flight_status_locked()

    @staticmethod
    def _supervisor_confirms_safe_ground(
        *,
        observation_current: bool,
        armed: bool | None,
        flying: bool | None,
        auto_arming: bool | None,
    ) -> bool:
        """Accept firmware auto-armed idle as safe only while explicitly not flying."""

        return bool(
            observation_current
            and flying is False
            and (armed is False or (armed is True and auto_arming is True))
        )

    @staticmethod
    def _is_observer_recovery_operation(operation: _ActivePhysicalFlight) -> bool:
        return (
            operation.operator_id == "observer-state-recovery"
            and operation.operation_id.startswith("observer-recovery-")
        )

    async def start_physical_flight(
        self,
        request: PhysicalBasicFlightRunRequest,
        *,
        target: PhysicalCommandTarget,
        operator_id: str,
    ) -> PhysicalFlightOperationStatus:
        """Start a backend-owned flight and return before any long motion completes."""

        async with self._physical_flight_lock:
            block_reason = self._physical_request_block_reason(request)
            if block_reason is not None:
                raise RuntimeError(block_reason)
            current = self._physical_flight
            if current is not None and current.stop_required:
                raise RuntimeError("a contained physical flight is already active")
            operation = _ActivePhysicalFlight(
                operation_id=(
                    f"twin-tuning-real-{uuid.uuid4().hex}"
                    if request.motion_id in CONTROLLER_TUNING_PHYSICAL_MOTION_IDS
                    else f"twin-acrobatics-real-{uuid.uuid4().hex}"
                    if request.motion_id == SINGLE_ROLL_MOTION_ID
                    else f"twin-basic-real-{uuid.uuid4().hex}"
                ),
                request=request,
                target=target,
                operator_id=operator_id,
                started_at_utc=datetime.now(UTC),
            )
            self._physical_flight = operation
            # Persist uncertainty before scheduling any radio or flight work.
            self._write_physical_flight_marker(operation)
            operation.task = asyncio.create_task(
                self._run_scheduled_physical_flight(operation),
                name=f"physical-flight-{operation.operation_id}",
            )
            return self._physical_flight_status_locked()

    async def request_acrobatics_flip(self) -> PhysicalFlightOperationStatus:
        """Trigger the one-shot roll only after its backend-owned hover is ready."""

        async with self._physical_flight_lock:
            operation = self._physical_flight
            if operation is None or not operation.stop_required:
                raise RuntimeError("no active cushioned-acrobatics hover is available")
            if operation.request.motion_id != SINGLE_ROLL_MOTION_ID:
                raise RuntimeError("Flip is only available for the cushioned-acrobatics mission")
            if operation.abort_requested:
                raise RuntimeError("the physical flight is already aborting")
            if operation.state == "FLIPPING" and operation.flip_triggered:
                return self._physical_flight_status_locked()
            if operation.state != "HOVERING_READY" or operation.flip_triggered:
                raise RuntimeError("Flip is not available until the 50 cm hover is captured")
            operation.flip_triggered = True
            operation.state = "FLIPPING"
            operation.detail = "Flip triggered; executing the finite roll profile"
            operation.flip_requested.set()
            self._write_physical_flight_marker(operation)
            return self._physical_flight_status_locked()

    async def abort_physical_flight(
        self,
        *,
        reason: str = "operator requested abort and land",
    ) -> PhysicalFlightOperationStatus:
        """Globally land and disarm the active contained flight, then cancel its plan."""

        async with self._physical_flight_lock:
            operation = self._physical_flight
            if operation is None:
                return PhysicalFlightOperationStatus(state="IDLE", stop_required=False)
            if not operation.stop_required:
                return self._physical_flight_status_locked()
            is_observation = operation.request.motion_id in PHYSICAL_OBSERVATION_MOTION_IDS
            operation.abort_requested = True
            operation.state = "ABORTING"
            operation.detail = (
                "Stopping fixture observation"
                if is_observation
                else "Landing and disarming the physical drone"
            )
            self._write_physical_flight_marker(operation)
            vehicle = operation.vehicle
            permit = operation.permit
            task = operation.task
            cancel_before_dispatch = (
                task is not None
                and task is not asyncio.current_task()
                and not task.done()
                and not operation.command_evidence
            )

        abort_error: Exception | None = None
        try:
            if cancel_before_dispatch:
                # Play may still be opening the command link. No command has been
                # dispatched, so cancel startup cleanly instead of opening a second
                # recovery connection that can only create an abort/reconnect loop.
                assert task is not None
                operation.abort_complete.set()
                with suppress(asyncio.CancelledError):
                    await task
            elif vehicle is None or permit is None:
                # A restored operation has no in-memory adapter. Cancel any
                # not-yet-connected plan, reconnect the exact retained URI, and
                # decide from fresh supervisor truth whether land/disarm is needed.
                if task is not None and task is not asyncio.current_task() and not task.done():
                    operation.abort_complete.set()
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                await self._recover_physical_flight_stop(operation, reason=reason)
            else:
                vehicle.install_command_permit(permit)
                if operation.request.motion_id == SINGLE_ROLL_MOTION_ID:
                    await vehicle.cancel_body_rate_thrust()
                await self._execute_recorded_physical_command(
                    operation,
                    vehicle,
                    AbortCommand(reason=reason),
                    command_prefix="abort",
                )
                if vehicle.supervisor_auto_arming is not True:
                    await self._execute_recorded_physical_command(
                        operation,
                        vehicle,
                        DisarmCommand(),
                        command_prefix="disarm",
                    )
        except Exception as error:
            abort_error = error
            if vehicle is not None and permit is not None:
                # The active link may have disappeared after dispatch. Stop the
                # remaining plan, then reconnect once and decide from fresh state;
                # this is not a blind command retry.
                if task is not None and task is not asyncio.current_task() and not task.done():
                    operation.abort_complete.set()
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                operation.vehicle = None
                operation.permit = None
                try:
                    await self._recover_physical_flight_stop(operation, reason=reason)
                except Exception as recovery_error:
                    operation.failure_details = {
                        "initial_abort_failure": self._exception_evidence(error),
                        "recovery_failure": self._exception_evidence(recovery_error),
                    }
                    abort_error = recovery_error
                else:
                    abort_error = None

        if task is not None and task is not asyncio.current_task() and not task.done():
            operation.abort_complete.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        else:
            operation.abort_complete.set()

        async with self._physical_flight_lock:
            if abort_error is None:
                operation.state = "ABORTED"
                operation.stop_required = False
                operation.detail = (
                    "Fixture observation stopped; no flight command was issued"
                    if operation.request.motion_id in PHYSICAL_OBSERVATION_MOTION_IDS
                    else "Physical flight aborted and landed safely"
                    if operation.vehicle is not None
                    and operation.vehicle.supervisor_auto_arming is True
                    else "Physical flight aborted, landed, and disarmed"
                )
                operation.failure_details = None
            else:
                operation.state = "FAILED"
                operation.stop_required = True
                operation.detail = f"Abort could not be confirmed: {abort_error}"
                if operation.failure_details is None:
                    operation.failure_details = self._exception_evidence(abort_error)
            self._write_physical_flight_marker(operation)
            status = self._physical_flight_status_locked()

        callback = self._physical_flight_terminal_callback
        if (
            callback is not None
            and operation.abort_task is not None
            and operation.abort_task is asyncio.current_task()
        ):
            with suppress(Exception):
                await callback()
        return status

    def _make_recovery_flight_permit(
        self,
        operation: _ActivePhysicalFlight,
        *,
        vehicle_id: str,
    ) -> CommandPermit:
        issued = datetime.now(UTC)
        authorization_sha256 = canonical_sha256(
            {
                "operation_id": operation.operation_id,
                "operator_id": operation.operator_id,
                "vehicle_id": vehicle_id,
                "selected_uri_sha256": canonical_sha256(operation.target.selected_uri),
                "purpose": "abort-and-land-recovery",
                "issued_at_utc": issued,
            }
        )
        return CommandPermit(
            permit_id=f"flight-recovery-{uuid.uuid4().hex}",
            vehicle_id=vehicle_id,
            selected_uri=operation.target.selected_uri,
            operator_id=operation.operator_id,
            scope=PermitScope.CONTAINED_FLIGHT,
            issued_at_utc=issued,
            expires_at_utc=issued + timedelta(seconds=30),
            operator_present=True,
            props_removed=False,
            physically_restrained=False,
            flight_entry_record_id=f"recovered-{operation.operation_id}",
            flight_entry_evidence_sha256=authorization_sha256,
        )

    async def _recover_physical_flight_stop(
        self,
        operation: _ActivePhysicalFlight,
        *,
        reason: str,
    ) -> None:
        if not operation.target.selected_uri:
            raise RuntimeError("recovered flight has no trusted Crazyflie URI")
        vehicle_id = (
            "flight-recovery:"
            f"{(operation.target.observed_identity_sha256 or uuid.uuid4().hex)[:16]}"
        )
        vehicle = CrazyflieVehicle(
            vehicle_id=vehicle_id,
            selected_uri=operation.target.selected_uri,
            link=self._physical_link_factory(),
            telemetry_listener=self._physical_telemetry_callback,
        )
        connected = False
        try:
            await asyncio.wait_for(
                vehicle.connect(),
                timeout=FLIGHT_RECOVERY_CONNECT_TIMEOUT_S,
            )
            connected = True
            sample = await asyncio.wait_for(
                vehicle.snapshot(),
                timeout=FLIGHT_RECOVERY_CONNECT_TIMEOUT_S,
            )
            if "SUPERVISOR_STATE_UNKNOWN" in sample.telemetry.faults:
                raise RuntimeError("fresh supervisor state is unavailable after reconnect")
            permit = self._make_recovery_flight_permit(operation, vehicle_id=vehicle_id)
            vehicle.install_command_permit(permit)
            if sample.telemetry.flying:
                await self._execute_recorded_physical_command(
                    operation,
                    vehicle,
                    AbortCommand(reason=reason),
                    command_prefix="recovery-abort",
                )
                sample = await vehicle.snapshot()
            if sample.telemetry.armed and vehicle.supervisor_auto_arming is not True:
                await self._execute_recorded_physical_command(
                    operation,
                    vehicle,
                    DisarmCommand(),
                    command_prefix="recovery-disarm",
                )
                sample = await vehicle.snapshot()
            if (
                "SUPERVISOR_STATE_UNKNOWN" in sample.telemetry.faults
                or sample.telemetry.flying
                or (sample.telemetry.armed and vehicle.supervisor_auto_arming is not True)
            ):
                raise RuntimeError("reconnected supervisor did not confirm a complete stop")
        finally:
            vehicle.clear_command_permit()
            if connected:
                with suppress(Exception):
                    await asyncio.wait_for(
                        vehicle.disconnect(),
                        timeout=FLIGHT_RECOVERY_COMMAND_TIMEOUT_S,
                    )

    async def _execute_recorded_physical_command(
        self,
        operation: _ActivePhysicalFlight,
        vehicle: CrazyflieVehicle,
        payload: CommandPayload,
        *,
        command_prefix: str,
        timeout_s: float = FLIGHT_RECOVERY_COMMAND_TIMEOUT_S,
        source: CommandSource = CommandSource.UI,
    ) -> None:
        command = CommandEnvelope(
            vehicle_id=vehicle.identity.vehicle_id,
            command_id=f"{command_prefix}-{uuid.uuid4().hex[:12]}",
            mission_run_id=operation.operation_id,
            issued_at_monotonic_s=time.monotonic(),
            source=source,
            mode=OperatingMode.LIVE,
            payload=payload,
        )
        record: dict[str, Any] = {
            "command_id": command.command_id,
            "command_kind": payload.kind.value,
            "phase": "DISPATCHING",
            "issued_at_monotonic_s": command.issued_at_monotonic_s,
            "recorded_at_utc": datetime.now(UTC).isoformat(),
        }
        operation.command_evidence.append(record)
        self._write_physical_flight_marker(operation)
        try:
            acknowledgement = await asyncio.wait_for(
                vehicle.execute(command),
                timeout=timeout_s,
            )
        except Exception as error:
            outcome_unknown = isinstance(error, asyncio.TimeoutError) or (
                isinstance(error, CrazySwarmError)
                and error.details.get("command_outcome")
                == AcknowledgementStatus.UNKNOWN_OUTCOME.value
            )
            record["phase"] = "OUTCOME_UNKNOWN" if outcome_unknown else "NOT_DISPATCHED"
            record["failure"] = self._exception_evidence(error)
            self._write_physical_flight_marker(operation)
            raise
        record.update(
            {
                "phase": "COMPLETED",
                "acknowledgement_status": acknowledgement.status.value,
                "received_at_monotonic_s": acknowledgement.received_at_monotonic_s,
                "completed_at_monotonic_s": acknowledgement.completed_at_monotonic_s,
            }
        )
        self._write_physical_flight_marker(operation)

    async def request_physical_flight_abort(
        self,
        *,
        reason: str = "operator requested abort and land",
    ) -> PhysicalFlightOperationStatus:
        """Acknowledge abort immediately; backend ownership completes it asynchronously."""

        async with self._physical_flight_lock:
            operation = self._physical_flight
            if operation is None:
                return PhysicalFlightOperationStatus(state="IDLE", stop_required=False)
            if not operation.stop_required:
                return self._physical_flight_status_locked()
            if operation.abort_task is not None and not operation.abort_task.done():
                return self._physical_flight_status_locked()
            operation.abort_requested = True
            operation.state = "ABORTING"
            operation.detail = (
                "Stopping fixture observation"
                if operation.request.motion_id in PHYSICAL_OBSERVATION_MOTION_IDS
                else "Landing and disarming the physical drone"
            )
            self._write_physical_flight_marker(operation)
            operation.abort_task = asyncio.create_task(
                self.abort_physical_flight(reason=reason),
                name=f"physical-flight-abort-{operation.operation_id}",
            )
            return self._physical_flight_status_locked()

    async def _run_scheduled_physical_flight(
        self,
        operation: _ActivePhysicalFlight,
    ) -> None:
        try:
            result = await self.run_physical(
                operation.request,
                target=operation.target,
                operator_id=operation.operator_id,
                active_operation=operation,
            )
        except asyncio.CancelledError:
            async with self._physical_flight_lock:
                if operation.state != "FAILED":
                    operation.state = "ABORTING"
                    operation.detail = "Flight plan cancelled; landing confirmation is pending"
                    self._write_physical_flight_marker(operation)
            raise
        except Exception as error:
            async with self._physical_flight_lock:
                operation.state = "FAILED"
                if not operation.command_evidence:
                    operation.stop_required = False
                    operation.detail = f"Physical flight did not start: {error}"
                else:
                    operation.detail = str(error)
                operation.failure_details = self._exception_evidence(error)
                self._write_physical_flight_marker(operation)
        else:
            async with self._physical_flight_lock:
                operation.result = result
                operation.state = "COMPLETED"
                operation.stop_required = False
                operation.detail = (
                    "Fixture observation completed; no flight command was issued"
                    if operation.request.motion_id in PHYSICAL_OBSERVATION_MOTION_IDS
                    else "Physical flight completed and landed safely"
                    if operation.vehicle is not None
                    and operation.vehicle.supervisor_auto_arming is True
                    else "Physical flight completed, landed, and disarmed"
                )
                operation.failure_details = None
                self._write_physical_flight_marker(operation)
        finally:
            callback = self._physical_flight_terminal_callback
            abort_owns_completion = (
                operation.abort_task is not None and not operation.abort_task.done()
            )
            if callback is not None and not abort_owns_completion:
                with suppress(Exception):
                    await callback()

    def _physical_flight_status_locked(self) -> PhysicalFlightOperationStatus:
        operation = self._physical_flight
        if operation is None:
            return PhysicalFlightOperationStatus(state="IDLE", stop_required=False)
        preparation = None
        if (
            operation.request.motion_id in CONTROLLER_TUNING_PHYSICAL_MOTION_IDS
            and operation.request.station_id is not None
        ):
            fixture, _ = self._controller_tuning_fixture()
            if fixture is not None:
                preparation = self._controller_tuning_preparation(
                    operation.request,
                    fixture,
                    resolved_height_m=(
                        operation.request.target_height_m
                        or (
                            fixture.nominal_hover_height_m
                            if operation.request.motion_id in CONTROLLER_TUNING_FLIGHT_MOTION_IDS
                            else None
                        )
                    ),
                )
        return PhysicalFlightOperationStatus(
            state=operation.state,
            stop_required=operation.stop_required,
            operation_id=operation.operation_id,
            motion_id=operation.request.motion_id,
            started_at_utc=operation.started_at_utc,
            detail=operation.detail,
            result=operation.result,
            failure_details=operation.failure_details,
            command_evidence=tuple(operation.command_evidence),
            controller_tuning_preparation=preparation,
            available_action=(
                "FLIP"
                if (
                    operation.request.motion_id == SINGLE_ROLL_MOTION_ID
                    and operation.state == "HOVERING_READY"
                    and not operation.flip_triggered
                    and not operation.abort_requested
                )
                else None
            ),
        )

    async def start_motor_bench(
        self,
        request: MotorBenchStartRequest,
        *,
        target: PhysicalCommandTarget,
        operator_id: str,
    ) -> MotorBenchSession:
        async with self._motor_lock:
            if self._motor_session is not None and self._motor_session.status == "ACTIVE":
                raise RuntimeError("a motor bench session is already active")
            session_id = f"motor-bench-real-{uuid.uuid4().hex}"
            vehicle_id = f"motor-bench:{(target.observed_identity_sha256 or uuid.uuid4().hex)[:16]}"
            vehicle = CrazyflieVehicle(
                vehicle_id=vehicle_id,
                selected_uri=target.selected_uri,
                link=self._physical_link_factory(),
                telemetry_listener=self._physical_telemetry_callback,
            )
            issued = datetime.now(UTC)
            permit = CommandPermit(
                permit_id=f"motor-bench-{uuid.uuid4().hex}",
                vehicle_id=vehicle_id,
                selected_uri=target.selected_uri,
                operator_id=operator_id,
                scope=PermitScope.PROPS_OFF_BENCH,
                issued_at_utc=issued,
                expires_at_utc=issued + timedelta(minutes=10),
                operator_present=True,
                props_removed=request.props_removed_confirmed,
                physically_restrained=request.physically_restrained_confirmed,
            )
            connected = False
            override_started = False
            self._write_motor_marker(
                session_id=session_id,
                selected_uri=target.selected_uri,
                motor_selection=request.motor_selection,
                output_percent=0.0,
            )
            try:
                await vehicle.connect()
                connected = True
                initial = await vehicle.snapshot()
                if "SUPERVISOR_LOCKED" in initial.telemetry.faults:
                    raise RuntimeError(
                        "Crazyflie safety watchdog is locked; power cycle the drone "
                        "before motor control"
                    )
                self._clear_motor_reboot_required()
                vehicle.install_command_permit(permit)
                await vehicle.begin_motor_bench(request.motor_selection)
                override_started = True
                session = _ActiveMotorBench(
                    session_id=session_id,
                    motor_selection=request.motor_selection,
                    selected_uri=target.selected_uri,
                    vehicle=vehicle,
                    started_at_utc=issued,
                    started_at_monotonic_s=time.monotonic(),
                )
                self._capture_motor_record(session, initial)
                session.monitor_task = asyncio.create_task(self._monitor_motor_bench(session))
                self._motor_session = session
                return self._motor_session_view(session)
            except Exception:
                cleanup_confirmed = not override_started
                if override_started:
                    try:
                        await vehicle.end_motor_bench()
                        cleanup_confirmed = True
                    except Exception:
                        pass
                vehicle.clear_command_permit()
                if connected:
                    with suppress(Exception):
                        await vehicle.disconnect()
                if cleanup_confirmed:
                    self._clear_motor_marker()
                raise

    async def update_motor_bench(
        self,
        request: MotorBenchUpdateRequest,
    ) -> MotorBenchSession:
        async with self._motor_lock:
            session = self._require_motor_session(request.session_id)
            if session.status != "ACTIVE":
                raise RuntimeError(session.error or "motor bench session is not active")
            if request.output_percent != session.output_percent:
                watchdog_will_be_armed = (
                    session.firmware_watchdog_armed or request.output_percent > 0.0
                )
                self._write_motor_marker(
                    session_id=session.session_id,
                    selected_uri=session.selected_uri,
                    motor_selection=session.motor_selection,
                    output_percent=request.output_percent,
                    firmware_watchdog_armed=watchdog_will_be_armed,
                )
                if request.output_percent > 0.0 and not session.firmware_watchdog_armed:
                    # Firmware stops all motors in about one second if this process
                    # disappears. Expiry intentionally locks until power cycle.
                    await session.vehicle.feed_motor_bench_watchdog()
                    session.firmware_watchdog_armed = True
                    self._mark_motor_reboot_required()
                await session.vehicle.set_motor_bench_power(
                    session.motor_selection,
                    request.output_percent,
                )
            session.output_percent = request.output_percent
            session.last_update_monotonic_s = time.monotonic()
            return self._motor_session_view(session)

    async def stop_motor_bench(self, request: MotorBenchStopRequest) -> MotorBenchSession:
        async with self._motor_lock:
            session = self._require_motor_session(request.session_id)
            if session.status == "ACTIVE":
                session.status = "STOPPED"
            task = session.monitor_task
            session.monitor_task = None
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await self._finish_motor_bench(session)
            self._motor_session = None
            return self._motor_session_view(session)

    def _require_motor_session(self, session_id: str) -> _ActiveMotorBench:
        session = self._motor_session
        if session is None or session.session_id != session_id:
            raise RuntimeError("motor bench session is not active")
        return session

    async def _monitor_motor_bench(self, session: _ActiveMotorBench) -> None:
        try:
            while session.status == "ACTIVE":
                async with self._motor_lock:
                    if self._motor_session is not session or session.status != "ACTIVE":
                        return
                    if (
                        time.monotonic() - session.last_update_monotonic_s
                        > self._motor_watchdog_timeout_s
                    ):
                        session.status = "FAILED"
                        session.error = "operator heartbeat lost; motor output was set to zero"
                        session.monitor_task = None
                        self._motor_session = None
                        break
                if session.firmware_watchdog_armed:
                    await session.vehicle.feed_motor_bench_watchdog()
                sample = await session.vehicle.snapshot(poll_supervisor=False)
                self._capture_motor_record(session, sample)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            async with self._motor_lock:
                if self._motor_session is session:
                    self._motor_session = None
                session.monitor_task = None
                session.status = "FAILED"
                session.error = str(error)
        if session.status == "FAILED":
            await self._finish_failed_motor_bench(session)

    async def _finish_failed_motor_bench(self, session: _ActiveMotorBench) -> None:
        try:
            await self._finish_motor_bench(session)
        except Exception as error:
            session.error = session.error or str(error)
        finally:
            callback = self._motor_bench_terminal_callback
            if callback is not None:
                with suppress(Exception):
                    await callback()

    async def _finish_motor_bench(self, session: _ActiveMotorBench) -> None:
        session.output_percent = 0.0
        cleanup_error: Exception | None = None
        try:
            # end_motor_power_override writes zero to M1-M4 before disabling the
            # override. One bounded operation avoids queueing a second cflib write
            # behind a stalled parameter transaction.
            await asyncio.wait_for(
                session.vehicle.end_motor_bench(),
                timeout=MOTOR_STOP_IO_TIMEOUT_S,
            )
        except Exception as error:
            cleanup_error = error
        session.vehicle.clear_command_permit()
        metadata = dict(session.vehicle.execution_metadata)
        with suppress(Exception):
            await asyncio.wait_for(
                session.vehicle.disconnect(),
                timeout=MOTOR_STOP_IO_TIMEOUT_S,
            )
        samples = list(session.vehicle.telemetry_history)
        artifact = self._persist_physical_telemetry(
            run_id=session.session_id,
            motion_id=f"motor-bench-{session.motor_selection}",
            controller_tuning_preparation=None,
            vehicle=session.vehicle,
            vehicle_execution_metadata=metadata,
            samples=samples,
            started_at_utc=session.started_at_utc,
            started_at_monotonic_s=session.started_at_monotonic_s,
            completed_at_monotonic_s=time.monotonic(),
            succeeded=session.status != "FAILED",
            message=session.error or "",
        )
        session.telemetry_artifact_path = str(artifact["path"])
        csv_path = self._write_motor_bench_csv(session)
        session.motor_csv_path = str(csv_path)
        session.motor_csv_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        if cleanup_error is None:
            self._clear_motor_marker()
            self._motor_stop_error = None
        else:
            session.status = "FAILED"
            session.error = f"Motor stop could not be confirmed: {cleanup_error}"
            self._motor_stop_error = session.error

    def _capture_motor_record(
        self,
        session: _ActiveMotorBench,
        sample: TelemetryEnvelope,
    ) -> None:
        telemetry = sample.telemetry
        measured = session.vehicle.latest_motor_pwm_percent
        session.measured_pwm_percent = measured
        position = telemetry.position_m
        attitude = telemetry.attitude
        session.records.append(
            {
                "recorded_at_utc": sample.recorded_at_utc.isoformat(),
                "source_timestamp_s": sample.source_timestamp_s,
                "motor_selection": session.motor_selection,
                "commanded_output_percent": session.output_percent,
                "measured_m1_pwm_percent": measured[0] if measured else None,
                "measured_m2_pwm_percent": measured[1] if measured else None,
                "measured_m3_pwm_percent": measured[2] if measured else None,
                "measured_m4_pwm_percent": measured[3] if measured else None,
                "battery_percent": telemetry.battery_percent,
                "battery_voltage_v": telemetry.battery_voltage_v,
                "position_x_m": position.x if position else None,
                "position_y_m": position.y if position else None,
                "position_z_m": position.z if position else None,
                "roll_rad": attitude.roll_rad if attitude else None,
                "pitch_rad": attitude.pitch_rad if attitude else None,
                "yaw_rad": attitude.yaw_rad if attitude else None,
                "faults_json": json.dumps(telemetry.faults, separators=(",", ":")),
            }
        )

    def _write_motor_bench_csv(self, session: _ActiveMotorBench) -> Path:
        directory = self._runtime.config.cache_directory / "motor-bench-runs"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{session.session_id}.csv"
        fieldnames = list(session.records[0]) if session.records else ["recorded_at_utc"]
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(session.records)
        return path

    @staticmethod
    def _motor_session_view(session: _ActiveMotorBench) -> MotorBenchSession:
        return MotorBenchSession(
            session_id=session.session_id,
            status=session.status,
            motor_selection=session.motor_selection,
            output_percent=session.output_percent,
            measured_pwm_percent=session.measured_pwm_percent,
            firmware_watchdog_armed=session.firmware_watchdog_armed,
            reboot_required=session.firmware_watchdog_armed,
            telemetry_row_count=len(session.vehicle.telemetry_history),
            telemetry_artifact_path=session.telemetry_artifact_path,
            motor_csv_path=session.motor_csv_path,
            motor_csv_sha256=session.motor_csv_sha256,
            error=session.error,
        )

    def _motor_actuation_status_locked(self) -> MotorActuationStatus:
        session = self._motor_session
        if self._motor_stop_in_progress:
            return MotorActuationStatus(
                state="STOPPING",
                stop_required=True,
                session_id=None if session is None else session.session_id,
                motor_selection=None if session is None else session.motor_selection,
                commanded_output_percent=None if session is None else session.output_percent,
                measured_pwm_percent=None if session is None else session.measured_pwm_percent,
                measured_output_active=(
                    None
                    if session is None or session.measured_pwm_percent is None
                    else any(value > 0.5 for value in session.measured_pwm_percent)
                ),
                firmware_watchdog_armed=(
                    False if session is None else session.firmware_watchdog_armed
                ),
                reboot_required=self._motor_reboot_required,
                detail="Stopping direct motor output",
            )
        if session is not None and session.status == "ACTIVE":
            measured = session.measured_pwm_percent
            return MotorActuationStatus(
                state="ACTIVE",
                stop_required=True,
                session_id=session.session_id,
                motor_selection=session.motor_selection,
                commanded_output_percent=session.output_percent,
                measured_pwm_percent=measured,
                measured_output_active=(
                    None if measured is None else any(value > 0.5 for value in measured)
                ),
                firmware_watchdog_armed=session.firmware_watchdog_armed,
                reboot_required=session.firmware_watchdog_armed,
                detail="Direct PWM authority is active",
            )
        marker = self._read_motor_marker()
        if marker is not None:
            selection_value = marker.get("motor_selection")
            selection = cast(
                MotorSelection,
                selection_value if selection_value in {"all", "m1", "m2", "m3", "m4"} else "all",
            )
            output_value = marker.get("output_percent")
            output_percent = (
                float(output_value)
                if isinstance(output_value, (int, float)) and 0.0 <= float(output_value) <= 70.0
                else None
            )
            return MotorActuationStatus(
                state="STOP_FAILED" if self._motor_stop_error else "POSSIBLY_ACTIVE",
                stop_required=True,
                session_id=(
                    str(marker["session_id"]) if isinstance(marker.get("session_id"), str) else None
                ),
                motor_selection=selection,
                commanded_output_percent=output_percent,
                measured_output_active=None,
                firmware_watchdog_armed=bool(marker.get("firmware_watchdog_armed", False)),
                reboot_required=bool(marker.get("firmware_watchdog_armed", False)),
                detail=(
                    self._motor_stop_error
                    or "The previous direct-PWM session did not record a confirmed stop"
                ),
            )
        if self._motor_stop_error is not None:
            return MotorActuationStatus(
                state="STOP_FAILED",
                stop_required=True,
                measured_output_active=None,
                detail=self._motor_stop_error,
            )
        return MotorActuationStatus(
            state="IDLE",
            stop_required=False,
            commanded_output_percent=0.0,
            measured_output_active=False,
            reboot_required=self._motor_reboot_required,
            detail=(
                "Direct motor output is off; power cycle the Crazyflie before another "
                "physical action"
                if self._motor_reboot_required
                else "Direct motor output is off"
            ),
        )

    def _write_motor_marker(
        self,
        *,
        session_id: str,
        selected_uri: str,
        motor_selection: MotorSelection,
        output_percent: float,
        firmware_watchdog_armed: bool = False,
    ) -> None:
        self._motor_marker_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._motor_marker_path.with_suffix(f".tmp-{uuid.uuid4().hex[:12]}")
        payload = {
            "schema_version": 1,
            "session_id": session_id,
            "selected_uri": selected_uri,
            "motor_selection": motor_selection,
            "output_percent": output_percent,
            "firmware_watchdog_armed": firmware_watchdog_armed,
            "updated_at_utc": datetime.now(UTC).isoformat(),
        }
        try:
            temporary.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self._motor_marker_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_motor_marker(self) -> dict[str, object] | None:
        if not self._motor_marker_path.exists():
            return None
        try:
            payload = json.loads(self._motor_marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1}
        return payload if isinstance(payload, dict) else {"schema_version": 1}

    def _clear_motor_marker(self) -> None:
        self._motor_marker_path.unlink(missing_ok=True)

    def _write_physical_flight_marker(self, operation: _ActivePhysicalFlight) -> None:
        """Atomically retain flight uncertainty independently of the API process."""

        self._physical_flight_marker_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._physical_flight_marker_path.with_suffix(f".tmp-{uuid.uuid4().hex[:12]}")
        payload = {
            "schema_version": 1,
            "operation_id": operation.operation_id,
            "motion_id": operation.request.motion_id,
            "station_id": operation.request.station_id,
            "heading_deg": operation.request.heading_deg,
            "target_height_m": operation.request.target_height_m,
            "selected_uri": operation.target.selected_uri,
            "vehicle_label": operation.target.vehicle_label,
            "observed_identity_sha256": operation.target.observed_identity_sha256,
            "operator_id": operation.operator_id,
            "started_at_utc": operation.started_at_utc.isoformat(),
            "state": operation.state,
            "stop_required": operation.stop_required,
            "detail": operation.detail,
            "failure_details": operation.failure_details,
            "command_evidence": operation.command_evidence,
            "flip_triggered": operation.flip_triggered,
            "hover_reference_m": (
                operation.hover_reference_m.model_dump(mode="json")
                if operation.hover_reference_m is not None
                else None
            ),
            "updated_at_utc": datetime.now(UTC).isoformat(),
        }
        try:
            temporary.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self._physical_flight_marker_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _load_physical_flight_marker(self) -> _ActivePhysicalFlight | None:
        path = self._physical_flight_marker_path
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("marker payload is not an object")
            if payload.get("operator_id") == "observer-state-recovery" and str(
                payload.get("operation_id", "")
            ).startswith("observer-recovery-"):
                return None
            motion_id = payload.get("motion_id")
            if motion_id not in PHYSICAL_BASIC_FLIGHT_MOTION_IDS:
                raise ValueError("marker motion is invalid")
            selected_uri = payload.get("selected_uri")
            if not isinstance(selected_uri, str) or not selected_uri:
                raise ValueError("marker URI is unavailable")
            started_value = payload.get("started_at_utc")
            started_at = (
                datetime.fromisoformat(started_value)
                if isinstance(started_value, str)
                else datetime.now(UTC)
            )
            persisted_state = payload.get("state")
            persisted_stop = payload.get("stop_required") is True
            terminal_states = {"COMPLETED", "ABORTED"}
            interrupted_observation = (
                motion_id in PHYSICAL_OBSERVATION_MOTION_IDS
                and persisted_state not in terminal_states
                and not payload.get("command_evidence")
            )
            state = (
                "FAILED"
                if interrupted_observation
                else cast(Any, persisted_state)
                if persisted_state in terminal_states and not persisted_stop
                else "STOP_UNCONFIRMED"
            )
            detail = (
                "Fixture observation was interrupted; no flight command was issued"
                if interrupted_observation
                else str(payload.get("detail"))
                if state in terminal_states and isinstance(payload.get("detail"), str)
                else "A previous physical flight did not retain a confirmed stop"
            )
            command_evidence = payload.get("command_evidence")
            return _ActivePhysicalFlight(
                operation_id=(
                    str(payload.get("operation_id"))
                    if isinstance(payload.get("operation_id"), str)
                    else f"recovered-flight-{uuid.uuid4().hex}"
                ),
                request=PhysicalBasicFlightRunRequest(
                    motion_id=cast(Any, motion_id),
                    station_id=cast(Any, payload.get("station_id")),
                    heading_deg=(
                        float(payload["heading_deg"])
                        if isinstance(payload.get("heading_deg"), int | float)
                        else 0.0
                    ),
                    target_height_m=(
                        float(payload["target_height_m"])
                        if isinstance(payload.get("target_height_m"), int | float)
                        else None
                    ),
                ),
                target=PhysicalCommandTarget(
                    selected_uri=selected_uri,
                    vehicle_label=(
                        str(payload.get("vehicle_label"))
                        if isinstance(payload.get("vehicle_label"), str)
                        else "Recovered Crazyflie"
                    ),
                    observed_identity_sha256=(
                        str(payload.get("observed_identity_sha256"))
                        if isinstance(payload.get("observed_identity_sha256"), str)
                        else None
                    ),
                ),
                operator_id=(
                    str(payload.get("operator_id"))
                    if isinstance(payload.get("operator_id"), str)
                    else "recovered-dashboard-operation"
                ),
                started_at_utc=started_at,
                state=cast(Any, state),
                detail=detail,
                stop_required=state not in terminal_states and not interrupted_observation,
                failure_details=(
                    cast(dict[str, Any], payload.get("failure_details"))
                    if isinstance(payload.get("failure_details"), dict)
                    else None
                ),
                command_evidence=(
                    [
                        cast(dict[str, Any], item)
                        for item in command_evidence
                        if isinstance(item, dict)
                    ]
                    if isinstance(command_evidence, list)
                    else []
                ),
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return _ActivePhysicalFlight(
                operation_id=f"recovered-flight-{uuid.uuid4().hex}",
                request=PhysicalBasicFlightRunRequest(),
                target=PhysicalCommandTarget(
                    selected_uri="",
                    vehicle_label="Recovered Crazyflie",
                    observed_identity_sha256=None,
                ),
                operator_id="recovered-dashboard-operation",
                started_at_utc=datetime.now(UTC),
                state="STOP_UNCONFIRMED",
                detail="Physical flight marker is unreadable; stop must be confirmed",
                stop_required=True,
                failure_details={"marker_error": str(error), "marker_path": str(path)},
            )

    @staticmethod
    def _exception_evidence(error: BaseException) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "type": type(error).__name__,
            "message": str(error),
        }
        if isinstance(error, CrazySwarmError):
            evidence["code"] = error.code.value
            evidence["details"] = error.details
        cause = error.__cause__
        if cause is not None and cause is not error:
            evidence["cause"] = BasicFlightLabService._exception_evidence(cause)
        return evidence

    def _mark_motor_reboot_required(self) -> None:
        self._motor_reboot_path.parent.mkdir(parents=True, exist_ok=True)
        self._motor_reboot_path.touch(exist_ok=True)
        self._motor_reboot_required = True

    def _clear_motor_reboot_required(self) -> None:
        self._motor_reboot_path.unlink(missing_ok=True)
        self._motor_reboot_required = False

    async def assess_physical_readiness(
        self,
        *,
        target: PhysicalCommandTarget,
    ) -> PhysicalBasicFlightReadiness:
        async with self._lock:
            vehicle_id = (
                f"basic-flight-check:{(target.observed_identity_sha256 or uuid.uuid4().hex)[:16]}"
            )
            vehicle = CrazyflieVehicle(
                vehicle_id=vehicle_id,
                selected_uri=target.selected_uri,
                link=self._physical_link_factory(),
                telemetry_listener=self._physical_telemetry_callback,
            )
            await vehicle.connect()
            try:
                sample = await vehicle.reset_estimator(timeout_s=10.0)
            finally:
                await vehicle.disconnect()
            telemetry = sample.telemetry
            estimator_converged = bool(
                telemetry.estimator is not None and telemetry.estimator.converged is True
            )
            floor_distance = telemetry.ranges.down_m if telemetry.ranges is not None else None
            issues: list[str] = []
            if not estimator_converged:
                issues.append("ESTIMATOR_NOT_CONVERGED")
            if telemetry.faults:
                issues.append("VEHICLE_FAULT_REPORTED")
            return PhysicalBasicFlightReadiness(
                ready=not issues,
                estimator_converged=estimator_converged,
                battery_percent=telemetry.battery_percent,
                battery_voltage_v=telemetry.battery_voltage_v,
                floor_distance_m=floor_distance,
                faults=telemetry.faults,
                issues=tuple(issues),
            )

    async def _run_contained_physical(
        self,
        request: PhysicalBasicFlightRunRequest,
        *,
        target: PhysicalCommandTarget,
        operator_id: str,
        active_operation: _ActivePhysicalFlight | None = None,
    ) -> BasicFlightLabRun:
        controller_tuning_fixture, _ = self._controller_tuning_fixture()
        is_controller_tuning = request.motion_id in CONTROLLER_TUNING_PHYSICAL_MOTION_IDS
        is_controller_tuning_flight = request.motion_id in CONTROLLER_TUNING_FLIGHT_MOTION_IDS
        is_acrobatics = request.motion_id == SINGLE_ROLL_MOTION_ID
        if is_acrobatics and active_operation is None:
            raise RuntimeError("cushioned acrobatics requires the staged hover and Flip workflow")
        if is_acrobatics:
            takeoff_height_m = ACROBATICS_HOVER_HEIGHT_M
        elif is_controller_tuning_flight and controller_tuning_fixture is not None:
            takeoff_height_m = (
                request.target_height_m or controller_tuning_fixture.nominal_hover_height_m
            )
        elif is_controller_tuning_flight:
            takeoff_height_m = None
        else:
            takeoff_height_m = TAKEOFF_CAPTURE_HEIGHT_M
        if takeoff_height_m is None:
            raise RuntimeError("controller-tuning nominal hover height is unavailable")
        tuning_preparation = (
            self._controller_tuning_preparation(
                request,
                controller_tuning_fixture,
                resolved_height_m=(
                    takeoff_height_m if is_controller_tuning_flight else request.target_height_m
                ),
            )
            if is_controller_tuning and controller_tuning_fixture is not None
            else None
        )
        started = (
            active_operation.started_at_utc if active_operation is not None else datetime.now(UTC)
        )
        started_monotonic_s = time.monotonic()
        run_id = (
            active_operation.operation_id
            if active_operation is not None
            else f"twin-basic-real-{uuid.uuid4().hex}"
        )
        vehicle_prefix = (
            "controller-tuning"
            if is_controller_tuning
            else "cushioned-acrobatics"
            if is_acrobatics
            else "basic-flight"
        )
        identity = target.observed_identity_sha256 or uuid.uuid4().hex
        vehicle_id = f"{vehicle_prefix}:{identity[:16]}"
        vehicle = (
            await self._physical_vehicle_provider(vehicle_id, target)
            if self._physical_vehicle_provider is not None
            else CrazyflieVehicle(
                vehicle_id=vehicle_id,
                selected_uri=target.selected_uri,
                link=self._physical_link_factory(),
                telemetry_listener=self._physical_telemetry_callback,
            )
        )
        step_results: list[BasicFlightLabStepResult] = []
        if request.motion_id == "commissioning-baseline":
            step_results.append(
                BasicFlightLabStepResult(
                    step_id="motors-30",
                    status="MODELED_ONLY",
                    detail=(
                        "Direct 30% motor output was not sent with installed props; "
                        "this remains a separate props-off bench motion"
                    ),
                )
            )
        issued = datetime.now(UTC)
        authorization_sha256 = canonical_sha256(
            {
                "request": request,
                "operator_id": operator_id,
                "vehicle_id": vehicle_id,
                "selected_uri_sha256": canonical_sha256(target.selected_uri),
                "issued_at_utc": issued,
            }
        )
        permit = CommandPermit(
            permit_id=f"fast-loop-{uuid.uuid4().hex}",
            vehicle_id=vehicle_id,
            selected_uri=target.selected_uri,
            operator_id=operator_id,
            scope=PermitScope.CONTAINED_FLIGHT,
            issued_at_utc=issued,
            expires_at_utc=issued + timedelta(seconds=90),
            operator_present=True,
            props_removed=False,
            physically_restrained=False,
            flight_entry_record_id=f"operator-confirmed-{run_id}",
            flight_entry_evidence_sha256=authorization_sha256,
        )

        async def command(step_id: str, payload: CommandPayload) -> None:
            if active_operation is not None and active_operation.abort_requested:
                raise asyncio.CancelledError
            if active_operation is not None:
                duration_s = float(getattr(payload, "duration_s", 0.0))
                await self._execute_recorded_physical_command(
                    active_operation,
                    vehicle,
                    payload,
                    command_prefix=step_id,
                    timeout_s=max(FLIGHT_RECOVERY_COMMAND_TIMEOUT_S, duration_s + 3.0),
                )
            else:
                await vehicle.execute(
                    CommandEnvelope(
                        vehicle_id=vehicle_id,
                        command_id=f"{step_id}-{uuid.uuid4().hex[:12]}",
                        mission_run_id=run_id,
                        issued_at_monotonic_s=time.monotonic(),
                        source=CommandSource.UI,
                        mode=OperatingMode.LIVE,
                        payload=payload,
                    )
                )
            await vehicle.snapshot()
            if active_operation is not None and active_operation.abort_requested:
                raise asyncio.CancelledError
            step_results.append(
                BasicFlightLabStepResult(
                    step_id=step_id,
                    status="COMPLETED",
                    detail="Measured Crazyflie command completed",
                )
            )

        async def mark_running(detail: str) -> None:
            if active_operation is None:
                return
            async with self._physical_flight_lock:
                if not active_operation.abort_requested:
                    active_operation.state = "RUNNING"
                    active_operation.detail = detail
                    self._write_physical_flight_marker(active_operation)

        connected = vehicle.connected
        failure: BaseException | None = None
        hover_history_start = 0
        vehicle_execution_metadata: dict[str, Any] = {}
        if active_operation is not None:
            async with self._physical_flight_lock:
                active_operation.vehicle = vehicle
                active_operation.permit = permit
        try:
            if active_operation is not None and active_operation.abort_requested:
                raise asyncio.CancelledError
            if not connected:
                await vehicle.connect()
                connected = True
            if active_operation is not None:
                active_operation.command_link_connected = True
                if active_operation.abort_requested:
                    raise asyncio.CancelledError
            connected_sample = await vehicle.snapshot()
            if "SUPERVISOR_CRASHED" in connected_sample.telemetry.faults:
                connected_sample = await vehicle.recover_from_crash()
            connected_telemetry = connected_sample.telemetry
            if "SUPERVISOR_STATE_UNKNOWN" in connected_telemetry.faults:
                raise RuntimeError("fresh supervisor state is unavailable after reconnect")
            if connected_telemetry.flying:
                raise RuntimeError(
                    "the Crazyflie reports flying; Abort and land recovery is required"
                )
            if "SUPERVISOR_LOCKED" in connected_telemetry.faults:
                raise RuntimeError("Crazyflie safety watchdog is locked; power cycle the drone")
            if request.motion_id in CONTROLLER_TUNING_FLIGHT_MOTION_IDS:
                metadata = vehicle.connection_metadata
                observed_parameters = {} if metadata is None else metadata.observed_parameters
                controller = observed_parameters.get("stabilizer.controller")
                estimator = observed_parameters.get("stabilizer.estimator")
                if controller != CRAZYFLIE_DEFAULT_PID_CONTROLLER_VALUE:
                    raise RuntimeError(
                        "missions B-E require the readable default PID controller "
                        f"snapshot (stabilizer.controller=1, observed {controller!r})"
                    )
                if estimator != CRAZYFLIE_KALMAN_ESTIMATOR_VALUE:
                    raise RuntimeError(
                        "missions B-E require the fixed Kalman estimator snapshot "
                        f"(stabilizer.estimator=2, observed {estimator!r})"
                    )
            auto_arming = vehicle.supervisor_auto_arming is True
            is_observation = request.motion_id in PHYSICAL_OBSERVATION_MOTION_IDS
            if is_observation and connected_telemetry.armed and not auto_arming:
                raise RuntimeError(
                    "fixture observation requires the manually armed drone to be disarmed"
                )
            if not is_observation:
                vehicle.install_command_permit(permit)
            if connected_telemetry.armed and not auto_arming and not is_observation:
                await command("preflight-disarm", DisarmCommand())
                connected_sample = await vehicle.snapshot()
                connected_telemetry = connected_sample.telemetry
                if (
                    "SUPERVISOR_STATE_UNKNOWN" in connected_telemetry.faults
                    or connected_telemetry.armed
                    or connected_telemetry.flying
                ):
                    raise RuntimeError(
                        "the Crazyflie did not confirm the grounded preflight disarm"
                    )
            is_flight = request.motion_id in PHYSICAL_FLIGHT_MOTION_IDS
            initial = (
                await vehicle.reset_estimator(timeout_s=10.0) if is_flight else connected_sample
            )
            telemetry = initial.telemetry
            if is_flight and (
                telemetry.estimator is None or telemetry.estimator.converged is not True
            ):
                raise RuntimeError("estimator is not converged")
            if request.motion_id in PHYSICAL_OBSERVATION_MOTION_IDS:
                await mark_running("Fixture observation running")
                step_results.append(
                    BasicFlightLabStepResult(
                        step_id="place",
                        status="COMPLETED",
                        detail="Operator started the selected fixture placement observation",
                    )
                )
                duration_s = controller_tuning_observation_duration_s(request.motion_id)
                await self._observe_vehicle(
                    vehicle,
                    duration_s=duration_s,
                    active_operation=active_operation,
                )
                step_results.append(
                    BasicFlightLabStepResult(
                        step_id="observe",
                        status="COMPLETED",
                        detail=f"Measured props-off telemetry for {duration_s:g} seconds",
                    )
                )
            elif request.motion_id == "arm-disarm":
                if auto_arming:
                    raise RuntimeError(
                        "manual arm and disarm is unavailable because this Crazyflie "
                        "uses firmware automatic arming"
                    )
                await command("arm", ArmCommand())
                await mark_running("Physical drone action running")
                step_results.append(
                    BasicFlightLabStepResult(
                        step_id="observe-armed",
                        status="COMPLETED",
                        detail=(
                            f"Measured armed state for {self._physical_arm_duration_s:g} seconds"
                        ),
                    )
                )
                await self._observe_vehicle(vehicle, duration_s=self._physical_arm_duration_s)
                await command("disarm", DisarmCommand())
            else:
                if not auto_arming:
                    await command("arm-for-flight", ArmCommand())
                    await mark_running("Physical drone action running")
                await command(
                    (
                        "takeoff"
                        if request.motion_id in CONTROLLER_TUNING_FLIGHT_MOTION_IDS
                        else "takeoff-50cm"
                        if is_acrobatics
                        else "takeoff-30cm"
                    ),
                    TakeoffCommand(height_m=takeoff_height_m, duration_s=2.0),
                )
                if auto_arming:
                    await mark_running("Physical drone action running")
                captured = await self._wait_for_takeoff_capture(
                    vehicle,
                    active_operation=active_operation,
                    target_height_m=takeoff_height_m,
                )
                captured_position = cast(Vector3, captured.telemetry.position_m)
                captured_velocity = cast(Vector3, captured.telemetry.velocity_m_s)
                step_results.append(
                    BasicFlightLabStepResult(
                        step_id="takeoff-capture",
                        status="COMPLETED",
                        detail=(
                            "Measured takeoff capture confirmed before task motion "
                            f"(z={captured_position.z:.3f} m, "
                            f"vz={captured_velocity.z:.3f} m/s)"
                        ),
                    )
                )
                hover_history_start = len(vehicle.telemetry_history)
                if is_acrobatics:
                    if active_operation is None:  # guarded before opening the link
                        raise RuntimeError("cushioned acrobatics has no active staged operation")
                    active_operation.hover_reference_m = captured_position
                    await self._wait_for_acrobatics_trigger(
                        vehicle,
                        active_operation=active_operation,
                        reference=captured_position,
                    )
                    for step_id, payload in _contained_flight_commands(
                        request.motion_id,
                        commissioning_hover_duration_s=self._physical_hover_duration_s,
                        controller_tuning_fixture=controller_tuning_fixture,
                    ):
                        if isinstance(payload, BodyRateThrustCommand):
                            payload = payload.model_copy(
                                update={"xy_reference_m": captured_position}
                            )
                        await command(step_id, payload)
                    await self._observe_acrobatics_recovery(
                        vehicle,
                        active_operation=active_operation,
                        reference=captured_position,
                    )
                    step_results.append(
                        BasicFlightLabStepResult(
                            step_id="recover-hover",
                            status="COMPLETED",
                            detail="Measured recovery interval completed inside the HOME XY box",
                        )
                    )
                else:
                    for step_id, payload in _contained_flight_commands(
                        request.motion_id,
                        commissioning_hover_duration_s=self._physical_hover_duration_s,
                        controller_tuning_fixture=controller_tuning_fixture,
                    ):
                        await command(step_id, payload)
                await command("land", LandCommand(duration_s=2.0))
                await self._wait_for_grounded(vehicle)
                if not auto_arming:
                    await command("disarm", DisarmCommand())
        except asyncio.CancelledError as error:
            failure = error
            if active_operation is not None and active_operation.abort_requested:
                await active_operation.abort_complete.wait()
        except Exception as error:
            if active_operation is not None and active_operation.abort_requested:
                failure = asyncio.CancelledError()
                await active_operation.abort_complete.wait()
            else:
                failure = error
            if connected and not isinstance(failure, asyncio.CancelledError):
                with suppress(Exception):
                    snapshot = await vehicle.snapshot()
                    if snapshot.telemetry.flying:
                        vehicle.install_command_permit(permit)
                        if active_operation is not None:
                            await self._execute_recorded_physical_command(
                                active_operation,
                                vehicle,
                                AbortCommand(reason="basic-flight run failure"),
                                command_prefix="failure-abort",
                                source=CommandSource.SUPERVISOR,
                            )
                        else:
                            await vehicle.execute(
                                CommandEnvelope(
                                    vehicle_id=vehicle_id,
                                    command_id=f"abort-{uuid.uuid4().hex[:12]}",
                                    mission_run_id=run_id,
                                    issued_at_monotonic_s=time.monotonic(),
                                    source=CommandSource.SUPERVISOR,
                                    mode=OperatingMode.LIVE,
                                    payload=AbortCommand(reason="basic-flight run failure"),
                                )
                            )
                    elif snapshot.telemetry.armed and vehicle.supervisor_auto_arming is not True:
                        vehicle.install_command_permit(permit)
                        if active_operation is not None:
                            await self._execute_recorded_physical_command(
                                active_operation,
                                vehicle,
                                DisarmCommand(),
                                command_prefix="failure-disarm",
                                source=CommandSource.SUPERVISOR,
                            )
                        else:
                            await vehicle.execute(
                                CommandEnvelope(
                                    vehicle_id=vehicle_id,
                                    command_id=f"disarm-{uuid.uuid4().hex[:12]}",
                                    mission_run_id=run_id,
                                    issued_at_monotonic_s=time.monotonic(),
                                    source=CommandSource.SUPERVISOR,
                                    mode=OperatingMode.LIVE,
                                    payload=DisarmCommand(),
                                )
                            )
        finally:
            vehicle.clear_command_permit()
            if connected:
                vehicle_execution_metadata = dict(vehicle.execution_metadata)
                await vehicle.disconnect()

        if active_operation is not None:
            vehicle_execution_metadata["command_evidence"] = list(active_operation.command_evidence)
        if failure is not None:
            vehicle_execution_metadata["failure_details"] = self._exception_evidence(failure)

        samples = list(vehicle.telemetry_history)
        completed = datetime.now(UTC)
        artifact = self._persist_physical_telemetry(
            run_id=run_id,
            motion_id=request.motion_id,
            controller_tuning_preparation=tuning_preparation,
            vehicle=vehicle,
            vehicle_execution_metadata=vehicle_execution_metadata,
            samples=samples,
            started_at_utc=started,
            started_at_monotonic_s=started_monotonic_s,
            completed_at_monotonic_s=time.monotonic(),
            succeeded=failure is None,
            message=(
                "operator requested abort and land"
                if isinstance(failure, asyncio.CancelledError)
                else ""
                if failure is None
                else str(failure)
            ),
        )
        if failure is not None:
            raise failure

        battery = [
            item.telemetry.battery_percent
            for item in samples
            if item.telemetry.battery_percent is not None
        ]
        voltages = [
            item.telemetry.battery_voltage_v
            for item in samples
            if item.telemetry.battery_voltage_v is not None
        ]
        positions = [
            item.telemetry.position_m for item in samples if item.telemetry.position_m is not None
        ]
        first_battery = battery[0]
        last_battery = battery[-1]
        hover_positions = _estimated_positions(samples[hover_history_start:])
        learning = BasicFlightLearningSample(
            battery_start_percent=first_battery,
            battery_minimum_percent=min(battery),
            battery_end_percent=last_battery,
            battery_delta_percent=max(0.0, first_battery - last_battery),
            minimum_voltage_v=min(voltages) if voltages else None,
            maximum_current_a=None,
            peak_motor_command_percent=None,
            hover_rms_drift_m=_rms_drift(hover_positions),
            maximum_altitude_m=max((item.z for item in positions), default=0.0),
            landing_contact_observed=(positions[-1].z <= 0.10 if positions else False),
            final_state=samples[-1].telemetry.state.value,
        )
        range_summary = (
            summarize_controller_tuning_ranges(
                controller_tuning_fixture,
                request.motion_id,
                samples,
                station_id=request.station_id,
                heading_deg=request.heading_deg,
                target_height_m=tuning_preparation.target_height_m,
            )
            if (
                is_controller_tuning
                and controller_tuning_fixture is not None
                and tuning_preparation is not None
            )
            else None
        )
        return BasicFlightLabRun(
            run_id=run_id,
            motion_id=request.motion_id,
            status="COMPLETED",
            execution_backend="REAL_CRAZYFLIE",
            evidence_class="MEASURED_REAL",
            started_at_utc=started,
            completed_at_utc=completed,
            steps=tuple(step_results),
            learning_sample=learning,
            artifact_path=str(artifact["path"]),
            telemetry_row_count=int(artifact["telemetry_row_count"]),
            telemetry_csv_sha256=str(artifact["sha256"]),
            controller_tuning_range_summary=range_summary,
            controller_tuning_preparation=tuning_preparation,
        )

    async def _wait_for_acrobatics_trigger(
        self,
        vehicle: CrazyflieVehicle,
        *,
        active_operation: _ActivePhysicalFlight,
        reference: Vector3,
    ) -> None:
        async with self._physical_flight_lock:
            if active_operation.abort_requested:
                raise asyncio.CancelledError
            active_operation.state = "HOVERING_READY"
            active_operation.detail = (
                "Hovering at 0.50 m; Flip is ready for one operator trigger"
            )
            self._write_physical_flight_marker(active_operation)

        deadline = time.monotonic() + self._acrobatics_trigger_timeout_s
        while True:
            if active_operation.abort_requested:
                raise asyncio.CancelledError
            sample = await vehicle.snapshot()
            self._require_acrobatics_xy_containment(sample, reference=reference)
            if active_operation.flip_requested.is_set():
                return
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0.0:
                raise RuntimeError(
                    "Flip was not triggered before the hover timeout; landing automatically"
                )
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    active_operation.flip_requested.wait(),
                    timeout=min(0.02, remaining_s),
                )

    async def _observe_acrobatics_recovery(
        self,
        vehicle: CrazyflieVehicle,
        *,
        active_operation: _ActivePhysicalFlight,
        reference: Vector3,
    ) -> None:
        deadline = time.monotonic() + self._acrobatics_recovery_duration_s
        while True:
            if active_operation.abort_requested:
                raise asyncio.CancelledError
            sample = await vehicle.snapshot()
            self._require_acrobatics_xy_containment(sample, reference=reference)
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0.0:
                return
            await asyncio.sleep(min(0.02, remaining_s))

    @staticmethod
    def _require_acrobatics_xy_containment(
        sample: TelemetryEnvelope,
        *,
        reference: Vector3,
    ) -> None:
        position = sample.telemetry.position_m
        if position is None:
            raise RuntimeError("cushioned acrobatics lost its current position estimate")
        dx_m = position.x - reference.x
        dy_m = position.y - reference.y
        if abs(dx_m) > ACROBATICS_MAX_ABS_XY_M or abs(dy_m) > ACROBATICS_MAX_ABS_XY_M:
            raise RuntimeError(
                "cushioned acrobatics left the ±0.50 m HOME XY containment box "
                f"(dx={dx_m:.3f} m, dy={dy_m:.3f} m)"
            )

    async def _observe_vehicle(
        self,
        vehicle: CrazyflieVehicle,
        *,
        duration_s: float,
        active_operation: _ActivePhysicalFlight | None = None,
    ) -> None:
        deadline = time.monotonic() + duration_s
        while True:
            if active_operation is not None and active_operation.abort_requested:
                raise asyncio.CancelledError
            await vehicle.snapshot()
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return
            await asyncio.sleep(min(0.02, remaining))

    async def _wait_for_takeoff_capture(
        self,
        vehicle: CrazyflieVehicle,
        *,
        active_operation: _ActivePhysicalFlight | None = None,
        timeout_s: float = TAKEOFF_CAPTURE_TIMEOUT_S,
        target_height_m: float = TAKEOFF_CAPTURE_HEIGHT_M,
    ) -> TelemetryEnvelope:
        """Separate vertical takeoff from the first task translation.

        The high-level command acknowledgement is duration based. It does not prove
        that measured altitude and vertical rate have captured the requested hover
        yet, so a following relative move could otherwise begin on the climb.
        """

        deadline = time.monotonic() + timeout_s
        consecutive = 0
        last_receive_timestamp_s: float | None = None
        latest = await vehicle.snapshot()
        while True:
            if active_operation is not None and active_operation.abort_requested:
                raise asyncio.CancelledError
            position = latest.telemetry.position_m
            velocity = latest.telemetry.velocity_m_s
            is_new_measurement = latest.received_timestamp_s != last_receive_timestamp_s
            if is_new_measurement:
                last_receive_timestamp_s = latest.received_timestamp_s
                captured = (
                    position is not None
                    and velocity is not None
                    and abs(position.z - target_height_m) <= TAKEOFF_CAPTURE_TOLERANCE_M
                    and abs(velocity.z) <= TAKEOFF_CAPTURE_MAX_VERTICAL_SPEED_M_S
                )
                consecutive = consecutive + 1 if captured else 0
                if consecutive >= TAKEOFF_CAPTURE_CONSECUTIVE_SAMPLES:
                    return latest
            if time.monotonic() >= deadline:
                observed_height = None if position is None else position.z
                observed_vertical_speed = None if velocity is None else velocity.z
                raise RuntimeError(
                    "Crazyflie did not capture the requested takeoff hover before task motion "
                    f"(target={target_height_m:.3f} m, "
                    f"z={observed_height!r}, vz={observed_vertical_speed!r})"
                )
            await asyncio.sleep(0.05)
            latest = await vehicle.snapshot()

    async def _wait_for_grounded(
        self,
        vehicle: CrazyflieVehicle,
        *,
        timeout_s: float = 3.0,
    ) -> TelemetryEnvelope:
        """Retain post-land telemetry until firmware confirms flight has ended."""

        deadline = time.monotonic() + timeout_s
        latest = await vehicle.snapshot()
        while latest.telemetry.flying:
            if time.monotonic() >= deadline:
                raise RuntimeError("Crazyflie did not confirm grounded state after landing")
            await asyncio.sleep(0.05)
            latest = await vehicle.snapshot()
        return latest

    def _persist_physical_telemetry(
        self,
        *,
        run_id: str,
        motion_id: str,
        controller_tuning_preparation: ControllerTuningRunPreparation | None,
        vehicle: CrazyflieVehicle,
        vehicle_execution_metadata: dict[str, Any],
        samples: Sequence[TelemetryEnvelope],
        started_at_utc: datetime,
        started_at_monotonic_s: float,
        completed_at_monotonic_s: float,
        succeeded: bool,
        message: str,
    ) -> dict[str, Any]:
        controller_tuning_fixture, controller_tuning_status = self._controller_tuning_fixture()
        is_controller_tuning = motion_id in CONTROLLER_TUNING_PHYSICAL_MOTION_IDS
        is_acrobatics = motion_id == SINGLE_ROLL_MOTION_ID
        mission_cluster = (
            "controller-characterization-tuning"
            if is_controller_tuning
            else ACROBATICS_CLUSTER_ID
            if is_acrobatics
            else "basic-flight"
        )
        mission_id = f"digital-twin-{mission_cluster}-{motion_id}"
        if motion_id == "arm-disarm":
            mission_name = "Digital Twin ground arm and disarm"
        elif motion_id.startswith("motor-bench-"):
            mission_name = "Digital Twin live motor bench"
        else:
            selected_motion = next(
                (motion for motion in self.catalog().motions if motion.motion_id == motion_id),
                None,
            )
            mission_name = (
                f"Digital Twin {selected_motion.motion}"
                if selected_motion is not None
                else "Digital Twin physical mission"
            )
        mission_version = "1.0" if is_controller_tuning else "2.0"
        is_flight = motion_id in PHYSICAL_FLIGHT_MOTION_IDS
        command_plan = (
            [
                {
                    "step_id": step_id,
                    "payload": payload.model_dump(mode="json"),
                }
                for step_id, payload in _contained_flight_commands(
                    cast(PhysicalBasicFlightMotionId, motion_id),
                    commissioning_hover_duration_s=self._physical_hover_duration_s,
                    controller_tuning_fixture=controller_tuning_fixture,
                )
            ]
            if is_flight
            else [
                {
                    "step_id": "observe",
                    "duration_s": controller_tuning_observation_duration_s(motion_id),
                    "physical_commands_sent": False,
                }
            ]
            if motion_id in PHYSICAL_OBSERVATION_MOTION_IDS
            else [
                {"step_id": "arm", "command": "ARM"},
                {"step_id": "observe-armed", "duration_s": self._physical_arm_duration_s},
                {"step_id": "disarm", "command": "DISARM"},
            ]
            if motion_id == "arm-disarm"
            else []
        )
        command_plan_sha256 = canonical_sha256(command_plan)
        configured_duration_s = (
            self._physical_hover_duration_s
            if motion_id == "commissioning-baseline"
            else self._physical_arm_duration_s
            if motion_id == "arm-disarm"
            else controller_tuning_observation_duration_s(motion_id)
            if motion_id in PHYSICAL_OBSERVATION_MOTION_IDS
            else sum(
                float(getattr(payload, "duration_s", 0.0))
                for _, payload in _contained_flight_commands(
                    cast(PhysicalBasicFlightMotionId, motion_id),
                    commissioning_hover_duration_s=self._physical_hover_duration_s,
                    controller_tuning_fixture=controller_tuning_fixture,
                )
            )
            if is_flight
            else 0.0
        )
        configuration_hash = canonical_sha256(
            {
                "mission_id": mission_id,
                "mission_version": mission_version,
                "hover_duration_s": self._physical_hover_duration_s,
                "armed_duration_s": self._physical_arm_duration_s,
                "takeoff_height_m": (
                    controller_tuning_preparation.target_height_m
                    if controller_tuning_preparation is not None
                    else ACROBATICS_HOVER_HEIGHT_M
                    if is_acrobatics
                    else 0.30
                ),
                "command_plan_sha256": command_plan_sha256,
                "mission_cluster": mission_cluster,
                "controller_tuning_fixture": (
                    controller_tuning_fixture.model_dump(mode="json")
                    if controller_tuning_fixture is not None
                    else None
                ),
                "controller_tuning_fixture_state": controller_tuning_status.state,
                "controller_tuning_preparation": (
                    controller_tuning_preparation.model_dump(mode="json")
                    if controller_tuning_preparation is not None
                    else None
                ),
                "vehicle_execution": vehicle_execution_metadata,
            }
        )
        retained_takeoff_height_m = (
            controller_tuning_preparation.target_height_m
            if is_flight and controller_tuning_preparation is not None
            else ACROBATICS_HOVER_HEIGHT_M
            if is_acrobatics
            else 0.30
            if is_flight
            else 0.0
        )
        mission_runtime_id = (
            "digital-twin-controller-tuning-lab"
            if is_controller_tuning
            else "digital-twin-cushioned-acrobatics-lab"
            if is_acrobatics
            else "digital-twin-basic-flight-lab"
        )
        snapshot = MissionRunSnapshot(
            mission_run_id=run_id,
            mission_execution_id=run_id,
            mission_id=mission_id,
            mission_name=mission_name,
            mission_version=mission_version,
            vehicle_id=vehicle.identity.vehicle_id,
            mode=OperatingMode.LIVE,
            phase=MissionPhase.COMPLETE,
            configuration_hash=configuration_hash,
            mission_runtime_id=mission_runtime_id,
            mission_runtime_version="1",
            vehicle_adapter=vehicle.identity.adapter,
            backend_role=vehicle.backend_profile.role.value,
            authority_class=vehicle.backend_profile.authority.value,
            parameters={
                "motion_id": motion_id,
                "height_m": retained_takeoff_height_m,
                "duration_s": configured_duration_s,
                "command_plan_sha256": command_plan_sha256,
                "fixture_id": (
                    controller_tuning_fixture.fixture_id
                    if is_controller_tuning and controller_tuning_fixture is not None
                    else None
                ),
                "controller_tuning_preparation": (
                    controller_tuning_preparation.model_dump(mode="json")
                    if controller_tuning_preparation is not None
                    else None
                ),
                "vehicle_execution": vehicle_execution_metadata,
            },
            started_at_monotonic_s=started_at_monotonic_s,
        )
        result = MissionResult(
            mission_run_id=run_id,
            mission_execution_id=run_id,
            mission_id=mission_id,
            mission_name=mission_name,
            mission_version=mission_version,
            vehicle_id=vehicle.identity.vehicle_id,
            mode=OperatingMode.LIVE,
            status=MissionStatus.SUCCEEDED if succeeded else MissionStatus.FAILED,
            reason_code="COMPLETED" if succeeded else "PHYSICAL_RUN_FAILED",
            message=message,
            configuration_hash=configuration_hash,
            mission_runtime_id=mission_runtime_id,
            mission_runtime_version="1",
            vehicle_adapter=vehicle.identity.adapter,
            backend_role=vehicle.backend_profile.role.value,
            authority_class=vehicle.backend_profile.authority.value,
            parameters={
                "motion_id": motion_id,
                "height_m": retained_takeoff_height_m,
                "duration_s": configured_duration_s,
                "command_plan_sha256": command_plan_sha256,
                "fixture_id": (
                    controller_tuning_fixture.fixture_id
                    if is_controller_tuning and controller_tuning_fixture is not None
                    else None
                ),
                "controller_tuning_preparation": (
                    controller_tuning_preparation.model_dump(mode="json")
                    if controller_tuning_preparation is not None
                    else None
                ),
                "vehicle_execution": vehicle_execution_metadata,
            },
            started_at_monotonic_s=started_at_monotonic_s,
            finished_at_monotonic_s=completed_at_monotonic_s,
            started_at_utc=started_at_utc,
        )
        self._runtime.store.begin_run(snapshot)
        self._runtime.store.append_event(
            EvidenceEvent(
                event_id=f"{run_id}-started",
                sequence=0,
                kind=EvidenceKind.MISSION_STARTED,
                vehicle_id=vehicle.identity.vehicle_id,
                run_id=run_id,
                mode=OperatingMode.LIVE,
                source=mission_runtime_id,
                source_timestamp_s=started_at_monotonic_s,
                received_timestamp_s=started_at_monotonic_s,
                recorded_at_utc=started_at_utc,
                unit="SI",
                frame=None,
                payload=MissionStartedPayload(
                    run=snapshot,
                    software_version="1",
                    configuration_schema_version=1,
                ),
            )
        )
        for sequence, sample in enumerate(samples, start=1):
            self._runtime.store.append_event(
                EvidenceEvent(
                    event_id=f"{run_id}-telemetry-{sequence:06d}",
                    sequence=sequence,
                    kind=EvidenceKind.TELEMETRY,
                    vehicle_id=vehicle.identity.vehicle_id,
                    run_id=run_id,
                    mode=OperatingMode.LIVE,
                    source=vehicle.identity.adapter,
                    source_timestamp_s=sample.source_timestamp_s,
                    received_timestamp_s=sample.received_timestamp_s,
                    recorded_at_utc=sample.recorded_at_utc,
                    unit="SI",
                    frame=sample.telemetry.frame,
                    payload=TelemetryPayload(telemetry=sample),
                )
            )
        completed_at_utc = datetime.now(UTC)
        self._runtime.store.append_event(
            EvidenceEvent(
                event_id=f"{run_id}-result",
                sequence=len(samples) + 1,
                kind=EvidenceKind.MISSION_RESULT,
                vehicle_id=vehicle.identity.vehicle_id,
                run_id=run_id,
                mode=OperatingMode.LIVE,
                source=mission_runtime_id,
                source_timestamp_s=completed_at_monotonic_s,
                received_timestamp_s=completed_at_monotonic_s,
                recorded_at_utc=completed_at_utc,
                unit="SI",
                frame=None,
                payload=MissionResultPayload(result=result),
            )
        )
        self._runtime.store.complete_run(result)
        self._runtime.store.materialize_run_files_for_run(run_id)
        return self._runtime.store.get_persisted_run_file_for_run(run_id)

    async def _run_private_simulator(self, motion: BasicFlightLabMotion) -> BasicFlightLabRun:
        started = datetime.now(UTC)
        simulation = self._runtime.scenario.simulation.model_copy(
            update={"clock_mode": ClockMode.ACCELERATED, "speed": 1.0}
        )
        vehicle = SimulatedVehicle(
            VehicleIdentity(
                vehicle_id="twin-lab-fast-sim",
                display_name="Digital Twin basic-flight rehearsal",
                adapter="sim",
            ),
            IndoorWorld(self._runtime.scenario.world),
            config=simulation,
            initial_position_m=Vector3(),
            scenario_id=f"{self._runtime.scenario.scenario_id}-twin-lab",
        )
        await vehicle.connect()
        step_results: list[BasicFlightLabStepResult] = []
        hover_samples: list[Vector3] = []

        async def command(step_id: str, payload: CommandPayload) -> None:
            await vehicle.execute(
                CommandEnvelope(
                    vehicle_id=vehicle.identity.vehicle_id,
                    command_id=f"{step_id}-{uuid.uuid4().hex[:12]}",
                    issued_at_monotonic_s=vehicle.clock.now_s,
                    source=CommandSource.MISSION,
                    mode=OperatingMode.SIM,
                    payload=payload,
                )
            )
            step_results.append(
                BasicFlightLabStepResult(
                    step_id=step_id, status="COMPLETED", detail="Fast Sim command completed"
                )
            )

        if motion.motion_id in {"commissioning-baseline", "arm-disarm"}:
            await command("arm", ArmCommand())
            if motion.motion_id == "commissioning-baseline":
                step_results.append(
                    BasicFlightLabStepResult(
                        step_id="motors-30",
                        status="MODELED_ONLY",
                        detail="Four equal 30% targets recorded; no actuator output was sent",
                    )
                )
                await command("disarm-after-bench", DisarmCommand())
            else:
                await command("disarm", DisarmCommand())
        elif motion.motion_id == "motors-30":
            step_results.append(
                BasicFlightLabStepResult(
                    step_id="motors-30",
                    status="MODELED_ONLY",
                    detail="Four equal 30% targets recorded; no actuator output was sent",
                )
            )

        if motion.physical_scope == "CONTAINED_FLIGHT":
            await command("arm-for-flight", ArmCommand())
            await command("takeoff-30cm", TakeoffCommand(height_m=0.30, duration_s=2.0))
            if motion.motion_id in PHYSICAL_FLIGHT_MOTION_IDS:
                history_start = len(vehicle.telemetry_history)
                for step_id, payload in _contained_flight_commands(
                    motion.motion_id,
                    commissioning_hover_duration_s=30.0,
                ):
                    await command(step_id, payload)
                hover_samples = _truth_positions(vehicle.telemetry_history[history_start:])
                await command("land", LandCommand(duration_s=2.0))
            elif motion.motion_id in {"forward-back", "left-right", "yaw-turn"}:
                vectors = {
                    "forward-back": ((0.20, 0.0, 0.0, 0.0), (-0.20, 0.0, 0.0, 0.0)),
                    "left-right": ((0.0, 0.20, 0.0, 0.0), (0.0, -0.20, 0.0, 0.0)),
                    "yaw-turn": ((0.0, 0.0, 0.0, -math.pi / 2), (0.0, 0.0, 0.0, math.pi / 2)),
                }[motion.motion_id]
                names = {
                    "forward-back": ("forward", "back"),
                    "left-right": ("left", "right"),
                    "yaw-turn": ("yaw-right", "yaw-left"),
                }[motion.motion_id]
                for name, (x_m, y_m, z_m, yaw_rad) in zip(names, vectors, strict=True):
                    await command(
                        name,
                        MoveRelativeCommand(
                            x_m=x_m,
                            y_m=y_m,
                            z_m=z_m,
                            yaw_rad=yaw_rad,
                            duration_s=2.0,
                            frame=CoordinateFrame.BODY,
                        ),
                    )
                await command("land", LandCommand(duration_s=2.0))
            elif motion.motion_id == "square":
                for index, (x_m, y_m) in enumerate(
                    ((0.20, 0.0), (0.0, -0.20), (-0.20, 0.0), (0.0, 0.20)), start=1
                ):
                    await command(
                        f"square-{index}",
                        MoveRelativeCommand(x_m=x_m, y_m=y_m, duration_s=2.0),
                    )
                await command("land", LandCommand(duration_s=2.0))
            elif motion.motion_id == "circle":
                points = [
                    (
                        0.10 * math.cos(-2.0 * math.pi * index / 12.0),
                        0.10 * math.sin(-2.0 * math.pi * index / 12.0),
                    )
                    for index in range(13)
                ]
                await command(
                    "circle-entry",
                    MoveRelativeCommand(x_m=0.10, duration_s=1.0),
                )
                for index, (previous, current) in enumerate(pairwise(points), start=1):
                    await command(
                        f"circle-{index}",
                        MoveRelativeCommand(
                            x_m=current[0] - previous[0],
                            y_m=current[1] - previous[1],
                            duration_s=0.75,
                        ),
                    )
                step_results.append(
                    BasicFlightLabStepResult(
                        step_id="circle",
                        status="COMPLETED",
                        detail="12 canonical clockwise segments completed",
                    )
                )
                await command(
                    "circle-exit",
                    MoveRelativeCommand(x_m=-0.10, duration_s=1.0),
                )
                await command("land", LandCommand(duration_s=2.0))
            elif motion.motion_id == "abort-to-land":
                await command("abort", AbortCommand(reason="basic-flight lab rehearsal"))
            elif motion.motion_id == "emergency-stop":
                await command(
                    "emergency", EmergencyStopCommand(reason="basic-flight lab rehearsal")
                )

        telemetry = vehicle.telemetry_history or [await vehicle.snapshot()]
        battery = [
            item.telemetry.battery_percent
            for item in telemetry
            if item.telemetry.battery_percent is not None
        ]
        voltages = [
            item.telemetry.battery_voltage_v
            for item in telemetry
            if item.telemetry.battery_voltage_v is not None
        ]
        currents = [
            item.telemetry.battery_current_a
            for item in telemetry
            if item.telemetry.battery_current_a is not None
        ]
        motor_commands = [
            reading.command_percent
            for item in telemetry
            if item.telemetry.motors is not None
            for reading in item.telemetry.motors.readings
        ]
        altitudes = [
            item.telemetry.ground_truth_position_m.z
            for item in telemetry
            if item.telemetry.ground_truth_position_m is not None
        ]
        first_battery = battery[0] if battery else simulation.battery_start_percent
        last_battery = battery[-1] if battery else first_battery
        learning = BasicFlightLearningSample(
            battery_start_percent=first_battery,
            battery_minimum_percent=min(battery, default=first_battery),
            battery_end_percent=last_battery,
            battery_delta_percent=max(0.0, first_battery - last_battery),
            minimum_voltage_v=min(voltages) if voltages else None,
            maximum_current_a=max(currents) if currents else None,
            peak_motor_command_percent=max(motor_commands)
            if motor_commands
            else (30.0 if motion.motion_id in {"commissioning-baseline", "motors-30"} else None),
            hover_rms_drift_m=_rms_drift(hover_samples),
            maximum_altitude_m=max(altitudes, default=0.0),
            landing_contact_observed=vehicle.last_landing_evidence is not None,
            final_state=vehicle.state.value,
        )
        run_id = f"twin-basic-{uuid.uuid4().hex}"
        return BasicFlightLabRun(
            run_id=run_id,
            motion_id=motion.motion_id,
            status="COMPLETED",
            started_at_utc=started,
            completed_at_utc=datetime.now(UTC),
            steps=tuple(step_results),
            learning_sample=learning,
            artifact_path=str(self._artifact_path),
        )


def _truth_positions(samples: Sequence[TelemetryEnvelope]) -> list[Vector3]:
    return [
        sample.telemetry.ground_truth_position_m
        for sample in samples
        if sample.telemetry.ground_truth_position_m is not None
    ]


def _estimated_positions(samples: Sequence[TelemetryEnvelope]) -> list[Vector3]:
    return [
        sample.telemetry.position_m for sample in samples if sample.telemetry.position_m is not None
    ]


def _rms_drift(samples: list[Vector3]) -> float | None:
    if not samples:
        return None
    reference = samples[0]
    return math.sqrt(
        sum(
            (item.x - reference.x) ** 2 + (item.y - reference.y) ** 2 + (item.z - reference.z) ** 2
            for item in samples
        )
        / len(samples)
    )
