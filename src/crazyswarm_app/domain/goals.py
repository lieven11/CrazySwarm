from __future__ import annotations

import math
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, CoordinateFrame, Identifier, Vector3


class GoalFailureAction(StrEnum):
    ABORT_AND_LAND = "ABORT_AND_LAND"
    DIVERT = "DIVERT"


class GoalCaptureOutcome(StrEnum):
    CAPTURED = "CAPTURED"
    DIVERTED = "DIVERTED"
    REJECTED = "REJECTED"
    TERMINAL_MISS = "TERMINAL_MISS"


class LandingGoalRegion(ContractModel):
    schema_version: Literal[1] = 1
    goal_id: Identifier
    role_id: Identifier
    vehicle_id: Identifier
    frame: Literal[CoordinateFrame.WORLD] = CoordinateFrame.WORLD
    landing_target_m: Vector3
    approach_point_m: Vector3
    horizontal_tolerance_m: float = Field(gt=0.0, le=1.0)
    vertical_tolerance_m: float = Field(gt=0.0, le=0.5)
    maximum_capture_speed_m_s: float = Field(gt=0.0, le=1.0)
    maximum_correction_attempts: int = Field(default=2, ge=0, le=5)
    correction_duration_s: float = Field(default=1.0, gt=0.0, le=10.0)
    failure_action: GoalFailureAction = GoalFailureAction.ABORT_AND_LAND
    diversion_target_m: Vector3 | None = None

    @model_validator(mode="after")
    def valid_approach_and_fallback(self) -> LandingGoalRegion:
        if self.approach_point_m.z <= self.landing_target_m.z:
            raise ValueError("landing approach must be above the landing target")
        if not math.isclose(
            self.approach_point_m.x, self.landing_target_m.x, abs_tol=1e-9
        ) or not math.isclose(
            self.approach_point_m.y,
            self.landing_target_m.y,
            abs_tol=1e-9,
        ):
            raise ValueError("landing approach must be vertically aligned with its target")
        if self.failure_action is GoalFailureAction.DIVERT and self.diversion_target_m is None:
            raise ValueError("diversion failure action requires a diversion target")
        if self.failure_action is GoalFailureAction.ABORT_AND_LAND and self.diversion_target_m:
            raise ValueError("abort-only goal must not declare an unused diversion target")
        return self


class GoalCaptureAttempt(ContractModel):
    attempt: int = Field(ge=1)
    estimated_position_m: Vector3 | None = None
    truth_position_m: Vector3 | None = None
    speed_m_s: float | None = Field(default=None, ge=0.0)
    horizontal_error_m: float | None = Field(default=None, ge=0.0)
    vertical_error_m: float | None = Field(default=None, ge=0.0)
    horizontal_capture_margin_m: float | None = None
    vertical_capture_margin_m: float | None = None
    speed_capture_margin_m_s: float | None = None
    source_timestamp_s: float | None = Field(default=None, ge=0.0)
    source_clock_id: Identifier | None = None
    source_clock_epoch: int | None = Field(default=None, ge=0)
    source_sequence: int | None = Field(default=None, ge=0)
    aligned: bool

    @model_validator(mode="after")
    def source_identity_is_complete(self) -> GoalCaptureAttempt:
        identity = (
            self.source_timestamp_s,
            self.source_clock_id,
            self.source_clock_epoch,
            self.source_sequence,
        )
        if any(value is not None for value in identity) and not all(
            value is not None for value in identity
        ):
            raise ValueError("goal capture attempt source identity must be complete")
        return self


class GoalCaptureRecord(ContractModel):
    schema_version: Literal[1, 2, 3] = 3
    goal: LandingGoalRegion
    attempts: tuple[GoalCaptureAttempt, ...]
    attempt_count: int = Field(ge=1)
    descent_authorized: bool
    outcome: GoalCaptureOutcome
    terminal_estimated_position_m: Vector3 | None = None
    terminal_truth_position_m: Vector3 | None = None
    terminal_speed_m_s: float | None = Field(default=None, ge=0.0)
    target_center_horizontal_error_m: float | None = Field(default=None, ge=0.0)
    alignment_completed_source_timestamp_s: float | None = Field(default=None, ge=0.0)
    pre_contact_vertical_speed_m_s: float | None = Field(default=None, ge=0.0)
    contact_source_timestamp_s: float | None = Field(default=None, ge=0.0)
    disarmed_source_timestamp_s: float | None = Field(default=None, ge=0.0)
    post_contact_settling_s: float | None = Field(default=None, ge=0.0)
    motors_cut_after_contact: bool | None = None
    authorized_capture_position_m: Vector3 | None = None
    descent_target_position_m: Vector3 | None = None
    commanded_pre_descent_horizontal_adjustment_m: float | None = Field(
        default=None, ge=0.0
    )
    alignment_duration_s: float | None = Field(default=None, ge=0.0)
    contact_source_clock_id: Identifier | None = None
    contact_source_clock_epoch: int | None = Field(default=None, ge=0)
    contact_source_sequence: int | None = Field(default=None, ge=0)
    correction_count: int = Field(default=0, ge=0)
    terminal_state: str | None = None
    terminal_contact: Literal[
        "SIMULATED_GROUND_CONTACT",
        "NO_CONTACT_EVIDENCE",
        "DESCENT_NOT_AUTHORIZED",
    ]

    @model_validator(mode="after")
    def attempts_and_outcome_agree(self) -> GoalCaptureRecord:
        if self.attempt_count != len(self.attempts):
            raise ValueError("goal attempt count does not match attempt evidence")
        if self.descent_authorized != (self.outcome is not GoalCaptureOutcome.REJECTED):
            raise ValueError("goal descent authority contradicts capture outcome")
        contact_identity = (
            self.contact_source_timestamp_s,
            self.contact_source_clock_id,
            self.contact_source_clock_epoch,
            self.contact_source_sequence,
        )
        if self.schema_version == 3 and any(
            value is not None for value in contact_identity
        ) and not all(
            value is not None for value in contact_identity
        ):
            raise ValueError("goal contact source identity must be complete")
        v3_values = (
            self.authorized_capture_position_m,
            self.descent_target_position_m,
            self.commanded_pre_descent_horizontal_adjustment_m,
            self.alignment_duration_s,
            self.contact_source_clock_id,
            self.contact_source_clock_epoch,
            self.contact_source_sequence,
        )
        if self.schema_version < 3 and any(value is not None for value in v3_values):
            raise ValueError("historical goal capture records cannot contain v3 evidence")
        return self
