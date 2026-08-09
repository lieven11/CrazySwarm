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
    aligned: bool


class GoalCaptureRecord(ContractModel):
    schema_version: Literal[1] = 1
    goal: LandingGoalRegion
    attempts: tuple[GoalCaptureAttempt, ...]
    attempt_count: int = Field(ge=1)
    descent_authorized: bool
    outcome: GoalCaptureOutcome
    terminal_estimated_position_m: Vector3 | None = None
    terminal_truth_position_m: Vector3 | None = None
    terminal_speed_m_s: float | None = Field(default=None, ge=0.0)
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
        return self
