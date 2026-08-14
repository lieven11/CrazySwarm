from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import LifecycleState, LockedDevelopmentInputs
from crazyswarm_app.campaign.service import (
    CampaignExecutionRequest,
    CampaignRunMode,
    CampaignRunRecord,
    CampaignRunStatus,
    CampaignService,
    ReviewDecision,
    RunArtifactSet,
    SnapshotAssessmentDisposition,
)


@pytest.mark.asyncio
async def test_cancelled_execution_waiter_does_not_orphan_campaign_capacity(
    tmp_path: Path,
) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    await service._acquire_execution_slot("active-run")
    waiting = asyncio.create_task(service._acquire_execution_slot("cancelled-waiter"))
    await asyncio.sleep(0)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await service._release_execution_slot("active-run")
    await asyncio.wait_for(service._acquire_execution_slot("next-run"), timeout=0.5)

    assert service._active_execution_run_ids == {"next-run"}
    await service._release_execution_slot("next-run")


@pytest.mark.asyncio
async def test_cancelled_queued_launch_becomes_terminal_and_releases_workflow(
    tmp_path: Path,
) -> None:
    async def executor_unreachable(request: CampaignExecutionRequest) -> RunArtifactSet:
        del request
        raise AssertionError("queued launch must not reach the executor")

    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
        executor=executor_unreachable,
    )
    service.set_active(
        "1d.takeoff_hover_land.canonical_nominal",
        actor_id="operator",
        reason="exercise queued task cancellation",
    )
    await service._acquire_execution_slot("capacity-owner")
    launch = asyncio.create_task(
        service.run_active(
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="cancelled-queued-launch",
        )
    )
    await asyncio.sleep(0)
    assert service.state.runs[-1].status is CampaignRunStatus.QUEUED

    launch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await launch

    cancelled = service.state.runs[-1]
    assert cancelled.status is CampaignRunStatus.CANCELLED_BEFORE_LAUNCH
    assert cancelled.finished_at_utc is not None
    assert cancelled.failure_reason == "campaign launch task was cancelled before execution"
    service.set_active(
        "1d.continuous_waypoint_sequence.canonical_nominal",
        actor_id="operator",
        reason="queued cancellation no longer blocks mission selection",
    )
    assert service.state.active_case_id == "1d.continuous_waypoint_sequence.canonical_nominal"
    await service._release_execution_slot("capacity-owner")


@pytest.mark.asyncio
async def test_cancelled_running_task_becomes_terminal_and_releases_capacity(
    tmp_path: Path,
) -> None:
    executor_started = asyncio.Event()
    executor_release = asyncio.Event()

    async def blocked_executor(request: CampaignExecutionRequest) -> RunArtifactSet:
        del request
        executor_started.set()
        await executor_release.wait()
        raise AssertionError("cancelled executor must not resume")

    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
        executor=blocked_executor,
    )
    service.set_active(
        "1d.takeoff_hover_land.canonical_nominal",
        actor_id="operator",
        reason="exercise running task cancellation",
    )
    launch = asyncio.create_task(
        service.run_active(
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="cancelled-running-launch",
        )
    )
    await asyncio.wait_for(executor_started.wait(), timeout=1)

    launch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await launch

    cancelled = service.state.runs[-1]
    assert cancelled.status is CampaignRunStatus.FAILED
    assert cancelled.finished_at_utc is not None
    assert cancelled.failure_reason == (
        "campaign execution task was cancelled; partial artifacts retained for review"
    )
    assert service._active_execution_run_ids == set()


def test_cancelling_queued_run_immediately_releases_operator_workflow(
    tmp_path: Path,
) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    lock = service.set_active(
        "1d.altitude_transition.canonical_nominal",
        actor_id="operator",
        reason="exercise queued cancellation",
    )
    queued = CampaignRunRecord(
        run_id="campaign-run-queued",
        mode=CampaignRunMode.AUTOMATED_ACCELERATED,
        status=CampaignRunStatus.QUEUED,
        locked_inputs=lock,
        requested_at_utc=datetime.now(UTC),
        plan_sha256="1" * 64,
        schedule_sha256="2" * 64,
        trajectory_set_sha256="3" * 64,
    )
    service._state = service.state.model_copy(update={"runs": (queued,)})

    assert service.cancel(queued.run_id) is True
    cancelled = service.state.runs[0]
    assert cancelled.status is CampaignRunStatus.CANCELLED_BEFORE_LAUNCH
    assert cancelled.finished_at_utc is not None


def test_mark_runs_old_persists_only_the_selected_evidence_generation(
    tmp_path: Path,
) -> None:
    state_directory = tmp_path / "campaign"
    catalog = CampaignCatalog(Path("missions/campaigns/sim/cases"))
    service = CampaignService(catalog=catalog, state_directory=state_directory)
    one_drone_lock = LockedDevelopmentInputs.from_case(
        catalog.get("1d.takeoff_hover_land.canonical_nominal")
    )
    two_drone_lock = LockedDevelopmentInputs.from_case(
        catalog.get("2d.bottleneck.canonical_nominal")
    )
    requested_at = datetime(2026, 8, 14, tzinfo=UTC)

    def retained_run(run_id: str, lock: LockedDevelopmentInputs) -> CampaignRunRecord:
        return CampaignRunRecord(
            run_id=run_id,
            mode=CampaignRunMode.AUTOMATED_ACCELERATED,
            status=CampaignRunStatus.SUCCEEDED,
            locked_inputs=lock,
            requested_at_utc=requested_at,
            finished_at_utc=requested_at,
            plan_sha256="1" * 64,
            schedule_sha256="2" * 64,
            trajectory_set_sha256="3" * 64,
        )

    service._state = service.state.model_copy(
        update={
            "runs": (
                retained_run("campaign-run-one", one_drone_lock),
                retained_run("campaign-run-two", two_drone_lock),
            )
        }
    )
    service._persist()

    changed = service.mark_runs_old(
        case_ids=(one_drone_lock.case_id,),
        revision_id="9621591e3558a8a46d2a1a3b1b119e4584cb735f",
        actor_id="operator",
        reason="1D implementation revision applied",
        marked_at_utc=requested_at + timedelta(hours=1),
    )

    assert tuple(run.run_id for run in changed) == ("campaign-run-one",)
    assert service.state.runs[0].superseded_at_utc == requested_at + timedelta(hours=1)
    assert service.state.runs[0].superseded_by_revision == (
        "9621591e3558a8a46d2a1a3b1b119e4584cb735f"
    )
    assert service.state.runs[1].superseded_at_utc is None
    assert service.mark_runs_old(
        case_ids=(one_drone_lock.case_id,),
        revision_id="9621591e3558a8a46d2a1a3b1b119e4584cb735f",
        actor_id="operator",
        reason="1D implementation revision applied",
    ) == ()

    restored = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=state_directory,
    )
    assert restored.state.runs[0].superseded_reason == "1D implementation revision applied"
    assert restored.state.runs[1].superseded_at_utc is None


@pytest.mark.asyncio
async def test_prelaunch_failure_does_not_leave_run_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def executor_unreachable(request: CampaignExecutionRequest) -> RunArtifactSet:
        del request
        raise AssertionError("executor must not be called after request construction fails")

    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
        executor=executor_unreachable,
    )
    service.set_active(
        "1d.takeoff_hover_land.canonical_nominal",
        actor_id="operator",
        reason="exercise prelaunch failure recording",
    )

    def reject_request(**_values: object) -> object:
        raise ValueError("constructed request is invalid")

    monkeypatch.setattr(
        "crazyswarm_app.campaign.service.CampaignExecutionRequest",
        reject_request,
    )
    with pytest.raises(ValueError, match="constructed request is invalid"):
        await service.run_active(
            CampaignRunMode.AUTOMATED_ACCELERATED,
            idempotency_key="prelaunch-failure",
        )

    failed = service.state.runs[-1]
    assert failed.status is CampaignRunStatus.FAILED
    assert failed.failure_reason == "constructed request is invalid"
    assert service._active_execution_run_ids == set()


def test_selecting_another_case_keeps_only_one_case_in_progress(tmp_path: Path) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    canonical_id = "1d.altitude_transition.canonical_nominal"
    wide_id = "1d.altitude_transition.wide"

    service.set_active(canonical_id, actor_id="operator", reason="start canonical")
    service.set_active(wide_id, actor_id="operator", reason="start wide")

    assert service.state.active_case_id == wide_id
    assert service.state.lifecycle[canonical_id].state is LifecycleState.READY
    assert service.state.lifecycle[wide_id].state is LifecycleState.ACTIVE_DEVELOPMENT


def test_child_cannot_widen_frozen_replanning_budget(tmp_path: Path) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    case_id = "2d.head_on_conflict.canonical_nominal"
    service.set_active(case_id, actor_id="operator", reason="author causal child")
    source = service.active_case

    with pytest.raises(ValueError, match=r"hard_constraints\.planning_budget_s"):
        service.create_child(
            child_case_id="2d.head_on_conflict.unsafe-budget-child",
            updates={
                "hard_constraints": {
                    "planning_budget_s": (
                        source.hard_constraints.planning_budget_s + 1.0
                    )
                }
            },
        )


def test_selecting_another_case_is_rejected_while_a_run_is_active(tmp_path: Path) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    first_id = "1d.altitude_transition.canonical_nominal"
    lock = service.set_active(first_id, actor_id="operator", reason="start canonical")
    service._state = service.state.model_copy(update={
        "runs": (
            CampaignRunRecord(
                run_id="campaign-run-active",
                mode=CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
                status=CampaignRunStatus.RUNNING,
                locked_inputs=lock,
                requested_at_utc=datetime.now(UTC),
                plan_sha256="1" * 64,
                schedule_sha256="2" * 64,
                trajectory_set_sha256="3" * 64,
            ),
        ),
    })

    with pytest.raises(ValueError, match="stop the active campaign run"):
        service.set_active(
            "1d.altitude_transition.wide",
            actor_id="operator",
            reason="switch while running",
        )

    assert service.state.active_case_id == first_id


def test_startup_repairs_legacy_multiple_in_progress_cases(tmp_path: Path) -> None:
    state_directory = tmp_path / "campaign"
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=state_directory,
    )
    active_id = "1d.altitude_transition.canonical_nominal"
    stale_id = "1d.altitude_transition.wide"
    service.set_active(active_id, actor_id="operator", reason="select canonical")
    stale = service.state.lifecycle[stale_id].transition(
        LifecycleState.ACTIVE_DEVELOPMENT,
        actor_id="legacy-client",
        reason="legacy client retained a second in-progress case",
    )
    service._state = service.state.model_copy(update={
        "lifecycle": {**service.state.lifecycle, stale_id: stale},
    })
    service._persist()

    restored = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=state_directory,
    )

    assert restored.state.active_case_id == active_id
    assert restored.state.lifecycle[active_id].state is LifecycleState.ACTIVE_DEVELOPMENT
    assert restored.state.lifecycle[stale_id].state is LifecycleState.READY


def test_comment_moves_case_to_review_and_completion_keeps_comment(tmp_path: Path) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    case_id = "three_drone_multi_conflict"
    active = service.state.lifecycle[case_id].transition(
        LifecycleState.ACTIVE_DEVELOPMENT,
        actor_id="test-fixture",
        reason="exercise direct completion from in progress",
    )
    service._replace_lifecycle(active)
    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_run-3db45c352258411b85c44649bdef5e6b"
    )
    review = service.import_artifacts(
        case_id=case_id,
        manifest_bytes=(directory / "manifest.json").read_bytes(),
        bundle_bytes=next(directory.glob("*execution-bundle-v1.json")).read_bytes(),
        evaluation_bytes=next(directory.glob("*evaluation-v1.json")).read_bytes(),
        csv_bytes=next(directory.glob("*telemetry-v1.csv")).read_bytes(),
    )
    snapshot = service.add_snapshot(
        review.run_id,
        content=b"RIFF\x08\x00\x00\x00WEBPVP8 ",
        content_type="image/webp",
        width_px=960,
        height_px=540,
    )
    service.set_snapshot_comment(snapshot.snapshot_id, "Drift remained visible")
    with pytest.raises(ValueError, match="neutral snapshot assessment"):
        service.purge_case_snapshot_images(case_id)
    assert service.state.snapshots[0].image_available
    service.set_snapshot_assessment(
        snapshot.snapshot_id,
        assessment="The source-bound frame supports the visible-drift comment.",
        disposition=SnapshotAssessmentDisposition.PARTLY_VALID,
        confidence=0.8,
        evidence_refs=(review.analysis.analysis_sha256,),
    )
    commented_review = service.add_observation(
        review.review_id,
        "The run is ready for joint review",
        actor_id="operator",
    )

    assert commented_review.operator_observations == ("The run is ready for joint review",)
    assert service.state.lifecycle[case_id].state is LifecycleState.BASELINED
    assert service.state.active_case_id is None
    retained_snapshot = service.state.snapshots[0]
    assert retained_snapshot.image_available is False
    assert retained_snapshot.operator_comment == "Drift remained visible"

    completed = service.complete_case(
        case_id,
        actor_id="operator",
        reason="review discussion complete",
    )
    assert completed.state is LifecycleState.PROMOTED


def test_case_can_complete_directly_from_in_progress(tmp_path: Path) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    case_id = "three_drone_multi_conflict"
    active = service.state.lifecycle[case_id].transition(
        LifecycleState.ACTIVE_DEVELOPMENT,
        actor_id="test-fixture",
        reason="exercise direct completion from in progress",
    )
    service._replace_lifecycle(active)
    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_run-3db45c352258411b85c44649bdef5e6b"
    )
    service.import_artifacts(
        case_id=case_id,
        manifest_bytes=(directory / "manifest.json").read_bytes(),
        bundle_bytes=next(directory.glob("*execution-bundle-v1.json")).read_bytes(),
        evaluation_bytes=next(directory.glob("*evaluation-v1.json")).read_bytes(),
        csv_bytes=next(directory.glob("*telemetry-v1.csv")).read_bytes(),
    )

    completed = service.complete_case(
        case_id,
        actor_id="operator",
        reason="successful evidence is complete",
    )

    assert completed.state is LifecycleState.PROMOTED
    assert completed.baseline_sha256 is not None
    assert completed.transitions[-1].previous_state is LifecycleState.ACTIVE_DEVELOPMENT
    assert service.state.active_case_id == case_id
    assert service.active_case.case_id == case_id


def test_selected_completed_case_remains_selected_for_a_repeat_run(tmp_path: Path) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    case_id = "1d.altitude_transition.canonical_nominal"

    service.set_active(case_id, actor_id="operator", reason="select mission")
    service.set_lifecycle_state(
        case_id,
        LifecycleState.PROMOTED,
        actor_id="operator",
        reason="operator marked the case complete",
    )

    assert service.state.active_case_id == case_id
    assert service.state.lifecycle[case_id].state is LifecycleState.PROMOTED
    service.set_active(case_id, actor_id="operator", reason="repeat completed mission")
    assert service.state.lifecycle[case_id].state is LifecycleState.PROMOTED


def test_explicit_lifecycle_choice_can_bypass_evidence_workflow(tmp_path: Path) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    case_id = "1d.altitude_transition.canonical_nominal"

    completed = service.set_lifecycle_state(
        case_id,
        LifecycleState.PROMOTED,
        actor_id="operator",
        reason="operator marked the case complete",
    )
    reopened = service.set_lifecycle_state(
        case_id,
        LifecycleState.DEFINED_NOT_RUN,
        actor_id="operator",
        reason="operator reset the case",
    )

    assert completed.state is LifecycleState.PROMOTED
    assert completed.baseline_sha256 is None
    assert reopened.state is LifecycleState.DEFINED_NOT_RUN
    assert reopened.transitions[-1].previous_state is LifecycleState.PROMOTED


def test_snapshot_capture_allows_only_a_short_run_finish_race(tmp_path: Path) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_run-3db45c352258411b85c44649bdef5e6b"
    )
    review = service.import_artifacts(
        case_id="three_drone_multi_conflict",
        manifest_bytes=(directory / "manifest.json").read_bytes(),
        bundle_bytes=next(directory.glob("*execution-bundle-v1.json")).read_bytes(),
        evaluation_bytes=next(directory.glob("*evaluation-v1.json")).read_bytes(),
        csv_bytes=next(directory.glob("*telemetry-v1.csv")).read_bytes(),
    )
    run = service.state.runs[0]
    recent_finish = run.model_copy(
        update={
            "status": CampaignRunStatus.SUCCEEDED,
            "finished_at_utc": datetime.now(UTC) - timedelta(seconds=1),
        }
    )
    service._state = service.state.model_copy(update={"runs": (recent_finish,)})

    snapshot = service.add_snapshot(
        review.run_id,
        content=b"RIFF\x08\x00\x00\x00WEBPVP8 ",
        content_type="image/webp",
        width_px=960,
        height_px=540,
    )

    assert snapshot.run_id == review.run_id
    expired_finish = recent_finish.model_copy(
        update={"finished_at_utc": datetime.now(UTC) - timedelta(seconds=6)}
    )
    service._state = service.state.model_copy(update={"runs": (expired_finish,)})
    with pytest.raises(ValueError, match="only be captured while a run is running"):
        service.add_snapshot(
            review.run_id,
            content=b"RIFF\x08\x00\x00\x00WEBPVP8 ",
            content_type="image/webp",
            width_px=960,
            height_px=540,
        )


def test_startup_refreshes_changed_definition_only_identity(tmp_path: Path) -> None:
    state_directory = tmp_path / "campaign"
    catalog_path = Path("missions/campaigns/sim/cases")
    service = CampaignService(
        catalog=CampaignCatalog(catalog_path),
        state_directory=state_directory,
    )
    case_id = "1d.takeoff_hover_land.canonical_nominal"
    service.static_validate(case_id)
    state_path = state_directory / "workspace-state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["lifecycle"][case_id]["case_sha256"] = "0" * 64
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    refreshed = CampaignService(
        catalog=CampaignCatalog(catalog_path),
        state_directory=state_directory,
    )

    record = refreshed.state.lifecycle[case_id]
    assert record.case_sha256 == refreshed.catalog.get(case_id).case_sha256
    assert record.state is LifecycleState.DEFINED_NOT_RUN
    assert record.transitions == ()


def test_startup_archives_changed_identity_with_evidence(tmp_path: Path) -> None:
    state_directory = tmp_path / "campaign"
    catalog_path = Path("missions/campaigns/sim/cases")
    service = CampaignService(
        catalog=CampaignCatalog(catalog_path),
        state_directory=state_directory,
    )
    case_id = "1d.takeoff_hover_land.canonical_nominal"
    service.set_active(case_id, actor_id="test", reason="bind old authority")
    state_path = state_directory / "workspace-state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["lifecycle"][case_id]["case_sha256"] = "0" * 64
    payload["lifecycle"][case_id]["run_ids"] = ["run-preserved-evidence"]
    payload["locked_inputs"]["case_sha256"] = "0" * 64
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    refreshed = CampaignService(
        catalog=CampaignCatalog(catalog_path),
        state_directory=state_directory,
    )

    current = refreshed.state.lifecycle[case_id]
    assert current.case_sha256 == refreshed.catalog.get(case_id).case_sha256
    assert current.state is LifecycleState.DEFINED_NOT_RUN
    assert refreshed.state.active_case_id is None
    assert refreshed.state.locked_inputs is None
    historical = refreshed.state.historical_lifecycle
    assert len(historical) == 1
    assert historical[0].case_id == case_id
    assert historical[0].case_sha256 == "0" * 64
    assert historical[0].run_ids == ("run-preserved-evidence",)


def test_historical_intake_is_idempotent_non_executing_and_reviewable(
    tmp_path: Path,
) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    assert service.state.runs == ()
    service.static_validate("three_drone_multi_conflict")
    assert service.state.runs == ()
    service.set_active(
        "3d.simultaneous_center_conflict.joint_schedule_v2",
        actor_id="campaign-service-test",
        reason="select semantic successor without launching",
    )
    child = service.create_child(
        child_case_id="3d.simultaneous_center_conflict.child-service",
        updates={"execution": {"seed": 73}},
    )
    assert child.execution.seed == 73
    assert child.execution.repetitions == 1
    assert child.execution.backend_profile_id == "fast-sim-v1"
    assert service.state.runs == ()
    service.set_active(
        "three_drone_multi_conflict",
        actor_id="campaign-service-test",
        reason="bind frozen historical evidence identity",
    )

    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_run-3db45c352258411b85c44649bdef5e6b"
    )
    manifest = (directory / "manifest.json").read_bytes()
    bundle = next(directory.glob("*execution-bundle-v1.json")).read_bytes()
    evaluation = next(directory.glob("*evaluation-v1.json")).read_bytes()
    telemetry = next(directory.glob("*telemetry-v1.csv")).read_bytes()
    first = service.import_artifacts(
        case_id="three_drone_multi_conflict",
        manifest_bytes=manifest,
        bundle_bytes=bundle,
        evaluation_bytes=evaluation,
        csv_bytes=telemetry,
    )
    second = service.import_artifacts(
        case_id="three_drone_multi_conflict",
        manifest_bytes=manifest,
        bundle_bytes=bundle,
        evaluation_bytes=evaluation,
        csv_bytes=telemetry,
    )
    assert second.review_id == first.review_id
    assert len(service.state.runs) == 1
    assert len(service.state.reviews) == 1
    assert first.analysis.telemetry_row_count == 8_245
    assert first.analysis.minimum_truth_separation_m is not None
    assert abs(first.analysis.minimum_truth_separation_m - 0.8444) <= 0.005

    approved = service.decide_review(
        first.review_id,
        operator_id="campaign-service-test",
        decision=ReviewDecision.APPROVE,
        reason="historical evidence reproduced",
    )
    assert approved.approval is not None
    assert service.state.lifecycle["three_drone_multi_conflict"].state is LifecycleState.BASELINED
    first_recommendation = service.recommend_next()
    second_recommendation = service.recommend_next()
    assert first_recommendation.recommendation_sha256 == (
        second_recommendation.recommendation_sha256
    )
    matrix = service.materialize_wp25_matrix()
    assert matrix["matrix_id"] == "fast-sim-mission-robustness-v1"
    assert len(matrix["cells"]) == 16


def test_completed_campaign_run_can_be_deleted_with_review_and_cached_evidence(
    tmp_path: Path,
) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    case_id = "three_drone_multi_conflict"
    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_run-3db45c352258411b85c44649bdef5e6b"
    )
    review = service.import_artifacts(
        case_id=case_id,
        manifest_bytes=(directory / "manifest.json").read_bytes(),
        bundle_bytes=next(directory.glob("*execution-bundle-v1.json")).read_bytes(),
        evaluation_bytes=next(directory.glob("*evaluation-v1.json")).read_bytes(),
        csv_bytes=next(directory.glob("*telemetry-v1.csv")).read_bytes(),
    )
    cached_evidence = tmp_path / "campaign" / "evidence" / review.analysis.mission_execution_id
    assert cached_evidence.is_dir()

    deleted = service.delete_run(review.run_id)

    assert deleted.run_id == review.run_id
    assert service.state.runs == ()
    assert service.state.reviews == ()
    assert review.run_id not in service.state.lifecycle[case_id].run_ids
    assert not cached_evidence.exists()


def test_approved_campaign_run_cannot_be_deleted(tmp_path: Path) -> None:
    service = CampaignService(
        catalog=CampaignCatalog(Path("missions/campaigns/sim/cases")),
        state_directory=tmp_path / "campaign",
    )
    case_id = "three_drone_multi_conflict"
    service.set_active(case_id, actor_id="campaign-service-test", reason="approve evidence")
    directory = Path(
        "run-files/20260809T132105Z_three_drone_multi_conflict_run-3db45c352258411b85c44649bdef5e6b"
    )
    review = service.import_artifacts(
        case_id=case_id,
        manifest_bytes=(directory / "manifest.json").read_bytes(),
        bundle_bytes=next(directory.glob("*execution-bundle-v1.json")).read_bytes(),
        evaluation_bytes=next(directory.glob("*evaluation-v1.json")).read_bytes(),
        csv_bytes=next(directory.glob("*telemetry-v1.csv")).read_bytes(),
    )
    completed_run = service.state.runs[0]
    service._state = service.state.model_copy(
        update={
            "runs": (
                completed_run.model_copy(
                    update={"status": CampaignRunStatus.RUNNING, "finished_at_utc": None}
                ),
            )
        }
    )
    snapshot = service.add_snapshot(
        review.run_id,
        content=b"RIFF\x08\x00\x00\x00WEBPVP8 ",
        content_type="image/webp",
        width_px=960,
        height_px=540,
    )
    commented = service.set_snapshot_comment(snapshot.snapshot_id, "Visible drift at capture")
    service.set_snapshot_assessment(
        snapshot.snapshot_id,
        assessment="The exact source-time frame is suitable for the stated observation.",
        disposition=SnapshotAssessmentDisposition.VALID,
        confidence=0.9,
        evidence_refs=(review.analysis.analysis_sha256,),
    )
    service._state = service.state.model_copy(update={"runs": (completed_run,)})
    service.decide_review(
        review.review_id,
        operator_id="campaign-service-test",
        decision=ReviewDecision.APPROVE,
        reason="bind this evidence as the baseline",
    )

    retained_snapshot = service.state.snapshots[0]
    assert retained_snapshot.operator_comment == commented.operator_comment
    assert retained_snapshot.image_available is False
    assert retained_snapshot.purged_at_utc is not None
    with pytest.raises(FileNotFoundError, match="purged"):
        service.snapshot_image_path(snapshot.snapshot_id)

    with pytest.raises(PermissionError, match="baseline evidence"):
        service.delete_run(review.run_id)
