from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.observability.evaluation import (
    EvaluationStatus,
    MissionExecutionEvaluation,
)
from crazyswarm_app.planning.deconfliction import ConflictResolutionStrategy
from crazyswarm_app.safety.policy import FlightVolume, SafetyPolicy
from crazyswarm_app.simulation.clock import ClockMode

CURRICULUM_CONTRACT = "progressive-mission-curriculum-v1"
TEMPLATE_VERSION = "1.0.0"
DEFAULT_SEEDS = (109, 811)


class MissionCaseTemplate(StrEnum):
    ENDPOINT_LANDING = "ENDPOINT_LANDING"
    CONTINUOUS_ROUTE = "CONTINUOUS_ROUTE"
    PARALLEL_TERMINAL = "PARALLEL_TERMINAL"
    STAGED_CROSSING = "STAGED_CROSSING"
    NO_HOVER_CROSSING = "NO_HOVER_CROSSING"


class BorderVariant(StrEnum):
    COMPACT = "COMPACT"
    NOMINAL = "NOMINAL"
    WIDE = "WIDE"


class ObjectiveKind(StrEnum):
    HARD_SAFETY = "HARD_SAFETY"
    GOAL_ACCURACY = "GOAL_ACCURACY"
    COMPLETION_TIME = "COMPLETION_TIME"
    PATH_LENGTH = "PATH_LENGTH"
    SMOOTHNESS = "SMOOTHNESS"
    HOVER_TIME = "HOVER_TIME"
    ROBUSTNESS_MARGIN = "ROBUSTNESS_MARGIN"
    ROLE_FAIRNESS = "ROLE_FAIRNESS"


class CaseGoal(ContractModel):
    role_id: Identifier
    start_m: Vector3
    landing_target_m: Vector3
    horizontal_tolerance_m: float = Field(gt=0.0)
    vertical_tolerance_m: float = Field(gt=0.0)
    maximum_terminal_speed_m_s: float = Field(gt=0.0)


class CaseAcceptanceThresholds(ContractModel):
    evidence_complete: Literal[True] = True
    maximum_critical_samples: int = Field(default=0, ge=0)
    maximum_warning_samples: int = Field(default=0, ge=0)
    maximum_goal_error_m: float = Field(default=0.10, gt=0.0)
    maximum_generated_unintended_stops: int = Field(default=0, ge=0)
    required_deconfliction_strategy: ConflictResolutionStrategy | None = None


class MissionCaseDefinition(ContractModel):
    schema_version: Literal[1] = 1
    case_id: Identifier
    template: MissionCaseTemplate
    template_version: Literal["1.0.0"] = "1.0.0"
    level: int = Field(ge=1, le=5)
    border_variant: BorderVariant
    seed: int = Field(ge=0)
    clock_modes: tuple[ClockMode, ...]
    role_count: int = Field(ge=1, le=2)
    flight_volume: FlightVolume
    max_altitude_m: float = Field(gt=0.0)
    warning_separation_m: float = Field(gt=0.0)
    critical_separation_m: float = Field(gt=0.0)
    planned_hold_permitted: bool
    allowed_deconfliction_strategies: tuple[ConflictResolutionStrategy, ...]
    hard_constraints: tuple[Identifier, ...]
    objective_order: tuple[ObjectiveKind, ...]
    goals: tuple[CaseGoal, ...]
    mission_filename: str
    mission_source: str
    mission_source_sha256: SHA256
    thresholds: CaseAcceptanceThresholds
    case_sha256: SHA256

    @model_validator(mode="after")
    def identities_and_constraints_agree(self) -> MissionCaseDefinition:
        source_sha256 = hashlib.sha256(self.mission_source.encode()).hexdigest()
        if source_sha256 != self.mission_source_sha256:
            raise ValueError("mission case source hash does not match its source")
        if len(self.goals) != self.role_count:
            raise ValueError("mission case goal count does not match role count")
        if self.warning_separation_m <= self.critical_separation_m:
            raise ValueError("mission case warning separation must exceed critical")
        if not self.planned_hold_permitted and (
            ConflictResolutionStrategy.STAGING_HOLD in self.allowed_deconfliction_strategies
        ):
            raise ValueError("no-hover case cannot admit staging hold")
        if self.case_sha256 != canonical_sha256(
            self.model_dump(mode="python", exclude={"case_sha256"})
        ):
            raise ValueError("mission case identity does not match its canonical payload")
        return self

    def safety_policy(self) -> SafetyPolicy:
        return SafetyPolicy(
            max_altitude_m=self.max_altitude_m,
            flight_volume=self.flight_volume,
        )


class CurriculumManifest(ContractModel):
    schema_version: Literal[1] = 1
    contract: Literal["progressive-mission-curriculum-v1"] = "progressive-mission-curriculum-v1"
    curriculum_id: Identifier
    cases: tuple[MissionCaseDefinition, ...]
    promotion_order: tuple[Literal[1, 2, 3, 4, 5], ...] = (1, 2, 3, 4, 5)
    generation_limitations: tuple[str, ...]
    manifest_sha256: SHA256

    @model_validator(mode="after")
    def deterministic_case_set(self) -> CurriculumManifest:
        if len({item.case_id for item in self.cases}) != len(self.cases):
            raise ValueError("curriculum case ids must be unique")
        if len({item.case_sha256 for item in self.cases}) != len(self.cases):
            raise ValueError("curriculum case hashes must be unique")
        if self.manifest_sha256 != canonical_sha256(
            self.model_dump(mode="python", exclude={"manifest_sha256"})
        ):
            raise ValueError("curriculum manifest hash does not match its payload")
        return self


class CurriculumBaseline(ContractModel):
    case_id: Identifier
    case_sha256: SHA256
    evaluator_id: Identifier
    evaluator_version: str
    evaluation_report_sha256: SHA256
    mission_execution_id: Identifier
    evidence_complete: bool
    vehicle_count: int = Field(ge=1)
    warning_samples: int = Field(ge=0)
    critical_samples: int = Field(ge=0)
    minimum_separation_m: float | None = Field(default=None, ge=0.0)
    minimum_goal_capture_margin_m: float | None = None
    maximum_generated_unintended_stops: int = Field(ge=0)
    selected_deconfliction_strategy: Identifier | None = None
    hard_gates_passed: bool
    findings: tuple[Identifier, ...]
    baseline_sha256: SHA256


class CurriculumPromotion(ContractModel):
    curriculum_manifest_sha256: SHA256
    baselines: tuple[CurriculumBaseline, ...]
    promoted_levels: tuple[int, ...]
    blocked_level: int | None = Field(default=None, ge=1, le=5)
    missing_case_sha256s: tuple[SHA256, ...]
    failed_case_sha256s: tuple[SHA256, ...]
    passed: bool
    promotion_sha256: SHA256


def generate_progressive_curriculum(
    *,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    border_variants: tuple[BorderVariant, ...] = tuple(BorderVariant),
) -> CurriculumManifest:
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("curriculum seeds must be non-empty and unique")
    if not border_variants or len(set(border_variants)) != len(border_variants):
        raise ValueError("curriculum border variants must be non-empty and unique")
    cases = tuple(
        _case(template, border, seed)
        for template in MissionCaseTemplate
        for border in border_variants
        for seed in sorted(seeds)
    )
    payload = {
        "schema_version": 1,
        "contract": CURRICULUM_CONTRACT,
        "curriculum_id": "mission-curriculum-fast-sim-v1",
        "cases": cases,
        "promotion_order": (1, 2, 3, 4, 5),
        "generation_limitations": (
            "configured borders only; perceived-object avoidance is excluded",
            "small exact template family with deterministic parameter expansion",
            "Fast Sim evidence does not establish physical or live-Isaac behavior",
        ),
    }
    return CurriculumManifest(
        **payload,
        manifest_sha256=canonical_sha256(payload),
    )


def baseline_from_evaluation(
    case: MissionCaseDefinition,
    evaluation: MissionExecutionEvaluation,
) -> CurriculumBaseline:
    findings: list[str] = []
    thresholds = case.thresholds
    if evaluation.status is not EvaluationStatus.COMPLETE or not evaluation.evidence.complete:
        findings.append("EVIDENCE_INCOMPLETE")
    if evaluation.fleet.vehicle_count != case.role_count:
        findings.append("ROLE_COUNT_MISMATCH")
    if evaluation.fleet.critical_sample_count > thresholds.maximum_critical_samples:
        findings.append("CRITICAL_SEPARATION_REGRESSION")
    if evaluation.fleet.warning_sample_count > thresholds.maximum_warning_samples:
        findings.append("WARNING_SEPARATION_REGRESSION")
    generated_stops = max(
        (item.trajectory_generation_unintended_stop_count for item in evaluation.vehicles),
        default=0,
    )
    if generated_stops > thresholds.maximum_generated_unintended_stops:
        findings.append("TRAJECTORY_STOP_REGRESSION")
    goal_margins = [
        item.terminal_goal_capture_margin_m
        for item in evaluation.vehicles
        if item.terminal_goal_capture_margin_m is not None
    ]
    if len(goal_margins) != case.role_count or min(goal_margins, default=-1.0) < 0.0:
        findings.append("GOAL_CAPTURE_REGRESSION")
    if any(item.terminal_contact != "SIMULATED_GROUND_CONTACT" for item in evaluation.vehicles):
        findings.append("TERMINAL_EVIDENCE_REGRESSION")
    required_strategy = thresholds.required_deconfliction_strategy
    selected_strategy = evaluation.fleet.selected_deconfliction_strategy
    if required_strategy is not None and selected_strategy != required_strategy.value:
        findings.append("DECONFLICTION_STRATEGY_MISMATCH")
    if (
        required_strategy is not None
        and evaluation.fleet.nominal_deconfliction_executed is not True
    ):
        findings.append("DECONFLICTION_IDENTITY_MISMATCH")
    payload = {
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "evaluator_id": evaluation.evaluator_id,
        "evaluator_version": evaluation.evaluator_version,
        "evaluation_report_sha256": evaluation.report_sha256,
        "mission_execution_id": evaluation.mission_execution_id,
        "evidence_complete": evaluation.evidence.complete,
        "vehicle_count": evaluation.fleet.vehicle_count,
        "warning_samples": evaluation.fleet.warning_sample_count,
        "critical_samples": evaluation.fleet.critical_sample_count,
        "minimum_separation_m": (
            evaluation.fleet.minimum_truth_separation_m
            if evaluation.fleet.minimum_truth_separation_m is not None
            else evaluation.fleet.minimum_estimated_separation_m
        ),
        "minimum_goal_capture_margin_m": min(goal_margins, default=None),
        "maximum_generated_unintended_stops": generated_stops,
        "selected_deconfliction_strategy": selected_strategy,
        "hard_gates_passed": not findings,
        "findings": tuple(findings),
    }
    return CurriculumBaseline(
        **payload,
        baseline_sha256=canonical_sha256(payload),
    )


def promote_curriculum(
    manifest: CurriculumManifest,
    reports_by_case_sha256: dict[str, MissionExecutionEvaluation],
) -> CurriculumPromotion:
    baselines = tuple(
        baseline_from_evaluation(case, reports_by_case_sha256[case.case_sha256])
        for case in manifest.cases
        if case.case_sha256 in reports_by_case_sha256
    )
    baseline_by_case = {item.case_sha256: item for item in baselines}
    promoted: list[int] = []
    missing: list[str] = []
    failed: list[str] = []
    blocked_level: int | None = None
    for level in manifest.promotion_order:
        level_cases = tuple(item for item in manifest.cases if item.level == level)
        level_missing = [
            item.case_sha256 for item in level_cases if item.case_sha256 not in baseline_by_case
        ]
        level_failed = [
            item.case_sha256
            for item in level_cases
            if item.case_sha256 in baseline_by_case
            and not baseline_by_case[item.case_sha256].hard_gates_passed
        ]
        missing.extend(level_missing)
        failed.extend(level_failed)
        if level_missing or level_failed:
            blocked_level = level
            break
        promoted.append(level)
    payload = {
        "curriculum_manifest_sha256": manifest.manifest_sha256,
        "baselines": baselines,
        "promoted_levels": tuple(promoted),
        "blocked_level": blocked_level,
        "missing_case_sha256s": tuple(sorted(missing)),
        "failed_case_sha256s": tuple(sorted(failed)),
        "passed": len(promoted) == len(manifest.promotion_order),
    }
    return CurriculumPromotion(
        **payload,
        promotion_sha256=canonical_sha256(payload),
    )


def _case(
    template: MissionCaseTemplate,
    border: BorderVariant,
    seed: int,
) -> MissionCaseDefinition:
    level = tuple(MissionCaseTemplate).index(template) + 1
    half_width = {
        BorderVariant.COMPACT: 1.35,
        BorderVariant.NOMINAL: 1.6,
        BorderVariant.WIDE: 2.0,
    }[border]
    flight_volume = FlightVolume(
        minimum_m=Vector3(x=-half_width, y=-half_width, z=0.0),
        maximum_m=Vector3(x=half_width, y=half_width, z=1.0),
    )
    source, role_count, goals = _template_source(template)
    strategies = (
        (
            ConflictResolutionStrategy.SPEED_RETIMING,
            ConflictResolutionStrategy.HORIZONTAL_DETOUR,
        )
        if template is MissionCaseTemplate.NO_HOVER_CROSSING
        else tuple(ConflictResolutionStrategy)
    )
    hold_permitted = template is not MissionCaseTemplate.NO_HOVER_CROSSING
    required_strategy = {
        MissionCaseTemplate.STAGED_CROSSING: ConflictResolutionStrategy.STAGING_HOLD,
        MissionCaseTemplate.NO_HOVER_CROSSING: ConflictResolutionStrategy.SPEED_RETIMING,
    }.get(template)
    case_id = f"case-l{level}-{border.value.lower()}-seed-{seed}"
    source_sha256 = hashlib.sha256(source.encode()).hexdigest()
    payload = {
        "schema_version": 1,
        "case_id": case_id,
        "template": template,
        "template_version": TEMPLATE_VERSION,
        "level": level,
        "border_variant": border,
        "seed": seed,
        "clock_modes": (ClockMode.ACCELERATED, ClockMode.REALTIME),
        "role_count": role_count,
        "flight_volume": flight_volume,
        "max_altitude_m": 1.0,
        "warning_separation_m": 0.75,
        "critical_separation_m": 0.4,
        "planned_hold_permitted": hold_permitted,
        "allowed_deconfliction_strategies": strategies,
        "hard_constraints": (
            "FLIGHT_VOLUME",
            "ALTITUDE",
            "CRITICAL_SEPARATION",
            "DYNAMICS",
            "GOAL_CAPTURE",
            "TERMINAL_READY",
        ),
        "objective_order": (
            ObjectiveKind.HARD_SAFETY,
            ObjectiveKind.GOAL_ACCURACY,
            ObjectiveKind.ROBUSTNESS_MARGIN,
            ObjectiveKind.COMPLETION_TIME,
            ObjectiveKind.PATH_LENGTH,
            ObjectiveKind.SMOOTHNESS,
            ObjectiveKind.HOVER_TIME,
            ObjectiveKind.ROLE_FAIRNESS,
        ),
        "goals": goals,
        "mission_filename": f"{template.value.lower()}.py",
        "mission_source": source,
        "mission_source_sha256": source_sha256,
        "thresholds": CaseAcceptanceThresholds(required_deconfliction_strategy=required_strategy),
    }
    case_sha256 = canonical_sha256(payload)
    return MissionCaseDefinition(**payload, case_sha256=case_sha256)


def _template_source(
    template: MissionCaseTemplate,
) -> tuple[str, int, tuple[CaseGoal, ...]]:
    if template in {
        MissionCaseTemplate.ENDPOINT_LANDING,
        MissionCaseTemplate.CONTINUOUS_ROUTE,
    }:
        repeats = 10 if template is MissionCaseTemplate.ENDPOINT_LANDING else 16
        start_x = -0.5 if repeats == 10 else -0.8
        source = f"""MISSION = {{
    "schema_version": 2,
    "roles": {{
        "primary": {{
            "logical_vehicle_id": "case-primary",
            "home_m": [{start_x}, 0.0, 0.0],
        }},
    }},
}}

async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    for _ in range({repeats}):
        await drone.move_relative(x_m=0.1, duration_s=0.8, frame="home")
    await drone.land(duration_s=2.0)
"""
        return (
            source,
            1,
            (
                CaseGoal(
                    role_id="primary",
                    start_m=Vector3(x=start_x),
                    landing_target_m=Vector3(x=-start_x),
                    horizontal_tolerance_m=0.10,
                    vertical_tolerance_m=0.08,
                    maximum_terminal_speed_m_s=0.08,
                ),
            ),
        )
    if template is MissionCaseTemplate.PARALLEL_TERMINAL:
        source = """MISSION = {
    "schema_version": 2,
    "roles": {
        "parallel_low": {"logical_vehicle_id": "parallel-low", "home_m": [-0.8, -0.6, 0.0]},
        "parallel_high": {"logical_vehicle_id": "parallel-high", "home_m": [-0.8, 0.6, 0.0]},
    },
    "warning_separation_m": 0.75,
    "critical_separation_m": 0.4,
}

async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    for _ in range(16):
        await drone.move_relative(x_m=0.1, duration_s=0.8, frame="home")
    await drone.land(duration_s=2.0)
"""
        return (
            source,
            2,
            tuple(
                CaseGoal(
                    role_id=role,
                    start_m=Vector3(x=-0.8, y=y_m),
                    landing_target_m=Vector3(x=0.8, y=y_m),
                    horizontal_tolerance_m=0.10,
                    vertical_tolerance_m=0.08,
                    maximum_terminal_speed_m_s=0.08,
                )
                for role, y_m in (("parallel_low", -0.6), ("parallel_high", 0.6))
            ),
        )
    strategies = (
        '"SPEED_RETIMING", "HORIZONTAL_DETOUR"'
        if template is MissionCaseTemplate.NO_HOVER_CROSSING
        else (
            '"STAGING_HOLD", "SPEED_RETIMING", "HORIZONTAL_DETOUR", '
            '"VERTICAL_SEPARATION", "COMBINED_RETIMING_VERTICAL"'
        )
    )
    no_hover = "False" if template is MissionCaseTemplate.NO_HOVER_CROSSING else "True"
    initial_hold = (
        ""
        if template is MissionCaseTemplate.NO_HOVER_CROSSING
        else "    await drone.hover(duration_s=1.0)\n"
    )
    source = f"""MISSION = {{
    "schema_version": 2,
    "roles": {{
        "cross_west": {{
            "logical_vehicle_id": "crossing-west",
            "home_m": [-1.2, 0.0, 0.0],
            "task": {{"task_type": "crossing-route", "priority": 150}},
        }},
        "cross_south": {{
            "logical_vehicle_id": "crossing-south",
            "home_m": [0.0, -1.2, 0.0],
            "task": {{"task_type": "crossing-route", "priority": 150}},
        }},
    }},
    "warning_separation_m": 0.75,
    "critical_separation_m": 0.4,
    "planned_hold_permitted": {no_hover},
    "deconfliction_strategies": [{strategies}],
}}

async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
{initial_hold}
    for _ in range(24):
        if drone.role == "cross_west":
            await drone.move_relative(x_m=0.1, duration_s=0.8, frame="home")
        else:
            await drone.move_relative(y_m=0.1, duration_s=0.8, frame="home")
    await drone.land(duration_s=2.0)
"""
    return (
        source,
        2,
        (
            CaseGoal(
                role_id="cross_south",
                start_m=Vector3(y=-1.2),
                landing_target_m=Vector3(y=1.2),
                horizontal_tolerance_m=0.10,
                vertical_tolerance_m=0.08,
                maximum_terminal_speed_m_s=0.08,
            ),
            CaseGoal(
                role_id="cross_west",
                start_m=Vector3(x=-1.2),
                landing_target_m=Vector3(x=1.2),
                horizontal_tolerance_m=0.10,
                vertical_tolerance_m=0.08,
                maximum_terminal_speed_m_s=0.08,
            ),
        ),
    )
