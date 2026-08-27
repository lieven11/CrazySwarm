from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

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
    ImplementationStatus,
    LifecycleRecord,
    LifecycleState,
    LockedDevelopmentInputs,
    ReplanningAuthority,
)
from crazyswarm_app.campaign.planner import (
    DEFAULT_LANDING_DURATION_S,
    DEFAULT_TAKEOFF_DURATION_S,
    BoundedJointPlanner,
    BoundedPlanningResult,
    PlanningStatus,
)
from crazyswarm_app.campaign.scheduling import GroundFirstSchedule, build_ground_first_schedule
from crazyswarm_app.campaign.submissions import (
    BASELINE_SUBMISSION_ID,
    CoordinationPreparationRequest,
    ExecutionCapabilityRequest,
    ExecutionProfileKind,
    ExecutionProfileSubmission,
    MotionPreparationRequest,
    PlanningCapabilityRequest,
    ResolvedPlanningPackage,
    bind_execution_capability,
    motion_contract_for_execution_profile,
    planning_submissions_for_case,
    resolve_planning_package,
    resolve_submission,
)
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


class SnapshotAssessmentDisposition(StrEnum):
    VALID = "VALID"
    PARTLY_VALID = "PARTLY_VALID"
    DISPLAY_EFFECT = "DISPLAY_EFFECT"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


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
    resolved_package: ResolvedPlanningPackage
    case: CampaignCase
    plan: BoundedPlanningResult
    schedule: GroundFirstSchedule
    trajectories: SmoothTrajectorySet

    @model_validator(mode="after")
    def exact_artifacts_form_one_authority_chain(self) -> CampaignExecutionRequest:
        package = self.resolved_package
        planning = package.planning_submission
        profile = package.execution_profile
        lock = self.locked_inputs
        if package.case != self.case:
            raise ValueError("execution request case differs from its resolved package")
        expected_lock = (
            lock.case_id == self.case.case_id
            and lock.case_sha256 == self.case.case_sha256
            and lock.submission_id == profile.submission_id
            and lock.submission_sha256 == profile.profile_sha256
            and lock.planning_submission_id == planning.planning_submission_id
            and lock.planning_submission_sha256 == planning.planning_submission_sha256
            and lock.resolved_planning_package_sha256 == package.resolved_package_sha256
            and lock.backend_profile_id == self.case.execution.backend_profile_id
            and lock.configuration_sha256 == package.backend_configuration_sha256
        )
        if not expected_lock:
            raise ValueError("execution request lock differs from its resolved package")
        plan_profile_matches = (
            self.plan.submission_id == profile.submission_id
            and self.plan.submission_sha256 == profile.profile_sha256
        ) or (
            profile.submission_id == BASELINE_SUBMISSION_ID
            and self.plan.submission_id is None
            and self.plan.submission_sha256 is None
        )
        motion_contract = motion_contract_for_execution_profile(self.case, profile)
        if (
            self.plan.case_sha256 != self.case.case_sha256
            or self.plan.motion_quality_contract != motion_contract
            or self.plan.motion_quality_contract_sha256 != canonical_sha256(motion_contract)
            or not plan_profile_matches
            or self.plan.planning_submission_id != planning.planning_submission_id
            or self.plan.planning_submission_sha256 != planning.planning_submission_sha256
        ):
            raise ValueError("execution request plan differs from resolved authority")
        if self.plan.selected is None or self.plan.feasibility_certificate is None:
            raise ValueError("execution request requires an independently certified plan")
        selected = self.plan.selected
        certificate = self.plan.feasibility_certificate
        if (
            self.plan.plan_sha256 != canonical_sha256(self.plan.canonical_payload())
            or selected.candidate_sha256 != canonical_sha256(selected.canonical_payload())
            or certificate.certificate_sha256 != canonical_sha256(certificate.canonical_payload())
            or not certificate.passed
            or certificate.case_sha256 != self.case.case_sha256
            or certificate.planning_submission_id != planning.planning_submission_id
            or certificate.planning_submission_sha256 != planning.planning_submission_sha256
            or certificate.candidate_sha256 != selected.candidate_sha256
        ):
            raise ValueError("execution request plan lacks matching feasibility authority")
        if (
            self.schedule.schedule_sha256 != canonical_sha256(self.schedule.canonical_payload())
            or self.schedule.case_sha256 != self.case.case_sha256
            or self.schedule.candidate_sha256 != selected.candidate_sha256
            or self.schedule.planning_submission_id != planning.planning_submission_id
            or self.schedule.planning_submission_sha256 != planning.planning_submission_sha256
        ):
            raise ValueError("execution request schedule differs from resolved authority")
        trajectory_profile_matches = (
            self.trajectories.submission_id == profile.submission_id
            and self.trajectories.submission_sha256 == profile.profile_sha256
        ) or (
            profile.submission_id == BASELINE_SUBMISSION_ID
            and self.trajectories.submission_id is None
            and self.trajectories.submission_sha256 is None
        )
        if (
            self.trajectories.set_sha256 != canonical_sha256(self.trajectories.canonical_payload())
            or self.trajectories.case_sha256 != self.case.case_sha256
            or self.trajectories.motion_quality_contract != motion_contract
            or self.trajectories.motion_quality_contract_sha256 != canonical_sha256(motion_contract)
            or self.trajectories.candidate_sha256 != selected.candidate_sha256
            or not trajectory_profile_matches
            or self.trajectories.planning_submission_id != planning.planning_submission_id
            or self.trajectories.planning_submission_sha256 != planning.planning_submission_sha256
        ):
            raise ValueError("execution request trajectories differ from resolved authority")
        expected_roles = {item.role_id for item in self.case.drones}
        selected_roles = tuple(item.role_id for item in selected.routes)
        schedule_roles = tuple(item.role_id for item in self.schedule.roles)
        trajectory_roles = tuple(item.role_id for item in self.trajectories.trajectories)
        profile_fallback = self.trajectories.execution_profile_fallback
        fallback_is_bound = (
            profile_fallback == "PLANNER_CANDIDATE_NATIVE_TIMING"
            and profile.kind is ExecutionProfileKind.CORNER_TRANSITION
            and selected.parameters.get("execution_profile_fallback")
            == "planner_candidate_native_timing"
            and not self.trajectories.profile_audits
        )
        if (
            len(selected_roles) != len(expected_roles)
            or len(schedule_roles) != len(expected_roles)
            or len(trajectory_roles) != len(expected_roles)
            or set(selected_roles) != expected_roles
            or set(schedule_roles) != expected_roles
            or set(trajectory_roles) != expected_roles
            or any(not audit.passed for audit in self.trajectories.audits)
            or {audit.trajectory_sha256 for audit in self.trajectories.audits}
            != {trajectory.sha256 for trajectory in self.trajectories.trajectories}
            or (
                profile.submission_id != BASELINE_SUBMISSION_ID
                and not fallback_is_bound
                and (
                    {audit.role_id for audit in self.trajectories.profile_audits} != expected_roles
                    or any(not audit.passed for audit in self.trajectories.profile_audits)
                )
            )
            or (profile_fallback is not None and not fallback_is_bound)
        ):
            raise ValueError("execution request route-role or trajectory audit is incomplete")
        return self


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
    # Planning identities are absent only during the durable QUEUED preparation
    # boundary. They are attached atomically before execution becomes RUNNING.
    plan_sha256: SHA256 | None = None
    schedule_sha256: SHA256 | None = None
    trajectory_set_sha256: SHA256 | None = None
    artifact_set_sha256: SHA256 | None = None
    analysis_sha256: SHA256 | None = None
    failure_reason: str | None = None
    automatic_retry_count: int = Field(default=0, ge=0, le=1)
    superseded_at_utc: datetime | None = None
    superseded_by_revision: Identifier | None = None
    superseded_by_actor: Identifier | None = None
    superseded_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def superseded_identity_is_complete(self) -> CampaignRunRecord:
        boundary = (
            self.superseded_at_utc,
            self.superseded_by_revision,
            self.superseded_by_actor,
            self.superseded_reason,
        )
        if any(value is not None for value in boundary) and not all(
            value is not None for value in boundary
        ):
            raise ValueError("superseded campaign run identity must be complete")
        return self


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
    cross_case_profile_comparison: dict[str, float | str | bool | None] = Field(
        default_factory=dict
    )
    mode_comparison: ModeComparison | None = None
    operator_questions: tuple[str, ...]
    operator_observations: tuple[str, ...] = ()
    twin_session_ids: tuple[Identifier, ...] = ()
    approval: ReviewApproval | None = None
    review_sha256: SHA256

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"review_sha256"})


MAX_CAMPAIGN_SNAPSHOT_BYTES = 1_000_000
MAX_CAMPAIGN_SNAPSHOT_BYTES_PER_CASE = 64_000_000
MAX_CAMPAIGN_SNAPSHOTS_PER_RUN = 60
CAMPAIGN_SNAPSHOT_FINISH_GRACE_S = 5.0


class CampaignReviewSourceRow(ContractModel):
    """One immutable raw telemetry row used to construct a review frame."""

    source_clock_id: Identifier
    source_clock_epoch: int = Field(ge=0)
    source_sequence: int = Field(ge=0)
    source_timestamp_s: float = Field(ge=0.0)
    correlation_id: Identifier


class CampaignReviewFrame(ContractModel):
    """Exact presentation-time context bound to one operator snapshot."""

    schema_version: Literal[1, 2] = 2
    source_timestamp_s: float = Field(ge=0.0)
    source_clock_id: Identifier
    source_clock_epoch: int = Field(ge=0)
    source_sequence: int = Field(ge=0)
    correlation_id: Identifier
    estimate_source_timestamp_s: float = Field(ge=0.0)
    truth_source_timestamp_s: float | None = Field(default=None, ge=0.0)
    desired_source_timestamp_s: float | None = Field(default=None, ge=0.0)
    playback_buffer_age_s: float = Field(ge=0.0)
    interpolation_state: Literal["EXACT", "INTERPOLATED", "FROZEN", "UNAVAILABLE"]
    captured_at_wall_utc: datetime | None = None
    source_rows: tuple[CampaignReviewSourceRow, ...] = Field(default=(), max_length=2)
    same_time_truth_estimate_error_m: float | None = Field(default=None, ge=0.0)
    buffer_induced_estimate_displacement_m: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def source_rows_recover_effective_frame(self) -> CampaignReviewFrame:
        # Empty source_rows is retained only for schema-v1 snapshot compatibility.
        if not self.source_rows:
            return self
        identities = {
            (
                row.source_clock_id,
                row.source_clock_epoch,
                row.source_sequence,
                row.correlation_id,
            )
            for row in self.source_rows
        }
        if len(identities) != len(self.source_rows):
            raise ValueError("review-frame source rows must be unique")
        if not any(
            row.source_sequence == self.source_sequence
            and row.correlation_id == self.correlation_id
            for row in self.source_rows
        ):
            raise ValueError("review-frame legacy identity does not name a source row")
        if any(
            row.source_clock_id != self.source_clock_id
            or row.source_clock_epoch != self.source_clock_epoch
            for row in self.source_rows
        ):
            raise ValueError("review-frame source rows cross a source-clock epoch")
        ordered = tuple(sorted(self.source_rows, key=lambda row: row.source_timestamp_s))
        if not (
            ordered[0].source_timestamp_s - 1e-9
            <= self.source_timestamp_s
            <= ordered[-1].source_timestamp_s + 1e-9
        ):
            raise ValueError("review-frame source rows do not bracket the effective source time")
        if self.interpolation_state == "INTERPOLATED" and (
            len(ordered) != 2
            or ordered[0].source_timestamp_s >= self.source_timestamp_s
            or ordered[1].source_timestamp_s <= self.source_timestamp_s
        ):
            raise ValueError("interpolated review frame requires two strictly bracketing rows")
        if self.interpolation_state == "EXACT" and not any(
            abs(row.source_timestamp_s - self.source_timestamp_s) <= 1e-9 for row in ordered
        ):
            raise ValueError("exact review frame requires an exact source row")
        return self


class CampaignSnapshotRecord(ContractModel):
    snapshot_id: Identifier
    run_id: Identifier
    captured_at_utc: datetime
    content_type: Literal["image/webp", "image/jpeg"]
    filename: str = Field(min_length=1, max_length=160)
    size_bytes: int = Field(ge=1, le=MAX_CAMPAIGN_SNAPSHOT_BYTES)
    sha256: SHA256
    width_px: int = Field(ge=1, le=4096)
    height_px: int = Field(ge=1, le=4096)
    case_id: Identifier | None = None
    case_sha256: SHA256 | None = None
    plan_sha256: SHA256 | None = None
    trajectory_set_sha256: SHA256 | None = None
    review_frame: CampaignReviewFrame | None = None
    operator_comment: str | None = Field(default=None, max_length=2000)
    commented_at_utc: datetime | None = None
    neutral_assessment: str | None = Field(default=None, max_length=4000)
    assessment_disposition: SnapshotAssessmentDisposition | None = None
    assessment_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    assessment_evidence_refs: tuple[str, ...] = ()
    assessed_at_utc: datetime | None = None
    image_available: bool = True
    purged_at_utc: datetime | None = None


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
    historical_lifecycle: tuple[LifecycleRecord, ...] = ()
    runs: tuple[CampaignRunRecord, ...] = ()
    reviews: tuple[ReviewItem, ...] = ()
    snapshots: tuple[CampaignSnapshotRecord, ...] = ()
    idempotency: dict[str, Identifier] = Field(default_factory=dict)


_planning_process_pool: ProcessPoolExecutor | None = None


def _campaign_planning_process_pool() -> ProcessPoolExecutor:
    """Return the single CPU-isolation worker shared by preview and launch planning."""

    global _planning_process_pool
    if _planning_process_pool is None:
        _planning_process_pool = ProcessPoolExecutor(
            max_workers=1,
            mp_context=multiprocessing.get_context("spawn"),
        )
    return _planning_process_pool


def _execution_artifacts_in_worker(
    case: CampaignCase,
    package: ResolvedPlanningPackage,
) -> tuple[BoundedPlanningResult, GroundFirstSchedule, SmoothTrajectorySet]:
    """Build the CPU-heavy immutable planning artifacts in an isolated process."""

    submission = package.execution_profile
    plan = BoundedJointPlanner().plan(
        case,
        submission,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
        first_certified_within_budget=True,
        requested_release_delay_s=(
            package.coordination_preparation.launch_gap_s
            if package.coordination_preparation is not None
            else None
        ),
    )
    if plan.status is not PlanningStatus.READY or plan.selected is None:
        raise ValueError(plan.blocking_reason or "active case planning is blocked")
    vertical_cycle_scale = (
        submission.parameters.duration_scale
        if submission.submission_id
        in {"vertical_cycle.precision_first", "vertical_cycle.minimum_duration"}
        and submission.parameters.duration_scale is not None
        else 1.0
    )
    schedule = build_ground_first_schedule(
        case,
        plan.selected,
        takeoff_duration_s=DEFAULT_TAKEOFF_DURATION_S * vertical_cycle_scale,
        landing_duration_s=DEFAULT_LANDING_DURATION_S * vertical_cycle_scale,
        planning_submission_id=package.planning_submission.planning_submission_id,
        planning_submission_sha256=(package.planning_submission.planning_submission_sha256),
    )
    trajectories = generate_smooth_trajectories(
        case,
        plan.selected,
        submission=submission,
        planning_submission=package.planning_submission,
        capability_resolution=package.capability_resolution,
    )
    return plan, schedule, trajectories


def _preview_artifacts_in_worker(
    case: CampaignCase,
    submission_id: str | None,
    planning_submission_id: str | None,
    comparison_context_id: str | None,
    planning_capability_request: PlanningCapabilityRequest | None,
    execution_capability_request: ExecutionCapabilityRequest | None,
    motion_preparation_request: MotionPreparationRequest | None,
    coordination_preparation_request: CoordinationPreparationRequest | None,
) -> tuple[
    ResolvedPlanningPackage,
    BoundedPlanningResult,
    GroundFirstSchedule,
    SmoothTrajectorySet,
]:
    """Resolve slider inputs and build their preview wholly inside the CPU worker."""

    package = resolve_planning_package(
        case,
        planning_submission_id,
        submission_id,
        comparison_context_id=comparison_context_id,
        planning_capability_request=planning_capability_request,
        execution_capability_request=execution_capability_request,
        motion_preparation_request=motion_preparation_request,
        coordination_preparation_request=coordination_preparation_request,
    )
    plan, schedule, trajectories = _execution_artifacts_in_worker(case, package)
    return package, plan, schedule, trajectories


def _analyze_execution_in_worker(
    case: CampaignCase,
    manifest: Mapping[str, Any],
    bundle: Mapping[str, Any],
    csv_bytes: bytes,
) -> MissionAnalysis:
    """Run terminal evidence analysis without contending with API liveness."""

    return analyze_execution(
        case=case,
        manifest=manifest,
        bundle=bundle,
        csv_bytes=csv_bytes,
    )


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
        # Track execution ownership directly instead of relying on a bare
        # semaphore permit.  A cancelled API task must not be able to orphan a
        # permit and leave every later run permanently QUEUED.
        self._execution_condition = asyncio.Condition()
        self._active_execution_run_ids: set[str] = set()
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

    def mark_runs_old(
        self,
        *,
        case_ids: Sequence[str],
        revision_id: str,
        actor_id: str,
        reason: str,
        marked_at_utc: datetime | None = None,
    ) -> tuple[CampaignRunRecord, ...]:
        """Start a new evidence generation without deleting the earlier journal."""

        selected_case_ids = frozenset(item.strip() for item in case_ids if item.strip())
        if not selected_case_ids:
            raise ValueError("marking runs old requires at least one campaign case")
        unknown = selected_case_ids.difference(case.case_id for case in self.catalog.cases())
        if unknown:
            raise KeyError("unknown campaign cases: " + ", ".join(sorted(unknown)))
        revision = revision_id.strip()
        actor = actor_id.strip()
        explanation = reason.strip()
        if not revision or not actor or not explanation:
            raise ValueError("revision, actor, and reason are required")
        active = tuple(
            run.run_id
            for run in self._state.runs
            if run.locked_inputs.case_id in selected_case_ids
            and run.status in {CampaignRunStatus.QUEUED, CampaignRunStatus.RUNNING}
        )
        if active:
            raise ValueError("active campaign runs cannot be marked old: " + ", ".join(active))

        timestamp = marked_at_utc or datetime.now(UTC)
        changed: list[CampaignRunRecord] = []
        runs: list[CampaignRunRecord] = []
        for run in self._state.runs:
            if (
                run.locked_inputs.case_id not in selected_case_ids
                or run.superseded_at_utc is not None
            ):
                runs.append(run)
                continue
            updated = CampaignRunRecord.model_validate(
                {
                    **run.model_dump(mode="python"),
                    "superseded_at_utc": timestamp,
                    "superseded_by_revision": revision,
                    "superseded_by_actor": actor,
                    "superseded_reason": explanation,
                }
            )
            runs.append(updated)
            changed.append(updated)
        if changed:
            self._state = self._state.model_copy(update={"runs": tuple(runs)})
            self._persist()
        return tuple(changed)

    def static_validate(
        self, case_id: str, *, actor_id: str = "campaign-validator"
    ) -> BoundedPlanningResult:
        case = self.catalog.get(case_id)
        planning_submissions = planning_submissions_for_case(case)
        environment = case.semantics.environment_constraints if case.semantics else None
        if environment is not None and environment.keep_out_regions:
            planning_submissions = tuple(reversed(planning_submissions))
        attempted_plans: list[BoundedPlanningResult] = []
        for planning_submission in planning_submissions:
            attempted_plans.append(
                self._planner.plan(case, planning_submission=planning_submission)
            )
            if attempted_plans[-1].status is PlanningStatus.READY:
                break
        plan = attempted_plans[-1]
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
        if any(
            run.status in {CampaignRunStatus.QUEUED, CampaignRunStatus.RUNNING}
            for run in self._state.runs
        ):
            raise ValueError("stop the active campaign run before selecting another mission")
        if case.environment.value == "REAL":
            raise PermissionError("Real campaign cases remain NOT_AUTHORIZED")
        # Catalog selection is operator intent, not an execution qualification gate.
        # Planning and every hard safety check still run before command authority is
        # granted, but they must not make a discovered simulation mission impossible
        # to select in the first place.
        lock = LockedDevelopmentInputs.from_case(case)
        self._state = self._state.model_copy(
            update={"active_case_id": case_id, "locked_inputs": lock}
        )
        self._persist()
        return lock

    def move_to_review(self, case_id: str, *, actor_id: str, reason: str) -> LifecycleRecord:
        """Move one development case into review without affecting sibling cases."""

        case = self.catalog.get(case_id)
        record = self._state.lifecycle[case_id]
        if record.state is LifecycleState.BASELINED:
            return record
        current_run_ids = {
            run.run_id
            for run in self._state.runs
            if run.superseded_at_utc is None
        }
        reviews = [
            item
            for item in self._state.reviews
            if item.run_id in current_run_ids
            and item.case_id == case_id
            and item.case_sha256 == case.case_sha256
        ]
        if not reviews:
            raise ValueError("moving to review requires at least one recorded run")
        self._assert_snapshot_assessments_complete(case_id)
        latest = reviews[-1]
        reviewed = record.transition(
            LifecycleState.BASELINED,
            actor_id=actor_id,
            reason=reason,
            evidence_sha256=latest.artifact_set_sha256,
            review_sha256=latest.review_sha256,
        )
        # Lifecycle records describe the qualification history; they do not revoke the
        # operator's current mission selection. Keeping the active case bound lets an
        # operator rerun a reviewed case from the mission panel without reopening it.
        self._state = self._state.model_copy(
            update={"lifecycle": {**self._state.lifecycle, case_id: reviewed}}
        )
        self._persist()
        self.purge_case_snapshot_images(case_id)
        return reviewed

    def complete_case(self, case_id: str, *, actor_id: str, reason: str) -> LifecycleRecord:
        """Complete a reviewed case through an explicit operator decision."""

        case = self.catalog.get(case_id)
        record = self._state.lifecycle[case_id]
        if record.state is LifecycleState.PROMOTED:
            return record
        current_run_ids = {
            run.run_id
            for run in self._state.runs
            if run.superseded_at_utc is None
        }
        succeeded = [
            item
            for item in self._state.reviews
            if item.run_id in current_run_ids
            and item.case_id == case_id
            and item.case_sha256 == case.case_sha256
            and item.status is CampaignRunStatus.SUCCEEDED
        ]
        if not succeeded:
            raise ValueError("completion requires at least one successful recorded run")
        self._assert_snapshot_assessments_complete(case_id)
        latest = succeeded[-1]
        completed = record.transition(
            LifecycleState.PROMOTED,
            actor_id=actor_id,
            reason=reason,
            evidence_sha256=latest.artifact_set_sha256,
            review_sha256=latest.review_sha256,
        )
        # Completion is durable evidence, not an instruction to remove a runnable
        # simulation mission from the operator's current selection.
        self._state = self._state.model_copy(
            update={"lifecycle": {**self._state.lifecycle, case_id: completed}}
        )
        self._persist()
        self.purge_case_snapshot_images(case_id)
        return completed

    def set_lifecycle_state(
        self,
        case_id: str,
        state: LifecycleState,
        *,
        actor_id: str,
        reason: str,
    ) -> LifecycleRecord:
        """Apply an explicit operator lifecycle choice from any current state."""

        case = self.catalog.get(case_id)
        current = self._state.lifecycle[case_id]
        if current.state is state:
            return current
        current_run_ids = {
            run.run_id
            for run in self._state.runs
            if run.superseded_at_utc is None
        }
        matching_reviews = [
            review
            for review in self._state.reviews
            if review.run_id in current_run_ids
            and review.case_id == case_id
            and review.case_sha256 == case.case_sha256
        ]
        latest = matching_reviews[-1] if matching_reviews else None
        changed = current.transition(
            state,
            actor_id=actor_id,
            reason=reason,
            evidence_sha256=(latest.artifact_set_sha256 if latest is not None else None),
            review_sha256=(latest.review_sha256 if latest is not None else None),
            require_qualification_evidence=False,
        )
        # The lifecycle picker must not make a selected executable mission disappear
        # from the mission panel. Run-time eligibility is checked separately when
        # previewing and launching it.
        self._state = self._state.model_copy(
            update={"lifecycle": {**self._state.lifecycle, case_id: changed}}
        )
        self._persist()
        return changed

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
        semantics = candidate.get("semantics")
        if isinstance(semantics, Mapping):
            candidate["semantics"] = {
                **semantics,
                "semantic_baseline_case_id": active.case_id,
                "intended_delta": (
                    "Child case overrides compiler-consumed fields: "
                    + ", ".join(sorted(str(key) for key in updates))
                    + "."
                ),
            }
        # Full revalidation catches attempts to weaken/contradict constraints.
        child = CampaignCase.model_validate(candidate)
        _assert_child_safety_is_monotone(active, child)
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
            raise ValueError("no campaign case is selected")
        case = self.catalog.get(self._state.active_case_id)
        lock = self._state.locked_inputs
        if lock is None or lock.case_sha256 != case.case_sha256:
            raise ValueError("active case no longer matches its locked identity")
        return case

    def preview_active(
        self,
        submission_id: str | None = None,
        planning_submission_id: str | None = None,
        *,
        comparison_context_id: str | None = None,
        planning_capability_request: PlanningCapabilityRequest | None = None,
        execution_capability_request: ExecutionCapabilityRequest | None = None,
        motion_preparation_request: MotionPreparationRequest | None = None,
        coordination_preparation_request: CoordinationPreparationRequest | None = None,
    ) -> tuple[BoundedPlanningResult, GroundFirstSchedule, SmoothTrajectorySet]:
        case = self.active_case
        _, plan, schedule, trajectories = _preview_artifacts_in_worker(
            case,
            submission_id,
            planning_submission_id,
            comparison_context_id,
            planning_capability_request,
            execution_capability_request,
            motion_preparation_request,
            coordination_preparation_request,
        )
        return plan, schedule, trajectories

    async def preview_active_off_loop(
        self,
        submission_id: str | None = None,
        planning_submission_id: str | None = None,
        *,
        comparison_context_id: str | None = None,
        planning_capability_request: PlanningCapabilityRequest | None = None,
        execution_capability_request: ExecutionCapabilityRequest | None = None,
        motion_preparation_request: MotionPreparationRequest | None = None,
        coordination_preparation_request: CoordinationPreparationRequest | None = None,
    ) -> tuple[
        ResolvedPlanningPackage,
        BoundedPlanningResult,
        GroundFirstSchedule,
        SmoothTrajectorySet,
    ]:
        case = self.active_case
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _campaign_planning_process_pool(),
            _preview_artifacts_in_worker,
            case,
            submission_id,
            planning_submission_id,
            comparison_context_id,
            planning_capability_request,
            execution_capability_request,
            motion_preparation_request,
            coordination_preparation_request,
        )

    def _execution_artifacts_for_package(
        self,
        case: CampaignCase,
        package: ResolvedPlanningPackage,
    ) -> tuple[BoundedPlanningResult, GroundFirstSchedule, SmoothTrajectorySet]:
        """Resolve the CPU-bound plan, schedule, and trajectories for one package."""

        return _execution_artifacts_in_worker(case, package)

    async def _execution_artifacts_for_package_off_loop(
        self,
        case: CampaignCase,
        package: ResolvedPlanningPackage,
    ) -> tuple[BoundedPlanningResult, GroundFirstSchedule, SmoothTrajectorySet]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _campaign_planning_process_pool(),
            _execution_artifacts_in_worker,
            case,
            package,
        )

    async def _analyze_execution_off_loop(
        self,
        case: CampaignCase,
        artifacts: RunArtifactSet,
    ) -> MissionAnalysis:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _campaign_planning_process_pool(),
            _analyze_execution_in_worker,
            case,
            artifacts.manifest,
            artifacts.bundle,
            artifacts.csv_content,
        )

    def resolved_active_package(
        self,
        submission_id: str | None = None,
        planning_submission_id: str | None = None,
        *,
        comparison_context_id: str | None = None,
        planning_capability_request: PlanningCapabilityRequest | None = None,
        execution_capability_request: ExecutionCapabilityRequest | None = None,
        motion_preparation_request: MotionPreparationRequest | None = None,
        coordination_preparation_request: CoordinationPreparationRequest | None = None,
    ) -> ResolvedPlanningPackage:
        return resolve_planning_package(
            self.active_case,
            planning_submission_id,
            submission_id,
            comparison_context_id=comparison_context_id,
            planning_capability_request=planning_capability_request,
            execution_capability_request=execution_capability_request,
            motion_preparation_request=motion_preparation_request,
            coordination_preparation_request=coordination_preparation_request,
        )

    def missing_submission_prerequisites(
        self,
        case: CampaignCase,
        submission: ExecutionProfileSubmission,
    ) -> tuple[str, ...]:
        missing = []
        for prerequisite in submission.prerequisite_submission_ids:
            if ":" in prerequisite:
                prerequisite_case_id, prerequisite_submission_id = prerequisite.split(":", 1)
            else:
                prerequisite_case_id = case.case_id
                prerequisite_submission_id = prerequisite
            satisfied = any(
                self._run_has_qualified_submission_evidence(run)
                and run.locked_inputs.case_id == prerequisite_case_id
                and run.locked_inputs.submission_id == prerequisite_submission_id
                for run in self._state.runs
            )
            if not satisfied:
                missing.append(prerequisite)
        return tuple(sorted(missing))

    def _run_has_qualified_submission_evidence(self, run: CampaignRunRecord) -> bool:
        if (
            run.superseded_at_utc is not None
            or run.status is not CampaignRunStatus.SUCCEEDED
            or run.mission_execution_id is None
        ):
            return False
        review = next(
            (
                item
                for item in self._state.reviews
                if item.run_id == run.run_id
                and item.status is CampaignRunStatus.SUCCEEDED
                and item.analysis.evidence_complete
                and item.analysis.all_required_behavior_oracles_passed
            ),
            None,
        )
        if review is None:
            return False
        evaluation_path = (
            self.state_directory / "evidence" / run.mission_execution_id / "evaluation.json"
        )
        try:
            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        evidence = evaluation.get("evidence")
        if evaluation.get("status") != "COMPLETE" or not isinstance(evidence, dict):
            return False
        if evidence.get("complete") is not True:
            return False
        vehicles = evaluation.get("vehicles")
        if not isinstance(vehicles, list) or not vehicles:
            return False
        if any(vehicle.get("accepted_plan_identity_match") is False for vehicle in vehicles):
            return False
        return not (
            run.locked_inputs.submission_id != BASELINE_SUBMISSION_ID
            and any(
                vehicle.get("planned_profile_conformance_passed") is not True
                for vehicle in vehicles
            )
        )

    async def run_active(
        self,
        mode: CampaignRunMode,
        *,
        idempotency_key: str,
        submission_id: str | None = None,
        planning_submission_id: str | None = None,
        comparison_context_id: str | None = None,
        planning_capability_request: PlanningCapabilityRequest | None = None,
        execution_capability_request: ExecutionCapabilityRequest | None = None,
        motion_preparation_request: MotionPreparationRequest | None = None,
        coordination_preparation_request: CoordinationPreparationRequest | None = None,
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
        package = self.resolved_active_package(
            submission_id,
            planning_submission_id,
            comparison_context_id=comparison_context_id,
            planning_capability_request=planning_capability_request,
            execution_capability_request=execution_capability_request,
            motion_preparation_request=motion_preparation_request,
            coordination_preparation_request=coordination_preparation_request,
        )
        submission = package.execution_profile
        missing_prerequisites = self.missing_submission_prerequisites(case, submission)
        if missing_prerequisites:
            raise ValueError(
                f"submission {submission.submission_id} requires successful evidence for: "
                + ", ".join(missing_prerequisites)
            )
        lock = LockedDevelopmentInputs.from_case(
            case,
            submission_id=submission.submission_id,
            submission_sha256=submission.profile_sha256,
            planning_submission_id=package.planning_submission.planning_submission_id,
            planning_submission_sha256=(package.planning_submission.planning_submission_sha256),
            resolved_planning_package_sha256=package.resolved_package_sha256,
        )
        requested = datetime.now(UTC)
        run_id = f"campaign-run-{canonical_sha256([lock, mode, idempotency_key, requested])[:20]}"
        record = CampaignRunRecord(
            run_id=run_id,
            mode=mode,
            status=CampaignRunStatus.QUEUED,
            locked_inputs=lock,
            requested_at_utc=requested,
        )
        self._state = self._state.model_copy(
            update={
                "runs": (*self._state.runs, record),
                "idempotency": {**self._state.idempotency, idempotency_key: run_id},
            }
        )
        self._persist()
        try:
            # Planning can take several seconds for bounded route/smoothness cases.
            # The QUEUED identity above is already durable, so keep that CPU work off
            # the API loop while health, state polling, and telemetry remain live.
            plan, schedule, trajectories = await self._execution_artifacts_for_package_off_loop(
                case,
                package,
            )
            current = next(item for item in self._state.runs if item.run_id == run_id)
            if current.status is not CampaignRunStatus.QUEUED or run_id in self._cancelled:
                raise asyncio.CancelledError(
                    "campaign run cancelled during planning; no authority granted"
                )
            record = record.model_copy(
                update={
                    "plan_sha256": plan.plan_sha256,
                    "schedule_sha256": schedule.schedule_sha256,
                    "trajectory_set_sha256": trajectories.set_sha256,
                }
            )
            self._update_run(record)
            await self._acquire_execution_slot(run_id)
        except asyncio.CancelledError:
            current = next(item for item in self._state.runs if item.run_id == run_id)
            if current.status is CampaignRunStatus.QUEUED:
                self._update_run(
                    current.model_copy(
                        update={
                            "status": CampaignRunStatus.CANCELLED_BEFORE_LAUNCH,
                            "finished_at_utc": datetime.now(UTC),
                            "failure_reason": "campaign launch task was cancelled before execution",
                        }
                    )
                )
            raise
        except Exception as error:
            current = next(item for item in self._state.runs if item.run_id == run_id)
            if current.status is CampaignRunStatus.QUEUED:
                self._update_run(
                    current.model_copy(
                        update={
                            "status": CampaignRunStatus.FAILED,
                            "finished_at_utc": datetime.now(UTC),
                            "failure_reason": str(error),
                        }
                    )
                )
            raise
        try:
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
                resolved_package=package,
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
            analysis = await self._analyze_execution_off_loop(case, artifacts)
            await self._persist_intake_artifacts_off_loop(
                artifacts,
                analysis,
            )
            review = await asyncio.to_thread(
                self._intake,
                case,
                record,
                artifacts,
                plan,
                execution_profile=package.execution_profile,
                analysis_override=analysis,
                artifacts_already_persisted=True,
            )
            return review
        except asyncio.CancelledError:
            current = next(item for item in self._state.runs if item.run_id == run_id)
            if current.status in {CampaignRunStatus.QUEUED, CampaignRunStatus.RUNNING}:
                cancelled_before_launch = current.status is CampaignRunStatus.QUEUED
                self._update_run(
                    current.model_copy(
                        update={
                            "status": (
                                CampaignRunStatus.CANCELLED_BEFORE_LAUNCH
                                if cancelled_before_launch
                                else CampaignRunStatus.FAILED
                            ),
                            "finished_at_utc": datetime.now(UTC),
                            "failure_reason": (
                                "campaign launch task was cancelled before execution"
                                if cancelled_before_launch
                                else "campaign execution task was cancelled; partial artifacts "
                                "retained for review"
                            ),
                        }
                    )
                )
            raise
        except Exception as error:
            current = next(item for item in self._state.runs if item.run_id == run_id)
            if current.status in {CampaignRunStatus.QUEUED, CampaignRunStatus.RUNNING}:
                self._update_run(
                    current.model_copy(
                        update={
                            "status": CampaignRunStatus.FAILED,
                            "finished_at_utc": datetime.now(UTC),
                            "failure_reason": str(error),
                        }
                    )
                )
            raise
        finally:
            await self._release_execution_slot(run_id)

    async def _acquire_execution_slot(self, run_id: str) -> None:
        async with self._execution_condition:
            await self._execution_condition.wait_for(
                lambda: len(self._active_execution_run_ids) < self.maximum_concurrency
            )
            self._active_execution_run_ids.add(run_id)

    async def _release_execution_slot(self, run_id: str) -> None:
        async with self._execution_condition:
            self._active_execution_run_ids.discard(run_id)
            self._execution_condition.notify_all()

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
        queued = next(
            (
                item
                for item in self._state.runs
                if item.run_id == run_id and item.status is CampaignRunStatus.QUEUED
            ),
            None,
        )
        if queued is not None:
            self._update_run(
                queued.model_copy(
                    update={
                        "status": CampaignRunStatus.CANCELLED_BEFORE_LAUNCH,
                        "finished_at_utc": datetime.now(UTC),
                    }
                )
            )
        if self.executor is not None:
            request_cancel = getattr(self.executor, "request_cancel", None)
            if callable(request_cancel):
                request_cancel(run_id)
        return any(item.run_id == run_id for item in self._state.runs)

    def validate_run_deletion(self, run_id: str) -> CampaignRunRecord:
        try:
            run = next(item for item in self._state.runs if item.run_id == run_id)
        except StopIteration as error:
            raise KeyError(f"unknown campaign run: {run_id}") from error
        if run.status in {CampaignRunStatus.QUEUED, CampaignRunStatus.RUNNING}:
            raise ValueError("an active campaign run cannot be deleted")
        review = next((item for item in self._state.reviews if item.run_id == run_id), None)
        lifecycle, _ = self._lifecycle_for_run(run)
        if review is not None and (
            review.approval is not None or lifecycle.baseline_sha256 == review.artifact_set_sha256
        ):
            raise PermissionError("approved campaign baseline evidence cannot be deleted")
        return run

    def delete_run(self, run_id: str) -> CampaignRunRecord:
        """Delete one non-authoritative completed run and its campaign evidence cache."""

        run = self.validate_run_deletion(run_id)
        lifecycle, historical = self._lifecycle_for_run(run)
        lifecycle = lifecycle.model_copy(
            update={
                "run_ids": tuple(
                    persisted_run_id
                    for persisted_run_id in lifecycle.run_ids
                    if persisted_run_id != run_id
                )
            }
        )
        lifecycle_update = self._state.lifecycle
        historical_update = self._state.historical_lifecycle
        if historical:
            historical_update = tuple(
                lifecycle
                if item.case_id == lifecycle.case_id and item.case_sha256 == lifecycle.case_sha256
                else item
                for item in historical_update
            )
        else:
            lifecycle_update = {
                **self._state.lifecycle,
                lifecycle.case_id: lifecycle,
            }
        self._cancelled.discard(run_id)
        self._state = self._state.model_copy(
            update={
                "runs": tuple(item for item in self._state.runs if item.run_id != run_id),
                "reviews": tuple(item for item in self._state.reviews if item.run_id != run_id),
                "snapshots": tuple(item for item in self._state.snapshots if item.run_id != run_id),
                "idempotency": {
                    key: persisted_run_id
                    for key, persisted_run_id in self._state.idempotency.items()
                    if persisted_run_id != run_id
                },
                "lifecycle": lifecycle_update,
                "historical_lifecycle": historical_update,
            }
        )
        if run.mission_execution_id is not None:
            cached_evidence = self.state_directory / "evidence" / run.mission_execution_id
            if cached_evidence.is_dir():
                shutil.rmtree(cached_evidence)
        snapshot_directory = self.state_directory / "snapshots" / run_id
        if snapshot_directory.is_dir():
            shutil.rmtree(snapshot_directory)
        self._persist()
        return run

    def _lifecycle_for_run(
        self,
        run: CampaignRunRecord,
    ) -> tuple[LifecycleRecord, bool]:
        current = self._state.lifecycle.get(run.locked_inputs.case_id)
        if current is not None and current.case_sha256 == run.locked_inputs.case_sha256:
            return current, False
        for record in self._state.historical_lifecycle:
            if (
                record.case_id == run.locked_inputs.case_id
                and record.case_sha256 == run.locked_inputs.case_sha256
            ):
                return record, True
        raise ValueError("campaign run lifecycle identity is unavailable")

    def add_snapshot(
        self,
        run_id: str,
        *,
        content: bytes,
        content_type: str,
        width_px: int,
        height_px: int,
        review_frame: CampaignReviewFrame | None = None,
        captured_at_utc: datetime | None = None,
    ) -> CampaignSnapshotRecord:
        try:
            run = next(item for item in self._state.runs if item.run_id == run_id)
        except StopIteration as error:
            raise KeyError(f"unknown campaign run: {run_id}") from error
        now = datetime.now(UTC)
        finish_elapsed_s = (
            (now - run.finished_at_utc).total_seconds() if run.finished_at_utc is not None else None
        )
        within_finish_grace = (
            run.status
            in {
                CampaignRunStatus.SUCCEEDED,
                CampaignRunStatus.ABORTED,
                CampaignRunStatus.FAILED,
            }
            and finish_elapsed_s is not None
            and 0.0 <= finish_elapsed_s <= CAMPAIGN_SNAPSHOT_FINISH_GRACE_S
        )
        if run.status is not CampaignRunStatus.RUNNING and not within_finish_grace:
            raise ValueError("scene snapshots can only be captured while a run is running")
        if content_type not in {"image/webp", "image/jpeg"}:
            raise ValueError("campaign snapshots must be WebP or JPEG images")
        if not 0 < len(content) <= MAX_CAMPAIGN_SNAPSHOT_BYTES:
            raise ValueError(
                f"campaign snapshots must be at most {MAX_CAMPAIGN_SNAPSHOT_BYTES} bytes"
            )
        if not 1 <= width_px <= 4096 or not 1 <= height_px <= 4096:
            raise ValueError("campaign snapshot dimensions must be within 1..4096 pixels")
        if content_type == "image/webp" and not (
            content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        ):
            raise ValueError("campaign snapshot bytes are not a WebP image")
        if content_type == "image/jpeg" and not content.startswith(b"\xff\xd8\xff"):
            raise ValueError("campaign snapshot bytes are not a JPEG image")
        existing_count = sum(snapshot.run_id == run_id for snapshot in self._state.snapshots)
        if existing_count >= MAX_CAMPAIGN_SNAPSHOTS_PER_RUN:
            raise ValueError(
                f"a campaign run can retain at most {MAX_CAMPAIGN_SNAPSHOTS_PER_RUN} snapshots"
            )
        case_run_ids = {
            item.run_id
            for item in self._state.runs
            if item.superseded_at_utc is None
            and item.locked_inputs.case_id == run.locked_inputs.case_id
            and item.locked_inputs.case_sha256 == run.locked_inputs.case_sha256
        }
        retained_case_bytes = sum(
            snapshot.size_bytes
            for snapshot in self._state.snapshots
            if snapshot.run_id in case_run_ids and snapshot.image_available
        )
        if retained_case_bytes + len(content) > MAX_CAMPAIGN_SNAPSHOT_BYTES_PER_CASE:
            raise ValueError("campaign snapshot storage reached its 64 MB active-review limit")

        timestamp = captured_at_utc or now
        if review_frame is not None and review_frame.captured_at_wall_utc is None:
            review_frame = review_frame.model_copy(update={"captured_at_wall_utc": timestamp})
        content_sha256 = hashlib.sha256(content).hexdigest()
        snapshot_id = (
            f"snapshot-{canonical_sha256([run_id, timestamp, content_sha256, review_frame])[:20]}"
        )
        extension = "webp" if content_type == "image/webp" else "jpg"
        filename = f"{snapshot_id}.{extension}"
        _write_bytes_atomic(
            self.state_directory / "snapshots" / run_id / filename,
            content,
        )
        snapshot = CampaignSnapshotRecord(
            snapshot_id=snapshot_id,
            run_id=run_id,
            captured_at_utc=timestamp,
            content_type=content_type,
            filename=filename,
            size_bytes=len(content),
            sha256=content_sha256,
            width_px=width_px,
            height_px=height_px,
            case_id=run.locked_inputs.case_id,
            case_sha256=run.locked_inputs.case_sha256,
            plan_sha256=run.plan_sha256,
            trajectory_set_sha256=run.trajectory_set_sha256,
            review_frame=review_frame,
        )
        self._state = self._state.model_copy(
            update={"snapshots": (*self._state.snapshots, snapshot)}
        )
        self._persist()
        return snapshot

    def set_snapshot_comment(self, snapshot_id: str, note: str) -> CampaignSnapshotRecord:
        if not note.strip():
            raise ValueError("snapshot comment cannot be empty")
        snapshot = self._snapshot(snapshot_id)
        updated = snapshot.model_copy(
            update={
                # Whitespace is part of an operator's attributable statement. Use
                # strip only for the empty-input check above, never for persistence.
                "operator_comment": note,
                "commented_at_utc": datetime.now(UTC),
            }
        )
        self._replace_snapshot(updated)
        return updated

    def set_snapshot_assessment(
        self,
        snapshot_id: str,
        *,
        assessment: str,
        disposition: SnapshotAssessmentDisposition,
        confidence: float,
        evidence_refs: Sequence[str] = (),
    ) -> CampaignSnapshotRecord:
        if not assessment.strip():
            raise ValueError("snapshot neutral assessment cannot be empty")
        normalized_refs = tuple(sorted({item.strip() for item in evidence_refs if item.strip()}))
        snapshot = self._snapshot(snapshot_id)
        updated = snapshot.model_copy(
            update={
                "neutral_assessment": assessment.strip(),
                "assessment_disposition": disposition,
                "assessment_confidence": confidence,
                "assessment_evidence_refs": normalized_refs,
                "assessed_at_utc": datetime.now(UTC),
            }
        )
        self._replace_snapshot(updated)
        return updated

    def snapshot_image_path(self, snapshot_id: str) -> tuple[Path, CampaignSnapshotRecord]:
        snapshot = self._snapshot(snapshot_id)
        if not snapshot.image_available:
            raise FileNotFoundError("campaign snapshot image has been purged")
        path = self.state_directory / "snapshots" / snapshot.run_id / snapshot.filename
        if not path.is_file():
            raise FileNotFoundError("campaign snapshot image is missing")
        return path, snapshot

    def purge_case_snapshot_images(self, case_id: str) -> int:
        self._assert_snapshot_assessments_complete(case_id)
        case_sha256 = self.catalog.get(case_id).case_sha256
        run_ids = {
            run.run_id
            for run in self._state.runs
            if run.superseded_at_utc is None
            and run.locked_inputs.case_id == case_id
            and run.locked_inputs.case_sha256 == case_sha256
        }
        timestamp = datetime.now(UTC)
        purged = 0
        snapshots: list[CampaignSnapshotRecord] = []
        for snapshot in self._state.snapshots:
            if snapshot.run_id not in run_ids or not snapshot.image_available:
                snapshots.append(snapshot)
                continue
            snapshots.append(
                snapshot.model_copy(update={"image_available": False, "purged_at_utc": timestamp})
            )
            purged += 1
        if not purged:
            return 0
        for run_id in run_ids:
            directory = self.state_directory / "snapshots" / run_id
            if directory.is_dir():
                shutil.rmtree(directory)
        self._state = self._state.model_copy(update={"snapshots": tuple(snapshots)})
        self._persist()
        return purged

    def _assert_snapshot_assessments_complete(self, case_id: str) -> None:
        case_sha256 = self.catalog.get(case_id).case_sha256
        run_ids = {
            run.run_id
            for run in self._state.runs
            if run.superseded_at_utc is None
            and run.locked_inputs.case_id == case_id
            and run.locked_inputs.case_sha256 == case_sha256
        }
        unassessed = tuple(
            snapshot.snapshot_id
            for snapshot in self._state.snapshots
            if snapshot.run_id in run_ids
            and snapshot.image_available
            and (
                snapshot.neutral_assessment is None
                or snapshot.assessment_disposition is None
                or snapshot.assessed_at_utc is None
            )
        )
        if unassessed:
            raise ValueError(
                "neutral snapshot assessment is required before image purge: "
                + ", ".join(unassessed)
            )

    def add_observation(
        self,
        review_id: str,
        note: str,
        *,
        actor_id: str = "campaign-review-comment",
    ) -> ReviewItem:
        if not note.strip():
            raise ValueError("operator observation cannot be empty")
        review = self._review(review_id)
        updated = _rehash_review(
            review.model_copy(
                update={"operator_observations": (*review.operator_observations, note.strip())}
            )
        )
        self._replace_review(updated)
        lifecycle = self._state.lifecycle[review.case_id]
        if (
            lifecycle.case_sha256 == review.case_sha256
            and lifecycle.state is LifecycleState.ACTIVE_DEVELOPMENT
        ):
            self._assert_snapshot_assessments_complete(review.case_id)
            reviewed = lifecycle.transition(
                LifecycleState.BASELINED,
                actor_id=actor_id,
                reason="operator comment opened the campaign evidence review",
                evidence_sha256=review.artifact_set_sha256,
                review_sha256=updated.review_sha256,
            )
            self._state = self._state.model_copy(
                update={"lifecycle": {**self._state.lifecycle, review.case_id: reviewed}}
            )
            self._persist()
            self.purge_case_snapshot_images(review.case_id)
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
        if decision is ReviewDecision.APPROVE:
            lifecycle = self._state.lifecycle[review.case_id]
            if (
                lifecycle.case_sha256 == review.case_sha256
                and lifecycle.state is LifecycleState.ACTIVE_DEVELOPMENT
            ):
                self._assert_snapshot_assessments_complete(review.case_id)
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
        moved_to_review = False
        if decision is ReviewDecision.APPROVE:
            lifecycle = self._state.lifecycle[review.case_id]
            if (
                lifecycle.case_sha256 == review.case_sha256
                and lifecycle.state is LifecycleState.ACTIVE_DEVELOPMENT
            ):
                self._replace_lifecycle(
                    lifecycle.transition(
                        LifecycleState.BASELINED,
                        actor_id=operator_id,
                        reason="approved passing campaign review bound as baseline",
                        evidence_sha256=review.artifact_set_sha256,
                        review_sha256=updated.review_sha256,
                    )
                )
                moved_to_review = True
        if moved_to_review:
            self.purge_case_snapshot_images(review.case_id)
        return updated

    def promote_active(self, *, operator_id: str, reason: str) -> LifecycleRecord:
        case = self.active_case
        incomplete_prerequisites = [
            prerequisite
            for prerequisite in case.prerequisites
            if prerequisite not in self._state.lifecycle
            or self._state.lifecycle[prerequisite].state is not LifecycleState.PROMOTED
        ]
        if incomplete_prerequisites and case.case_id != "three_drone_multi_conflict":
            raise ValueError(
                "promotion requires promoted prerequisites: "
                + ", ".join(sorted(incomplete_prerequisites))
            )
        lifecycle = self._state.lifecycle[case.case_id]
        if lifecycle.state is not LifecycleState.BASELINED:
            raise ValueError("promotion requires a BASELINED active case")
        run_by_id = {
            run.run_id: run
            for run in self._state.runs
            if run.superseded_at_utc is None
        }
        approved = [
            review
            for review in self._state.reviews
            if review.run_id in run_by_id
            and review.case_id == case.case_id
            and review.case_sha256 == case.case_sha256
            and review.status is CampaignRunStatus.SUCCEEDED
            and review.approval is not None
            and review.approval.decision is ReviewDecision.APPROVE
        ]
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
        self.purge_case_snapshot_images(case.case_id)
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
                and review.case_id in records
                and review.case_sha256 == records[review.case_id].case_sha256
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
            if case.family
            in {"boundary_constrained_route", "constrained_border_height", "no_hover_crossing"}
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
        execution_profile: ExecutionProfileSubmission | None = None,
        original_bytes: tuple[bytes, bytes, bytes] | None = None,
        artifact_hash_override: str | None = None,
        analysis_override: MissionAnalysis | None = None,
        artifacts_already_persisted: bool = False,
    ) -> ReviewItem:
        analysis = analysis_override or analyze_execution(
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
        if not artifacts_already_persisted:
            self._persist_intake_artifacts(
                artifacts,
                analysis,
                original_bytes=original_bytes,
            )
        status = _run_status(artifacts.status)
        oracle_failure = (
            status is CampaignRunStatus.SUCCEEDED
            and not analysis.all_required_behavior_oracles_passed
        )
        if oracle_failure:
            status = CampaignRunStatus.FAILED
        finished = run.model_copy(
            update={
                "status": status,
                "finished_at_utc": datetime.now(UTC),
                "mission_execution_id": artifacts.mission_execution_id,
                "artifact_set_sha256": artifact_hash,
                "analysis_sha256": analysis.analysis_sha256,
                "failure_reason": (
                    "one or more required behavior oracles failed"
                    if oracle_failure
                    else run.failure_reason
                ),
            }
        )
        review_payload: dict[str, Any] = {
            "review_id": f"review-{canonical_sha256([run.run_id, artifact_hash])[:20]}",
            "run_id": run.run_id,
            "case_id": case.case_id,
            "case_sha256": case.case_sha256,
            "status": status,
            "plan_sha256": plan.plan_sha256,
            "artifact_set_sha256": artifact_hash,
            "analysis": analysis,
            "baseline_comparison": self._baseline_comparison(
                case,
                run,
                analysis,
                artifacts.evaluation,
                execution_profile=execution_profile,
            ),
            "cross_case_profile_comparison": self._cross_case_profile_comparison(
                case,
                run,
                analysis,
                artifacts.evaluation,
            ),
            "mode_comparison": self._mode_comparison(case, run, analysis),
            "operator_questions": case.operator_observation_questions,
        }
        review = ReviewItem(**review_payload, review_sha256=canonical_sha256(review_payload))
        lifecycle = self._state.lifecycle[case.case_id].model_copy(
            update={"run_ids": (*self._state.lifecycle[case.case_id].run_ids, run.run_id)}
        )
        # Publish the terminal run, review, and lifecycle link as one in-memory
        # transition and one durable workspace write. Pollers cannot observe a
        # terminal run whose review has not been attached yet.
        self._state = self._state.model_copy(
            update={
                "runs": tuple(
                    finished if item.run_id == finished.run_id else item
                    for item in self._state.runs
                ),
                "reviews": (*self._state.reviews, review),
                "lifecycle": {**self._state.lifecycle, case.case_id: lifecycle},
            }
        )
        self._persist()
        return review

    async def _persist_intake_artifacts_off_loop(
        self,
        artifacts: RunArtifactSet,
        analysis: MissionAnalysis,
    ) -> None:
        """Keep terminal evidence serialization and fsyncs off the API event loop."""

        await asyncio.to_thread(
            self._persist_intake_artifacts,
            artifacts,
            analysis,
        )

    def _persist_intake_artifacts(
        self,
        artifacts: RunArtifactSet,
        analysis: MissionAnalysis,
        *,
        original_bytes: tuple[bytes, bytes, bytes] | None = None,
    ) -> None:
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
            and run_by_id[review.run_id].superseded_at_utc is None
            and run_by_id[review.run_id].mode is opposite_mode
            and run_by_id[review.run_id].locked_inputs.submission_id
            == run.locked_inputs.submission_id
            and run_by_id[review.run_id].locked_inputs.submission_sha256
            == run.locked_inputs.submission_sha256
            and run_by_id[review.run_id].locked_inputs.configuration_sha256
            == run.locked_inputs.configuration_sha256
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
        self,
        case: CampaignCase,
        run: CampaignRunRecord,
        analysis: MissionAnalysis,
        evaluation: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfileSubmission | None = None,
    ) -> dict[str, float | str | bool | None]:
        if execution_profile is not None:
            if (
                execution_profile.submission_id != run.locked_inputs.submission_id
                or execution_profile.profile_sha256 != run.locked_inputs.submission_sha256
            ):
                raise ValueError("intake execution profile does not match the retained run lock")
            submission = execution_profile
        else:
            try:
                submission = resolve_submission(
                    case,
                    run.locked_inputs.submission_id,
                    require_executable=False,
                )
            except ValueError as error:
                if run.locked_inputs.submission_id != "core.energy_aware_retiming":
                    raise
                from crazyswarm_app.campaign.submissions import ExecutionProfileParameters

                submission = bind_execution_capability(
                    case,
                    ExecutionCapabilityRequest(
                        capability_id="core.energy_aware_retiming",
                        parameters=ExecutionProfileParameters(),
                    ),
                )
                if submission.profile_sha256 != run.locked_inputs.submission_sha256:
                    raise ValueError(
                        "run lock does not match reconstructed energy capability"
                    ) from error
        baseline_id = submission.baseline_submission_id
        baseline_sha256 = submission.baseline_submission_sha256
        if baseline_id is None or baseline_sha256 is None:
            return {
                "comparison_kind": "RETAINED_CASE_BASELINE",
                "baseline_available": case.baseline_sha256 is not None,
                "baseline_sha256": case.baseline_sha256,
                "subject_run_id": run.run_id,
                "subject_submission_id": submission.submission_id,
                "subject_submission_sha256": submission.profile_sha256,
                "minimum_truth_separation_m": analysis.minimum_truth_separation_m,
                "mission_outcome": analysis.mission_outcome,
            }
        candidate = self._comparison_run(
            subject=run,
            case_sha256=case.case_sha256,
            submission_id=baseline_id,
            submission_sha256=baseline_sha256,
        )
        result: dict[str, float | str | bool | None] = {
            "comparison_kind": "EXACT_CASE_SUBMISSION_BASELINE",
            "baseline_available": candidate is not None,
            "baseline_submission_id": baseline_id,
            "baseline_submission_sha256": baseline_sha256,
            "subject_run_id": run.run_id,
            "subject_submission_id": submission.submission_id,
            "subject_submission_sha256": submission.profile_sha256,
        }
        if candidate is None:
            return result
        baseline_run, baseline_review, baseline_evaluation = candidate
        result.update(
            {
                "baseline_run_id": baseline_run.run_id,
                "baseline_artifact_set_sha256": baseline_review.artifact_set_sha256,
            }
        )
        result.update(
            _metric_deltas(
                _comparison_metrics(analysis, evaluation),
                _comparison_metrics(baseline_review.analysis, baseline_evaluation),
            )
        )
        return result

    def _cross_case_profile_comparison(
        self,
        case: CampaignCase,
        run: CampaignRunRecord,
        analysis: MissionAnalysis,
        evaluation: Mapping[str, Any],
    ) -> dict[str, float | str | bool | None]:
        submission_id = run.locked_inputs.submission_id
        if submission_id != "constant_path_speed.stress" or case.family != "altitude_transition":
            return {"comparison_available": False}
        candidate = next(
            (
                (other, review, other_case, other_evaluation)
                for other in reversed(self._state.runs)
                if other.run_id != run.run_id
                and other.superseded_at_utc is None
                and other.status is CampaignRunStatus.SUCCEEDED
                and other.mode is run.mode
                and other.locked_inputs.submission_id == submission_id
                and other.locked_inputs.case_id != case.case_id
                for other_case in (self.catalog.get(other.locked_inputs.case_id),)
                if other_case.family == case.family
                for review in self._state.reviews
                if review.run_id == other.run_id and review.status is CampaignRunStatus.SUCCEEDED
                for other_evaluation in (self._read_evaluation(other),)
                if other_evaluation is not None
            ),
            None,
        )
        result: dict[str, float | str | bool | None] = {
            "comparison_kind": "SAME_PROFILE_CANONICAL_WIDE",
            "comparison_available": candidate is not None,
            "subject_run_id": run.run_id,
            "subject_case_id": case.case_id,
            "subject_case_sha256": case.case_sha256,
            "subject_submission_id": submission_id,
            "subject_submission_sha256": run.locked_inputs.submission_sha256,
        }
        if candidate is None:
            return result
        other_run, other_review, other_case, other_evaluation = candidate
        result.update(
            {
                "comparison_run_id": other_run.run_id,
                "comparison_case_id": other_case.case_id,
                "comparison_case_sha256": other_case.case_sha256,
                "comparison_submission_sha256": other_run.locked_inputs.submission_sha256,
            }
        )
        result.update(
            _metric_deltas(
                _comparison_metrics(analysis, evaluation),
                _comparison_metrics(other_review.analysis, other_evaluation),
                prefix="subject_minus_comparison",
            )
        )
        return result

    def _comparison_run(
        self,
        *,
        subject: CampaignRunRecord,
        case_sha256: str,
        submission_id: str,
        submission_sha256: str,
    ) -> tuple[CampaignRunRecord, ReviewItem, dict[str, Any]] | None:
        for candidate in reversed(self._state.runs):
            if (
                candidate.run_id == subject.run_id
                or candidate.superseded_at_utc is not None
                or candidate.status is not CampaignRunStatus.SUCCEEDED
                or candidate.mode is not subject.mode
                or candidate.locked_inputs.case_sha256 != case_sha256
                or candidate.locked_inputs.submission_id != submission_id
                or candidate.locked_inputs.submission_sha256 != submission_sha256
            ):
                continue
            review = next(
                (
                    item
                    for item in self._state.reviews
                    if item.run_id == candidate.run_id
                    and item.status is CampaignRunStatus.SUCCEEDED
                ),
                None,
            )
            evaluation = self._read_evaluation(candidate)
            if review is not None and evaluation is not None:
                return candidate, review, evaluation
        return None

    def _read_evaluation(self, run: CampaignRunRecord) -> dict[str, Any] | None:
        if run.mission_execution_id is None:
            return None
        path = self.state_directory / "evidence" / run.mission_execution_id / "evaluation.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _load_state(self) -> CampaignWorkspaceState:
        path = self.state_directory / "workspace-state.json"
        if path.exists():
            state = CampaignWorkspaceState.model_validate_json(path.read_text(encoding="utf-8"))
            current = {case.case_id: case for case in self.catalog.cases()}
            reconciled: dict[str, LifecycleRecord] = {}
            historical = {
                (record.case_id, record.case_sha256): record
                for record in state.historical_lifecycle
            }
            reset_active_authority = False
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
                if self._identity_requires_archive(state, record):
                    historical[(record.case_id, record.case_sha256)] = record
                if state.active_case_id == case_id:
                    reset_active_authority = True
                reconciled[case_id] = LifecycleRecord(
                    case_id=case_id,
                    case_sha256=case.case_sha256,
                )

            for case_id, record in state.lifecycle.items():
                if case_id not in current and self._identity_requires_archive(state, record):
                    historical[(record.case_id, record.case_sha256)] = record
                if case_id not in current and state.active_case_id == case_id:
                    reset_active_authority = True

            if state.active_case_id is not None and state.locked_inputs is not None:
                active = current.get(state.active_case_id)
                if (
                    active is None
                    or state.locked_inputs.case_id != active.case_id
                    or state.locked_inputs.case_sha256 != active.case_sha256
                ):
                    reset_active_authority = True

            update: dict[str, Any] = {
                "lifecycle": reconciled,
                "historical_lifecycle": tuple(historical[key] for key in sorted(historical)),
            }
            if reset_active_authority:
                update.update({"active_case_id": None, "locked_inputs": None})
            return state.model_copy(update=update)
        return CampaignWorkspaceState(
            lifecycle={record.case_id: record for record in self.catalog.initial_lifecycle()}
        )

    @staticmethod
    def _identity_requires_archive(
        state: CampaignWorkspaceState,
        record: LifecycleRecord,
    ) -> bool:
        """Return whether an obsolete lifecycle carries evidence or operator authority."""

        has_run = bool(record.run_ids) or any(
            run.locked_inputs.case_id == record.case_id for run in state.runs
        )
        has_review = any(review.case_id == record.case_id for review in state.reviews)
        authority_bound = state.active_case_id == record.case_id or record.state in {
            LifecycleState.ACTIVE_DEVELOPMENT,
            LifecycleState.BASELINED,
            LifecycleState.PROMOTED,
        }
        return has_run or has_review or record.baseline_sha256 is not None or authority_bound

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

    def link_twin_session(self, run_id: str, twin_session_id: str) -> ReviewItem:
        """Bind retained twin evidence to its immutable campaign review."""

        try:
            review = next(item for item in self._state.reviews if item.run_id == run_id)
        except StopIteration as error:
            raise KeyError(f"unknown campaign run review: {run_id}") from error
        if twin_session_id in review.twin_session_ids:
            return review
        updated = _rehash_review(
            review.model_copy(
                update={"twin_session_ids": (*review.twin_session_ids, twin_session_id)}
            )
        )
        self._replace_review(updated)
        return updated

    def _snapshot(self, snapshot_id: str) -> CampaignSnapshotRecord:
        try:
            return next(item for item in self._state.snapshots if item.snapshot_id == snapshot_id)
        except StopIteration as error:
            raise KeyError(f"unknown campaign snapshot: {snapshot_id}") from error

    def _replace_snapshot(self, snapshot: CampaignSnapshotRecord) -> None:
        self._state = self._state.model_copy(
            update={
                "snapshots": tuple(
                    snapshot if item.snapshot_id == snapshot.snapshot_id else item
                    for item in self._state.snapshots
                )
            }
        )
        self._persist()


def _assert_mode_eligible(case: CampaignCase, mode: CampaignRunMode) -> None:
    # Every discovered simulation case may be launched from the catalog.  The
    # immutable planner, backend, and Safety Kernel checks remain authoritative and
    # can still reject the run before provisioning or command authority.
    if case.environment.value == "SIMULATION":
        return
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


def _assert_child_safety_is_monotone(parent: CampaignCase, child: CampaignCase) -> None:
    """Reject child authoring that silently broadens the parent's execution authority.

    A child may change problem truth (for example, add/move a solid or open a passage),
    but it is not a back door for relaxing vehicle, safety, authorization, evidence, or
    backend eligibility limits.  Those changes require a separately reviewed root case.
    """

    violations: list[str] = []

    def require(condition: bool, field: str) -> None:
        if not condition:
            violations.append(field)

    parent_volume = parent.hard_constraints.flight_volume
    child_volume = child.hard_constraints.flight_volume
    require(
        parent_volume.contains(child_volume.minimum_m)
        and parent_volume.contains(child_volume.maximum_m),
        "hard_constraints.flight_volume",
    )
    require(parent.environment is child.environment, "environment")
    require(parent.authorization is child.authorization, "authorization")
    require(child.drone_count == parent.drone_count, "drone_count")
    require(
        {item.role_id for item in child.drones} == {item.role_id for item in parent.drones},
        "drones.role_ids",
    )
    require(
        set(child.allowed_strategies).issubset(parent.allowed_strategies),
        "allowed_strategies",
    )
    if parent.implementation_status is ImplementationStatus.PLANNED_NOT_EXECUTABLE:
        require(
            child.implementation_status is ImplementationStatus.PLANNED_NOT_EXECUTABLE,
            "implementation_status",
        )
    require(
        _required_modes(child.execution_eligibility).issubset(
            _required_modes(parent.execution_eligibility)
        ),
        "execution_eligibility",
    )
    authority_rank = {
        ReplanningAuthority.ABORT_ONLY: 0,
        ReplanningAuthority.OPERATOR_APPROVAL_REQUIRED: 1,
        ReplanningAuthority.AUTO_WITHIN_FROZEN_LIMITS: 2,
    }
    require(
        authority_rank[child.replanning_authority] <= authority_rank[parent.replanning_authority],
        "replanning_authority",
    )

    before = parent.hard_constraints
    after = child.hard_constraints
    minimum_fields = (
        "warning_separation_m",
        "critical_separation_m",
        "position_uncertainty_m",
        "minimum_realtime_factor",
        "minimum_goal_update_interval_s",
        "watchdog_guard_s",
    )
    maximum_fields = (
        "deadline_s",
        "maximum_hover_s",
        "maximum_unrequired_airborne_wait_s",
        "maximum_equal_route_battery_spread_percent",
        "observation_freshness_limit_s",
        "planning_budget_s",
    )
    for field in minimum_fields:
        require(getattr(after, field) >= getattr(before, field), f"hard_constraints.{field}")
    for field in maximum_fields:
        require(getattr(after, field) <= getattr(before, field), f"hard_constraints.{field}")
    require(before.hover_allowed or not after.hover_allowed, "hard_constraints.hover_allowed")
    require(
        before.vertical_layers_allowed or not after.vertical_layers_allowed,
        "hard_constraints.vertical_layers_allowed",
    )
    require(
        not before.synchronized_launch_required or after.synchronized_launch_required,
        "hard_constraints.synchronized_launch_required",
    )
    for field in (
        "maximum_horizontal_speed_m_s",
        "maximum_vertical_speed_m_s",
        "maximum_acceleration_m_s2",
        "maximum_jerk_m_s3",
        "stop_speed_threshold_m_s",
        "unintended_stop_persistence_s",
    ):
        parent_value = getattr(before.dynamics, field)
        child_value = getattr(after.dynamics, field)
        if field == "stop_speed_threshold_m_s":
            require(child_value >= parent_value, f"hard_constraints.dynamics.{field}")
        else:
            require(child_value <= parent_value, f"hard_constraints.dynamics.{field}")
    for field in type(before.mode_comparison).model_fields:
        require(
            getattr(after.mode_comparison, field) <= getattr(before.mode_comparison, field),
            f"hard_constraints.mode_comparison.{field}",
        )
    parent_drone_by_role = {item.role_id: item for item in parent.drones}
    for drone in child.drones:
        source = parent_drone_by_role.get(drone.role_id)
        if source is not None:
            require(
                drone.minimum_reserve_battery_percent >= source.minimum_reserve_battery_percent,
                f"drones.{drone.role_id}.minimum_reserve_battery_percent",
            )

    if violations:
        raise ValueError(
            "child case weakens parent authority or safety bounds: "
            + ", ".join(sorted(set(violations)))
        )


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


def _comparison_metrics(
    analysis: MissionAnalysis,
    evaluation: Mapping[str, Any],
) -> dict[str, float | None]:
    vehicles = evaluation.get("vehicles")
    vehicle_rows = (
        [item for item in vehicles if isinstance(item, Mapping)]
        if isinstance(vehicles, list)
        else []
    )

    def evaluation_value(name: str, *, minimum: bool = False) -> float | None:
        values = [
            float(item[name]) for item in vehicle_rows if isinstance(item.get(name), (int, float))
        ]
        if not values:
            return None
        return min(values) if minimum else max(values)

    return {
        "source_duration_s": max(
            (item.source_duration_s for item in analysis.vehicles),
            default=None,
        ),
        "battery_used_percent": max(
            (
                item.battery_used_percent
                for item in analysis.vehicles
                if item.battery_used_percent is not None
            ),
            default=None,
        ),
        "tracking_rms_error_m": max(
            (
                item.tracking_rms_error_m
                for item in analysis.vehicles
                if item.tracking_rms_error_m is not None
            ),
            default=None,
        ),
        "trajectory_speed_rms_error_m_s": evaluation_value("trajectory_speed_rms_error_m_s"),
        "planned_profile_maximum_fractional_error": evaluation_value(
            "planned_profile_maximum_fractional_error"
        ),
        "minimum_motor_thrust_headroom_n": evaluation_value(
            "minimum_motor_thrust_headroom_n",
            minimum=True,
        ),
        "touchdown_target_center_error_m": evaluation_value("touchdown_target_center_error_m"),
    }


def _metric_deltas(
    subject: Mapping[str, float | None],
    comparison: Mapping[str, float | None],
    *,
    prefix: str = "subject_minus_baseline",
) -> dict[str, float | str | bool | None]:
    result: dict[str, float | str | bool | None] = {}
    for metric in sorted(set(subject).union(comparison)):
        subject_value = subject.get(metric)
        comparison_value = comparison.get(metric)
        result[f"subject_{metric}"] = subject_value
        result[f"comparison_{metric}"] = comparison_value
        result[f"{prefix}_{metric}"] = (
            subject_value - comparison_value
            if subject_value is not None and comparison_value is not None
            else None
        )
    return result


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
