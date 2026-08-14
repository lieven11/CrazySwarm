from pathlib import Path

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import CoordinateFrame
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.twin.coordinator import TwinCoordinator
from crazyswarm_app.twin.curriculum import (
    TwinCurriculum,
    TwinCurriculumResultRequest,
    TwinStageStatus,
)
from crazyswarm_app.twin.models import (
    TwinInitialState,
    TwinSessionConfig,
    TwinSourceClass,
)


def test_curriculum_is_ordered_and_real_stages_remain_not_run() -> None:
    curriculum = TwinCurriculum.configured()
    simulated = [item for item in curriculum.stages if item.environment == "FAST_SIM"]
    real = [item for item in curriculum.stages if item.environment == "REAL_ADAPTER"]
    assert [item.mission_family for item in simulated] == [
        "startup_props_off_equivalent",
        "slow_takeoff",
        "hover",
        "landing",
        "straight_1d",
        "checkpoint_path",
        "continuous_path",
        "online_obstacle_replan",
    ]
    assert simulated[0].status is TwinStageStatus.READY
    assert all(item.status is TwinStageStatus.NOT_RUN for item in real)
    assert all(item.prerequisites == (f"sim.{item.mission_family}",) for item in real)


def _session_config(stage_id: str) -> TwinSessionConfig:
    return TwinSessionConfig(
        observed_vehicle_id=f"observed-{stage_id}",
        simulated_vehicle_id=f"predicted-{stage_id}",
        mission_id=stage_id,
        mission_version="1",
        curriculum_stage_id=stage_id,
        observed_initial_state=TwinInitialState(
            source_class=TwinSourceClass.CONFIGURED,
            source_id="fast-sim-truth",
            frame=CoordinateFrame.WORLD,
        ),
        simulated_initial_state=TwinInitialState(
            source_class=TwinSourceClass.SIMULATED_MODEL,
            source_id="candidate-model",
            frame=CoordinateFrame.WORLD,
        ),
        ground_truth_available=True,
    )


def test_stage_result_unlocks_only_the_next_sim_stage_and_survives_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "twin"
    coordinator = TwinCoordinator(root)
    stage_id = "sim.startup_props_off_equivalent"
    session = coordinator.create_session(_session_config(stage_id))
    coordinator.complete(session.session_id)
    result = coordinator.record_curriculum_result(
        stage_id,
        TwinCurriculumResultRequest(
            session_id=session.session_id,
            status=TwinStageStatus.PASSED,
            result_sha256=canonical_sha256([stage_id, session.session_id, "passed"]),
        ),
    )
    assert result.status is TwinStageStatus.PASSED
    restarted = TwinCoordinator(root).curriculum()
    by_id = {item.stage_id: item for item in restarted.stages}
    assert by_id["sim.slow_takeoff"].status is TwinStageStatus.READY
    assert by_id["sim.hover"].status is TwinStageStatus.NOT_RUN
    assert all(
        item.status is TwinStageStatus.NOT_RUN
        for item in restarted.stages
        if item.environment == "REAL_ADAPTER"
    )


def test_failed_or_mismatched_stage_cannot_bypass_prerequisites(tmp_path: Path) -> None:
    coordinator = TwinCoordinator(tmp_path / "twin")
    stage_id = "sim.startup_props_off_equivalent"
    session = coordinator.create_session(_session_config(stage_id))
    coordinator.complete(session.session_id)
    with pytest.raises(CrazySwarmError, match="not bound"):
        coordinator.record_curriculum_result(
            "sim.slow_takeoff",
            TwinCurriculumResultRequest(
                session_id=session.session_id,
                status=TwinStageStatus.PASSED,
                result_sha256=canonical_sha256("wrong-stage"),
            ),
        )
    coordinator.record_curriculum_result(
        stage_id,
        TwinCurriculumResultRequest(
            session_id=session.session_id,
            status=TwinStageStatus.FAILED,
            result_sha256=canonical_sha256("failed"),
        ),
    )
    by_id = {item.stage_id: item for item in coordinator.curriculum().stages}
    assert by_id["sim.slow_takeoff"].status is TwinStageStatus.NOT_RUN
