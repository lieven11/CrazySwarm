from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from crazyswarm_app.api.runtime import create_runtime
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.models import LifecycleState
from crazyswarm_app.campaign.qualification import qualify_tracking_rms_repeats
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.service import (
    CampaignRunMode,
    CampaignRunStatus,
    CampaignService,
    ReviewDecision,
)
from crazyswarm_app.campaign.submissions import MotionPreparationRequest
from crazyswarm_app.config import load_config
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.simulation.faults import FaultType, FaultWindow
from crazyswarm_app.simulation.world import load_scenario

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT / "missions/campaigns/sim/qualification/wp62-66-runtime-qualification-v1.json"
)
DEFAULT_EVIDENCE = (
    ROOT / "missions/campaigns/sim/qualification/wp62-66-runtime-evidence-v1"
)
ONLINE_CASE_ID = "1d.online_obstacle_replan.dynamic_nominal"
PREDECESSOR_CASE_ID = "1d.point_to_point_relocation.canonical_nominal"
WP64_CASE_IDS = (
    "1d.curved_route.canonical_nominal",
    "1d.planar_shape_loop.figure_eight",
    "1d.altitude_transition.canonical_nominal",
)
WP64_PREPARATION_REQUESTS = {
    "1d.curved_route.canonical_nominal": MotionPreparationRequest(),
    # The long loop deliberately exercises the operator's Flow/accuracy trade-off:
    # a 10 cm soft tube and 0.27 m/s request retain the continuous crossover while
    # preserving truthful tracking, ripple, motor, and energy margin on every repeat.
    "1d.planar_shape_loop.figure_eight": MotionPreparationRequest(
        speed_m_s=0.27,
        accuracy_m=0.10,
        smoothness=0,
    ),
    "1d.altitude_transition.canonical_nominal": MotionPreparationRequest(),
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Qualify three consecutive realtime online replans and one immediate retry"
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-directory", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--repetitions", type=int, default=3, choices=(3,))
    return parser.parse_args()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _retained_file(
    source: Path,
    destination: Path,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {
        "path": destination.relative_to(ROOT).as_posix(),
        "size_bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
    }


def _trace_result(
    bundle: dict[str, Any],
    *,
    expected_event_ids: set[str],
) -> dict[str, Any]:
    trace = bundle["context"]["campaign_execution_head_trace"]
    records = trace["records"]
    persisted = [item for item in records if item.get("stage") == "PERCEPTION_PERSISTED"]
    recertified = [
        item for item in records if item.get("stage") == "MOVING_CUTOVER_RECERTIFIED"
    ]
    dispatched = [
        item for item in records if item.get("execution_disposition") == "DISPATCHED"
    ]
    persisted_event_ids = {
        item["observation_id"].split(".", 2)[-1] for item in persisted
    }
    recertified_event_ids = {item["event_id"] for item in recertified}
    dispatched_event_ids = {item["event_id"] for item in dispatched}
    forbidden = ("TELEMETRY_STALE", "STALE_FLEET_OBSERVATION")
    serialized = json.dumps(records, sort_keys=True)
    return {
        "expected_event_ids": sorted(expected_event_ids),
        "persisted_event_ids": sorted(persisted_event_ids),
        "recertified_event_ids": sorted(recertified_event_ids),
        "dispatched_event_ids": sorted(dispatched_event_ids),
        "all_events_persisted": persisted_event_ids == expected_event_ids,
        "all_events_recertified": recertified_event_ids == expected_event_ids,
        "all_events_dispatched": dispatched_event_ids == expected_event_ids,
        "all_cutover_certificates_passed": all(
            item["moving_cutover_certificate"]["passed"] for item in recertified
        ),
        "all_safe_prefix_certificates_passed": all(
            item["safe_prefix_certificate"]["passed"] for item in dispatched
        ),
        "stale_failure_absent": not any(token in serialized for token in forbidden),
        "unqualified_emergency_absent": not any(
            item.get("stage") == "UNQUALIFIED_EMERGENCY_FALLBACK" for item in records
        ),
    }


def _tracking_rms_record(
    review: Any,
    *,
    packet_id: str,
    case_id: str,
    mode: CampaignRunMode,
    ordinal: int,
) -> dict[str, Any]:
    analyses = tuple(review.analysis.motion_quality)
    value = analyses[0].vector.tracking_rms_m if len(analyses) == 1 else None
    return {
        "identity": {
            "packet_id": packet_id,
            "case_id": case_id,
            "mode": mode.value,
            "ordinal": ordinal,
        },
        "applicable": True,
        "tracking_rms_m": value,
    }


def _kinematics_reconciliation(review: Any) -> dict[str, Any]:
    vehicles = tuple(review.analysis.vehicles)
    records = tuple(
        {
            "vehicle_id": vehicle.vehicle_id,
            **vehicle.kinematics_gate_reconciliation.model_dump(mode="json"),
        }
        for vehicle in vehicles
    )
    return {
        "records": records,
        "passed": bool(records)
        and all(
            record["raw_gate_passed"] is True
            and record["processed_gate_passed"] is True
            and record["gate_disagreement"] is False
            for record in records
        ),
    }


def _runtime_cleanup_state(runtime: Any, service: CampaignService) -> dict[str, bool]:
    return {
        "no_active_run": not any(
            item.status in {CampaignRunStatus.QUEUED, CampaignRunStatus.RUNNING}
            for item in service.state.runs
        ),
        "dynamic_obstacles_cleared": not runtime.dynamic_obstacles,
        "fleet_tasks_cleared": not runtime.fleet_tasks,
        "fleet_preparations_cleared": not runtime.fleet_preparations,
        "fleet_coordinators_cleared": not runtime.fleet_coordinators,
    }


def _assert_generated_evidence_target(path: Path) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise ValueError("runtime evidence directory must be inside the repository") from error
    if not relative.parts or resolved == ROOT.resolve():
        raise ValueError("runtime evidence directory must not be the repository root")
    return resolved


def _csv_has_forbidden_stale_fault(path: Path) -> bool:
    payload = path.read_text(encoding="utf-8", errors="replace")
    return any(
        token in payload for token in ("TELEMETRY_STALE", "STALE_FLEET_OBSERVATION")
    )


async def _run(arguments: argparse.Namespace) -> int:
    evidence_directory = _assert_generated_evidence_target(arguments.evidence_directory)
    if evidence_directory.exists():
        shutil.rmtree(evidence_directory)
    evidence_directory.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="crazyswarm-wp62-66-runtime-") as raw:
        temporary = Path(raw)
        config = load_config(ROOT / "config/app.yaml").model_copy(
            update={"cache_directory": temporary / "cache"}
        )
        scenario = load_scenario(ROOT / "config/worlds/one_drone.yaml")
        runtime = create_runtime(
            config,
            scenario,
            evidence_path=temporary / "evidence.sqlite3",
        )
        catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
        service = CampaignService(
            catalog=catalog,
            state_directory=temporary / "campaign",
            executor=FastSimCampaignExecutor(runtime),
        )
        online_case = catalog.get(ONLINE_CASE_ID)
        if online_case.semantics is None:
            raise RuntimeError("online qualification case lacks scenario semantics")
        expected_event_ids = {
            event.event_id for event in online_case.semantics.scenario_events
        }
        rows: list[dict[str, Any]] = []
        motion_rows: list[dict[str, Any]] = []
        tracking_rms_records: list[dict[str, Any]] = []
        dropout_row: dict[str, Any] | None = None
        missing_ack_row: dict[str, Any] | None = None
        await runtime.start()
        try:
            service.set_lifecycle_state(
                PREDECESSOR_CASE_ID,
                LifecycleState.ACTIVE_DEVELOPMENT,
                actor_id="wp62-66-runtime-qualifier",
                reason="explicitly open the static predecessor lifecycle",
            )
            service.set_active(
                PREDECESSOR_CASE_ID,
                actor_id="wp62-66-runtime-qualifier",
                reason="qualify the required static predecessor",
            )
            predecessor = await service.run_active(
                CampaignRunMode.AUTOMATED_ACCELERATED,
                idempotency_key="wp62-66-runtime:static-predecessor",
            )
            if predecessor.status is not CampaignRunStatus.SUCCEEDED:
                raise RuntimeError("static predecessor did not succeed")
            service.decide_review(
                predecessor.review_id,
                operator_id="wp62-66-runtime-qualifier",
                decision=ReviewDecision.APPROVE,
                reason="automated software-only qualification prerequisite",
            )

            for case_id in WP64_CASE_IDS:
                service.set_lifecycle_state(
                    case_id,
                    LifecycleState.ACTIVE_DEVELOPMENT,
                    actor_id="wp62-66-runtime-qualifier",
                    reason="qualify compact prepared-motion anchor",
                )
                service.set_active(
                    case_id,
                    actor_id="wp62-66-runtime-qualifier",
                    reason="qualify WP-64 motion quality repeats",
                )
                for mode, repeat_count in (
                    (CampaignRunMode.AUTOMATED_ACCELERATED, 3),
                    (CampaignRunMode.OPERATOR_OBSERVED_REALTIME, 1),
                ):
                    for ordinal in range(1, repeat_count + 1):
                        review = await service.run_active(
                            mode,
                            idempotency_key=(
                                f"wp62-66-runtime:wp64:{case_id}:{mode.value}:{ordinal}"
                            ),
                            motion_preparation_request=WP64_PREPARATION_REQUESTS[case_id],
                        )
                        record = _tracking_rms_record(
                            review,
                            packet_id="WP-64",
                            case_id=case_id,
                            mode=mode,
                            ordinal=ordinal,
                        )
                        tracking_rms_records.append(record)
                        motion_analyses = tuple(review.analysis.motion_quality)
                        kinematics = _kinematics_reconciliation(review)
                        passed = (
                            review.status is CampaignRunStatus.SUCCEEDED
                            and len(motion_analyses) == 1
                            and not motion_analyses[0].failed_guards
                            and not motion_analyses[0].missing_guards
                            and record["tracking_rms_m"] is not None
                            and record["tracking_rms_m"] <= 0.05
                            and kinematics["passed"]
                        )
                        execution_id = review.analysis.mission_execution_id
                        evidence = temporary / "campaign" / "evidence" / execution_id
                        csv_path = evidence / "telemetry.csv"
                        prefix = (
                            f"wp64-{case_id.replace('.', '-')}-{mode.value.lower()}-{ordinal}"
                        )
                        retained = {
                            name: _retained_file(
                                evidence / filename,
                                evidence_directory / f"{prefix}-{filename}",
                            )
                            for name, filename in (
                                ("manifest", "manifest.json"),
                                ("execution_bundle", "execution-bundle.json"),
                                ("evaluation", "evaluation.json"),
                                ("analysis", "analysis.json"),
                                ("telemetry_csv", "telemetry.csv"),
                            )
                        }
                        csv_stale_fault_absent = not _csv_has_forbidden_stale_fault(csv_path)
                        passed = passed and csv_stale_fault_absent
                        motion_rows.append(
                            {
                                "packet_id": "WP-64",
                                "case_id": case_id,
                                "mode": mode,
                                "ordinal": ordinal,
                                "run_id": review.run_id,
                                "mission_execution_id": execution_id,
                                "status": review.status,
                                "tracking_rms_record": record,
                                "tracking_oracle": (
                                    "independent-source-time-quintic-pva-v1"
                                ),
                                "motion_preparation_request": WP64_PREPARATION_REQUESTS[
                                    case_id
                                ].model_dump(mode="json"),
                                "failed_guards": (
                                    list(motion_analyses[0].failed_guards)
                                    if motion_analyses
                                    else ["MISSING_MOTION_ANALYSIS"]
                                ),
                                "missing_guards": (
                                    list(motion_analyses[0].missing_guards)
                                    if motion_analyses
                                    else ["MISSING_MOTION_ANALYSIS"]
                                ),
                                "kinematics_gate_reconciliation": kinematics,
                                "csv_stale_fault_absent": csv_stale_fault_absent,
                                "retained_evidence": retained,
                                "passed": passed,
                            }
                        )
                        print(
                            f"wp64 {case_id} {mode.value} {ordinal}: "
                            + ("PASS" if passed else "FAIL"),
                            flush=True,
                        )
            service.set_active(
                ONLINE_CASE_ID,
                actor_id="wp62-66-runtime-qualifier",
                reason="qualify realtime sensed-world moving replanning",
            )

            total_runs = arguments.repetitions + 1
            for ordinal in range(1, total_runs + 1):
                review = await service.run_active(
                    CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
                    idempotency_key=f"wp62-66-runtime:realtime:{ordinal}",
                )
                execution_id = review.analysis.mission_execution_id
                evidence = temporary / "campaign" / "evidence" / execution_id
                manifest_path = evidence / "manifest.json"
                analysis_path = evidence / "analysis.json"
                csv_path = evidence / "telemetry.csv"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                trace_result = _trace_result(
                    {
                        "context": {
                            "campaign_execution_head_trace": manifest[
                                "campaign_execution_head_trace"
                            ]
                        }
                    },
                    expected_event_ids=expected_event_ids,
                )
                vehicle_factors = [
                    item.realtime_factor
                    for item in review.analysis.vehicles
                    if item.realtime_factor is not None
                ]
                retained = {
                    "manifest": _retained_file(
                        manifest_path,
                        evidence_directory / f"realtime-{ordinal}-manifest.json",
                    ),
                    "execution_bundle": _retained_file(
                        evidence / "execution-bundle.json",
                        evidence_directory / f"realtime-{ordinal}-execution-bundle.json",
                    ),
                    "evaluation": _retained_file(
                        evidence / "evaluation.json",
                        evidence_directory / f"realtime-{ordinal}-evaluation.json",
                    ),
                    "analysis": _retained_file(
                        analysis_path,
                        evidence_directory / f"realtime-{ordinal}-analysis.json",
                    ),
                    "telemetry_csv": _retained_file(
                        csv_path,
                        evidence_directory / f"realtime-{ordinal}-telemetry.csv",
                    ),
                }
                csv_stale_fault_absent = not _csv_has_forbidden_stale_fault(csv_path)
                cleanup = _runtime_cleanup_state(runtime, service)
                motion_analyses = tuple(review.analysis.motion_quality)
                kinematics = _kinematics_reconciliation(review)
                passed = (
                    review.status is CampaignRunStatus.SUCCEEDED
                    and review.analysis.all_required_behavior_oracles_passed
                    and len(motion_analyses) == 1
                    and not motion_analyses[0].failed_guards
                    and not motion_analyses[0].missing_guards
                    and motion_analyses[0].vector.tracking_rms_m is not None
                    and motion_analyses[0].vector.tracking_rms_m <= 0.05
                    and kinematics["passed"]
                    and bool(vehicle_factors)
                    and min(vehicle_factors) >= online_case.hard_constraints.minimum_realtime_factor
                    and all(
                        value
                        for key, value in trace_result.items()
                        if key.startswith("all_") or key.endswith("_absent")
                    )
                    and all(cleanup.values())
                    and csv_stale_fault_absent
                )
                rows.append(
                    {
                        "ordinal": ordinal,
                        "purpose": (
                            "IMMEDIATE_RETRY" if ordinal == total_runs else "REQUIRED_REPEAT"
                        ),
                        "run_id": review.run_id,
                        "mission_execution_id": execution_id,
                        "status": review.status,
                        "all_required_behavior_oracles_passed": (
                            review.analysis.all_required_behavior_oracles_passed
                        ),
                        "realtime_factor_by_vehicle": vehicle_factors,
                        "minimum_required_realtime_factor": (
                            online_case.hard_constraints.minimum_realtime_factor
                        ),
                        "trace": trace_result,
                        "cleanup": cleanup,
                        "csv_stale_fault_absent": csv_stale_fault_absent,
                        "motion_quality_failed_guards": (
                            list(motion_analyses[0].failed_guards)
                            if motion_analyses
                            else ["MISSING_MOTION_ANALYSIS"]
                        ),
                        "motion_quality_missing_guards": (
                            list(motion_analyses[0].missing_guards)
                            if motion_analyses
                            else ["MISSING_MOTION_ANALYSIS"]
                        ),
                        "kinematics_gate_reconciliation": kinematics,
                        "tracking_oracle": "independent-source-time-quintic-pva-v1",
                        "retained_evidence": retained,
                        "passed": passed,
                    }
                )
                if ordinal <= arguments.repetitions:
                    tracking_rms_records.append(
                        _tracking_rms_record(
                            review,
                            packet_id="WP-66",
                            case_id=ONLINE_CASE_ID,
                            mode=CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
                            ordinal=ordinal,
                        )
                    )
                print(
                    f"realtime {ordinal}/{total_runs}: " + ("PASS" if passed else "FAIL"),
                    flush=True,
                )
                if not passed:
                    print(
                        json.dumps(
                            {
                                "status": review.status,
                                "realtime_factor_by_vehicle": vehicle_factors,
                                "trace": trace_result,
                                "cleanup": cleanup,
                            },
                            indent=2,
                            default=str,
                        ),
                        flush=True,
                    )
                if ordinal == arguments.repetitions:
                    runtime.scenario = scenario.model_copy(
                        update={
                            "faults": (
                                FaultWindow(
                                    fault=FaultType.STALE_TELEMETRY,
                                    start_s=5.0,
                                    end_s=5.65,
                                    vehicle_id="Alpha",
                                ),
                            )
                        }
                    )
                    try:
                        dropout = await service.run_active(
                            CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
                            idempotency_key="wp62-66-runtime:authoritative-dropout",
                        )
                    finally:
                        runtime.scenario = scenario
                    dropout_execution_id = dropout.analysis.mission_execution_id
                    dropout_evidence = (
                        temporary / "campaign" / "evidence" / dropout_execution_id
                    )
                    dropout_bundle_path = dropout_evidence / "execution-bundle.json"
                    dropout_bundle = json.loads(
                        dropout_bundle_path.read_text(encoding="utf-8")
                    )
                    fleet_result = dropout_bundle["context"]["fleet_result"]
                    events = fleet_result["events"]
                    child_results = fleet_result["child_results"]
                    dropout_cleanup = _runtime_cleanup_state(runtime, service)
                    dropout_retained = {
                        name: _retained_file(
                            dropout_evidence / filename,
                            evidence_directory / f"dropout-{filename}",
                        )
                        for name, filename in (
                            ("manifest", "manifest.json"),
                            ("execution_bundle", "execution-bundle.json"),
                            ("evaluation", "evaluation.json"),
                            ("analysis", "analysis.json"),
                            ("telemetry_csv", "telemetry.csv"),
                        )
                    }
                    dropout_passed = (
                        dropout.status is not CampaignRunStatus.SUCCEEDED
                        and fleet_result["status"] == "FAILED"
                        and len(child_results) == 1
                        and child_results[0]["mission_result"]["reason_code"]
                        == "TELEMETRY_STALE"
                        and sum(
                            event["event_type"] == "VEHICLE_ABORT_REQUESTED"
                            and event["details"].get("reason")
                            == "STALE_FLEET_OBSERVATION"
                            for event in events
                        )
                        == 1
                        and sum(
                            event["event_type"] == "STALE_MEMBER_ABORTED"
                            for event in events
                        )
                        == 1
                        and all(dropout_cleanup.values())
                    )
                    dropout_row = {
                        "run_id": dropout.run_id,
                        "mission_execution_id": dropout_execution_id,
                        "status": dropout.status,
                        "fault": {
                            "kind": FaultType.STALE_TELEMETRY,
                            "start_source_s": 5.0,
                            "end_source_s": 5.65,
                            "duration_s": 0.65,
                            "freshness_limit_s": (
                                online_case.hard_constraints.observation_freshness_limit_s
                            ),
                        },
                        "child_reason_code": (
                            child_results[0]["mission_result"]["reason_code"]
                            if child_results
                            else None
                        ),
                        "stale_abort_request_count": sum(
                            event["event_type"] == "VEHICLE_ABORT_REQUESTED"
                            and event["details"].get("reason")
                            == "STALE_FLEET_OBSERVATION"
                            for event in events
                        ),
                        "stale_member_abort_count": sum(
                            event["event_type"] == "STALE_MEMBER_ABORTED"
                            for event in events
                        ),
                        "cleanup": dropout_cleanup,
                        "retained_evidence": dropout_retained,
                        "passed": dropout_passed,
                    }
                    print(
                        "authoritative dropout: "
                        + ("PASS" if dropout_passed else "FAIL"),
                        flush=True,
                    )
                    with patch.object(
                        runtime.supervisor,
                        "prepare_trajectory_replacement",
                        side_effect=RuntimeError(
                            "INJECTED_MISSING_SUPERVISOR_PREPARATION_ACK"
                        ),
                    ):
                        missing_ack = await service.run_active(
                            CampaignRunMode.OPERATOR_OBSERVED_REALTIME,
                            idempotency_key="wp62-66-runtime:missing-preparation-ack",
                        )
                    missing_ack_execution_id = missing_ack.analysis.mission_execution_id
                    missing_ack_evidence = (
                        temporary / "campaign" / "evidence" / missing_ack_execution_id
                    )
                    missing_ack_bundle = json.loads(
                        (missing_ack_evidence / "execution-bundle.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    missing_ack_trace = missing_ack_bundle["context"][
                        "campaign_execution_head_trace"
                    ]
                    missing_ack_records = missing_ack_trace["records"]
                    safe_fallback_records = [
                        record
                        for record in missing_ack_records
                        if record.get("stage") == "SAFE_FALLBACK_EXECUTED"
                    ]
                    missing_ack_cleanup = _runtime_cleanup_state(runtime, service)
                    missing_ack_retained = {
                        name: _retained_file(
                            missing_ack_evidence / filename,
                            evidence_directory / f"missing-ack-{filename}",
                        )
                        for name, filename in (
                            ("manifest", "manifest.json"),
                            ("execution_bundle", "execution-bundle.json"),
                            ("evaluation", "evaluation.json"),
                            ("analysis", "analysis.json"),
                            ("telemetry_csv", "telemetry.csv"),
                        )
                    }
                    missing_ack_passed = (
                        len(safe_fallback_records) == 1
                        and safe_fallback_records[0]["stopped_or_landed_observation"]
                        is True
                        and not any(
                            record.get("decision_sha256")
                            or record.get("execution_disposition") == "DISPATCHED"
                            for record in missing_ack_records
                        )
                        and not any(
                            record.get("stage") == "UNQUALIFIED_EMERGENCY_FALLBACK"
                            for record in missing_ack_records
                        )
                        and any(
                            "INJECTED_MISSING_SUPERVISOR_PREPARATION_ACK"
                            in str(record.get("reason", ""))
                            for record in missing_ack_records
                        )
                        and all(missing_ack_cleanup.values())
                    )
                    missing_ack_row = {
                        "run_id": missing_ack.run_id,
                        "mission_execution_id": missing_ack_execution_id,
                        "status": missing_ack.status,
                        "injected_boundary": "SUPERVISOR_PREPARATION_ACK_MISSING",
                        "atomic_commit_count": sum(
                            bool(record.get("decision_sha256"))
                            for record in missing_ack_records
                        ),
                        "replacement_dispatch_count": sum(
                            record.get("execution_disposition") == "DISPATCHED"
                            for record in missing_ack_records
                        ),
                        "safe_fallback_records": safe_fallback_records,
                        "cleanup": missing_ack_cleanup,
                        "retained_evidence": missing_ack_retained,
                        "passed": missing_ack_passed,
                    }
                    print(
                        "missing Supervisor preparation ack: "
                        + ("PASS" if missing_ack_passed else "FAIL"),
                        flush=True,
                    )
        finally:
            await runtime.stop()

    tracking_rms_qualification = qualify_tracking_rms_repeats(tracking_rms_records)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "qualification_id": "wp62-66-runtime-qualification-v1",
        "accepted_design_payload_sha256s": {
            "base": "52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6",
            "r2": "4201ea8a858e1d91b3f5877bdfacbd4716b5fa59b42cac9ac9d796cf38477806",
            "r3": "5c24eb560133232cf5fb9e7a5105a727083f78854f07cba85c86c2d5ee6c3b5d",
            "r4": "34d6640165a86a86ad741fbc16202f4f4ec22fe6a06f18de701bec6900a99a1b",
        },
        "claim_boundary": (
            "Normal CampaignService production entry in deterministic Fast Sim realtime "
            "mode. No hardware, physical-flight, live-Isaac, or aerodynamic-fidelity claim."
        ),
        "tracking_oracle": {
            "oracle_id": "independent-source-time-quintic-pva-v1",
            "production_sampler_imported": False,
            "temporal_lag_counterexample_test": (
                "tests/campaign/test_motion_quality_contract.py::"
                "test_independent_temporal_oracle_detects_same_polyline_time_lag"
            ),
        },
        "case_id": ONLINE_CASE_ID,
        "case_sha256": online_case.case_sha256,
        "required_repeat_count": arguments.repetitions,
        "immediate_retry_count": 1,
        "runs": rows,
        "authoritative_telemetry_dropout": dropout_row,
        "missing_preparation_acknowledgement": missing_ack_row,
        "motion_quality_runs": motion_rows,
        "tracking_rms_repeat_qualification": tracking_rms_qualification.model_dump(
            mode="json"
        ),
        "all_required_repeats_and_retry_passed": (
            len(rows) == arguments.repetitions + 1
            and all(item["passed"] for item in rows)
            and dropout_row is not None
            and dropout_row["passed"]
            and missing_ack_row is not None
            and missing_ack_row["passed"]
            and len(motion_rows) == 12
            and all(item["passed"] for item in motion_rows)
            and tracking_rms_qualification.passed
        ),
    }
    payload["qualification_sha256"] = canonical_sha256(payload)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"runtime qualification -> {arguments.output}", flush=True)
    return 0 if payload["all_required_repeats_and_retry_passed"] else 1


def main() -> int:
    return asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
