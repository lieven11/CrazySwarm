from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.calibration import (
    CalibrationCandidate,
    CalibrationCandidateRequest,
    CalibrationDisposition,
    CalibrationPromotionAcceptance,
    CalibrationPromotionOracle,
    CalibrationPromotionReport,
)
from crazyswarm_app.twin.curriculum import (
    TwinCurriculum,
    TwinCurriculumResultRequest,
    TwinCurriculumStage,
)
from crazyswarm_app.twin.ingestion import TwinIngestionBoundary, default_twin_channels
from crazyswarm_app.twin.models import (
    CanonicalMissionIntent,
    ModelCalibration,
    TwinComparisonReport,
    TwinDeviation,
    TwinIngestionBatch,
    TwinIngestionReceipt,
    TwinIntentAcknowledgement,
    TwinObservation,
    TwinSessionConfig,
    TwinSessionRecord,
    TwinSessionStatus,
    TwinSourceClass,
    TwinTimeline,
    TwinValidity,
)
from crazyswarm_app.twin.pipeline import telemetry_csv_twin_batches
from crazyswarm_app.twin.storage import DurableTwinStore

IntentExecutor = Callable[[CanonicalMissionIntent], Awaitable[Any]]


@dataclass(slots=True)
class _Session:
    record: TwinSessionRecord
    config: TwinSessionConfig
    deviations: list[TwinDeviation] = field(default_factory=list)


class TwinCoordinator:
    """Observer-side twin orchestration; it never owns real-flight safety authority."""

    def __init__(self, storage_directory: Path | None = None) -> None:
        self._store = DurableTwinStore(storage_directory) if storage_directory is not None else None
        self.ingestion = TwinIngestionBoundary(self._store) if self._store is not None else None
        self._sessions: dict[str, _Session] = (
            {
                record.session_id: _Session(
                    record=record,
                    config=self._store.config(record.session_id),
                )
                for record in self._store.sessions()
            }
            if self._store is not None
            else {}
        )
        if self.ingestion is not None:
            for session_id in self._sessions:
                self.ingestion.register_channels(session_id, default_twin_channels())
        self._calibrations: dict[str, ModelCalibration] = {}
        self._promotion_candidates: dict[str, CalibrationCandidate] = (
            {
                item.calibration_id: item
                for item in (
                    CalibrationCandidate.model_validate(payload)
                    for payload in self._store.calibration_candidates()
                )
            }
            if self._store is not None
            else {}
        )
        self._promotion_reports: dict[str, CalibrationPromotionReport] = (
            {
                item.calibration_id: item
                for item in (
                    CalibrationPromotionReport.model_validate(payload)
                    for payload in self._store.calibration_reports()
                )
            }
            if self._store is not None
            else {}
        )
        self._active_calibration_id = (
            self._store.active_calibration_id() if self._store is not None else None
        )
        self._curriculum = TwinCurriculum.configured()
        if self._store is not None:
            for payload in self._store.curriculum_results():
                self._curriculum = self._curriculum.replay_result(
                    TwinCurriculumStage.model_validate(payload)
                )

    def create_session(self, config: TwinSessionConfig) -> TwinSessionRecord:
        if config.observed_vehicle_id == config.simulated_vehicle_id:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "observed and simulated twin vehicles must be distinct",
            )
        if config.observed_initial_state.source_class not in {
            TwinSourceClass.MEASURED_REAL,
            TwinSourceClass.CONFIGURED,
            TwinSourceClass.TEST,
        }:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "observed initial state requires measured, configured, or test provenance",
            )
        if config.simulated_initial_state.source_class not in {
            TwinSourceClass.SIMULATED_MODEL,
            TwinSourceClass.CONFIGURED,
            TwinSourceClass.TEST,
        }:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "simulated initial state requires model, configured, or test provenance",
            )
        if (
            config.observed_initial_state.source_class is TwinSourceClass.TEST
            or config.simulated_initial_state.source_class is TwinSourceClass.TEST
        ) and not config.test_only:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "test streams require a test-only twin session",
            )
        session_id = f"twin-{uuid.uuid4().hex}"
        record = TwinSessionRecord(
            session_id=session_id,
            status=TwinSessionStatus.READY,
            observed_vehicle_id=config.observed_vehicle_id,
            simulated_vehicle_id=config.simulated_vehicle_id,
            observed_source_class=config.observed_initial_state.source_class,
            simulated_source_class=config.simulated_initial_state.source_class,
            observed_source_id=config.observed_initial_state.source_id,
            simulated_source_id=config.simulated_initial_state.source_id,
            mission_id=config.mission_id,
            mission_version=config.mission_version,
            mission_source_sha256=config.mission_source_sha256,
            physics_model_id=config.physics_model_id,
            physics_model_version=config.physics_model_version,
            physics_configuration_sha256=config.physics_configuration_sha256,
            calibration_id=config.calibration_id,
            curriculum_stage_id=config.curriculum_stage_id,
            campaign_run_id=config.campaign_run_id,
            campaign_review_id=config.campaign_review_id,
            created_at_monotonic_s=time.monotonic(),
            ground_truth_available=config.ground_truth_available,
            test_only=config.test_only,
        )
        self._sessions[session_id] = _Session(record=record, config=config)
        if self._store is not None and self.ingestion is not None:
            try:
                self._store.register_session(record, config)
                self.ingestion.register_channels(session_id, default_twin_channels())
            except Exception:
                # Session creation is a single lifecycle boundary.  If durable
                # creation succeeded but channel registration did not, retain a
                # FAILED tombstone instead of an orphan READY session.  If no
                # durable record was created, remove the provisional entry.
                try:
                    self._store.record(session_id)
                except KeyError:
                    self._sessions.pop(session_id, None)
                else:
                    failed_record = record.model_copy(
                        update={"status": TwinSessionStatus.FAILED}
                    )
                    self._sessions[session_id].record = failed_record
                    self._store.update_session(failed_record)
                raise
        return record

    def session_for_campaign_run(self, run_id: str) -> TwinSessionRecord | None:
        return next(
            (
                session.record
                for session in self._sessions.values()
                if session.record.campaign_run_id == run_id
            ),
            None,
        )

    def list_sessions(self, *, include_test: bool = False) -> tuple[TwinSessionRecord, ...]:
        return tuple(
            session.record
            for session in self._sessions.values()
            if include_test or not session.record.test_only
        )

    def session(self, session_id: str, *, include_test: bool = False) -> TwinSessionRecord:
        session = self._require_session(session_id)
        if session.record.test_only and not include_test:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "unknown twin session")
        return session.record

    async def route_intent(
        self,
        session_id: str,
        intent: CanonicalMissionIntent,
        *,
        observed_executor: IntentExecutor,
        simulated_executor: IntentExecutor,
    ) -> tuple[TwinIntentAcknowledgement, TwinIntentAcknowledgement]:
        session = self._require_session(session_id)
        expected_artifact = (
            session.config.mission_id,
            session.config.mission_version,
            session.config.mission_source_sha256,
            session.config.physics_model_id,
            session.config.physics_model_version,
            session.config.physics_configuration_sha256,
        )
        actual_artifact = (
            intent.mission_id,
            intent.mission_version,
            intent.mission_source_sha256,
            intent.physics_model_id,
            intent.physics_model_version,
            intent.physics_configuration_sha256,
        )
        if actual_artifact != expected_artifact:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "intent artifact or physics model does not match twin session",
            )
        session.record = session.record.model_copy(update={"status": TwinSessionStatus.ACTIVE})
        observed_task = asyncio.create_task(
            self._execute_side("observed", intent, observed_executor)
        )
        simulated_task = asyncio.create_task(
            self._execute_side("simulated", intent, simulated_executor)
        )
        observed_ack, simulated_ack = await asyncio.gather(observed_task, simulated_task)
        acknowledgements = (
            *session.record.intent_acknowledgements,
            observed_ack,
            simulated_ack,
        )
        session.record = session.record.model_copy(
            update={"intent_acknowledgements": acknowledgements}
        )
        self._persist_record(session.record)
        return observed_ack, simulated_ack

    def add_observations(
        self,
        session_id: str,
        observed: TwinObservation,
        simulated: TwinObservation,
    ) -> TwinDeviation:
        session = self._require_session(session_id)
        self._validate_observations(session, observed, simulated)
        alignment_delta = abs(observed.source_timestamp_s - simulated.source_timestamp_s)
        observed_latency = max(0.0, observed.received_timestamp_s - observed.source_timestamp_s)
        simulated_latency = max(0.0, simulated.received_timestamp_s - simulated.source_timestamp_s)
        compatible = observed.frame is simulated.frame
        aligned = alignment_delta <= session.config.alignment_tolerance_s
        valid = observed.valid and simulated.valid and compatible and aligned
        comparable = valid and any(
            (
                observed.position_m is not None and simulated.position_m is not None,
                observed.velocity_m_s is not None and simulated.velocity_m_s is not None,
                observed.yaw_rad is not None and simulated.yaw_rad is not None,
                observed.battery_percent is not None and simulated.battery_percent is not None,
            )
        )
        validity = (
            TwinValidity.VALID
            if comparable
            else TwinValidity.INCOMPATIBLE
            if not compatible or not aligned
            else TwinValidity.UNAVAILABLE
        )
        position = (
            _distance(observed.position_m, simulated.position_m)
            if validity is TwinValidity.VALID
            and observed.position_m is not None
            and simulated.position_m is not None
            else None
        )
        altitude = (
            abs(observed.position_m.z - simulated.position_m.z)
            if validity is TwinValidity.VALID
            and observed.position_m is not None
            and simulated.position_m is not None
            else None
        )
        velocity = (
            _distance(observed.velocity_m_s, simulated.velocity_m_s)
            if validity is TwinValidity.VALID
            and observed.velocity_m_s is not None
            and simulated.velocity_m_s is not None
            else None
        )
        yaw = (
            abs(_wrapped_angle(observed.yaw_rad - simulated.yaw_rad))
            if validity is TwinValidity.VALID
            and observed.yaw_rad is not None
            and simulated.yaw_rad is not None
            else None
        )
        battery = (
            abs(observed.battery_percent - simulated.battery_percent)
            if validity is TwinValidity.VALID
            and observed.battery_percent is not None
            and simulated.battery_percent is not None
            else None
        )
        deviation = TwinDeviation(
            observed_source_timestamp_s=observed.source_timestamp_s,
            simulated_source_timestamp_s=simulated.source_timestamp_s,
            source_timestamp_s=max(observed.source_timestamp_s, simulated.source_timestamp_s),
            observed_latency_ms=observed_latency * 1000.0,
            simulated_latency_ms=simulated_latency * 1000.0,
            alignment_delta_ms=alignment_delta * 1000.0,
            frame=observed.frame.value if compatible else "incompatible",
            validity=validity,
            position_m=position,
            altitude_m=altitude,
            velocity_m_s=velocity,
            yaw_rad=yaw,
            battery_percent=battery,
            ground_truth_available=session.config.ground_truth_available,
            observed_source_class=observed.source_class,
            simulated_source_class=simulated.source_class,
        )
        session.deviations.append(deviation)
        session.record = session.record.model_copy(
            update={
                "latest_deviation": deviation,
                "deviation_count": len(session.deviations),
            }
        )
        self._persist_record(session.record)
        return deviation

    def complete(self, session_id: str, *, failed: bool = False) -> TwinSessionRecord:
        session = self._require_session(session_id)
        if session.record.status in {TwinSessionStatus.COMPLETE, TwinSessionStatus.FAILED}:
            return session.record
        session.record = session.record.model_copy(
            update={"status": TwinSessionStatus.FAILED if failed else TwinSessionStatus.COMPLETE}
        )
        self._persist_record(session.record)
        return session.record

    def ingest(self, batch: TwinIngestionBatch) -> TwinIngestionReceipt:
        if self.ingestion is None:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "persistent twin ingestion is not configured",
            )
        self._require_session(batch.session_id)
        return self.ingestion.ingest(batch)

    def ingest_telemetry_csv(
        self,
        session_id: str,
        csv_bytes: bytes,
        *,
        minimum_source_period_s: float | None = None,
    ) -> tuple[TwinIngestionReceipt, ...]:
        session = self._require_session(session_id)
        return tuple(
            self.ingest(batch)
            for batch in telemetry_csv_twin_batches(
                session_id=session_id,
                config=session.config,
                csv_bytes=csv_bytes,
                minimum_source_period_s=minimum_source_period_s,
            )
        )

    def timeline(
        self,
        session_id: str,
        *,
        channel_ids: tuple[str, ...] = (),
        after_source_s: float | None = None,
        limit: int = 4096,
    ) -> TwinTimeline:
        self._require_session(session_id)
        if self.ingestion is None:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "persistent twin ingestion is not configured",
            )
        return self.ingestion.timeline(
            session_id,
            channel_ids=channel_ids,
            after_source_s=after_source_s,
            limit=limit,
        )

    def report(self, session_id: str, *, include_test: bool = False) -> TwinComparisonReport:
        session = self._require_session(session_id)
        if session.record.test_only and not include_test:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "unknown twin session")
        valid = [item for item in session.deviations if item.validity is TwinValidity.VALID]
        positions = [item.position_m for item in valid if item.position_m is not None]
        altitudes = [item.altitude_m for item in valid if item.altitude_m is not None]
        return TwinComparisonReport(
            session_id=session_id,
            sample_count=len(session.deviations),
            valid_sample_count=len(valid),
            ground_truth_available=session.config.ground_truth_available,
            mean_position_m=_mean(positions),
            max_position_m=max(positions) if positions else None,
            mean_altitude_m=_mean(altitudes),
            mean_observed_latency_ms=_mean([item.observed_latency_ms for item in valid]),
            mean_simulated_latency_ms=_mean([item.simulated_latency_ms for item in valid]),
        )

    def calibrate(
        self,
        session_id: str,
        *,
        base_model_id: str,
        base_model_version: str,
    ) -> ModelCalibration:
        report = self.report(session_id, include_test=True)
        if report.valid_sample_count == 0:
            raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "calibration requires valid samples")
        calibration_id = f"cal-{uuid.uuid4().hex}"
        calibration = ModelCalibration(
            calibration_id=calibration_id,
            session_id=session_id,
            base_model_id=base_model_id,
            base_model_version=base_model_version,
            model_version=f"{base_model_version}+{calibration_id[-8:]}",
            created_at_monotonic_s=time.monotonic(),
            sample_count=report.valid_sample_count,
            parameters={
                key: value
                for key, value in {
                    "mean_position_residual_m": report.mean_position_m,
                    "mean_altitude_residual_m": report.mean_altitude_m,
                    "mean_observed_latency_ms": report.mean_observed_latency_ms,
                    "mean_simulated_latency_ms": report.mean_simulated_latency_ms,
                }.items()
                if value is not None
            },
        )
        self._calibrations[calibration_id] = calibration
        return calibration

    def create_calibration_candidate(
        self,
        request: CalibrationCandidateRequest,
    ) -> CalibrationCandidate:
        for session_id in (*request.train_session_ids, *request.holdout_session_ids):
            session = self._require_session(session_id)
            if session.record.status is not TwinSessionStatus.COMPLETE:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "calibration requires accepted complete whole sessions",
                )
            if self._store is not None:
                retained_sha256 = canonical_sha256(self._store.samples(session_id))
                if request.session_sha256s[session_id] != retained_sha256:
                    raise CrazySwarmError(
                        ErrorCode.INVALID_COMMAND,
                        "calibration session hash does not match retained whole-session samples",
                    )
        calibration_id = f"calibration-{uuid.uuid4().hex}"
        payload = {
            "schema_version": 1,
            "calibration_id": calibration_id,
            "created_at_monotonic_s": time.monotonic(),
            **request.model_dump(mode="python"),
            "disposition": CalibrationDisposition.CANDIDATE,
        }
        candidate = CalibrationCandidate(
            **payload,
            candidate_sha256=canonical_sha256(payload),
        )
        self._promotion_candidates[calibration_id] = candidate
        if self._store is not None:
            self._store.append_calibration_candidate(
                calibration_id,
                candidate.model_dump(mode="json"),
            )
        return candidate

    def calibration_candidates(self) -> tuple[CalibrationCandidate, ...]:
        return tuple(
            self._promotion_candidates[key] for key in sorted(self._promotion_candidates)
        )

    def calibration_reports(self) -> tuple[CalibrationPromotionReport, ...]:
        return tuple(self._promotion_reports[key] for key in sorted(self._promotion_reports))

    def active_calibration_id(self) -> str | None:
        return self._active_calibration_id

    def curriculum(self) -> TwinCurriculum:
        return self._curriculum

    def curriculum_stage(self, stage_id: str) -> TwinCurriculumStage:
        try:
            return next(item for item in self._curriculum.stages if item.stage_id == stage_id)
        except StopIteration as error:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "unknown twin curriculum stage",
            ) from error

    def record_curriculum_result(
        self,
        stage_id: str,
        request: TwinCurriculumResultRequest,
    ) -> TwinCurriculumStage:
        session = self._require_session(request.session_id)
        if session.record.status is not TwinSessionStatus.COMPLETE:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "twin curriculum result requires a complete retained session",
            )
        if session.config.curriculum_stage_id != stage_id:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "twin session is not bound to the requested curriculum stage",
            )
        if (
            session.config.observed_initial_state.source_class
            is TwinSourceClass.MEASURED_REAL
            or session.config.simulated_initial_state.source_class
            is not TwinSourceClass.SIMULATED_MODEL
        ):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "Fast Sim curriculum results require configured/simulated source classes",
            )
        updated, stage = self._curriculum.record_result(stage_id, request)
        if self._store is not None:
            self._store.append_curriculum_result(
                stage_id,
                stage.model_dump(mode="json"),
            )
        self._curriculum = updated
        return stage

    def promote_calibration(
        self,
        calibration_id: str,
        acceptance: CalibrationPromotionAcceptance,
    ) -> CalibrationPromotionReport:
        try:
            candidate = self._promotion_candidates[calibration_id]
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.IDENTITY_MISMATCH,
                "unknown calibration candidate",
            ) from error
        if calibration_id in self._promotion_reports:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "calibration candidate already has a retained promotion disposition",
            )
        if candidate.predecessor_calibration_id != self._active_calibration_id:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "calibration predecessor does not match the active model version",
            )
        report = CalibrationPromotionOracle().evaluate(
            calibration_id=calibration_id,
            parameters=candidate.parameters,
            baseline=candidate.baseline,
            candidate=candidate.candidate,
            train_session_ids=candidate.train_session_ids,
            holdout_session_ids=candidate.holdout_session_ids,
            session_geometry_ids=candidate.session_geometry_ids,
            session_sha256s=candidate.session_sha256s,
            operator_accepted=True,
            operator_id=acceptance.operator_id,
            predecessor_calibration_id=candidate.predecessor_calibration_id,
        )
        self._promotion_reports[calibration_id] = report
        if self._store is not None:
            self._store.append_calibration_report(
                calibration_id,
                report.model_dump(mode="json"),
            )
        if report.disposition is CalibrationDisposition.PROMOTED:
            activation = {
                "calibration_id": calibration_id,
                "predecessor_calibration_id": candidate.predecessor_calibration_id,
                "report_sha256": report.report_sha256,
            }
            if self._store is not None:
                self._store.activate_calibration(calibration_id, activation)
            self._active_calibration_id = calibration_id
        return report

    async def _execute_side(
        self,
        side: str,
        intent: CanonicalMissionIntent,
        executor: IntentExecutor,
    ) -> TwinIntentAcknowledgement:
        received = time.monotonic()
        try:
            result = await executor(intent)
        except Exception as error:
            return TwinIntentAcknowledgement(
                side=side,
                accepted=False,
                received_at_monotonic_s=received,
                completed_at_monotonic_s=time.monotonic(),
                message=f"{type(error).__name__}: {error}",
            )
        return TwinIntentAcknowledgement(
            side=side,
            accepted=True,
            received_at_monotonic_s=received,
            completed_at_monotonic_s=time.monotonic(),
            message=str(result) if result is not None else None,
        )

    def _validate_observations(
        self,
        session: _Session,
        observed: TwinObservation,
        simulated: TwinObservation,
    ) -> None:
        if observed.vehicle_id != session.config.observed_vehicle_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "observed vehicle mismatch")
        if simulated.vehicle_id != session.config.simulated_vehicle_id:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "simulated vehicle mismatch")
        if observed.source_class is TwinSourceClass.SIMULATED_MODEL:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "observed side cannot claim model data"
            )
        if simulated.source_class is TwinSourceClass.MEASURED_REAL:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "simulated side cannot claim real data"
            )
        if (
            observed.source_class is TwinSourceClass.TEST
            or simulated.source_class is TwinSourceClass.TEST
        ) and not session.config.test_only:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND, "test observation leaked to operator twin"
            )

    def _require_session(self, session_id: str) -> _Session:
        try:
            return self._sessions[session_id]
        except KeyError as error:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "unknown twin session") from error

    def _persist_record(self, record: TwinSessionRecord) -> None:
        if self._store is not None:
            self._store.update_session(record)


def _distance(left: Vector3, right: Vector3) -> float:
    return math.sqrt((left.x - right.x) ** 2 + (left.y - right.y) ** 2 + (left.z - right.z) ** 2)


def _wrapped_angle(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
