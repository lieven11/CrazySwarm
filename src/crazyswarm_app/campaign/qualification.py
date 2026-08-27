from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Literal, cast

from pydantic import Field

from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.geometry import (
    SolidGeometry,
    StructuredWorld,
    TraversableGeometry,
    validate_structured_world,
)
from crazyswarm_app.campaign.models import (
    CampaignCase,
    PlannerStrategy,
    Region3D,
    ReplanningAuthority,
)
from crazyswarm_app.campaign.planner import (
    BoundedJointPlanner,
    PlanningStatus,
    SearchDisposition,
)
from crazyswarm_app.campaign.replanning import (
    ChangedWorldReplanProposal,
    DynamicEventKind,
    DynamicReplanDisposition,
    FleetRouteReplacement,
    InFlightEnvironmentEvent,
    InFlightReplanCoordinator,
    ReplanObservation,
    SafeFallback,
    plan_changed_world_replacement,
)
from crazyswarm_app.campaign.submissions import (
    BASELINE_PLANNING_SUBMISSION_ID,
    ClearancePolicy,
    ManeuverDimension,
    PlanningSubmission,
    rebind_planning_submission,
    resolve_planning_submission,
)
from crazyswarm_app.campaign.trajectory import generate_smooth_trajectories
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.domain.trajectory import sample_trajectory

TRACKING_RMS_THRESHOLD_M = 0.05
TRACKING_RMS_REPEAT_IDENTITIES: tuple[tuple[str, str, str, int], ...] = (
    *(
        ("WP-64", case_id, "AUTOMATED_ACCELERATED", ordinal)
        for case_id in (
            "1d.curved_route.canonical_nominal",
            "1d.planar_shape_loop.figure_eight",
            "1d.altitude_transition.canonical_nominal",
        )
        for ordinal in (1, 2, 3)
    ),
    *(
        ("WP-64", case_id, "OPERATOR_OBSERVED_REALTIME", 1)
        for case_id in (
            "1d.curved_route.canonical_nominal",
            "1d.planar_shape_loop.figure_eight",
            "1d.altitude_transition.canonical_nominal",
        )
    ),
    *(
        (
            "WP-66",
            "1d.online_obstacle_replan.dynamic_nominal",
            "OPERATOR_OBSERVED_REALTIME",
            ordinal,
        )
        for ordinal in (1, 2, 3)
    ),
)


class TrackingRmsRepeatQualification(ContractModel):
    schema_version: Literal[1] = 1
    threshold_m: float = Field(default=TRACKING_RMS_THRESHOLD_M, ge=0.05, le=0.05)
    passed: bool
    failures: tuple[str, ...]
    expected_count: Literal[15] = 15
    observed_record_count: int = Field(ge=0)
    unique_expected_observed_count: int = Field(ge=0, le=15)


def qualify_tracking_rms_repeats(records: Any) -> TrackingRmsRepeatQualification:
    """Evaluate the exact 15-repeat universe without formatting untrusted identities."""

    expected = set(TRACKING_RMS_REPEAT_IDENTITIES)
    failures: list[str] = []
    if type(records) is not list:
        return TrackingRmsRepeatQualification(
            passed=False,
            failures=("records:INVALID_CONTAINER",),
            observed_record_count=0,
            unique_expected_observed_count=0,
        )
    seen: set[tuple[str, str, str, int]] = set()
    for index, record in enumerate(records):
        if type(record) is not dict:
            failures.append(f"record-{index}:INVALID_RECORD")
            continue
        if frozenset(record) != {"identity", "applicable", "tracking_rms_m"}:
            failures.append(f"record-{index}:INVALID_RECORD_FIELDS")
        key = _bounded_tracking_rms_identity(record.get("identity"))
        if key is None:
            failures.append(f"record-{index}:INVALID_IDENTITY")
            continue
        label = _tracking_rms_label(key)
        if key in seen:
            failures.append(f"{label}:DUPLICATE")
        else:
            seen.add(key)
        if key not in expected:
            failures.append(f"{label}:UNEXPECTED")
        if record.get("applicable") is not True:
            failures.append(f"{label}:INVALID_NOT_APPLICABLE")
        value = record.get("tracking_rms_m")
        if type(value) not in (int, float):
            failures.append(f"{label}:MISSING_OR_NON_NUMERIC")
        else:
            numeric_value = cast(int | float, value)
            if type(numeric_value) is float and not math.isfinite(numeric_value):
                failures.append(f"{label}:NON_FINITE")
            elif numeric_value < 0:
                failures.append(f"{label}:NEGATIVE")
            elif numeric_value > TRACKING_RMS_THRESHOLD_M:
                failures.append(f"{label}:ABOVE_THRESHOLD")
    for key in sorted(expected - seen):
        failures.append(f"{_tracking_rms_label(key)}:MISSING")
    return TrackingRmsRepeatQualification(
        passed=not failures,
        failures=tuple(sorted(failures)),
        observed_record_count=len(records),
        unique_expected_observed_count=len(expected & seen),
    )


def _bounded_tracking_rms_identity(value: Any) -> tuple[str, str, str, int] | None:
    if type(value) is not dict or frozenset(value) != {
        "packet_id",
        "case_id",
        "mode",
        "ordinal",
    }:
        return None
    packet_id = value["packet_id"]
    case_id = value["case_id"]
    mode = value["mode"]
    ordinal = value["ordinal"]
    if (
        type(packet_id) is not str
        or not 1 <= len(packet_id) <= 5
        or type(case_id) is not str
        or not 1 <= len(case_id) <= 96
        or type(mode) is not str
        or not 1 <= len(mode) <= 32
        or type(ordinal) is not int
        or not 1 <= ordinal <= 3
    ):
        return None
    return packet_id, case_id, mode, ordinal


def _tracking_rms_label(key: tuple[str, str, str, int]) -> str:
    return f"{key[0]}|{key[1]}|{key[2]}|{key[3]}"


class CaseMutation(StrEnum):
    NONE = "NONE"
    DIRECT_ONLY = "DIRECT_ONLY"
    VERTICAL_FORBIDDEN = "VERTICAL_FORBIDDEN"
    OPEN_CEILING_VERTICAL_ONLY = "OPEN_CEILING_VERTICAL_ONLY"


class MatrixExpectedDisposition(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class ConstraintDirectedMatrixRow(ContractModel):
    row_id: Identifier
    base_case_id: Identifier
    planning_submission_id: Identifier
    principal_variable: Identifier
    mutation: CaseMutation = CaseMutation.NONE
    expected_disposition: MatrixExpectedDisposition
    expected_strategy: PlannerStrategy | None = None
    causal_question: str = Field(min_length=1, max_length=1000)


class ConstraintDirectedMatrixResult(ContractModel):
    row_id: Identifier
    case_id: Identifier
    case_sha256: SHA256
    planning_submission_sha256: SHA256
    passed: bool
    actual_status: PlanningStatus
    search_disposition: SearchDisposition
    selected_strategy: PlannerStrategy | None = None
    selected_candidate_sha256: SHA256 | None = None
    feasibility_certificate_sha256: SHA256 | None = None
    result_sha256: SHA256


class WorldGeometryMatrixRow(ContractModel):
    row_id: Identifier
    principal_variable: Identifier
    horizontal_width_m: float = Field(gt=0.0)
    vertical_height_m: float = Field(gt=0.0)
    solid_overlap: bool = False
    expected_valid: bool


class WorldGeometryMatrixResult(ContractModel):
    row_id: Identifier
    valid: bool
    passable: bool
    contradictions: tuple[str, ...]
    passed: bool
    result_sha256: SHA256


class DynamicQualificationScope(StrEnum):
    REAL_CHANGED_WORLD_PLAN_PLUS_COORDINATOR_COMMIT = (
        "REAL_CHANGED_WORLD_PLAN_PLUS_COORDINATOR_COMMIT"
    )
    COORDINATOR_TRANSACTION_ONLY = "COORDINATOR_TRANSACTION_ONLY"


class DynamicReplanningMatrixResult(ContractModel):
    row_id: Identifier
    event_kind: DynamicEventKind
    qualification_scope: DynamicQualificationScope
    actual_disposition: DynamicReplanDisposition
    reaction_horizon_passed: bool
    committed_route_count: int = Field(ge=0, le=3)
    fallback: SafeFallback | None = None
    proposal_sha256: SHA256 | None = None
    replacement_world_sha256: SHA256 | None = None
    feasibility_certificate_sha256s: tuple[SHA256, ...] = ()
    passed: bool
    decision_sha256: SHA256
    result_sha256: SHA256


class ConstraintDirectedQualificationReport(ContractModel):
    schema_version: Literal[1] = 1
    matrix_id: Identifier = "constraint-directed-bottleneck-head-on-merge-v1"
    rows: tuple[ConstraintDirectedMatrixResult, ...]
    geometry_rows: tuple[WorldGeometryMatrixResult, ...]
    dynamic_rows: tuple[DynamicReplanningMatrixResult, ...]
    passed: bool
    report_sha256: SHA256


CONSTRAINT_DIRECTED_MATRIX: tuple[ConstraintDirectedMatrixRow, ...] = (
    ConstraintDirectedMatrixRow(
        row_id="bottleneck.serialized-baseline",
        base_case_id="2d.bottleneck.canonical_nominal",
        planning_submission_id=BASELINE_PLANNING_SUBMISSION_ID,
        principal_variable="coordination_policy",
        expected_disposition=MatrixExpectedDisposition.READY,
        expected_strategy=PlannerStrategy.GROUND_DELAY,
        causal_question="Does the retained bottleneck remain safe when serialization is allowed?",
    ),
    ConstraintDirectedMatrixRow(
        row_id="bottleneck.simultaneous-vertical",
        base_case_id="2d.bottleneck.canonical_nominal",
        planning_submission_id="constraint_directed.bottleneck.simultaneous_vertical",
        principal_variable="vertical_passage_capacity",
        expected_disposition=MatrixExpectedDisposition.READY,
        expected_strategy=PlannerStrategy.VERTICAL_LAYER,
        causal_question=(
            "Can both roles remain active and use vertical separation in the bottleneck?"
        ),
    ),
    ConstraintDirectedMatrixRow(
        row_id="bottleneck.simultaneous-no-vertical",
        base_case_id="2d.bottleneck.canonical_nominal",
        planning_submission_id="constraint_directed.bottleneck.simultaneous_vertical",
        principal_variable="vertical_layers_allowed",
        mutation=CaseMutation.VERTICAL_FORBIDDEN,
        expected_disposition=MatrixExpectedDisposition.BLOCKED,
        causal_question=(
            "Is the same simultaneous bottleneck correctly blocked without vertical capacity?"
        ),
    ),
    ConstraintDirectedMatrixRow(
        row_id="head-on.direct-only",
        base_case_id="2d.head_on_conflict.canonical_nominal",
        planning_submission_id="constraint_directed.head_on.same_path",
        principal_variable="maneuver_authority",
        mutation=CaseMutation.DIRECT_ONLY,
        expected_disposition=MatrixExpectedDisposition.BLOCKED,
        causal_question=(
            "Does the same-path head-on conflict remain unsafe with no avoidance freedom?"
        ),
    ),
    ConstraintDirectedMatrixRow(
        row_id="head-on.paired-lateral",
        base_case_id="2d.head_on_conflict.canonical_nominal",
        planning_submission_id="constraint_directed.head_on.same_path",
        principal_variable="lateral_clearance",
        expected_disposition=MatrixExpectedDisposition.READY,
        expected_strategy=PlannerStrategy.HORIZONTAL_DETOUR,
        causal_question="Does paired lateral routing resolve the forced same-path encounter?",
    ),
    ConstraintDirectedMatrixRow(
        row_id="head-on.open-ceiling-vertical",
        base_case_id="2d.head_on_conflict.canonical_nominal",
        planning_submission_id="constraint_directed.head_on.same_path",
        principal_variable="open_ceiling_height",
        mutation=CaseMutation.OPEN_CEILING_VERTICAL_ONLY,
        expected_disposition=MatrixExpectedDisposition.READY,
        expected_strategy=PlannerStrategy.VERTICAL_LAYER,
        causal_question="Does extra vertical capacity enable a vertical-only head-on solution?",
    ),
    ConstraintDirectedMatrixRow(
        row_id="merge.direct-only",
        base_case_id="2d.merge.canonical_nominal",
        planning_submission_id="constraint_directed.merge.flexible_geometry",
        principal_variable="maneuver_authority",
        mutation=CaseMutation.DIRECT_ONLY,
        expected_disposition=MatrixExpectedDisposition.BLOCKED,
        causal_question="Is the simultaneous merge blocked when all avoidance freedom is removed?",
    ),
    ConstraintDirectedMatrixRow(
        row_id="merge.flexible-geometry",
        base_case_id="2d.merge.canonical_nominal",
        planning_submission_id="constraint_directed.merge.flexible_geometry",
        principal_variable="lateral_path_freedom",
        expected_disposition=MatrixExpectedDisposition.READY,
        expected_strategy=PlannerStrategy.HORIZONTAL_DETOUR,
        causal_question=(
            "Can the merge use admissible lateral geometry instead of a fixed workflow?"
        ),
    ),
    ConstraintDirectedMatrixRow(
        row_id="merge.serialized-baseline",
        base_case_id="2d.merge.canonical_nominal",
        planning_submission_id=BASELINE_PLANNING_SUBMISSION_ID,
        principal_variable="coordination_policy",
        expected_disposition=MatrixExpectedDisposition.READY,
        expected_strategy=PlannerStrategy.GROUND_DELAY,
        causal_question="Does the retained merge remain safe when serialized release is allowed?",
    ),
)


WORLD_GEOMETRY_MATRIX: tuple[WorldGeometryMatrixRow, ...] = (
    WorldGeometryMatrixRow(
        row_id="obstacle.under-only-clearance",
        principal_variable="underpass_height",
        horizontal_width_m=0.50,
        vertical_height_m=0.30,
        expected_valid=True,
    ),
    WorldGeometryMatrixRow(
        row_id="obstacle.under-only-too-low",
        principal_variable="underpass_height",
        horizontal_width_m=0.50,
        vertical_height_m=0.20,
        expected_valid=False,
    ),
    WorldGeometryMatrixRow(
        row_id="obstacle.side-opening",
        principal_variable="side_opening_width",
        horizontal_width_m=0.35,
        vertical_height_m=0.50,
        expected_valid=True,
    ),
    WorldGeometryMatrixRow(
        row_id="obstacle.open-ceiling",
        principal_variable="ceiling_height",
        horizontal_width_m=0.50,
        vertical_height_m=0.80,
        expected_valid=True,
    ),
    WorldGeometryMatrixRow(
        row_id="obstacle.parallel-corridor",
        principal_variable="parallel_corridor_width",
        horizontal_width_m=0.40,
        vertical_height_m=0.40,
        expected_valid=True,
    ),
    WorldGeometryMatrixRow(
        row_id="obstacle.solid-free-contradiction",
        principal_variable="solid_free_precedence",
        horizontal_width_m=0.50,
        vertical_height_m=0.50,
        solid_overlap=True,
        expected_valid=False,
    ),
)


def run_constraint_directed_qualification(
    catalog: CampaignCatalog,
) -> ConstraintDirectedQualificationReport:
    planner = BoundedJointPlanner()
    results = []
    for row in CONSTRAINT_DIRECTED_MATRIX:
        base_case = catalog.get(row.base_case_id)
        source_submission = resolve_planning_submission(
            base_case,
            row.planning_submission_id,
            require_executable=False,
        )
        case = _mutated_case(base_case, row)
        compatible_authority = tuple(
            strategy
            for strategy in source_submission.strategy_authority
            if strategy in case.allowed_strategies
        )
        if not compatible_authority:
            expected_block = (
                row.expected_disposition is MatrixExpectedDisposition.BLOCKED
            )
            payload = {
                "row_id": row.row_id,
                "case_id": case.case_id,
                "case_sha256": case.case_sha256,
                "planning_submission_sha256": (
                    source_submission.planning_submission_sha256
                ),
                "passed": expected_block,
                "actual_status": PlanningStatus.BLOCKED,
                "search_disposition": (
                    SearchDisposition.INDEPENDENT_VERIFICATION_REJECTED
                ),
                "selected_strategy": None,
                "selected_candidate_sha256": None,
                "feasibility_certificate_sha256": None,
            }
            results.append(
                ConstraintDirectedMatrixResult(
                    **payload,
                    result_sha256=canonical_sha256(payload),
                )
            )
            continue
        qualification_source = _qualification_authority_projection(
            source_submission,
            compatible_authority,
        )
        submission = (
            qualification_source
            if case.case_sha256 == base_case.case_sha256
            else rebind_planning_submission(case, qualification_source)
        )
        plan = planner.plan(case, planning_submission=submission)
        expected_status = (
            PlanningStatus.READY
            if row.expected_disposition is MatrixExpectedDisposition.READY
            else PlanningStatus.BLOCKED
        )
        selected_strategy = plan.selected.strategy if plan.selected else None
        passed = plan.status is expected_status and (
            row.expected_strategy is None or selected_strategy is row.expected_strategy
        )
        payload = {
            "row_id": row.row_id,
            "case_id": case.case_id,
            "case_sha256": case.case_sha256,
            "planning_submission_sha256": submission.planning_submission_sha256,
            "passed": passed,
            "actual_status": plan.status,
            "search_disposition": plan.search_disposition,
            "selected_strategy": selected_strategy,
            "selected_candidate_sha256": plan.selected_candidate_sha256,
            "feasibility_certificate_sha256": (
                plan.feasibility_certificate.certificate_sha256
                if plan.feasibility_certificate
                else None
            ),
        }
        results.append(
            ConstraintDirectedMatrixResult(
                **payload,
                result_sha256=canonical_sha256(payload),
            )
        )
    geometry_results = run_world_geometry_qualification()
    dynamic_results = run_dynamic_replanning_qualification(catalog)
    report_payload = {
        "schema_version": 1,
        "matrix_id": "constraint-directed-bottleneck-head-on-merge-v1",
        "rows": tuple(results),
        "geometry_rows": geometry_results,
        "dynamic_rows": dynamic_results,
        "passed": (
            all(item.passed for item in results)
            and all(item.passed for item in geometry_results)
            and all(item.passed for item in dynamic_results)
        ),
    }
    return ConstraintDirectedQualificationReport(
        **report_payload,
        report_sha256=canonical_sha256(report_payload),
    )


def run_world_geometry_qualification() -> tuple[WorldGeometryMatrixResult, ...]:
    volume = Region3D(
        region_id="qualification-volume",
        minimum_m=Vector3(x=-2.0, y=-2.0, z=0.0),
        maximum_m=Vector3(x=2.0, y=2.0, z=2.0),
    )
    policy = ClearancePolicy(required_pairwise_center_separation_m=0.80)
    output = []
    for row in WORLD_GEOMETRY_MATRIX:
        passage_region = Region3D(
            region_id=f"{row.row_id}.passage",
            minimum_m=Vector3(
                x=-row.horizontal_width_m / 2.0,
                y=-row.horizontal_width_m / 2.0,
                z=0.20,
            ),
            maximum_m=Vector3(
                x=row.horizontal_width_m / 2.0,
                y=row.horizontal_width_m / 2.0,
                z=0.20 + row.vertical_height_m,
            ),
        )
        world = StructuredWorld(
            flight_volume=volume,
            solids=(
                (
                    SolidGeometry(
                        solid_id=f"{row.row_id}.solid",
                        bounds=passage_region.model_copy(
                            update={"region_id": f"{row.row_id}.solid"}
                        ),
                    ),
                )
                if row.solid_overlap
                else ()
            ),
            traversable_passages=(
                TraversableGeometry(
                    passage_id=f"{row.row_id}.passage",
                    bounds=passage_region,
                ),
            ),
            world_sha256="0" * 64,
        )
        report = validate_structured_world(world, policy)
        passable = report.passage_capacities[0].passable
        passed = report.valid is row.expected_valid and (
            passable if row.expected_valid else True
        )
        payload = {
            "row_id": row.row_id,
            "valid": report.valid,
            "passable": passable,
            "contradictions": report.contradictions,
            "passed": passed,
        }
        output.append(
            WorldGeometryMatrixResult(
                **payload,
                result_sha256=canonical_sha256(payload),
            )
        )
    return tuple(output)


def _qualification_authority_projection(
    source: PlanningSubmission,
    strategy_authority: tuple[PlannerStrategy, ...],
) -> PlanningSubmission:
    dimensions_by_strategy = {
        PlannerStrategy.DIRECT: (ManeuverDimension.TIMING,),
        PlannerStrategy.GROUND_DELAY: (ManeuverDimension.TIMING,),
        PlannerStrategy.AIRBORNE_STAGING: (ManeuverDimension.TIMING,),
        PlannerStrategy.SPEED_RETIMING: (ManeuverDimension.SPEED,),
        PlannerStrategy.HORIZONTAL_DETOUR: (ManeuverDimension.LATERAL,),
        PlannerStrategy.VERTICAL_LAYER: (ManeuverDimension.VERTICAL,),
        PlannerStrategy.COMBINED_TIMING_GEOMETRY: (
            ManeuverDimension.TIMING,
            ManeuverDimension.LATERAL,
            ManeuverDimension.VERTICAL,
        ),
    }
    maneuver_dimensions = tuple(
        dict.fromkeys(
            dimension
            for strategy in strategy_authority
            for dimension in dimensions_by_strategy[strategy]
        )
    )
    return source.model_copy(
        update={
            "strategy_authority": strategy_authority,
            "maneuver_dimensions": maneuver_dimensions,
        }
    )


def _real_object_in_line_proposal(
    catalog: CampaignCatalog,
) -> tuple[CampaignCase, InFlightEnvironmentEvent, ChangedWorldReplanProposal]:
    source = catalog.get("2d.head_on_conflict.canonical_nominal")
    source_submission = resolve_planning_submission(
        source,
        "constraint_directed.head_on.same_path",
    )
    case = _replanning_qualification_child(source, "object-in-line")
    submission = rebind_planning_submission(case, source_submission)
    initial_plan = BoundedJointPlanner().plan(
        case,
        planning_submission=submission,
    )
    if initial_plan.status is not PlanningStatus.READY or initial_plan.selected is None:
        raise RuntimeError("object-in-line qualification lacks an admitted initial plan")
    initial = generate_smooth_trajectories(
        case,
        initial_plan.selected,
        planning_submission=submission,
    )
    old_trajectories = {item.role_id: item for item in initial.trajectories}
    observations = tuple(
        ReplanObservation.create(
            observation_id=f"qualification-line-object-{trajectory.role_id}",
            role_id=trajectory.role_id,
            source_timestamp_s=10.0,
            captured_at_source_s=10.0,
            position_m=sample.position_m,
            velocity_m_s=sample.velocity_m_s,
            acceleration_m_s2=sample.acceleration_m_s2,
        )
        for trajectory in initial.trajectories
        for sample in (sample_trajectory(trajectory, trajectory.duration_s / 3.0),)
    )
    obstacle = Region3D(
        region_id="qualification-object-in-line",
        minimum_m=Vector3(x=0.1, y=-0.2, z=0.1),
        maximum_m=Vector3(x=0.4, y=0.2, z=0.6),
    )
    event = InFlightEnvironmentEvent(
        event_id="qualification-object-in-line-detected",
        kind=DynamicEventKind.OBSTACLE_ADDED,
        source_id="qualification-world-observer",
        sequence=1,
        source_timestamp_s=10.0,
        received_source_s=10.05,
        effective_source_s=13.0,
        affected_role_ids=tuple(sorted(old_trajectories)),
        region_id=obstacle.region_id,
        region=obstacle,
    )
    proposal = plan_changed_world_replacement(
        case=case,
        planning_submission=submission,
        event=event,
        observations=observations,
        old_trajectories=old_trajectories,
    )
    return case, event, proposal


def run_dynamic_replanning_qualification(
    catalog: CampaignCatalog,
) -> tuple[DynamicReplanningMatrixResult, ...]:
    source = catalog.get("2d.merge.canonical_nominal")
    case = _replanning_qualification_child(source, "coordinator-transaction")
    real_case, real_event, real_proposal = _real_object_in_line_proposal(catalog)
    scenarios = (
        (
            "dynamic.obstacle-atomic-cutover",
            DynamicEventKind.OBSTACLE_ADDED,
            13.0,
            True,
            DynamicReplanDisposition.ACCEPTED,
            2,
            None,
            DynamicQualificationScope.REAL_CHANGED_WORLD_PLAN_PLUS_COORDINATOR_COMMIT,
        ),
        (
            "dynamic.peer-atomic-cutover",
            DynamicEventKind.PEER_TRAJECTORY_UPDATED,
            11.0,
            True,
            DynamicReplanDisposition.ACCEPTED,
            2,
            None,
            DynamicQualificationScope.COORDINATOR_TRANSACTION_ONLY,
        ),
        (
            "dynamic.obstacle-late-fallback",
            DynamicEventKind.OBSTACLE_ADDED,
            10.20,
            True,
            DynamicReplanDisposition.BLOCKED_REACTION_HORIZON,
            0,
            SafeFallback.FLEET_ABORT_AND_LAND,
            DynamicQualificationScope.COORDINATOR_TRANSACTION_ONLY,
        ),
        (
            "dynamic.peer-partial-ack-zero-commit",
            DynamicEventKind.PEER_TRAJECTORY_UPDATED,
            11.0,
            False,
            DynamicReplanDisposition.BLOCKED_ATOMIC_COMMIT,
            0,
            SafeFallback.CONTINUE_OLD_SAFE_EPOCH,
            DynamicQualificationScope.COORDINATOR_TRANSACTION_ONLY,
        ),
    )
    output = []
    for sequence, scenario in enumerate(scenarios, start=1):
        (
            row_id,
            kind,
            effective_source_s,
            complete_acknowledgement,
            expected_disposition,
            expected_committed,
            expected_fallback,
            qualification_scope,
        ) = scenario
        event_payload: dict[str, object] = {
            "event_id": f"{row_id}.event",
            "kind": kind,
            "source_id": f"qualification-source-{sequence}",
            "sequence": sequence,
            "source_timestamp_s": 10.0,
            "received_source_s": 10.05,
            "effective_source_s": effective_source_s,
            "affected_role_ids": ("Alpha", "Beta"),
        }
        if kind is DynamicEventKind.PEER_TRAJECTORY_UPDATED:
            event_payload["peer_trajectory_sha256"] = str(sequence) * 64
        else:
            event_payload.update(
                {
                    "region_id": "qualification-dynamic-obstacle",
                    "region": Region3D(
                        region_id="qualification-dynamic-obstacle",
                        minimum_m=Vector3(x=-0.2, y=-0.2, z=0.0),
                        maximum_m=Vector3(x=0.2, y=0.2, z=1.0),
                    ),
                }
            )
        proposal = (
            real_proposal
            if qualification_scope
            is DynamicQualificationScope.REAL_CHANGED_WORLD_PLAN_PLUS_COORDINATOR_COMMIT
            else None
        )
        if proposal is not None:
            selected_case = real_case
            selected_event = real_event
            replacements = tuple(
                FleetRouteReplacement(
                    role_id=item.role_id,
                    old_trajectory_sha256=item.old_trajectory_sha256,
                    replacement_trajectory_sha256=item.replacement_trajectory_sha256,
                    replacement_plan_sha256=item.replacement_plan_sha256,
                    feasible=True,
                    cancellation_acknowledged=True,
                    replacement_acknowledged=True,
                )
                for item in proposal.route_authorities
            )
            old_world_sha256 = proposal.old_world_sha256
            replacement_world_sha256 = proposal.replacement_world_sha256
            certificate_sha256s = tuple(
                item.feasibility_certificate_sha256
                for item in proposal.route_authorities
            )
        else:
            selected_case = case
            selected_event = InFlightEnvironmentEvent(**event_payload)
            replacements = tuple(
                FleetRouteReplacement(
                    role_id=role_id,
                    old_trajectory_sha256=str(index) * 64,
                    replacement_trajectory_sha256=str(index + 2) * 64,
                    replacement_plan_sha256=str(index + 4) * 64,
                    feasible=True,
                    cancellation_acknowledged=True,
                    replacement_acknowledged=(
                        complete_acknowledgement or role_id == "Alpha"
                    ),
                )
                for index, role_id in enumerate(("Alpha", "Beta"), start=1)
            )
            old_world_sha256 = "b" * 64
            replacement_world_sha256 = "c" * 64
            certificate_sha256s = ("d" * 64, "e" * 64)
        decision = InFlightReplanCoordinator(selected_case).replan(
            selected_event,
            decision_time_source_s=10.30,
            queue_latency_s=0.05,
            planning_latency_s=0.20,
            acknowledgement_latency_s=0.05,
            cutover_guard_s=0.10,
            old_epoch_safe_until_source_s=(
                10.20
                if expected_disposition
                is DynamicReplanDisposition.BLOCKED_REACTION_HORIZON
                else 13.20
            ),
            old_epoch_still_safe=(
                expected_disposition
                is not DynamicReplanDisposition.BLOCKED_REACTION_HORIZON
            ),
            old_epoch=1,
            old_reservation_sha256="a" * 64,
            old_world_sha256=old_world_sha256,
            replacement_world_sha256=replacement_world_sha256,
            replacements=replacements,
            feasibility_certificate_sha256s=certificate_sha256s,
        )
        committed = (
            decision.fleet_decision.committed_route_count
            if decision.fleet_decision is not None
            else 0
        )
        passed = (
            decision.disposition is expected_disposition
            and committed == expected_committed
            and decision.fallback is expected_fallback
        )
        payload = {
            "row_id": row_id,
            "event_kind": kind,
            "qualification_scope": qualification_scope,
            "actual_disposition": decision.disposition,
            "reaction_horizon_passed": decision.reaction_horizon.passed,
            "committed_route_count": committed,
            "fallback": decision.fallback,
            "proposal_sha256": proposal.proposal_sha256 if proposal else None,
            "replacement_world_sha256": (
                proposal.replacement_world_sha256 if proposal else None
            ),
            "feasibility_certificate_sha256s": (
                certificate_sha256s if proposal else ()
            ),
            "passed": passed,
            "decision_sha256": decision.decision_sha256,
        }
        output.append(
            DynamicReplanningMatrixResult(
                **payload,
                result_sha256=canonical_sha256(payload),
            )
        )
    return tuple(output)


def _replanning_qualification_child(
    source: CampaignCase,
    suffix: str,
) -> CampaignCase:
    payload = source.model_dump(mode="python")
    payload.update(
        {
            "case_id": f"{source.case_id}.qualification.{suffix}",
            "parent_case_sha256": source.case_sha256,
            "baseline_sha256": source.case_sha256,
            "replanning_authority": ReplanningAuthority.AUTO_WITHIN_FROZEN_LIMITS,
            "purpose": f"Dynamic replanning qualification child for {source.case_id}.",
        }
    )
    return CampaignCase.model_validate(payload)


def _mutated_case(
    source: CampaignCase,
    row: ConstraintDirectedMatrixRow,
) -> CampaignCase:
    if row.mutation is CaseMutation.NONE:
        return source
    allowed = source.allowed_strategies
    hard_constraints = source.hard_constraints
    if row.mutation is CaseMutation.DIRECT_ONLY:
        allowed = (PlannerStrategy.DIRECT,)
    elif row.mutation is CaseMutation.VERTICAL_FORBIDDEN:
        allowed = tuple(
            strategy
            for strategy in allowed
            if strategy
            not in {
                PlannerStrategy.VERTICAL_LAYER,
                PlannerStrategy.COMBINED_TIMING_GEOMETRY,
            }
        )
        hard_constraints = hard_constraints.model_copy(
            update={"vertical_layers_allowed": False}
        )
    elif row.mutation is CaseMutation.OPEN_CEILING_VERTICAL_ONLY:
        allowed = (PlannerStrategy.VERTICAL_LAYER,)
        volume = hard_constraints.flight_volume
        hard_constraints = hard_constraints.model_copy(
            update={
                "flight_volume": volume.model_copy(
                    update={
                        "minimum_m": volume.minimum_m.model_copy(
                            update={
                                "x": volume.minimum_m.x - 0.25,
                                "y": volume.minimum_m.y - 0.25,
                            }
                        ),
                        "maximum_m": volume.maximum_m.model_copy(
                            update={
                                "x": volume.maximum_m.x + 0.25,
                                "y": volume.maximum_m.y + 0.25,
                                "z": volume.maximum_m.z + 1.0,
                            }
                        )
                    }
                )
            }
        )
    payload = source.model_dump(mode="python")
    payload.update(
        {
            "case_id": f"{source.case_id}.qualification.{row.row_id.split('.', 1)[1]}",
            "parent_case_sha256": source.case_sha256,
            "allowed_strategies": allowed,
            "hard_constraints": hard_constraints,
            "purpose": f"Causal qualification row {row.row_id}.",
            "behavior_under_test": row.causal_question,
        }
    )
    return CampaignCase.model_validate(payload)
