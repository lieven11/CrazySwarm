from __future__ import annotations

from enum import StrEnum
from statistics import mean
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256

CalibrationGeometry = Literal["straight", "curve"]

CALIBRATION_PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "mass_scale": (0.85, 1.15),
    "linear_drag_scale": (0.50, 1.50),
    "motor_time_constant_scale": (0.75, 1.25),
    "thrust_scale": (0.85, 1.15),
}


class CalibrationDisposition(StrEnum):
    CANDIDATE = "CANDIDATE"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class CalibrationSessionResult(ContractModel):
    session_id: Identifier
    geometry_id: CalibrationGeometry
    accepted: bool
    whole_session_sha256: SHA256
    repeat_vector_sha256s: tuple[SHA256, SHA256, SHA256]
    position_rmse_m: float = Field(ge=0.0)
    altitude_rmse_m: float = Field(ge=0.0)
    velocity_rmse_m_s: float = Field(ge=0.0)
    guards: dict[Identifier, float | int | bool]

    @model_validator(mode="after")
    def exact_repeat_and_guard_universe(self) -> CalibrationSessionResult:
        if len(set(self.repeat_vector_sha256s)) != 1:
            raise ValueError("calibration whole-session repeats are not deterministic")
        if set(self.guards) != set(MOTION_GUARD_REGISTRY):
            raise ValueError("calibration result does not contain the exact 22-guard universe")
        return self


class CalibrationPromotionReport(ContractModel):
    calibration_id: Identifier
    predecessor_calibration_id: Identifier | None = None
    train_session_ids: tuple[Identifier, ...]
    holdout_session_ids: tuple[Identifier, ...]
    parameters: dict[Identifier, float]
    operator_accepted: bool
    operator_id: Identifier | None = None
    primary_improvement_absolute_m: float
    primary_improvement_fraction: float
    failed_guards: tuple[Identifier, ...]
    disposition: CalibrationDisposition
    report_sha256: SHA256


class CalibrationCandidateRequest(ContractModel):
    predecessor_calibration_id: Identifier | None = None
    train_session_ids: tuple[Identifier, ...]
    holdout_session_ids: tuple[Identifier, ...]
    session_geometry_ids: dict[Identifier, CalibrationGeometry]
    session_sha256s: dict[Identifier, SHA256]
    parameters: dict[Identifier, float]
    baseline: tuple[CalibrationSessionResult, ...]
    candidate: tuple[CalibrationSessionResult, ...]

    @model_validator(mode="after")
    def candidate_boundary_is_causal(self) -> CalibrationCandidateRequest:
        _validate_candidate_boundary(
            parameters=self.parameters,
            baseline=self.baseline,
            candidate=self.candidate,
            train_session_ids=self.train_session_ids,
            holdout_session_ids=self.holdout_session_ids,
            session_geometry_ids=self.session_geometry_ids,
            session_sha256s=self.session_sha256s,
            minimum_session_count=3,
        )
        return self


class CalibrationCandidate(ContractModel):
    schema_version: Literal[1] = 1
    calibration_id: Identifier
    created_at_monotonic_s: float = Field(ge=0.0)
    predecessor_calibration_id: Identifier | None = None
    train_session_ids: tuple[Identifier, ...]
    holdout_session_ids: tuple[Identifier, ...]
    session_geometry_ids: dict[Identifier, CalibrationGeometry]
    session_sha256s: dict[Identifier, SHA256]
    parameters: dict[Identifier, float]
    baseline: tuple[CalibrationSessionResult, ...]
    candidate: tuple[CalibrationSessionResult, ...]
    disposition: Literal[CalibrationDisposition.CANDIDATE] = CalibrationDisposition.CANDIDATE
    candidate_sha256: SHA256

    @model_validator(mode="after")
    def hash_matches_payload(self) -> CalibrationCandidate:
        payload = self.model_dump(mode="python", exclude={"candidate_sha256"})
        if canonical_sha256(payload) != self.candidate_sha256:
            raise ValueError("calibration candidate hash mismatch")
        return self


class CalibrationPromotionAcceptance(ContractModel):
    operator_id: Identifier
    acceptance_phrase: Literal["PROMOTE CALIBRATION"]


class CalibrationPromotionOracle:
    allowed_parameters = frozenset(CALIBRATION_PARAMETER_BOUNDS)

    def evaluate(
        self,
        *,
        calibration_id: str,
        parameters: dict[str, float],
        baseline: tuple[CalibrationSessionResult, ...],
        candidate: tuple[CalibrationSessionResult, ...],
        train_session_ids: tuple[str, ...],
        holdout_session_ids: tuple[str, ...],
        session_geometry_ids: dict[str, CalibrationGeometry],
        session_sha256s: dict[str, SHA256],
        operator_accepted: bool,
        operator_id: str | None = None,
        predecessor_calibration_id: str | None = None,
    ) -> CalibrationPromotionReport:
        _validate_candidate_boundary(
            parameters=parameters,
            baseline=baseline,
            candidate=candidate,
            train_session_ids=train_session_ids,
            holdout_session_ids=holdout_session_ids,
            session_geometry_ids=session_geometry_ids,
            session_sha256s=session_sha256s,
            minimum_session_count=6,
        )
        if len(train_session_ids) != 4 or len(holdout_session_ids) != 2:
            raise ValueError("promotion requires four train and two holdout whole sessions")
        if any(
            sum(geometry == expected for geometry in session_geometry_ids.values()) != 3
            for expected in ("straight", "curve")
        ):
            raise ValueError("promotion requires three whole sessions per geometry")
        if len(baseline) != len(candidate) or len(candidate) != 2:
            raise ValueError("promotion requires one baseline/candidate holdout per geometry")
        if {item.session_id for item in baseline} != set(holdout_session_ids) or {
            item.session_id for item in candidate
        } != set(holdout_session_ids):
            raise ValueError("calibration results are not the frozen whole-session holdouts")
        baseline_by_geometry = {item.geometry_id: item for item in baseline}
        candidate_by_geometry = {item.geometry_id: item for item in candidate}
        if set(baseline_by_geometry) != {"straight", "curve"} or set(
            candidate_by_geometry
        ) != {"straight", "curve"}:
            raise ValueError("promotion holdouts must cover straight and curve geometries")
        if any(not item.accepted for item in (*baseline, *candidate)):
            raise ValueError("calibration cannot use an unaccepted session")
        baseline_position = mean(item.position_rmse_m for item in baseline)
        candidate_position = mean(item.position_rmse_m for item in candidate)
        absolute_improvement = baseline_position - candidate_position
        relative_improvement = absolute_improvement / max(baseline_position, 1e-12)
        failures = []
        if absolute_improvement < 0.005:
            failures.append("position_rmse_absolute_improvement")
        if relative_improvement < 0.10:
            failures.append("position_rmse_relative_improvement")
        for geometry in ("straight", "curve"):
            before = baseline_by_geometry[geometry]
            after = candidate_by_geometry[geometry]
            if after.altitude_rmse_m > before.altitude_rmse_m * 1.05 + 1e-12:
                failures.append(f"altitude_rmse.{geometry}")
            if after.velocity_rmse_m_s > before.velocity_rmse_m_s * 1.05 + 1e-12:
                failures.append(f"velocity_rmse.{geometry}")
            failures.extend(_guard_failures(before, after, geometry))
        if not operator_accepted:
            failures.append("operator_acceptance")
        elif operator_id is None:
            failures.append("operator_identity")
        disposition = (
            CalibrationDisposition.PROMOTED if not failures else CalibrationDisposition.REJECTED
        )
        payload = {
            "calibration_id": calibration_id,
            "predecessor_calibration_id": predecessor_calibration_id,
            "train_session_ids": train_session_ids,
            "holdout_session_ids": holdout_session_ids,
            "parameters": parameters,
            "operator_accepted": operator_accepted,
            "operator_id": operator_id,
            "primary_improvement_absolute_m": absolute_improvement,
            "primary_improvement_fraction": relative_improvement,
            "failed_guards": tuple(failures),
            "disposition": disposition,
        }
        return CalibrationPromotionReport(**payload, report_sha256=canonical_sha256(payload))


def _validate_candidate_boundary(
    *,
    parameters: dict[str, float],
    baseline: tuple[CalibrationSessionResult, ...],
    candidate: tuple[CalibrationSessionResult, ...],
    train_session_ids: tuple[str, ...],
    holdout_session_ids: tuple[str, ...],
    session_geometry_ids: dict[str, CalibrationGeometry],
    session_sha256s: dict[str, SHA256],
    minimum_session_count: int,
) -> None:
    if not 1 <= len(parameters) <= 4 or not set(parameters).issubset(
        CALIBRATION_PARAMETER_BOUNDS
    ):
        raise ValueError("calibration must use 1..4 members of the frozen parameter family")
    for parameter_id, value in parameters.items():
        minimum, maximum = CALIBRATION_PARAMETER_BOUNDS[parameter_id]
        if not minimum <= value <= maximum:
            raise ValueError(f"calibration parameter {parameter_id} leaves its frozen bound")
    session_ids = (*train_session_ids, *holdout_session_ids)
    if len(session_ids) != len(set(session_ids)):
        raise ValueError("calibration train and holdout sessions overlap or repeat")
    if len(session_ids) < minimum_session_count:
        raise ValueError(
            f"calibration boundary requires at least {minimum_session_count} whole sessions"
        )
    if set(session_geometry_ids) != set(session_ids) or set(session_sha256s) != set(
        session_ids
    ):
        raise ValueError("calibration session geometry/hash maps must cover the frozen split")
    if set(session_geometry_ids.values()) != {"straight", "curve"}:
        raise ValueError("calibration sessions must cover straight and curve geometries")
    expected_holdouts = {
        max(
            (
                (session_sha256s[session_id], session_id)
                for session_id in session_ids
                if session_geometry_ids[session_id] == geometry
            ),
        )[1]
        for geometry in ("straight", "curve")
    }
    if set(holdout_session_ids) != expected_holdouts:
        raise ValueError("calibration split is not canonical session-hash rank")
    if set(train_session_ids) != set(session_ids) - expected_holdouts:
        raise ValueError("calibration training split is not the canonical complement")
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("calibration requires paired baseline/candidate holdout results")
    baseline_by_session = {item.session_id: item for item in baseline}
    candidate_by_session = {item.session_id: item for item in candidate}
    if set(baseline_by_session) != set(holdout_session_ids) or set(
        candidate_by_session
    ) != set(holdout_session_ids):
        raise ValueError("calibration results are not the canonical whole-session holdouts")
    for session_id in holdout_session_ids:
        before = baseline_by_session[session_id]
        after = candidate_by_session[session_id]
        if before.geometry_id != session_geometry_ids[session_id] or (
            after.geometry_id != session_geometry_ids[session_id]
        ):
            raise ValueError("calibration result geometry differs from the frozen split")
        if before.whole_session_sha256 != session_sha256s[session_id] or (
            after.whole_session_sha256 != session_sha256s[session_id]
        ):
            raise ValueError("calibration result is not bound to the frozen whole session")


# direction, hard threshold, maximum relative regression; ``None`` means exact-only.
MOTION_GUARD_REGISTRY: dict[str, tuple[str, float | bool, float | None]] = {
    "speed_compliance_fraction": ("MIN", 0.95, 0.05),
    "speed_ripple_m_s": ("MAX", 0.05, 0.05),
    "acceleration_p95_m_s2": ("MAX", 1.0, 0.05),
    "jerk_p95_m_s3": ("MAX", 8.0, 0.05),
    "angular_rate_p95_rad_s": ("MAX", 0.40, 0.05),
    "minimum_motor_thrust_headroom_n": ("MIN", 0.030, 0.05),
    "motor_spread_p95_percent": ("MAX", 0.50, 0.10),
    "motor_saturation_fraction": ("MAX", 0.02, 0.05),
    "motor_differential_sign_agreement_fraction": ("MIN", 0.95, 0.05),
    "motor_differential_normalized_error_p95": ("MAX", 0.10, 0.05),
    "electrical_energy_used_j": ("MAX", 220.0, 0.05),
    "tracking_rms_m": ("MAX", 0.05, 0.05),
    "path_tube_max_error_m": ("MAX", 0.05, 0.05),
    "minimum_clearance_m": ("MIN", 0.15, 0.05),
    "collision_count": ("MAX", 0.0, None),
    "checkpoint_hold_conformance_fraction": ("MIN", 1.0, None),
    "minimum_continuous_knot_speed_ratio": ("MODE", 0.0, 0.05),
    "unintended_fly_through_stop_count": ("MAX", 0.0, None),
    "terminal_secondary_peak_m_s": ("MAX", 0.02, 0.05),
    "terminal_reversal_count": ("MAX", 0.0, None),
    "duration_s": ("MAX", 17.5, 0.05),
    "supervisor_safety_gate_passed": ("BOOL", True, None),
}


def _guard_failures(
    baseline: CalibrationSessionResult,
    candidate: CalibrationSessionResult,
    geometry: str,
) -> list[str]:
    failures = []
    for guard_id, (direction, threshold, regression) in MOTION_GUARD_REGISTRY.items():
        before = baseline.guards[guard_id]
        after = candidate.guards[guard_id]
        hard = threshold
        if direction == "MODE":
            hard = 0.85 if geometry == "straight" else 0.95
            direction = "MIN"
        if direction == "BOOL":
            hard_passed = after is hard
        elif direction == "MIN":
            hard_passed = float(after) >= float(hard) - 1e-12
        else:
            hard_passed = float(after) <= float(hard) + 1e-12
        if not hard_passed:
            failures.append(f"{guard_id}.{geometry}.hard")
            continue
        if regression is None:
            continue
        if direction == "MIN":
            regressed = float(after) < float(before) * (1.0 - regression) - 1e-12
        else:
            regressed = float(after) > float(before) * (1.0 + regression) + 1e-12
        if regressed:
            failures.append(f"{guard_id}.{geometry}.regression")
    return failures
