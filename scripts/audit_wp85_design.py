#!/usr/bin/env python3
"""Focused executable prefreeze audit for the WP-85 successor correction.

The artifact intentionally contains only deterministic semantic observations. Runtime
latencies and fresh-state transaction hashes are compared inside each witness but are
not serialized as cross-run identities.
"""

from __future__ import annotations

import asyncio
import ast
import hashlib
import json
import sys
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any

from crazyswarm_app.campaign import execution_head as execution_head_module
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.execution_head import CampaignExecutionHead
from crazyswarm_app.campaign.planner import BoundedJointPlanner
from crazyswarm_app.campaign.replanning import (
    ChangedWorldSafetyMonitor,
    plan_changed_world_replacement,
    rebase_changed_world_replacement,
)
from crazyswarm_app.campaign.submissions import resolve_planning_package
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.commands import TrajectoryReplacementPreparationReceipt
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.trajectory import sample_trajectory
from crazyswarm_app.simulation.sensors import (
    PerceptionModelConfig,
    SimulatedPerceptionObservationSource,
)
from crazyswarm_app.simulation.world import (
    DynamicWorldTimeline,
    ObstacleConfig,
    WorldTruthEvent,
    WorldTruthEventKind,
)


ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "40cd9947f87eb9bf2719d72e7c72ea867eab9977"
SOURCE_CASE_ID = "1d.online_obstacle_replan.dynamic_nominal"
WP84_BASE_PAYLOAD_SHA256 = "c993df7c80b18a5fe5b4e3fe950d94ce736d1fb6c851dbb9b69cf2f2cc17d4a0"
WP84_R1_PAYLOAD_SHA256 = "1dc093e440d8e2e624e060d8fb37370f761ca99b4d68506bc7927e0076641c73"
WP84_BOUNDARY_ARTIFACT_SHA256 = "8140602daeb08845dc242f5e3be94620e37b3fcbedab83c87e8d31e05bfbabab"

WP85_BOUNDARY_DELTA = {
    "docs/project/REQUIREMENTS_CHANGELOG.md",
    "docs/project/requirements/README.md",
    "docs/project/requirements/workflow/COST_SCOPE_AND_HANDOFF.md",
    "scripts/audit_wp85_design.py",
    "scripts/check_requirement_catalog.py",
    "missions/campaigns/sim/qualification/wp85-design-audit-v1.json",
}

PRODUCTION_TRANSIT_ROOTS = {
    "src/crazyswarm_app/api/app.py",
    "src/crazyswarm_app/api/runtime.py",
    "src/crazyswarm_app/campaign/service.py",
    "src/crazyswarm_app/campaign/runtime_executor.py",
    "src/crazyswarm_app/campaign/execution_head.py",
    "src/crazyswarm_app/observability/storage.py",
}


def _strict_stress_seed(value: object) -> int:
    if type(value) is not int:  # exact public-domain boundary; bool is deliberately rejected
        raise TypeError("variation_seed must be an exact integer")
    if value < 0 or value > 34:
        raise ValueError("variation_seed must be in 0..34")
    return value


def _seed_boundary_witnesses() -> dict[str, Any]:
    passing = {}
    for value in (0, 1, 34):
        passing[str(value)] = _strict_stress_seed(value)
    failing_values: tuple[tuple[str, object], ...] = (
        ("bool_false", False),
        ("bool_true", True),
        ("float_integral", 1.0),
        ("float_fractional", 1.5),
        ("string", "1"),
        ("below", -1),
        ("above", 35),
        ("none", None),
    )
    rejected = {}
    for label, value in failing_values:
        try:
            _strict_stress_seed(value)
        except (TypeError, ValueError) as error:
            rejected[label] = {
                "input_type": type(value).__name__,
                "error_type": type(error).__name__,
                "message": str(error),
            }
        else:  # pragma: no cover - makes a missing rejection fail the audit loudly
            rejected[label] = {"error_type": None}
    return {"passing": passing, "rejected": rejected}


class _Boundary(Enum):
    NONE = "NONE"
    SAFE_PREFIX = "SAFE_PREFIX"
    ABORT = "ABORT"
    FEASIBILITY = "FEASIBILITY"
    CUTOVER = "CUTOVER"
    PROPOSAL = "PROPOSAL"
    RECEIPT = "RECEIPT"


class _Fault(Enum):
    NONE = "NONE"
    MISSING = "MISSING"
    TAMPERED = "TAMPERED"


@dataclass(frozen=True, slots=True)
class _Mutation:
    label: str
    boundary: _Boundary
    fault: _Fault


class _SpyContext:
    def __init__(self, *, sampled: Any, mutation: _Mutation) -> None:
        self.role_id = "Alpha"
        self.vehicle_id = "Alpha"
        self.sampled = sampled
        self.mutation = mutation
        self.old_cancelled = asyncio.Event()
        self.observation_sequence = 0
        self.replacement_dispatch_calls = 0
        self.fallback_calls: list[str] = []

    async def execute_trajectory(self, trajectory: Any) -> None:
        del trajectory
        await self.old_cancelled.wait()

    async def observe(self, *, timeout_s: float) -> Any:
        del timeout_s
        self.observation_sequence += 1
        stopped = bool(self.fallback_calls)
        return SimpleNamespace(
            valid=True,
            sequence=self.observation_sequence,
            source_timestamp_s=2.12,
            estimated_position_m=self.sampled.position_m,
            velocity_m_s=Vector3() if stopped else self.sampled.velocity_m_s,
        )

    async def prepare_replanned_trajectory(
        self,
        trajectory: Any,
        *,
        accepted_plan_id: str,
        accepted_plan_sha256: str,
        replacement_authority_sha256: str,
        proposal_sha256: str,
        safe_prefix_certificate_sha256: str,
        active_trajectory_sha256: str,
    ) -> TrajectoryReplacementPreparationReceipt:
        del accepted_plan_id
        if (
            self.mutation.boundary is _Boundary.RECEIPT
            and self.mutation.fault is _Fault.MISSING
        ):
            return None  # type: ignore[return-value]
        receipt = TrajectoryReplacementPreparationReceipt(
            vehicle_id="Alpha",
            role_id="Alpha",
            mission_run_id="wp85-design-command-spy",
            fleet_binding_sha256="d" * 64,
            proposal_sha256=proposal_sha256,
            safe_prefix_certificate_sha256=safe_prefix_certificate_sha256,
            active_trajectory_sha256=active_trajectory_sha256,
            replacement_trajectory_sha256=trajectory.sha256,
            replacement_route_sha256=trajectory.route_sha256,
            replacement_plan_sha256=accepted_plan_sha256,
            replacement_authority_sha256=replacement_authority_sha256,
            prepared_at_monotonic_s=1.0,
        )
        # A real Supervisor preparation receipt acknowledges cancellation of the
        # old future before atomic commit; mirror that command-boundary effect so the
        # production head can drain the superseded task after dispatch.
        self.old_cancelled.set()
        if (
            self.mutation.boundary is _Boundary.RECEIPT
            and self.mutation.fault is _Fault.TAMPERED
        ):
            return receipt.model_copy(update={"proposal_sha256": "e" * 64})
        return receipt

    async def execute_replanned_trajectory(self, trajectory: Any, **kwargs: Any) -> None:
        del trajectory, kwargs
        self.replacement_dispatch_calls += 1

    def discard_replanned_trajectory_preparation(self, receipt: Any) -> None:
        del receipt

    async def stop_and_hold_for_replan(self, *, reason: str) -> None:
        self.fallback_calls.append(f"STOP_AND_HOLD:{reason}")
        self.old_cancelled.set()

    async def certified_abort_and_land_for_replan(self, **kwargs: Any) -> None:
        self.fallback_calls.append(f"ABORT_AND_LAND:{kwargs.get('reason')}")
        self.old_cancelled.set()

    async def emergency_fallback_for_replan(self, *, reason: str) -> None:
        self.fallback_calls.append(f"UNQUALIFIED:{reason}")
        self.old_cancelled.set()


class _MonitorInjection:
    def __init__(self, case: Any, mutation: _Mutation) -> None:
        self.delegate = ChangedWorldSafetyMonitor(case)
        self.mutation = mutation

    def certify_abort_route(self, **kwargs: Any) -> Any:
        if (
            self.mutation.boundary is _Boundary.ABORT
            and self.mutation.fault is _Fault.MISSING
        ):
            return None
        certificate = self.delegate.certify_abort_route(**kwargs)
        if (
            self.mutation.boundary is _Boundary.ABORT
            and self.mutation.fault is _Fault.TAMPERED
        ):
            return certificate.model_copy(update={"case_sha256": "e" * 64})
        return certificate

    def certify(self, **kwargs: Any) -> Any:
        certificate = self.delegate.certify(**kwargs)
        if (
            self.mutation.boundary is _Boundary.SAFE_PREFIX
            and self.mutation.fault is _Fault.MISSING
        ):
            return None
        if (
            self.mutation.boundary is _Boundary.SAFE_PREFIX
            and self.mutation.fault is _Fault.TAMPERED
        ):
            return certificate.model_copy(update={"case_sha256": "e" * 64})
        return certificate


async def _command_spy_case(mutation: _Mutation) -> dict[str, Any]:
    catalog = CampaignCatalog(ROOT / "missions/campaigns/sim/cases")
    catalog.discover()
    case = catalog.get(SOURCE_CASE_ID)
    package = resolve_planning_package(case)
    plan = BoundedJointPlanner().plan(
        case,
        planning_submission=package.planning_submission,
        first_certified_within_budget=True,
    )
    if plan.selected is None:
        raise RuntimeError("initial command-spy plan is unavailable")
    initial = generate_smooth_trajectories(
        case,
        plan.selected,
        planning_submission=package.planning_submission,
    ).trajectories[0]
    sampled = sample_trajectory(initial, initial.duration_s * 0.20)
    obstacle = ObstacleConfig(
        obstacle_id="wp85-command-spy-rock",
        minimum_m=Vector3(x=-0.15, y=-0.20, z=0.10),
        maximum_m=Vector3(x=0.20, y=0.20, z=0.70),
    )
    truth_event = WorldTruthEvent.create(
        event_id="wp85-command-spy-event",
        sequence=1,
        source_timestamp_s=2.0,
        effective_source_s=5.0,
        kind=WorldTruthEventKind.SOLID_APPEARED,
        solid_id=obstacle.obstacle_id,
        obstacle=obstacle,
    )
    source = SimulatedPerceptionObservationSource(
        timeline=DynamicWorldTimeline((), (truth_event,)),
        config=PerceptionModelConfig(latency_s=0.12),
        mission_id="wp85-design-mission",
        run_id="wp85-design-run",
        vehicle_id="Alpha",
    )
    head = CampaignExecutionHead(
        case=case,
        planning_submission=package.planning_submission,
        execution_profile=package.execution_profile,
        capability_resolution=package.capability_resolution,
        perception_source=source,
        mission_id="wp85-design-mission",
        run_id="wp85-design-run",
    )
    context = _SpyContext(sampled=sampled, mutation=mutation)
    head._contexts = {"Alpha": context}
    head._trajectories = {"Alpha": initial}

    async def source_now(self: CampaignExecutionHead, target_source_s: float) -> float:
        del self
        return target_source_s

    async def advance(self: CampaignExecutionHead, target_source_s: float) -> None:
        del self, target_source_s

    plan_calls = 0

    async def changed_world(self: CampaignExecutionHead, **kwargs: Any) -> Any:
        nonlocal plan_calls
        del self
        plan_calls += 1
        proposal = plan_changed_world_replacement(**kwargs)
        if mutation.boundary is _Boundary.PROPOSAL:
            if mutation.fault is _Fault.MISSING:
                return None
            return proposal.model_copy(update={"proposal_sha256": "e" * 64})
        if mutation.boundary is _Boundary.FEASIBILITY:
            certificate = proposal.plan.feasibility_certificate
            if mutation.fault is _Fault.MISSING:
                changed_plan = proposal.plan.model_copy(
                    update={"feasibility_certificate": None}
                )
            else:
                assert certificate is not None
                changed_plan = proposal.plan.model_copy(
                    update={
                        "feasibility_certificate": certificate.model_copy(
                            update={"passed": False}
                        )
                    }
                )
            return proposal.model_copy(update={"plan": changed_plan})
        return proposal

    async def rebase(self: CampaignExecutionHead, proposal: Any, observations: Any) -> Any:
        del self
        rebased = rebase_changed_world_replacement(proposal, observations)
        if mutation.boundary is _Boundary.CUTOVER:
            if mutation.fault is _Fault.MISSING:
                return rebased.model_copy(update={"cutover_certificate": None})
            certificate = rebased.cutover_certificate.model_copy(
                update={"passed": False, "violations": ("WP85_TAMPER",)}
            )
            return rebased.model_copy(update={"cutover_certificate": certificate})
        return rebased

    head._wait_for_source_time = MethodType(source_now, head)  # type: ignore[method-assign]
    head._advance_fleet_to = MethodType(advance, head)  # type: ignore[method-assign]
    head._plan_changed_world = MethodType(changed_world, head)  # type: ignore[method-assign]
    head._rebase_changed_world = MethodType(rebase, head)  # type: ignore[method-assign]

    original_monitor = execution_head_module.ChangedWorldSafetyMonitor
    execution_head_module.ChangedWorldSafetyMonitor = lambda active_case: _MonitorInjection(  # type: ignore[assignment]
        active_case, mutation
    )
    error_type = None
    error_message = None
    try:
        await head._orchestrate()
    except (TypeError, ValueError, RuntimeError, Exception) as error:
        error_type = type(error).__name__
        error_message = str(error)
        context.old_cancelled.set()
    finally:
        execution_head_module.ChangedWorldSafetyMonitor = original_monitor
        await head.close()
    normalized = error_type in {None, "ValueError", "RuntimeError", "CrazySwarmError"}
    return {
        "injection": mutation.label,
        "semantic_boundary": mutation.boundary.value,
        "semantic_fault": mutation.fault.value,
        "replacement_command_spy_calls": context.replacement_dispatch_calls,
        "fallback_command_count": len(context.fallback_calls),
        "error_type": error_type,
        "error_message": error_message,
        "normalized_outcome": normalized,
        "production_head_exercised": True,
        "actual_command_method": "execute_replanned_trajectory",
        "pre_fix_regression_failed": (
            mutation.boundary is not _Boundary.NONE
            and (
                context.replacement_dispatch_calls != 0
                or not normalized
            )
        ),
        "expected_post_fix_replacement_command_calls": (
            1 if mutation.boundary is _Boundary.NONE else 0
        ),
    }


async def _command_spy_witnesses() -> dict[str, Any]:
    mutations = (
        _Mutation("accepted", _Boundary.NONE, _Fault.NONE),
        *(
            _Mutation(
                f"{fault.value.lower()}_{boundary.value.lower()}",
                boundary,
                fault,
            )
            for boundary in (
                _Boundary.SAFE_PREFIX,
                _Boundary.ABORT,
                _Boundary.FEASIBILITY,
                _Boundary.CUTOVER,
                _Boundary.PROPOSAL,
                _Boundary.RECEIPT,
            )
            for fault in (_Fault.MISSING, _Fault.TAMPERED)
        ),
    )
    witnesses = {item.label: await _command_spy_case(item) for item in mutations}
    renamed = {}
    for item in (
        next(row for row in mutations if row.label == "tampered_proposal"),
        next(row for row in mutations if row.label == "missing_feasibility"),
        next(row for row in mutations if row.label == "tampered_cutover"),
    ):
        alternate = replace(item, label=f"renamed-{item.label}-variant")
        renamed[item.label] = await _command_spy_case(alternate)
    witnesses["rename_perturbations"] = renamed
    return witnesses


def _stable_wp84_structural_witness() -> dict[str, Any]:
    retained = json.loads(
        (ROOT / "missions/campaigns/sim/qualification/wp84-design-audit-v1.json").read_text()
    )["production_transit_witness"]
    return {
        "witness_kind": "SINGLE_RUN_STRUCTURAL_PREIMAGE",
        "cross_run_identity_claim": False,
        "entry": retained["entry"],
        "off_loop_methods_substituted": retained["off_loop_methods_substituted"],
        "maximum_simultaneous_obstacle_count": retained[
            "maximum_simultaneous_obstacle_count"
        ],
        "configured_event_count": retained["configured_event_count"],
        "perception_observation_count": retained["perception_observation_count"],
        "safe_prefix_certificate_count": retained["safe_prefix_certificate_count"],
        "preparation_receipt_count": retained["preparation_receipt_count"],
        "accepted_atomic_commit_count": retained["accepted_atomic_commit_count"],
        "replacement_dispatch_count": retained["replacement_dispatch_count"],
        "fallback_count": retained["fallback_count"],
        "event_order": [row["event_id"] for row in retained["sequential_event_epochs"]],
        "within_run_epoch_identities_distinct": len(
            {row["decision_sha256"] for row in retained["sequential_event_epochs"]}
        )
        == retained["configured_event_count"],
    }


def _boundary_manifest() -> dict[str, Any]:
    base_path = ROOT / "missions/campaigns/sim/qualification/wp84-design-audit-v1.json"
    base = json.loads(base_path.read_text())["affected_boundary_manifest"]
    paths = dict(base["paths"])
    transit = _python_import_closure(PRODUCTION_TRANSIT_ROOTS)
    successor_paths = WP85_BOUNDARY_DELTA | transit
    for relative in sorted(successor_paths):
        if relative in paths:
            sources = set(paths[relative].get("discovery_sources", []))
            if relative in transit:
                sources.add("TRANSITIVE_PRODUCTION_IMPORT")
            paths[relative]["discovery_sources"] = sorted(sources)
            continue
        path = ROOT / relative
        self_output = relative.endswith("wp85-design-audit-v1.json")
        paths[relative] = {
            "classification": "PRESERVE",
            "state": "SELF_OUTPUT_EXTERNAL_PACKET_HASH" if self_output else "EXISTING",
            "sha256": None if self_output else hashlib.sha256(path.read_bytes()).hexdigest(),
            "discovery_sources": [
                *(["TRANSITIVE_PRODUCTION_IMPORT"] if relative in transit else []),
                *(["WP84_FINAL_FINDING_BOUNDARY", "REQ_WFL_054_DURABLE_FEEDBACK", "WP85_FOCUSED_AUDIT_OWNER"] if relative in WP85_BOUNDARY_DELTA else []),
            ],
        }
    return {
        "base_manifest_artifact_sha256": WP84_BOUNDARY_ARTIFACT_SHA256,
        "base_path_count": len(base["paths"]),
        "delta_paths": sorted(WP85_BOUNDARY_DELTA),
        "production_transit_roots": sorted(PRODUCTION_TRANSIT_ROOTS),
        "transitive_production_paths": sorted(transit),
        "expected_path_count": len(set(base["paths"]) | successor_paths),
        "paths": dict(sorted(paths.items())),
    }


def _python_import_closure(roots: set[str]) -> set[str]:
    source_root = ROOT / "src"

    def candidates(module: str) -> tuple[Path, ...]:
        base = source_root.joinpath(*module.split("."))
        return (base.with_suffix(".py"), base / "__init__.py")

    def module_for(path: Path) -> tuple[str, ...]:
        relative = path.relative_to(source_root).with_suffix("")
        parts = relative.parts
        return parts[:-1] if parts[-1] == "__init__" else parts

    discovered = set(roots)
    queue = list(sorted(roots))
    while queue:
        relative = queue.pop(0)
        path = ROOT / relative
        current_parts = module_for(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names if alias.name.startswith("crazyswarm_app"))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parent = current_parts[: max(0, len(current_parts) - node.level)]
                    base_parts = (*parent, *((node.module or "").split(".") if node.module else ()))
                    base = ".".join(base_parts)
                else:
                    base = node.module or ""
                if base.startswith("crazyswarm_app"):
                    modules.add(base)
                    modules.update(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
        for module in sorted(modules):
            for candidate in candidates(module):
                if not candidate.is_file():
                    continue
                found = candidate.relative_to(ROOT).as_posix()
                if found not in discovered:
                    discovered.add(found)
                    queue.append(found)
    return discovered


async def _payload() -> dict[str, Any]:
    seeds = _seed_boundary_witnesses()
    spies = await _command_spy_witnesses()
    rename_perturbations = spies.pop("rename_perturbations")
    negatives = {key: row for key, row in spies.items() if key != "accepted"}
    stable = _stable_wp84_structural_witness()
    boundary = _boundary_manifest()

    def semantic_result(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            row["semantic_boundary"],
            row["semantic_fault"],
            row["replacement_command_spy_calls"],
            row["fallback_command_count"],
            row["error_type"],
            row["pre_fix_regression_failed"],
            row["expected_post_fix_replacement_command_calls"],
        )

    checks = {
        "strict_seed_endpoints_pass": seeds["passing"] == {"0": 0, "1": 1, "34": 34},
        "strict_seed_type_and_range_perturbations_reject": all(
            row["error_type"] in {"TypeError", "ValueError"}
            for row in seeds["rejected"].values()
        ),
        "accepted_control_reaches_one_actual_replacement_command": (
            spies["accepted"]["replacement_command_spy_calls"] == 1
            and spies["accepted"]["production_head_exercised"]
        ),
        "semantic_authority_mutations_reach_real_consumption_boundaries": (
            {row["semantic_boundary"] for row in negatives.values()}
            == {item.value for item in _Boundary if item is not _Boundary.NONE}
            and {row["semantic_fault"] for row in negatives.values()}
            == {_Fault.MISSING.value, _Fault.TAMPERED.value}
            and all(row["production_head_exercised"] for row in negatives.values())
        ),
        "pre_fix_regressions_are_sensitive_not_manufactured_passes": (
            any(row["pre_fix_regression_failed"] for row in negatives.values())
            and all(
                row["expected_post_fix_replacement_command_calls"] == 0
                for row in negatives.values()
            )
            and all(
                row["replacement_command_spy_calls"] == 0
                and row["normalized_outcome"]
                and row["error_type"] != "AttributeError"
                for row in negatives.values()
                if not row["pre_fix_regression_failed"]
            )
        ),
        "semantic_mutations_are_invariant_to_display_label_rename": all(
            semantic_result(negatives[label]) == semantic_result(alternate)
            for label, alternate in rename_perturbations.items()
        ),
        "stable_structural_comparator_closes_wp84_p2": (
            stable["witness_kind"] == "SINGLE_RUN_STRUCTURAL_PREIMAGE"
            and not stable["cross_run_identity_claim"]
            and stable["configured_event_count"] == 5
            and stable["configured_event_count"]
            == stable["replacement_dispatch_count"]
            and stable["fallback_count"] == 0
        ),
        "successor_boundary_is_exact_wp84_union_focused_delta": (
            boundary["base_path_count"] == 76
            and set(boundary["delta_paths"]) == WP85_BOUNDARY_DELTA
            and len(boundary["paths"]) == boundary["expected_path_count"]
            and {
                "src/crazyswarm_app/campaign/execution.py",
                "src/crazyswarm_app/missions/runner.py",
                "src/crazyswarm_app/campaign/perception.py",
                "src/crazyswarm_app/observability/csv_export.py",
                "src/crazyswarm_app/campaign/geometry.py",
                "src/crazyswarm_app/domain/commands.py",
                "src/crazyswarm_app/fleet/preparation.py",
                "src/crazyswarm_app/missions/script.py",
                "src/crazyswarm_app/simulation/clock.py",
                "src/crazyswarm_app/vehicles/providers.py",
            }
            <= set(boundary["paths"])
            and all(row["discovery_sources"] for row in boundary["paths"].values())
        ),
    }
    return {
        "schema_version": 1,
        "audit_id": "wp85-design-audit-v1",
        "base_commit": BASE_COMMIT,
        "predecessor_payloads": {
            "wp84_initial": WP84_BASE_PAYLOAD_SHA256,
            "wp84_r1": WP84_R1_PAYLOAD_SHA256,
        },
        "strict_seed_boundary_witnesses": seeds,
        "execution_head_command_spy_witnesses": spies,
        "command_spy_rename_perturbations": rename_perturbations,
        "stable_wp84_structural_witness": stable,
        "affected_boundary_manifest": boundary,
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    output = (
        Path(sys.argv[1])
        if len(sys.argv) == 2
        else ROOT / "missions/campaigns/sim/qualification/wp85-design-audit-v1.json"
    )
    payload = asyncio.run(_payload())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"checks": payload["checks"], "passed": payload["passed"]}, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
