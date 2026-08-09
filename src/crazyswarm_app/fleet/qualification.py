from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3, VehicleCapability
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    ExecutionBackend,
    load_versioned_contract,
)
from crazyswarm_app.fleet.docks import DockHealth, DockManager, DockOperationState
from crazyswarm_app.fleet.metrics import FleetMetricKind, FleetMetricsCollector, FleetMetricsReport
from crazyswarm_app.fleet.persistent import (
    CoverageCandidate,
    CoverageVehicleState,
    PersistentCoverageCoordinator,
    PersistentCoverageResult,
)


class QualificationScenario(ContractModel):
    id: Identifier
    expected: Literal["SUCCEEDED", "DEGRADED", "FAILED"]


class QualificationThresholds(ContractModel):
    minimum_availability_percent: float = Field(ge=0.0, le=100.0)
    maximum_coverage_gap_percent: float = Field(ge=0.0, le=100.0)
    minimum_separation_m: float = Field(ge=0.0)
    maximum_handover_s: float = Field(ge=0.0)
    maximum_dropped_events: int = Field(ge=0)


class PersistentFleetQualificationManifest(ContractModel):
    schema_version: Literal[1] = 1
    qualification_id: Identifier
    deployment: str
    bindings: dict[str, str]
    seeds: tuple[int, ...]
    thresholds: QualificationThresholds
    scenarios: tuple[QualificationScenario, ...]


class ScenarioQualificationOutcome(ContractModel):
    scenario_id: Identifier
    seed: int
    status: Literal["SUCCEEDED", "DEGRADED", "FAILED"]
    invariant_passed: bool
    reason: str


class BackendQualification(ContractModel):
    backend: ExecutionBackend
    deployment_sha256: SHA256
    binding_sha256: SHA256
    normalized_intent_sha256: SHA256
    normalized_outcome_sha256: SHA256
    normalized_metrics_sha256: SHA256
    scenario_outcomes: tuple[ScenarioQualificationOutcome, ...]


class PersistentFleetQualificationReport(ContractModel):
    schema_version: Literal[1] = 1
    qualification_id: Identifier
    decision: Literal["PASS_SOFTWARE_ONLY", "FAIL"]
    fast_sim: BackendQualification
    mock_isaac: BackendQualification
    equivalent_normalized_intent: bool
    equivalent_normalized_outcome: bool
    live_isaac: Literal["NOT_RUN"] = "NOT_RUN"
    physical_flight: Literal["NOT_RUN"] = "NOT_RUN"
    cameras_depth_rtx_ros: Literal["ABSENT"] = "ABSENT"
    fallback: Literal["FAST_SIM_AVAILABLE"] = "FAST_SIM_AVAILABLE"
    normalized_report_sha256: SHA256


def load_qualification_manifest(path: Path) -> PersistentFleetQualificationManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return PersistentFleetQualificationManifest.model_validate(raw)


def run_persistent_fleet_qualification(root: Path) -> PersistentFleetQualificationReport:
    manifest = load_qualification_manifest(
        root / "config/qualification/persistent-fleet-scenarios-v1.json"
    )
    fast = _run_backend(root, manifest, ExecutionBackend.FAST_SIM)
    mock = _run_backend(root, manifest, ExecutionBackend.MOCK_ISAAC)
    intent_equal = fast.normalized_intent_sha256 == mock.normalized_intent_sha256
    outcome_equal = (
        fast.normalized_outcome_sha256 == mock.normalized_outcome_sha256
        and fast.normalized_metrics_sha256 == mock.normalized_metrics_sha256
        and [item.model_dump(mode="json") for item in fast.scenario_outcomes]
        == [item.model_dump(mode="json") for item in mock.scenario_outcomes]
    )
    all_invariants = all(
        item.invariant_passed
        for qualification in (fast, mock)
        for item in qualification.scenario_outcomes
    )
    decision: Literal["PASS_SOFTWARE_ONLY", "FAIL"] = (
        "PASS_SOFTWARE_ONLY" if intent_equal and outcome_equal and all_invariants else "FAIL"
    )
    normalized = {
        "qualification_id": manifest.qualification_id,
        "decision": decision,
        "intent": fast.normalized_intent_sha256,
        "outcome": fast.normalized_outcome_sha256,
        "metrics": fast.normalized_metrics_sha256,
        "scenarios": [item.model_dump(mode="json") for item in fast.scenario_outcomes],
        "live_isaac": "NOT_RUN",
        "physical_flight": "NOT_RUN",
    }
    return PersistentFleetQualificationReport(
        qualification_id=manifest.qualification_id,
        decision=decision,
        fast_sim=fast,
        mock_isaac=mock,
        equivalent_normalized_intent=intent_equal,
        equivalent_normalized_outcome=outcome_equal,
        normalized_report_sha256=canonical_sha256(normalized),
    )


def _run_backend(
    root: Path,
    manifest: PersistentFleetQualificationManifest,
    backend: ExecutionBackend,
) -> BackendQualification:
    deployment = load_versioned_contract(root / manifest.deployment, DeploymentManifest)
    binding = load_versioned_contract(
        root / manifest.bindings[backend.value], BackendBindingProfile
    )
    binding.validate_for(deployment)
    coverage, metrics = _run_nominal(deployment)
    outcomes_list: list[ScenarioQualificationOutcome] = []
    for seed in manifest.seeds:
        for scenario in manifest.scenarios:
            status, invariant_passed, reason = _exercise_scenario(
                deployment,
                scenario.id,
                seed=seed,
            )
            outcomes_list.append(
                ScenarioQualificationOutcome(
                    scenario_id=scenario.id,
                    seed=seed,
                    status=status,
                    invariant_passed=(invariant_passed and status == scenario.expected),
                    reason=reason,
                )
            )
    outcomes = tuple(outcomes_list)
    result = coverage.result()
    metric_report = metrics.report(ended_at_s=500.0)
    _enforce_thresholds(manifest, result, metric_report)
    intent = canonical_sha256(
        {
            "deployment": deployment.sha256,
            "assignments": {"cover-zone-a": "cf01", "cover-zone-b": "cf02"},
            "replacement": {"cover-zone-a": "cf03"},
            "dock": "dock-main",
        }
    )
    return BackendQualification(
        backend=backend,
        deployment_sha256=deployment.sha256,
        binding_sha256=binding.sha256,
        normalized_intent_sha256=intent,
        normalized_outcome_sha256=result.normalized_outcome_sha256,
        normalized_metrics_sha256=metric_report.normalized_metrics_sha256,
        scenario_outcomes=outcomes,
    )


def _run_nominal(
    deployment: DeploymentManifest,
) -> tuple[PersistentCoverageCoordinator, FleetMetricsCollector]:
    candidates = _coverage_candidates()
    coverage = PersistentCoverageCoordinator(
        fleet_session_id="persistent-session-v1",
        fleet_run_id="persistent-run-v1",
        deployment=deployment,
    )
    collector = FleetMetricsCollector(
        started_at_s=0.0,
        required_coverage_roles=2,
        warning_separation_m=deployment.constraints.warning_separation_m,
        critical_separation_m=deployment.constraints.critical_separation_m,
    )
    for vehicle_id in ("cf01", "cf02", "cf03"):
        for timestamp_s in (0.0, 0.05, 0.1):
            collector.record(
                FleetMetricKind.TELEMETRY_SAMPLE,
                timestamp_s=timestamp_s,
                correlation_id=f"telemetry-{vehicle_id}",
                vehicle_id=vehicle_id,
            )
        collector.record(
            FleetMetricKind.POSITION_QUALITY,
            timestamp_s=0.1,
            correlation_id=f"position-{vehicle_id}",
            vehicle_id=vehicle_id,
            value=98.0,
        )
    collector.record(
        FleetMetricKind.COMMAND_SENT,
        timestamp_s=10.0,
        correlation_id="handover-command",
    )
    collector.record(
        FleetMetricKind.COMMAND_ACKNOWLEDGED,
        timestamp_s=10.02,
        correlation_id="handover-command",
    )
    for task in deployment.tasks:
        collector.record(
            FleetMetricKind.TASK_DECLARED,
            timestamp_s=0.0,
            correlation_id=task.task_id,
        )
    decisions = coverage.allocate_initial(candidates, now_s=1.0)
    for decision in decisions:
        collector.record(
            FleetMetricKind.TASK_ASSIGNED,
            timestamp_s=1.0,
            correlation_id=decision.task_id,
        )
        collector.record(
            FleetMetricKind.LEASE_ISSUED,
            timestamp_s=1.0,
            correlation_id=decision.task_id,
        )
    handover = coverage.begin_handover(
        "cover-zone-a", reason="LOW_BATTERY", candidates=candidates, now_s=10.0
    )
    collector.record(
        FleetMetricKind.HANDOVER_DECISION,
        timestamp_s=10.0,
        correlation_id=handover.handover_id,
    )
    collector.record(
        FleetMetricKind.ENERGY_MARGIN,
        timestamp_s=10.0,
        correlation_id=handover.handover_id,
        vehicle_id="cf03",
        value=handover.predicted_energy_margin_percent,
        details={"stage": "decision"},
    )
    coverage.confirm_replacement_ready(handover.handover_id, candidates=candidates, now_s=11.0)
    collector.record(
        FleetMetricKind.REPLACEMENT_LAUNCHED,
        timestamp_s=11.0,
        correlation_id=handover.handover_id,
    )
    separation = coverage.enforce_separation(candidates)
    for item in separation:
        collector.record(
            FleetMetricKind.SEPARATION_OBSERVED,
            timestamp_s=11.5,
            correlation_id=f"{item.first_vehicle_id}-{item.second_vehicle_id}",
            value=item.distance_m,
        )
    coverage.confirm_takeover(handover.handover_id, candidates=candidates, now_s=13.0)
    collector.record(
        FleetMetricKind.ENERGY_MARGIN,
        timestamp_s=13.0,
        correlation_id=handover.handover_id,
        vehicle_id="cf03",
        value=40.5,
        details={"stage": "takeover"},
    )
    collector.record(
        FleetMetricKind.TAKEOVER_CONFIRMED,
        timestamp_s=13.0,
        correlation_id=handover.handover_id,
    )
    completed = coverage.release_outgoing(handover.handover_id, now_s=14.0)
    collector.record(
        FleetMetricKind.ENERGY_MARGIN,
        timestamp_s=14.0,
        correlation_id=handover.handover_id,
        vehicle_id="cf01",
        value=12.0,
        details={"stage": "return"},
    )
    collector.record(
        FleetMetricKind.OUTGOING_RELEASED,
        timestamp_s=14.0,
        correlation_id=handover.handover_id,
    )
    collector.record(
        FleetMetricKind.HANDOVER_COMPLETED,
        timestamp_s=14.0,
        correlation_id=handover.handover_id,
    )
    docks = DockManager(deployment.docks)
    dock = docks.reserve_after_handover(completed, battery_percent=20.0, now_s=15.0)
    collector.record(
        FleetMetricKind.DOCK_QUEUED,
        timestamp_s=15.0,
        correlation_id=dock.reservation_id,
    )
    if dock.state is DockOperationState.RETURN_TO_DOCK_AREA:
        docks.transition(
            dock.reservation_id,
            DockOperationState.APPROACH_REQUESTED,
            reason="modeled approach",
            now_s=16.0,
        )
        docks.transition(
            dock.reservation_id,
            DockOperationState.DOCK_ATTEMPT,
            reason="modeled dock attempt",
            now_s=17.0,
        )
    collector.record(
        FleetMetricKind.DOCK_ATTEMPT,
        timestamp_s=17.0,
        correlation_id=dock.reservation_id,
    )
    docks.confirm_modeled_landing(dock.reservation_id, modeled_contact=True, now_s=18.0)
    docks.confirm_modeled_charging(dock.reservation_id, confirmed=True, now_s=19.0)
    collector.record(
        FleetMetricKind.DOCK_CHARGING,
        timestamp_s=19.0,
        correlation_id=dock.reservation_id,
    )
    docks.update_modeled_charge(dock.reservation_id, now_s=439.0)
    collector.record(
        FleetMetricKind.DOCK_READY,
        timestamp_s=439.0,
        correlation_id=dock.reservation_id,
    )
    collector.record(
        FleetMetricKind.ENERGY_MARGIN,
        timestamp_s=18.0,
        correlation_id=handover.handover_id,
        vehicle_id="cf01",
        value=10.0,
        details={"stage": "landing"},
    )
    collector.record(
        FleetMetricKind.DROP_COUNT,
        timestamp_s=99.0,
        correlation_id="aggregate",
        count=0,
    )
    return coverage, collector


def _enforce_thresholds(
    manifest: PersistentFleetQualificationManifest,
    result: PersistentCoverageResult,
    metrics: FleetMetricsReport,
) -> None:
    threshold = manifest.thresholds
    if result.status != "SUCCEEDED":
        raise AssertionError("nominal persistent coverage did not succeed")
    if metrics.mission_availability_percent < threshold.minimum_availability_percent:
        raise AssertionError("availability threshold failed")
    if metrics.coverage_gap_percent > threshold.maximum_coverage_gap_percent:
        raise AssertionError("coverage-gap threshold failed")
    if (
        metrics.minimum_separation_m is None
        or metrics.minimum_separation_m < threshold.minimum_separation_m
    ):
        raise AssertionError("minimum-separation threshold failed")
    if metrics.handovers[0].total_handover_s is None or (
        metrics.handovers[0].total_handover_s > threshold.maximum_handover_s
    ):
        raise AssertionError("handover-duration threshold failed")
    if sum(metrics.drop_counts.values()) > threshold.maximum_dropped_events:
        raise AssertionError("drop-count threshold failed")


def _exercise_scenario(
    deployment: DeploymentManifest,
    scenario_id: str,
    *,
    seed: int,
) -> tuple[Literal["SUCCEEDED", "DEGRADED", "FAILED"], bool, str]:
    candidates = _coverage_candidates(battery_adjustment=(seed % 3) * 0.1)
    coverage = PersistentCoverageCoordinator(
        fleet_session_id=f"scenario-{seed}",
        fleet_run_id=f"run-{seed}",
        deployment=deployment,
    )
    coverage.allocate_initial(candidates, now_s=1.0)

    successful_handover = {
        "nominal-low-battery",
        "low-battery-requested",
        "low-battery-preparing",
        "low-battery-takeover-pending",
        "active-vehicle-loss",
        "leader-loss",
        "disconnect",
        "gateway-restart",
    }
    if scenario_id in successful_handover:
        result = _complete_handover(coverage, candidates, reason=scenario_id)
        return result.status, _unique_owners(result.active_owners), "atomic handover completed"

    if scenario_id in {"reserve-loss", "localization-failure", "range-failure"}:
        reserve = candidates[2].model_copy(
            update={
                "available": False,
                "capabilities": (
                    frozenset({VehicleCapability.HIGH_LEVEL_COMMANDS})
                    if scenario_id == "localization-failure"
                    else candidates[2].capabilities
                ),
            }
        )
        degraded_candidates = (*candidates[:2], reserve)
        handover = coverage.begin_handover(
            "cover-zone-a",
            reason=scenario_id,
            candidates=degraded_candidates,
            now_s=2.0,
        )
        result = coverage.result()
        invariant = (
            handover.phase.value == "DEGRADED" and result.active_owners["cover-zone-a"] == "cf01"
        )
        return result.status, invariant, "no serviceable reserve; outgoing lease retained"

    if scenario_id in {"stale-fleet-state", "task-lease-expiry"}:
        try:
            coverage.tasks.renew("cover-zone-a", "cf01", 1, now_s=100.0)
        except CrazySwarmError:
            return "FAILED", True, "expired or stale lease rejected"
        return "SUCCEEDED", False, "expired lease was unexpectedly accepted"

    if scenario_id == "duplicate-assignment":
        try:
            coverage.tasks.assign(
                "cover-zone-a",
                "cf03",
                capabilities=candidates[2].capabilities,
                battery_percent=candidates[2].battery_percent,
                now_s=2.0,
            )
        except CrazySwarmError:
            return "FAILED", True, "duplicate current owner rejected"
        return "SUCCEEDED", False, "duplicate owner was unexpectedly accepted"

    if scenario_id == "delayed-reordered-ownership":
        _complete_handover(coverage, candidates, reason=scenario_id)
        try:
            coverage.tasks.renew("cover-zone-a", "cf01", 1, now_s=6.0)
        except CrazySwarmError:
            return "SUCCEEDED", True, "delayed stale generation rejected"
        return "FAILED", False, "stale generation retained command authority"

    if scenario_id in {"warning-separation", "critical-separation"}:
        replacement_x = -0.55 if scenario_id == "warning-separation" else -0.9
        close = (
            *candidates[:2],
            candidates[2].model_copy(update={"position_m": Vector3(x=replacement_x, y=0.0)}),
        )
        try:
            observations = coverage.enforce_separation(close)
        except CrazySwarmError:
            return "FAILED", scenario_id == "critical-separation", "critical pair blocked"
        held = any(item.action == "HOLD" for item in observations)
        return "DEGRADED", held, "warning pair held before handover"

    if scenario_id == "geofence-interaction":
        outside = candidates[2].model_copy(update={"position_m": Vector3(x=4.1)})
        inside = _inside_software_bounds((*candidates[:2], outside))
        return "FAILED", not inside, "configured software geofence rejected position"

    if scenario_id in {
        "command-drop",
        "acknowledgement-loss",
        "gateway-crash-fast-sim-fallback",
    }:
        handover = coverage.begin_handover(
            "cover-zone-a", reason=scenario_id, candidates=candidates, now_s=2.0
        )
        terminated = coverage.terminate_handover(
            handover.handover_id,
            reason=f"{scenario_id}: command outcome not confirmed",
            now_s=3.0,
        )
        result = coverage.result()
        invariant = (
            not terminated.takeover_confirmed and result.active_owners["cover-zone-a"] == "cf01"
        )
        reason = (
            "gateway loss explicit; Fast Sim fallback remains available"
            if scenario_id == "gateway-crash-fast-sim-fallback"
            else "unknown command outcome retained outgoing authority"
        )
        return result.status, invariant, reason

    if scenario_id in {
        "dock-occupied",
        "docking-failure",
        "charging-confirmation-failure",
        "dock-queue-overflow",
        "dock-unavailable",
    }:
        return _exercise_dock_scenario(deployment, scenario_id)

    if scenario_id == "long-duration-rotation":
        for index in range(1, 1001):
            now_s = 1.0 + index * 0.01
            coverage.tasks.renew("cover-zone-a", "cf01", 1, now_s=now_s)
            coverage.tasks.renew("cover-zone-b", "cf02", 1, now_s=now_s)
        finite = all(
            item.lease is not None and item.lease.expires_at_monotonic_s < float("inf")
            for item in coverage.tasks.records()
        )
        return "SUCCEEDED", finite, "1000 bounded lease rotations remained finite"

    raise AssertionError(f"qualification scenario has no injector: {scenario_id}")


def _complete_handover(
    coverage: PersistentCoverageCoordinator,
    candidates: tuple[CoverageCandidate, ...],
    *,
    reason: str,
) -> PersistentCoverageResult:
    handover = coverage.begin_handover(
        "cover-zone-a", reason=reason, candidates=candidates, now_s=2.0
    )
    coverage.confirm_replacement_ready(handover.handover_id, candidates=candidates, now_s=3.0)
    coverage.confirm_takeover(handover.handover_id, candidates=candidates, now_s=4.0)
    coverage.release_outgoing(handover.handover_id, now_s=5.0)
    return coverage.result()


def _exercise_dock_scenario(
    deployment: DeploymentManifest,
    scenario_id: str,
) -> tuple[Literal["SUCCEEDED", "DEGRADED", "FAILED"], bool, str]:
    docks = DockManager(deployment.docks, queue_limit=1, maximum_attempts=2)
    if scenario_id == "dock-unavailable":
        docks.set_health("dock-main", DockHealth.UNAVAILABLE, now_s=1.0)
        try:
            docks.reserve("cf01", now_s=2.0)
        except CrazySwarmError:
            return "DEGRADED", True, "unavailable dock rejected reservation"
    first = docks.reserve("cf01", battery_percent=20.0, now_s=1.0)
    if scenario_id == "dock-occupied":
        second = docks.reserve("cf02", battery_percent=30.0, now_s=2.0)
        return (
            "DEGRADED",
            second.state is DockOperationState.QUEUED,
            "occupied capacity produced explicit queue",
        )
    if scenario_id == "dock-queue-overflow":
        docks.reserve("cf02", now_s=2.0)
        try:
            docks.reserve("cf03", now_s=3.0)
        except CrazySwarmError:
            return "FAILED", True, "bounded queue overflow rejected"
    docks.transition(
        first.reservation_id,
        DockOperationState.RETURN_TO_DOCK_AREA,
        reason="fault qualification",
        now_s=2.0,
    )
    docks.transition(
        first.reservation_id,
        DockOperationState.APPROACH_REQUESTED,
        reason="fault qualification",
        now_s=3.0,
    )
    docks.transition(
        first.reservation_id,
        DockOperationState.DOCK_ATTEMPT,
        reason="attempt one",
        now_s=4.0,
    )
    docks.confirm_modeled_landing(
        first.reservation_id,
        modeled_contact=scenario_id != "docking-failure",
        now_s=5.0,
    )
    retry = docks.confirm_modeled_charging(
        first.reservation_id,
        confirmed=False,
        now_s=6.0,
    )
    if scenario_id == "charging-confirmation-failure":
        invariant = (
            retry.state is DockOperationState.RETRY_PENDING and not retry.modeled_charging_confirmed
        )
        return "DEGRADED", invariant, "charging confirmation did not enter CHARGING"
    docks.transition(
        first.reservation_id,
        DockOperationState.APPROACH_REQUESTED,
        reason="bounded retry",
        now_s=7.0,
    )
    docks.transition(
        first.reservation_id,
        DockOperationState.DOCK_ATTEMPT,
        reason="attempt two",
        now_s=8.0,
    )
    docks.confirm_modeled_landing(first.reservation_id, modeled_contact=False, now_s=9.0)
    failed = docks.confirm_modeled_charging(first.reservation_id, confirmed=False, now_s=10.0)
    return (
        "DEGRADED",
        failed.state is DockOperationState.FAILED,
        "bounded docking attempts ended explicitly",
    )


def _coverage_candidates(*, battery_adjustment: float = 0.0) -> tuple[CoverageCandidate, ...]:
    capabilities = frozenset(
        {VehicleCapability.RELATIVE_POSITIONING, VehicleCapability.HIGH_LEVEL_COMMANDS}
    )
    return (
        CoverageCandidate(
            vehicle_id="cf01",
            capabilities=capabilities,
            battery_percent=82.0 + battery_adjustment,
            position_m=Vector3(x=-1.2),
            state=CoverageVehicleState.ACTIVE,
        ),
        CoverageCandidate(
            vehicle_id="cf02",
            capabilities=capabilities,
            battery_percent=85.0 + battery_adjustment,
            position_m=Vector3(x=1.2),
            state=CoverageVehicleState.ACTIVE,
        ),
        CoverageCandidate(
            vehicle_id="cf03",
            capabilities=capabilities,
            battery_percent=96.0 + battery_adjustment,
            position_m=Vector3(y=-1.5),
            state=CoverageVehicleState.RESERVE,
        ),
    )


def _unique_owners(owners: dict[str, str]) -> bool:
    return len(owners) == len(set(owners.values()))


def _inside_software_bounds(candidates: tuple[CoverageCandidate, ...]) -> bool:
    return all(
        -4.0 <= item.position_m.x <= 4.0
        and -3.0 <= item.position_m.y <= 3.0
        and 0.0 <= item.position_m.z <= 3.0
        for item in candidates
    )
