from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class TwinStageStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    READY = "READY"
    PASSED = "PASSED"
    FAILED = "FAILED"


class TwinCurriculumStage(ContractModel):
    stage_id: Identifier
    order: int = Field(ge=1)
    environment: Literal["FAST_SIM", "REAL_ADAPTER"]
    prerequisites: tuple[Identifier, ...] = ()
    mission_family: Identifier
    case_id: Identifier
    status: TwinStageStatus = TwinStageStatus.NOT_RUN
    session_id: Identifier | None = None
    result_sha256: SHA256 | None = None


class TwinCurriculumResultRequest(ContractModel):
    session_id: Identifier
    status: Literal[TwinStageStatus.PASSED, TwinStageStatus.FAILED]
    result_sha256: SHA256


class TwinCurriculum(ContractModel):
    schema_version: Literal[1] = 1
    stages: tuple[TwinCurriculumStage, ...]
    curriculum_sha256: SHA256

    def record_result(
        self,
        stage_id: str,
        request: TwinCurriculumResultRequest,
    ) -> tuple[TwinCurriculum, TwinCurriculumStage]:
        by_id = {item.stage_id: item for item in self.stages}
        try:
            current = by_id[stage_id]
        except KeyError as error:
            raise ValueError("unknown twin curriculum stage") from error
        if current.environment != "FAST_SIM":
            raise ValueError("real-adapter curriculum stages remain literal NOT_RUN")
        if current.status != TwinStageStatus.READY:
            raise ValueError("twin curriculum stage prerequisites are not ready")
        completed = current.model_copy(
            update={
                "status": request.status,
                "session_id": request.session_id,
                "result_sha256": request.result_sha256,
            }
        )
        by_id[stage_id] = completed
        if request.status == TwinStageStatus.PASSED:
            for candidate in self.stages:
                if (
                    candidate.environment == "FAST_SIM"
                    and candidate.status == TwinStageStatus.NOT_RUN
                    and all(
                        by_id[prerequisite].status == TwinStageStatus.PASSED
                        for prerequisite in candidate.prerequisites
                    )
                ):
                    by_id[candidate.stage_id] = candidate.model_copy(
                        update={"status": TwinStageStatus.READY}
                    )
        stages = tuple(by_id[item.stage_id] for item in self.stages)
        payload = {"schema_version": 1, "stages": stages}
        return (
            TwinCurriculum(**payload, curriculum_sha256=canonical_sha256(payload)),
            completed,
        )

    def replay_result(self, stage: TwinCurriculumStage) -> TwinCurriculum:
        if stage.status not in {TwinStageStatus.PASSED, TwinStageStatus.FAILED}:
            raise ValueError("persisted curriculum result is not terminal")
        request = TwinCurriculumResultRequest(
            session_id=stage.session_id,
            status=stage.status,
            result_sha256=stage.result_sha256,
        )
        updated, reproduced = self.record_result(stage.stage_id, request)
        if reproduced != stage:
            raise ValueError("persisted curriculum stage result is inconsistent")
        return updated

    @classmethod
    def configured(cls) -> TwinCurriculum:
        families = (
            "startup_props_off_equivalent",
            "slow_takeoff",
            "hover",
            "landing",
            "straight_1d",
            "checkpoint_path",
            "continuous_path",
            "online_obstacle_replan",
        )
        cases = {
            "startup_props_off_equivalent": "1d.takeoff_hover_land.canonical_nominal",
            "slow_takeoff": "1d.takeoff_hover_land.canonical_nominal",
            "hover": "1d.takeoff_hover_land.canonical_nominal",
            "landing": "1d.takeoff_hover_land.canonical_nominal",
            "straight_1d": "1d.point_to_point_relocation.canonical_nominal",
            "checkpoint_path": "1d.static_multi_goal_sequence.canonical_nominal",
            "continuous_path": "1d.continuous_waypoint_sequence.canonical_nominal",
            "online_obstacle_replan": "1d.online_obstacle_replan.dynamic_nominal",
        }
        simulated = tuple(
            TwinCurriculumStage(
                stage_id=f"sim.{family}",
                order=index,
                environment="FAST_SIM",
                prerequisites=(() if index == 1 else (f"sim.{families[index - 2]}",)),
                mission_family=family,
                case_id=cases[family],
                status=(TwinStageStatus.READY if index == 1 else TwinStageStatus.NOT_RUN),
            )
            for index, family in enumerate(families, start=1)
        )
        real = tuple(
            TwinCurriculumStage(
                stage_id=f"real.{family}",
                order=index + len(families),
                environment="REAL_ADAPTER",
                prerequisites=(f"sim.{family}",),
                mission_family=family,
                case_id=cases[family],
                status=TwinStageStatus.NOT_RUN,
            )
            for index, family in enumerate(families, start=1)
        )
        payload = {"schema_version": 1, "stages": (*simulated, *real)}
        return cls(**payload, curriculum_sha256=canonical_sha256(payload))
