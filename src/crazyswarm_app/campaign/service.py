from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from crazyswarm_app.campaign.analyzer import (
    MissionAnalysis,
    ModeComparison,
    analyze_execution,
    compare_execution_modes,
)
from crazyswarm_app.campaign.catalog import CampaignCatalog, validate_case_against_policy
from crazyswarm_app.campaign.models import (
    CampaignCase,
    ExecutionEligibility,
    LifecycleRecord,
    LifecycleState,
    LockedDevelopmentInputs,
)
from crazyswarm_app.campaign.planner import (
    BoundedJointPlanner,
    BoundedPlanningResult,
    PlanningStatus,
)
from crazyswarm_app.campaign.scheduling import GroundFirstSchedule, build_ground_first_schedule
from crazyswarm_app.campaign.trajectory import SmoothTrajectorySet, generate_smooth_trajectories
from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.planning.robustness import generate_robustness_matrix


class CampaignAction(StrEnum):
    SET_ACTIVE_DEVELOPMENT_CASE = "SET_ACTIVE_DEVELOPMENT_CASE"
    RUN_ACTIVE_ACCELERATED = "RUN_ACTIVE_ACCELERATED"
    RUN_ACTIVE_OPERATOR_REALTIME = "RUN_ACTIVE_OPERATOR_REALTIME"
    RERUN_ACTIVE_SAME_INPUTS = "RERUN_ACTIVE_SAME_INPUTS"
    CREATE_CHILD_FROM_ACTIVE = "CREATE_CHILD_FROM_ACTIVE"


class CampaignRunMode(StrEnum):
    AUTOMATED_ACCELERATED = "AUTOMATED_ACCELERATED"
    OPERATOR_OBSERVED_REALTIME = "OPERATOR_OBSERVED_REALTIME"


class CampaignRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"
    CANCELLED_BEFORE_LAUNCH = "CANCELLED_BEFORE_LAUNCH"


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    NEEDS_RERUN = "NEEDS_RERUN"


class RunArtifactSet(ContractModel):
    mission_execution_id: Identifier
    status: str
    manifest: dict[str, Any]
    bundle: dict[str, Any]
    evaluation: dict[str, Any]
    csv_bytes_sha256: SHA256
    csv_content: bytes


class CampaignExecutionRequest(ContractModel):
    run_id: Identifier
    mode: CampaignRunMode
    locked_inputs: LockedDevelopmentInputs
    case: CampaignCase
    plan: BoundedPlanningResult
    schedule: GroundFirstSchedule
    trajectories: SmoothTrajectorySet


class CampaignExecutor(Protocol):
    async def __call__(self, request: CampaignExecutionRequest) -> RunArtifactSet: ...


class CampaignRunRecord(ContractModel):
    run_id: Identifier
    mode: CampaignRunMode
    status: CampaignRunStatus
    locked_inputs: LockedDevelopmentInputs
    requested_at_utc: datetime
    started_at_utc: datetime | None = None
    finished_at_utc: datetime | None = None
    mission_execution_id: Identifier | None = None
    plan_sha256: SHA256
    schedule_sha256: SHA256
    trajectory_set_sha256: SHA256
    artifact_set_sha256: SHA256 | None = None
    analysis_sha256: SHA256 | None = None
    failure_reason: str | None = None
    automatic_retry_count: int = Field(default=0, ge=0, le=1)


class ReviewApproval(ContractModel):
    schema_version: Literal[1] = 1
    operator_id: Identifier
    decided_at_utc: datetime
    decision: ReviewDecision
    report_schema_version: Literal[1] = 1
    report_sha256: SHA256
    reason: str = Field(min_length=1, max_length=1000)
    note: str | None = Field(default=None, max_length=2000)
    approval_sha256: SHA256


class ReviewItem(ContractModel):
    review_id: Identifier
    run_id: Identifier
    case_id: Identifier
    case_sha256: SHA256
    status: CampaignRunStatus
    plan_sha256: SHA256
    artifact_set_sha256: SHA256
    analysis: MissionAnalysis
    baseline_comparison: dict[str, float | str | bool | None] = Field(default_factory=dict)
    mode_comparison: ModeComparison | None = None
    operator_questions: tuple[str, ...]
    operator_observations: tuple[str, ...] = ()
    approval: ReviewApproval | None = None
    review_sha256: SHA256

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"review_sha256"})


class RecommendationRule(StrEnum):
    MISSING_PREREQUISITE = "MISSING_PREREQUISITE"
    UNRESOLVED_FAILURE = "UNRESOLVED_FAILURE"
    UNTESTED_HARD_BOUNDARY = "UNTESTED_HARD_BOUNDARY"
    LOWEST_DIFFICULTY_CHILD = "LOWEST_DIFFICULTY_CHILD"
    CAMPAIGN_COMPLETE = "CAMPAIGN_COMPLETE"


class NextCaseRecommendation(ContractModel):
    rule: RecommendationRule
    candidate_case_ids: tuple[Identifier, ...]
    recommended_case_id: Identifier | None = None
    reason: str
    input_sha256: SHA256
    recommendation_sha256: SHA256
    auto_execute: Literal[False] = False


class CampaignWorkspaceState(ContractModel):
    schema_version: Literal[1] = 1
    active_case_id: Identifier | None = None
    locked_inputs: LockedDevelopmentInputs | None = None
    lifecycle: dict[Identifier, LifecycleRecord]
    runs: tuple[CampaignRunRecord, ...] = ()
    reviews: tuple[ReviewItem, ...] = ()
    idempotency: dict[str, Identifier] = Field(default_factory=dict)


class CampaignService:
    """Persistent headless campaign loop. Discovery and selection never call an executor."""

    def __init__(
        self,
        *,
        catalog: CampaignCatalog,
        state_directory: Path,
        executor: CampaignExecutor | None = None,
        maximum_concurrency: int = 1,
    ) -> None:
        if not 1 <= maximum_concurrency <= 3:
            raise ValueError("campaign concurrency must be in 1..3")
        self.catalog = catalog
        self.state_directory = state_directory
        self.executor = executor
        self.maximum_concurrency = maximum_concurrency
        self._semaphore = asyncio.Semaphore(maximum_concurrency)
        self._cancelled: set[str] = set()
        self._planner = BoundedJointPlanner()
        self.state_directory.mkdir(parents=True, exist_ok=True)
        self.catalog.discover()
        self._load_children()
        self._state = self._load_state()
        self._reconcile_interrupted_runs()
        # Persist catalog additions and safe identity refreshes immediately so a
        # restarted API process sees the same reconciled workspace.
        self._persist()

    @property
    def state(self) -> CampaignWorkspaceState:
        return self._state

    def static_validate(
        self, case_id: str, *, actor_id: str = "campaign-validator"
    ) -> BoundedPlanningResult:
        case = self.catalog.get(case_id)
        plan = self._planner.plan(case)
        record = self._state.lifecycle[case_id]
        if record.state is LifecycleState.DEFINED_NOT_RUN:
            target = (
                LifecycleState.READY
                if plan.status is PlanningStatus.READY
                else LifecycleState.BLOCKED
            )
            record = record.transition(
                target,
                actor_id=actor_id,
                reason=(
                    "schema, compilation, and planning preview passed"
                    if target is LifecycleState.READY
                    else str(plan.blocking_reason)
                ),
            )
            self._replace_lifecycle(record)
        return plan

    def set_active(self, case_id: str, *, actor_id: str, reason: str) -> LockedDevelopmentInputs:
        case = self.catalog.get(case_id)
        if case.environment.value == "REAL":
            raise PermissionError("Real campaign cases remain NOT_AUTHORIZED")
        if case.implementation_status.value != "EXECUTABLE":
            raise ValueError(f"case implementation is {case.implementation_status.value}")
        if case.implementation_milestone in {"WP-34A", "WP-34B"}:
            incomplete = [
                prerequisite
                for prerequisite in case.prerequisites
                if prerequisite not in self._state.lifecycle
                or self._state.lifecycle[prerequisite].state
                not in {LifecycleState.BASELINED, LifecycleState.PROMOTED}
            ]
            if incomplete:
                raise ValueError(
                    "dynamic activation requires passing static baselines: "
                    + ", ".join(sorted(incomplete))
                )
        lifecycle = dict(self._state.lifecycle)
        if self._state.active_case_id and self._state.active_case_id != case_id:
            previous = lifecycle[self._state.active_case_id]
            lifecycle[previous.case_id] = previous.transition(
                LifecycleState.READY,
                actor_id=actor_id,
                reason="operator selected a different active development case",
            )
        record = lifecycle[case_id]
        if record.state is not LifecycleState.ACTIVE_DEVELOPMENT:
            if record.state not in {
                LifecycleState.DEFINED_NOT_RUN,
                LifecycleState.READY,
                LifecycleState.BASELINED,
                LifecycleState.PROMOTED,
                LifecycleState.BLOCKED,
            }:
                raise ValueError(f"case cannot become active from {record.state}")
            record = record.transition(
                LifecycleState.ACTIVE_DEVELOPMENT,
                actor_id=actor_id,
                reason=reason,
            )
            lifecycle[case_id] = record
        lock = LockedDevelopmentInputs.from_case(case)
        self._state = self._state.model_copy(
            update={"active_case_id": case_id, "locked_inputs": lock, "lifecycle": lifecycle}
        )
        self._persist()
        return lock

    def create_child(
        self,
        *,
        child_case_id: str,
        updates: Mapping[str, Any],
    ) -> CampaignCase:
        active = self.active_case
        if "case_id" in updates or "parent_case_sha256" in updates:
            raise ValueError("child identity fields are service-owned")
        candidate = _deep_merge(active.model_dump(mode="python"), updates)
        candidate.update(
            {
                "case_id": child_case_id,
                "parent_case_sha256": active.case_sha256,
            }
        )
        # Full revalidation catches attempts to weaken/contradict constraints.
        child = CampaignCase.model_validate(candidate)
        validate_case_against_policy(child, self.catalog.policy)
        content = json.dumps(
            child.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        path = self.state_directory / "children" / f"{child.case_id}.json"
        _write_bytes_atomic(path, content)
        self.catalog.register(child, manifest_path=path, source_bytes=content)
        lifecycle = {
            **self._state.lifecycle,
            child.case_id: LifecycleRecord(case_id=child.case_id, case_sha256=child.case_sha256),
        }
        self._state = self._state.model_copy(update={"lifecycle": lifecycle})
        self._persist()
        return child

    @property
    def active_case(self) -> CampaignCase:
        if self._state.active_case_id is None:
            raise ValueError("no ACTIVE_DEVELOPMENT case is selected")
        case = self.catalog.get(self._state.active_case_id)
        lock = self._state.locked_inputs
        if lock is None or lock.case_sha256 != case.case_sha256:
            raise ValueError("active case no longer matches its locked identity")
        return case

    def preview_active(
        self,
    ) -> tuple[BoundedPlanningResult, GroundFirstSchedule, SmoothTrajectorySet]:
        case = self.active_case
        plan = self._planner.plan(case)
        if plan.status is not PlanningStatus.READY or plan.selected is None:
            raise ValueError(plan.blocking_reason or "active case planning is blocked")
        schedule = build_ground_first_schedule(case, plan.selected)
        trajectories = generate_smooth_trajectories(case, plan.selected)
        return plan, schedule, trajectories

    async def run_active(
        self,
        mode: CampaignRunMode,
        *,
        idempotency_key: str,
        transient_retry: Callable[[Exception], bool] | None = None,
    ) -> ReviewItem:
        existing = self._state.idempotency.get(idempotency_key)
        if existing is not None:
            review = next((item for item in self._state.reviews if item.run_id == existing), None)
            if review is None:
                raise RuntimeError("idempotent campaign run is still incomplete")
            return review
        if self.executor is None:
            raise RuntimeError(
                "campaign execution requires an explicitly configured Fast Sim executor"
            )
        case = self.active_case
        _assert_mode_eligible(case, mode)
        plan, schedule, trajectories = self.preview_active()
        ordinal = len(self._state.runs) + 1
        lock = self._state.locked_inputs
        assert lock is not None
        run_id = f"campaign-run-{canonical_sha256([lock, mode, ordinal])[:20]}"
        requested = datetime.now(UTC)
        record = CampaignRunRecord(
            run_id=run_id,
            mode=mode,
            status=CampaignRunStatus.QUEUED,
            locked_inputs=lock,
            requested_at_utc=requested,
            plan_sha256=plan.plan_sha256,
            schedule_sha256=schedule.schedule_sha256,
            trajectory_set_sha256=trajectories.set_sha256,
        )
        self._state = self._state.model_copy(
            update={
                "runs": (*self._state.runs, record),
                "idempotency": {**self._state.idempotency, idempotency_key: run_id},
            }
        )
        self._persist()
        async with self._semaphore:
            if run_id in self._cancelled:
                self._update_run(
                    record.model_copy(
                        update={
                            "status": CampaignRunStatus.CANCELLED_BEFORE_LAUNCH,
                            "finished_at_utc": datetime.now(UTC),
                        }
                    )
                )
                raise asyncio.CancelledError(
                    "campaign run cancelled before launch; no authority granted"
                )
            request = CampaignExecutionRequest(
                run_id=run_id,
                mode=mode,
                locked_inputs=lock,
                case=case,
                plan=plan,
                schedule=schedule,
                trajectories=trajectories,
            )
            record = record.model_copy(
                update={"status": CampaignRunStatus.RUNNING, "started_at_utc": datetime.now(UTC)}
            )
            self._update_run(record)
            attempts = 0
            while True:
                try:
                    artifacts = await self.executor(request)
                    break
                except Exception as error:
                    if attempts == 0 and transient_retry is not None and transient_retry(error):
                        attempts += 1
                        continue
                    failed = record.model_copy(
                        update={
                            "status": CampaignRunStatus.FAILED,
                            "finished_at_utc": datetime.now(UTC),
                            "failure_reason": str(error),
                            "automatic_retry_count": attempts,
                        }
                    )
                    self._update_run(failed)
                    raise
            if hashlib.sha256(artifacts.csv_content).hexdigest() != artifacts.csv_bytes_sha256:
                raise ValueError("executor CSV bytes do not match the declared hash")
            review = self._intake(case, record, artifacts, plan)
            return review

    def import_artifacts(
        self,
        *,
        case_id: str,
        manifest_bytes: bytes,
        bundle_bytes: bytes,
        evaluation_bytes: bytes,
        csv_bytes: bytes,
    ) -> ReviewItem:
        """Idempotent byte-preserving historical intake; this method cannot execute a mission."""

        artifact_hash = canonical_sha256(
            [
                hashlib.sha256(value).hexdigest()
                for value in (manifest_bytes, bundle_bytes, evaluation_bytes, csv_bytes)
            ]
        )
        existing = next(
            (item for item in self._state.reviews if item.artifact_set_sha256 == artifact_hash),
            None,
        )
        if existing is not None:
            return existing
        case = self.catalog.get(case_id)
        manifest = json.loads(manifest_bytes)
        bundle = json.loads(bundle_bytes)
        evaluation = json.loads(evaluation_bytes)
        execution_id = str(
            manifest.get("mission_execution_id") or bundle.get("mission_execution_id")
        )
        if not execution_id:
            raise ValueError("historical artifact set has no mission execution ID")
        plan_sha = str(manifest.get("plan_sha256") or bundle.get("plan_sha256") or "0" * 64)
        lock = LockedDevelopmentInputs.from_case(case)
        run_id = f"imported-{artifact_hash[:20]}"
        record = CampaignRunRecord(
            run_id=run_id,
            mode=CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
            status=_run_status(str(manifest.get("status", "FAILED"))),
            locked_inputs=lock,
            requested_at_utc=datetime.now(UTC),
            finished_at_utc=datetime.now(UTC),
            mission_execution_id=execution_id,
            plan_sha256=plan_sha if len(plan_sha) == 64 else "0" * 64,
            schedule_sha256="0" * 64,
            trajectory_set_sha256="0" * 64,
            artifact_set_sha256=artifact_hash,
        )
        artifacts = RunArtifactSet(
            mission_execution_id=execution_id,
            status=str(manifest.get("status", "FAILED")),
            manifest=manifest,
            bundle=bundle,
            evaluation=evaluation,
            csv_bytes_sha256=hashlib.sha256(csv_bytes).hexdigest(),
            csv_content=csv_bytes,
        )
        raw_plan = bundle.get("campaign_plan")
        plan = (
            BoundedPlanningResult.model_validate(raw_plan)
            if raw_plan is not None
            else self._planner.plan(case)
        )
        if plan.status is not PlanningStatus.READY:
            raise ValueError("historical intake requires an analyzable admitted plan")
        self._state = self._state.model_copy(update={"runs": (*self._state.runs, record)})
        return self._intake(
            case,
            record,
            artifacts,
            plan,
            original_bytes=(manifest_bytes, bundle_bytes, evaluation_bytes),
            artifact_hash_override=artifact_hash,
        )

    def cancel(self, run_id: str) -> bool:
        self._cancelled.add(run_id)
        if self.executor is not None:
            request_cancel = getattr(self.executor, "request_cancel", None)
            if callable(request_cancel):
                request_cancel(run_id)
        return any(item.run_id == run_id for item in self._state.runs)

    def add_observation(self, review_id: str, note: str) -> ReviewItem:
        if not note.strip():
            raise ValueError("operator observation cannot be empty")
        review = self._review(review_id)
        updated = _rehash_review(
            review.model_copy(
                update={"operator_observations": (*review.operator_observations, note.strip())}
            )
        )
        self._replace_review(updated)
        return updated

    def decide_review(
        self,
        review_id: str,
        *,
        operator_id: str,
        decision: ReviewDecision,
        reason: str,
        note: str | None = None,
    ) -> ReviewItem:
        review = self._review(review_id)
        if decision is ReviewDecision.APPROVE and review.status is not CampaignRunStatus.SUCCEEDED:
            raise ValueError("failed or aborted evidence cannot be approved as passed")
        timestamp = datetime.now(UTC)
        approval_payload = {
            "operator_id": operator_id,
            "decided_at_utc": timestamp,
            "decision": decision,
            "report_sha256": review.review_sha256,
            "reason": reason,
            "note": note,
        }
        approval = ReviewApproval(
            **approval_payload,
            approval_sha256=canonical_sha256(approval_payload),
        )
        updated = _rehash_review(review.model_copy(update={"approval": approval}))
        self._replace_review(updated)
        if decision is ReviewDecision.APPROVE:
            lifecycle = self._state.lifecycle[review.case_id]
            if lifecycle.state is LifecycleState.ACTIVE_DEVELOPMENT:
                self._replace_lifecycle(
                    lifecycle.transition(
                        LifecycleState.BASELINED,
                        actor_id=operator_id,
                        reason="approved passing campaign review bound as baseline",
                        evidence_sha256=review.artifact_set_sha256,
                        review_sha256=updated.review_sha256,
                    )
                )
        return updated

    def promote_active(self, *, operator_id: str, reason: str) -> LifecycleRecord:
        case = self.active_case
        lifecycle = self._state.lifecycle[case.case_id]
        if lifecycle.state is not LifecycleState.BASELINED:
            raise ValueError("promotion requires a BASELINED active case")
        approved = [
            review
            for review in self._state.reviews
            if review.case_id == case.case_id
            and review.status is CampaignRunStatus.SUCCEEDED
            and review.approval is not None
            and review.approval.decision is ReviewDecision.APPROVE
        ]
        run_by_id = {run.run_id: run for run in self._state.runs}
        modes = {run_by_id[review.run_id].mode for review in approved if review.run_id in run_by_id}
        required = _required_modes(case.execution_eligibility)
        if not required.issubset(modes):
            raise ValueError(
                "promotion is missing required approved execution modes: "
                + ", ".join(sorted(mode.value for mode in required.difference(modes)))
            )
        latest = approved[-1]
        promoted = lifecycle.transition(
            LifecycleState.PROMOTED,
            actor_id=operator_id,
            reason=reason,
            evidence_sha256=latest.artifact_set_sha256,
            review_sha256=latest.review_sha256,
        )
        self._replace_lifecycle(promoted)
        return promoted

    def recommend_next(self) -> NextCaseRecommendation:
        cases = self.catalog.cases()
        records = self._state.lifecycle
        active = self._state.active_case_id
        missing = sorted(
            {
                prerequisite
                for case in cases
                if records[case.case_id].state
                not in {LifecycleState.PROMOTED, LifecycleState.BASELINED}
                for prerequisite in case.prerequisites
                if prerequisite in records
                and records[prerequisite].state is not LifecycleState.PROMOTED
            }
        )
        if missing:
            return _recommend(
                RecommendationRule.MISSING_PREREQUISITE,
                missing,
                "satisfy the first missing prerequisite",
            )
        failed_case_ids = sorted(
            {
                review.case_id
                for review in self._state.reviews
                if review.status in {CampaignRunStatus.ABORTED, CampaignRunStatus.FAILED}
                and (
                    review.approval is None
                    or review.approval.decision is not ReviewDecision.APPROVE
                )
            }
        )
        if failed_case_ids:
            return _recommend(
                RecommendationRule.UNRESOLVED_FAILURE,
                failed_case_ids,
                "rerun the first unresolved failure",
            )
        ready = [
            case
            for case in cases
            if case.case_id != active
            and records[case.case_id].state
            in {LifecycleState.READY, LifecycleState.DEFINED_NOT_RUN}
        ]
        boundary = sorted(
            case.case_id
            for case in ready
            if case.variation_name in {"compact", "constrained_height", "no_hover"}
        )
        if boundary:
            return _recommend(
                RecommendationRule.UNTESTED_HARD_BOUNDARY,
                boundary,
                "cover an untested declared hard boundary",
            )
        if ready:
            minimum = min(case.difficulty for case in ready)
            children = sorted(case.case_id for case in ready if case.difficulty == minimum)
            return _recommend(
                RecommendationRule.LOWEST_DIFFICULTY_CHILD,
                children,
                "select the lowest-difficulty unpassed case",
            )
        return _recommend(
            RecommendationRule.CAMPAIGN_COMPLETE,
            [],
            "all registered cases are baselined, promoted, or blocked",
        )

    def materialize_wp25_matrix(self) -> dict[str, Any]:
        """Materialize the retained 16-cell definition without executing it."""

        return generate_robustness_matrix().model_dump(mode="json")

    def _intake(
        self,
        case: CampaignCase,
        run: CampaignRunRecord,
        artifacts: RunArtifactSet,
        plan: BoundedPlanningResult,
        *,
        original_bytes: tuple[bytes, bytes, bytes] | None = None,
        artifact_hash_override: str | None = None,
    ) -> ReviewItem:
        analysis = analyze_execution(
            case=case,
            manifest=artifacts.manifest,
            bundle=artifacts.bundle,
            csv_bytes=artifacts.csv_content,
        )
        artifact_hash = artifact_hash_override or canonical_sha256(
            [
                canonical_sha256(artifacts.manifest),
                canonical_sha256(artifacts.bundle),
                canonical_sha256(artifacts.evaluation),
                artifacts.csv_bytes_sha256,
            ]
        )
        directory = self.state_directory / "evidence" / artifacts.mission_execution_id
        directory.mkdir(parents=True, exist_ok=True)
        if original_bytes is None:
            original_bytes = (
                json.dumps(
                    artifacts.manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode(),
                json.dumps(
                    artifacts.bundle,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode(),
                json.dumps(
                    artifacts.evaluation,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode(),
            )
        for filename, content in zip(
            ("manifest.json", "execution-bundle.json", "evaluation.json"),
            original_bytes,
            strict=True,
        ):
            _write_bytes_atomic(directory / filename, content)
        _write_bytes_atomic(directory / "telemetry.csv", artifacts.csv_content)
        _write_json_atomic(directory / "analysis.json", analysis.model_dump(mode="json"))
        status = _run_status(artifacts.status)
        finished = run.model_copy(
            update={
                "status": status,
                "finished_at_utc": datetime.now(UTC),
                "mission_execution_id": artifacts.mission_execution_id,
                "artifact_set_sha256": artifact_hash,
                "analysis_sha256": analysis.analysis_sha256,
            }
        )
        self._update_run(finished)
        review_payload: dict[str, Any] = {
            "review_id": f"review-{canonical_sha256([run.run_id, artifact_hash])[:20]}",
            "run_id": run.run_id,
            "case_id": case.case_id,
            "case_sha256": case.case_sha256,
            "status": status,
            "plan_sha256": plan.plan_sha256,
            "artifact_set_sha256": artifact_hash,
            "analysis": analysis,
            "baseline_comparison": self._baseline_comparison(case, analysis),
            "mode_comparison": self._mode_comparison(case, run, analysis),
            "operator_questions": case.operator_observation_questions,
        }
        review = ReviewItem(**review_payload, review_sha256=canonical_sha256(review_payload))
        self._state = self._state.model_copy(update={"reviews": (*self._state.reviews, review)})
        lifecycle = self._state.lifecycle[case.case_id].model_copy(
            update={"run_ids": (*self._state.lifecycle[case.case_id].run_ids, run.run_id)}
        )
        self._replace_lifecycle(lifecycle)
        self._persist()
        return review

    def _mode_comparison(
        self,
        case: CampaignCase,
        run: CampaignRunRecord,
        analysis: MissionAnalysis,
    ) -> ModeComparison | None:
        run_by_id = {item.run_id: item for item in self._state.runs}
        opposite_mode = (
            CampaignRunMode.OPERATOR_OBSERVED_REALTIME
            if run.mode is CampaignRunMode.AUTOMATED_ACCELERATED
            else CampaignRunMode.AUTOMATED_ACCELERATED
        )
        candidates = [
            review
            for review in self._state.reviews
            if review.case_sha256 == case.case_sha256
            and review.status is CampaignRunStatus.SUCCEEDED
            and run_by_id.get(review.run_id) is not None
            and run_by_id[review.run_id].mode is opposite_mode
        ]
        if not candidates:
            return None
        other = candidates[-1].analysis
        accelerated, realtime = (
            (analysis, other)
            if run.mode is CampaignRunMode.AUTOMATED_ACCELERATED
            else (other, analysis)
        )
        return compare_execution_modes(case, accelerated, realtime)

    def _baseline_comparison(
        self, case: CampaignCase, analysis: MissionAnalysis
    ) -> dict[str, float | str | bool | None]:
        if case.baseline_sha256 is None:
            return {"baseline_available": False}
        return {
            "baseline_available": True,
            "baseline_sha256": case.baseline_sha256,
            "minimum_truth_separation_m": analysis.minimum_truth_separation_m,
            "mission_outcome": analysis.mission_outcome,
        }

    def _load_state(self) -> CampaignWorkspaceState:
        path = self.state_directory / "workspace-state.json"
        if path.exists():
            state = CampaignWorkspaceState.model_validate_json(path.read_text(encoding="utf-8"))
            current = {case.case_id: case for case in self.catalog.cases()}
            reconciled: dict[str, LifecycleRecord] = {}
            for case_id, case in current.items():
                record = state.lifecycle.get(case_id)
                if record is None:
                    reconciled[case_id] = LifecycleRecord(
                        case_id=case_id,
                        case_sha256=case.case_sha256,
                    )
                    continue
                if record.case_sha256 == case.case_sha256:
                    reconciled[case_id] = record
                    continue
                self._assert_identity_refresh_is_safe(state, record)
                reconciled[case_id] = LifecycleRecord(
                    case_id=case_id,
                    case_sha256=case.case_sha256,
                )

            for case_id, record in state.lifecycle.items():
                if case_id not in current:
                    self._assert_identity_refresh_is_safe(state, record)

            return state.model_copy(update={"lifecycle": reconciled})
        return CampaignWorkspaceState(
            lifecycle={record.case_id: record for record in self.catalog.initial_lifecycle()}
        )

    @staticmethod
    def _assert_identity_refresh_is_safe(
        state: CampaignWorkspaceState,
        record: LifecycleRecord,
    ) -> None:
        """Fail closed when a changed definition has evidence or operator authority."""

        has_run = bool(record.run_ids) or any(
            run.locked_inputs.case_id == record.case_id for run in state.runs
        )
        has_review = any(review.case_id == record.case_id for review in state.reviews)
        authority_bound = (
            state.active_case_id == record.case_id
            or record.state
            in {
                LifecycleState.ACTIVE_DEVELOPMENT,
                LifecycleState.BASELINED,
                LifecycleState.PROMOTED,
            }
        )
        if has_run or has_review or record.baseline_sha256 is not None or authority_bound:
            raise ValueError(
                "persisted lifecycle identity with evidence or operator authority "
                f"no longer matches case {record.case_id}"
            )

    def _load_children(self) -> None:
        directory = self.state_directory / "children"
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.json")):
            source = path.read_bytes()
            child = CampaignCase.model_validate_json(source)
            self.catalog.register(child, manifest_path=path, source_bytes=source)

    def _reconcile_interrupted_runs(self) -> None:
        runs = tuple(
            item.model_copy(
                update={
                    "status": CampaignRunStatus.FAILED,
                    "finished_at_utc": datetime.now(UTC),
                    "failure_reason": "process interrupted; partial artifacts retained for review",
                }
            )
            if item.status in {CampaignRunStatus.QUEUED, CampaignRunStatus.RUNNING}
            else item
            for item in self._state.runs
        )
        if runs != self._state.runs:
            self._state = self._state.model_copy(update={"runs": runs})
            self._persist()

    def _persist(self) -> None:
        _write_json_atomic(
            self.state_directory / "workspace-state.json",
            self._state.model_dump(mode="json"),
        )

    def _replace_lifecycle(self, record: LifecycleRecord) -> None:
        self._state = self._state.model_copy(
            update={"lifecycle": {**self._state.lifecycle, record.case_id: record}}
        )
        self._persist()

    def _update_run(self, run: CampaignRunRecord) -> None:
        self._state = self._state.model_copy(
            update={
                "runs": tuple(
                    run if item.run_id == run.run_id else item for item in self._state.runs
                )
            }
        )
        self._persist()

    def _review(self, review_id: str) -> ReviewItem:
        try:
            return next(item for item in self._state.reviews if item.review_id == review_id)
        except StopIteration as error:
            raise KeyError(f"unknown review item: {review_id}") from error

    def _replace_review(self, review: ReviewItem) -> None:
        self._state = self._state.model_copy(
            update={
                "reviews": tuple(
                    review if item.review_id == review.review_id else item
                    for item in self._state.reviews
                )
            }
        )
        self._persist()


def _assert_mode_eligible(case: CampaignCase, mode: CampaignRunMode) -> None:
    eligible = case.execution_eligibility
    if eligible is ExecutionEligibility.STATIC_VALIDATE_ONLY:
        raise PermissionError("case is eligible only for static validation")
    if mode is CampaignRunMode.AUTOMATED_ACCELERATED and eligible not in {
        ExecutionEligibility.AUTOMATED_ACCELERATED,
        ExecutionEligibility.BOTH,
    }:
        raise PermissionError("case is not eligible for accelerated execution")
    if mode is CampaignRunMode.OPERATOR_OBSERVED_REALTIME and eligible not in {
        ExecutionEligibility.OPERATOR_OBSERVED_REALTIME,
        ExecutionEligibility.BOTH,
    }:
        raise PermissionError("case is not eligible for operator-observed realtime execution")


def _required_modes(eligibility: ExecutionEligibility) -> frozenset[CampaignRunMode]:
    if eligibility is ExecutionEligibility.BOTH:
        return frozenset(
            {
                CampaignRunMode.AUTOMATED_ACCELERATED,
                CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
            }
        )
    if eligibility is ExecutionEligibility.AUTOMATED_ACCELERATED:
        return frozenset({CampaignRunMode.AUTOMATED_ACCELERATED})
    if eligibility is ExecutionEligibility.OPERATOR_OBSERVED_REALTIME:
        return frozenset({CampaignRunMode.OPERATOR_OBSERVED_REALTIME})
    return frozenset()


def _run_status(value: str) -> CampaignRunStatus:
    upper = value.upper()
    if upper in {"SUCCEEDED", "PASSED"}:
        return CampaignRunStatus.SUCCEEDED
    if upper == "ABORTED":
        return CampaignRunStatus.ABORTED
    return CampaignRunStatus.FAILED


def _rehash_review(review: ReviewItem) -> ReviewItem:
    return review.model_copy(update={"review_sha256": canonical_sha256(review.canonical_payload())})


def _recommend(
    rule: RecommendationRule, candidates: Sequence[str], reason: str
) -> NextCaseRecommendation:
    ordered = tuple(sorted(candidates))
    payload = {
        "rule": rule,
        "candidate_case_ids": ordered,
        "recommended_case_id": ordered[0] if ordered else None,
        "reason": reason,
        "input_sha256": canonical_sha256([rule, ordered]),
    }
    return NextCaseRecommendation(**payload, recommendation_sha256=canonical_sha256(payload))


def _write_json_atomic(path: Path, value: Any) -> None:
    content = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    _write_bytes_atomic(path, content)


def _deep_merge(base: Mapping[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    """Apply child overrides without resetting unspecified nested case fields."""

    merged = dict(base)
    for key, value in updates.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
