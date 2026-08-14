from pathlib import Path

import pytest

from crazyswarm_app.domain.models import CoordinateFrame
from crazyswarm_app.twin.coordinator import TwinCoordinator
from crazyswarm_app.twin.models import TwinInitialState, TwinSessionConfig, TwinSourceClass


def _config() -> TwinSessionConfig:
    return TwinSessionConfig(
        observed_vehicle_id="observed",
        simulated_vehicle_id="predicted",
        mission_id="straight-1d",
        mission_version="1.0.0",
        observed_initial_state=TwinInitialState(
            source_class=TwinSourceClass.CONFIGURED,
            source_id="sim-observed",
            frame=CoordinateFrame.WORLD,
        ),
        simulated_initial_state=TwinInitialState(
            source_class=TwinSourceClass.SIMULATED_MODEL,
            source_id="model",
            frame=CoordinateFrame.WORLD,
        ),
        ground_truth_available=True,
    )


def test_session_journal_recovers_exact_record_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "twin"
    first = TwinCoordinator(root)
    created = first.create_session(_config())
    first.complete(created.session_id)
    recovered = TwinCoordinator(root).session(created.session_id)
    assert recovered.status.value == "COMPLETE"
    assert recovered.observed_source_class is TwinSourceClass.CONFIGURED
    assert recovered.simulated_source_class is TwinSourceClass.SIMULATED_MODEL


def test_truncated_journal_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "twin"
    coordinator = TwinCoordinator(root)
    coordinator.create_session(_config())
    journal = root / "twin-journal-v1.jsonl"
    journal.write_bytes(journal.read_bytes()[:-1])
    with pytest.raises(ValueError, match="truncated twin journal"):
        TwinCoordinator(root)
