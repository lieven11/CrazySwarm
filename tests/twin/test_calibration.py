import json
from pathlib import Path

import pytest

from crazyswarm_app.domain.models import CoordinateFrame
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.calibration import (
    CALIBRATION_PARAMETER_BOUNDS,
    MOTION_GUARD_REGISTRY,
    CalibrationCandidateRequest,
    CalibrationDisposition,
    CalibrationPromotionAcceptance,
    CalibrationPromotionOracle,
    CalibrationSessionResult,
)
from crazyswarm_app.twin.coordinator import TwinCoordinator
from crazyswarm_app.twin.models import (
    TwinInitialState,
    TwinSessionConfig,
    TwinSourceClass,
)

_SESSION_GEOMETRIES = {
    "straight-1": "straight",
    "straight-2": "straight",
    "straight-3": "straight",
    "curve-1": "curve",
    "curve-2": "curve",
    "curve-3": "curve",
}
_SESSION_SHA256S = {
    session_id: canonical_sha256([session_id, "whole"])
    for session_id in _SESSION_GEOMETRIES
}
_HOLDOUTS = tuple(
    max(
        (
            (_SESSION_SHA256S[session_id], session_id)
            for session_id, session_geometry in _SESSION_GEOMETRIES.items()
            if session_geometry == geometry
        )
    )[1]
    for geometry in ("straight", "curve")
)
_TRAIN = tuple(session_id for session_id in _SESSION_GEOMETRIES if session_id not in _HOLDOUTS)


def _guards(*, headroom: float = 0.04) -> dict[str, float | int | bool]:
    values: dict[str, float | int | bool] = {
        "speed_compliance_fraction": 0.97,
        "speed_ripple_m_s": 0.04,
        "acceleration_p95_m_s2": 0.6,
        "jerk_p95_m_s3": 4.0,
        "angular_rate_p95_rad_s": 0.25,
        "minimum_motor_thrust_headroom_n": headroom,
        "motor_spread_p95_percent": 0.25,
        "motor_saturation_fraction": 0.005,
        "motor_differential_sign_agreement_fraction": 0.98,
        "motor_differential_normalized_error_p95": 0.06,
        "electrical_energy_used_j": 150.0,
        "tracking_rms_m": 0.035,
        "path_tube_max_error_m": 0.04,
        "minimum_clearance_m": 0.20,
        "collision_count": 0,
        "checkpoint_hold_conformance_fraction": 1.0,
        "minimum_continuous_knot_speed_ratio": 0.98,
        "unintended_fly_through_stop_count": 0,
        "terminal_secondary_peak_m_s": 0.01,
        "terminal_reversal_count": 0,
        "duration_s": 10.0,
        "supervisor_safety_gate_passed": True,
    }
    assert set(values) == set(MOTION_GUARD_REGISTRY)
    return values


def _result(
    session_id: str,
    geometry: str,
    *,
    position: float,
    headroom: float = 0.04,
) -> CalibrationSessionResult:
    vector_hash = canonical_sha256([session_id, geometry, position, headroom])
    return CalibrationSessionResult(
        session_id=session_id,
        geometry_id=geometry,
        accepted=True,
        whole_session_sha256=canonical_sha256([session_id, "whole"]),
        repeat_vector_sha256s=(vector_hash, vector_hash, vector_hash),
        position_rmse_m=position,
        altitude_rmse_m=0.04,
        velocity_rmse_m_s=0.09,
        guards=_guards(headroom=headroom),
    )


def test_six_session_holdout_promotion_requires_every_guard_and_operator() -> None:
    baseline = (
        *(
            _result(
                session_id,
                _SESSION_GEOMETRIES[session_id],
                position=0.075 if _SESSION_GEOMETRIES[session_id] == "straight" else 0.065,
            )
            for session_id in _HOLDOUTS
        ),
    )
    candidate = (
        *(
            _result(
                session_id,
                _SESSION_GEOMETRIES[session_id],
                position=0.068 if _SESSION_GEOMETRIES[session_id] == "straight" else 0.058,
                headroom=0.039,
            )
            for session_id in _HOLDOUTS
        ),
    )
    report = CalibrationPromotionOracle().evaluate(
        calibration_id="candidate-1",
        parameters={"mass_scale": 1.02, "linear_drag_scale": 0.98},
        baseline=baseline,
        candidate=candidate,
        train_session_ids=_TRAIN,
        holdout_session_ids=_HOLDOUTS,
        session_geometry_ids=_SESSION_GEOMETRIES,
        session_sha256s=_SESSION_SHA256S,
        operator_accepted=True,
        operator_id="operator",
    )
    assert report.disposition is CalibrationDisposition.PROMOTED
    assert report.failed_guards == ()


def test_regression_only_headroom_clause_rejects_promotion() -> None:
    baseline = (
        *(
            _result(
                session_id,
                _SESSION_GEOMETRIES[session_id],
                position=0.075 if _SESSION_GEOMETRIES[session_id] == "straight" else 0.065,
            )
            for session_id in _HOLDOUTS
        ),
    )
    candidate = (
        *(
            _result(
                session_id,
                _SESSION_GEOMETRIES[session_id],
                position=0.068 if _SESSION_GEOMETRIES[session_id] == "straight" else 0.058,
                headroom=(
                    0.0379 if _SESSION_GEOMETRIES[session_id] == "straight" else 0.04
                ),
            )
            for session_id in _HOLDOUTS
        ),
    )
    report = CalibrationPromotionOracle().evaluate(
        calibration_id="candidate-regression",
        parameters={"mass_scale": 1.01},
        baseline=baseline,
        candidate=candidate,
        train_session_ids=_TRAIN,
        holdout_session_ids=_HOLDOUTS,
        session_geometry_ids=_SESSION_GEOMETRIES,
        session_sha256s=_SESSION_SHA256S,
        operator_accepted=True,
        operator_id="operator",
    )
    assert report.disposition is CalibrationDisposition.REJECTED
    assert "minimum_motor_thrust_headroom_n.straight.regression" in report.failed_guards


def test_parameter_family_uses_the_frozen_physics_scales() -> None:
    assert CALIBRATION_PARAMETER_BOUNDS == {
        "mass_scale": (0.85, 1.15),
        "linear_drag_scale": (0.50, 1.50),
        "motor_time_constant_scale": (0.75, 1.25),
        "thrust_scale": (0.85, 1.15),
    }


def _retained_sessions(
    coordinator: TwinCoordinator,
    geometries: tuple[str, ...],
) -> tuple[dict[str, str], dict[str, str]]:
    geometry_by_id = {}
    hashes = {}
    for index, geometry in enumerate(geometries, start=1):
        record = coordinator.create_session(
            TwinSessionConfig(
                observed_vehicle_id=f"observed-{geometry}-{index}",
                simulated_vehicle_id=f"predicted-{geometry}-{index}",
                mission_id=f"calibration-{geometry}",
                mission_version="1",
                observed_initial_state=TwinInitialState(
                    source_class=TwinSourceClass.CONFIGURED,
                    source_id="fast-sim-truth",
                    frame=CoordinateFrame.WORLD,
                ),
                simulated_initial_state=TwinInitialState(
                    source_class=TwinSourceClass.SIMULATED_MODEL,
                    source_id="candidate-model",
                    frame=CoordinateFrame.WORLD,
                ),
            )
        )
        coordinator.complete(record.session_id)
        geometry_by_id[record.session_id] = geometry
        hashes[record.session_id] = canonical_sha256(())
    return geometry_by_id, hashes


def _candidate_request(
    geometry_by_id: dict[str, str],
    hashes: dict[str, str],
) -> CalibrationCandidateRequest:
    holdouts = tuple(
        max(
            (
                (hashes[session_id], session_id)
                for session_id, value in geometry_by_id.items()
                if value == geometry
            )
        )[1]
        for geometry in ("straight", "curve")
    )
    train = tuple(session_id for session_id in geometry_by_id if session_id not in holdouts)
    baseline = tuple(
        _result(
            session_id,
            geometry_by_id[session_id],
            position=0.08 if geometry_by_id[session_id] == "straight" else 0.07,
        ).model_copy(update={"whole_session_sha256": hashes[session_id]})
        for session_id in holdouts
    )
    candidate = tuple(
        _result(
            session_id,
            geometry_by_id[session_id],
            position=0.068 if geometry_by_id[session_id] == "straight" else 0.060,
        ).model_copy(update={"whole_session_sha256": hashes[session_id]})
        for session_id in holdouts
    )
    return CalibrationCandidateRequest(
        train_session_ids=train,
        holdout_session_ids=holdouts,
        session_geometry_ids=geometry_by_id,
        session_sha256s=hashes,
        parameters={"mass_scale": 1.02, "thrust_scale": 0.99},
        baseline=baseline,
        candidate=candidate,
    )


def test_candidate_and_promotion_decisions_survive_restart(tmp_path: Path) -> None:
    root = tmp_path / "twin"
    coordinator = TwinCoordinator(root)
    geometry_by_id, hashes = _retained_sessions(
        coordinator,
        ("straight", "straight", "straight", "curve", "curve", "curve"),
    )
    candidate = coordinator.create_calibration_candidate(
        _candidate_request(geometry_by_id, hashes)
    )
    report = coordinator.promote_calibration(
        candidate.calibration_id,
        CalibrationPromotionAcceptance(
            operator_id="operator",
            acceptance_phrase="PROMOTE CALIBRATION",
        ),
    )
    assert report.disposition is CalibrationDisposition.PROMOTED
    assert coordinator.active_calibration_id() == candidate.calibration_id
    restarted = TwinCoordinator(root)
    assert restarted.calibration_candidates() == (candidate,)
    assert restarted.calibration_reports() == (report,)
    assert restarted.active_calibration_id() == candidate.calibration_id


def test_three_session_candidate_is_auditable_but_cannot_promote(tmp_path: Path) -> None:
    coordinator = TwinCoordinator(tmp_path / "twin")
    geometry_by_id, hashes = _retained_sessions(
        coordinator,
        ("straight", "straight", "curve"),
    )
    candidate = coordinator.create_calibration_candidate(
        _candidate_request(geometry_by_id, hashes)
    )
    assert candidate.disposition is CalibrationDisposition.CANDIDATE
    with pytest.raises(ValueError, match="at least 6 whole sessions"):
        coordinator.promote_calibration(
            candidate.calibration_id,
            CalibrationPromotionAcceptance(
                operator_id="operator",
                acceptance_phrase="PROMOTE CALIBRATION",
            ),
        )


def _audit_result(
    session_id: str,
    geometry: str,
    outputs: dict[str, list[float | int | bool]],
) -> CalibrationSessionResult:
    vector = {key: values[0] for key, values in outputs.items()}
    repeat_hash = canonical_sha256(vector)
    return CalibrationSessionResult(
        session_id=session_id,
        geometry_id=geometry,
        accepted=True,
        whole_session_sha256="f" * 64,
        repeat_vector_sha256s=(repeat_hash, repeat_hash, repeat_hash),
        position_rmse_m=float(vector.pop("position_rmse_m")),
        altitude_rmse_m=float(vector.pop("altitude_rmse_m")),
        velocity_rmse_m_s=float(vector.pop("velocity_rmse_m_s")),
        guards=vector,
    )


def test_every_frozen_guard_binding_clause_has_an_isolated_rejection() -> None:
    audit = json.loads(
        Path(
            "missions/campaigns/sim/qualification/wp57-61-r3-design-audit-v1.json"
        ).read_text(encoding="utf-8")
    )["calibration_oracle"]
    session_geometry_ids = {
        "straight-train-1": "straight",
        "straight-train-2": "straight",
        "straight-holdout": "straight",
        "curve-train-1": "curve",
        "curve-train-2": "curve",
        "curve-holdout": "curve",
    }
    session_sha256s = {
        session_id: (
            "f" * 64 if session_id.endswith("holdout") else f"{index:064x}"
        )
        for index, session_id in enumerate(session_geometry_ids, start=1)
    }
    train = tuple(
        session_id for session_id in session_geometry_ids if not session_id.endswith("holdout")
    )
    holdouts = ("straight-holdout", "curve-holdout")
    for witness in audit["binding_clause_coverage"]["witnesses"]:
        scenario_id = witness["scenario_id"].removeprefix("fail_guard.").removeprefix(
            "fail_clause."
        )
        source = (
            audit["isolated_guard_failures"]
            if witness["scenario_id"].startswith("fail_guard.")
            else audit["additional_binding_clause_failures"]
        )
        scenario = source[scenario_id]
        baseline = tuple(
            _audit_result(
                f"{geometry}-holdout",
                geometry,
                scenario["geometries"][geometry]["baseline_repeat_outputs"],
            )
            for geometry in ("straight", "curve")
        )
        candidate = tuple(
            _audit_result(
                f"{geometry}-holdout",
                geometry,
                scenario["geometries"][geometry]["candidate_repeat_outputs"],
            )
            for geometry in ("straight", "curve")
        )
        report = CalibrationPromotionOracle().evaluate(
            calibration_id=f"isolated-{scenario_id}",
            parameters={"mass_scale": 1.0},
            baseline=baseline,
            candidate=candidate,
            train_session_ids=train,
            holdout_session_ids=holdouts,
            session_geometry_ids=session_geometry_ids,
            session_sha256s=session_sha256s,
            operator_accepted=True,
            operator_id="oracle-test",
        )
        suffix = (
            "regression"
            if witness["expected_clause"] == "REGRESSION_ONLY"
            else "hard"
        )
        assert report.failed_guards == (
            f"{witness['guard_id']}.{witness['geometry']}.{suffix}",
        )
