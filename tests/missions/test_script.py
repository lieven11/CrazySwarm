from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import VehicleIdentity, VehicleState
from crazyswarm_app.missions import script as script_module
from crazyswarm_app.missions.models import MissionStatus
from crazyswarm_app.missions.registry import MissionRegistry
from crazyswarm_app.missions.runner import MissionRunner
from crazyswarm_app.missions.script import (
    MissionFileLibrary,
    execute_isolated_mission,
    parse_python_mission,
    preview_isolated_mission_role,
)
from crazyswarm_app.safety.supervisor import SafetySupervisor
from crazyswarm_app.simulation.vehicle import SimulatedVehicle
from crazyswarm_app.simulation.world import IndoorWorld, WorldConfig

SOURCE = """\
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2.0)
    await drone.hover(duration_s=1.0)
    await drone.move_relative(x_m=0.2, duration_s=1.5, frame="home")
    await drone.land(duration_s=2.0)
"""


def test_parser_accepts_only_a_complete_restricted_mission() -> None:
    record = parse_python_mission(filename="hover.py", name="Hover", source=SOURCE)
    assert record.mission_id.startswith("py-")
    assert [step.action for step in record.steps] == [
        "takeoff",
        "hover",
        "move_relative",
        "land",
    ]
    with pytest.raises(CrazySwarmError, match="only async def mission"):
        parse_python_mission(
            filename="unsafe.py",
            name="Unsafe",
            source="import os\nasync def mission(drone):\n    await drone.land(duration_s=2.0)\n",
        )
    with pytest.raises(CrazySwarmError, match="start with takeoff"):
        parse_python_mission(
            filename="incomplete.py",
            name="Incomplete",
            source="async def mission(drone):\n    await drone.hover(duration_s=1.0)\n",
        )


def test_worker_accepts_legacy_record_request_without_protocol_mode() -> None:
    worker = Path(script_module.__file__).with_name("_mission_worker.py")
    request = json.dumps(
        {
            "source": SOURCE,
            "source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        },
        separators=(",", ":"),
    ).encode()

    completed = subprocess.run(
        [sys.executable, "-I", str(worker)],
        input=request,
        capture_output=True,
        check=False,
        timeout=2.0,
    )

    response = json.loads(completed.stdout)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert response["ok"] is True
    assert [step["action"] for step in response["steps"]] == [
        "takeoff",
        "hover",
        "move_relative",
        "land",
    ]


@pytest.mark.asyncio
async def test_uploaded_file_runs_unchanged_through_simulator(tmp_path: Path) -> None:
    registry = MissionRegistry()
    library = MissionFileLibrary(tmp_path / "missions", registry)
    record = library.add(filename="hover.py", name="Hover", source=SOURCE)
    vehicle = SimulatedVehicle(
        VehicleIdentity(vehicle_id="sim01", display_name="Sim", adapter="sim"),
        IndoorWorld(WorldConfig(width_m=4.0, depth_m=4.0, height_m=1.0)),
    )
    supervisor = SafetySupervisor()
    supervisor.register_vehicle(vehicle)
    result = await MissionRunner(supervisor, registry).run(record.mission_id, "sim01")
    assert result.status is MissionStatus.SUCCEEDED
    assert result.mission_version == record.source_sha256[:12]
    assert supervisor.session("sim01").state is VehicleState.DISCONNECTED
    assert vehicle.true_position_m.x == pytest.approx(0.2, abs=0.03)
    assert vehicle.true_position_m.z == 0.0

    reloaded = MissionRegistry()
    MissionFileLibrary(tmp_path / "missions", reloaded).load()
    assert reloaded.metadata(record.mission_id).source_sha256 == record.source_sha256

    archived = library.archive(record.mission_id)
    assert archived.archived is True
    assert library.list_archive()[0].source == SOURCE
    archived_registry = MissionRegistry()
    MissionFileLibrary(tmp_path / "missions", archived_registry).load()
    assert archived_registry.list_metadata() == ()


@pytest.mark.asyncio
async def test_role_preview_records_only_the_selected_fleet_branch() -> None:
    source = """\
MISSION = {
    "schema_version": 2,
    "roles": {
        "left": {"logical_vehicle_id": "drone-left", "home_m": [-0.8, 0, 0]},
        "right": {"logical_vehicle_id": "drone-right", "home_m": [0.8, 0, 0]},
    },
}
async def mission(drone):
    await drone.takeoff(height_m=0.3, duration_s=2)
    if drone.role == "left":
        await drone.move_relative(x_m=-0.1, duration_s=1, frame="home")
    else:
        await drone.move_relative(y_m=0.1, duration_s=1, frame="home")
    await drone.land(duration_s=2)
"""
    record = parse_python_mission(filename="roles.py", name="Roles", source=source)

    left = await preview_isolated_mission_role(record, "left")
    right = await preview_isolated_mission_role(record, "right")

    assert [step.action for step in left] == ["takeoff", "move_relative", "land"]
    assert left[1].arguments["x_m"] == -0.1
    assert left[1].arguments["frame"] == "home"
    assert right[1].arguments["y_m"] == 0.1
    assert right[1].arguments["frame"] == "home"


@pytest.mark.parametrize(
    "payload",
    [
        "import os\n",
        "secret = open('/etc/passwd').read()\n",
        "module = __import__('socket')\n",
        "value = globals()\n",
    ],
)
@pytest.mark.asyncio
async def test_isolated_worker_has_no_import_filesystem_network_or_host_builtins(
    payload: str,
) -> None:
    record = parse_python_mission(filename="safe.py", name="Safe", source=SOURCE)
    hostile_source = payload + "async def mission(drone):\n    return None\n"
    hostile = record.model_copy(
        update={
            "source": hostile_source,
            "source_sha256": hashlib.sha256(hostile_source.encode()).hexdigest(),
        }
    )
    with pytest.raises(CrazySwarmError, match="mission worker rejected artifact"):
        await execute_isolated_mission(hostile)


@pytest.mark.asyncio
async def test_isolated_worker_timeout_kills_nonterminating_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = parse_python_mission(filename="safe.py", name="Safe", source=SOURCE)
    source = "async def mission(drone):\n    while True:\n        pass\n"
    hostile = record.model_copy(
        update={"source": source, "source_sha256": hashlib.sha256(source.encode()).hexdigest()}
    )
    monkeypatch.setattr(script_module, "MISSION_WORKER_TIMEOUT_S", 0.1)
    with pytest.raises(CrazySwarmError, match="mission worker timed out"):
        await execute_isolated_mission(hostile)


def test_archive_rejects_path_traversal_and_mismatched_metadata(tmp_path: Path) -> None:
    directory = tmp_path / "missions"
    registry = MissionRegistry()
    library = MissionFileLibrary(directory, registry)
    record = library.add(filename="hover.py", name="Hover", source=SOURCE)
    outside = tmp_path / "outside.py"
    outside.write_text(SOURCE, encoding="utf-8")
    metadata_path = directory / f"{record.mission_id}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["source_file"] = "../outside.py"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CrazySwarmError, match="unknown uploaded mission"):
        library.archive(record.mission_id)
    with pytest.raises(CrazySwarmError, match="invalid uploaded mission identity"):
        library.archive("../../outside")
    assert outside.read_text(encoding="utf-8") == SOURCE


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_library_ignores_symlinked_source_artifacts(tmp_path: Path) -> None:
    directory = tmp_path / "missions"
    library = MissionFileLibrary(directory, MissionRegistry())
    record = library.add(filename="hover.py", name="Hover", source=SOURCE)
    source_path = directory / f"{record.mission_id}.py"
    outside = tmp_path / "outside.py"
    outside.write_text(SOURCE, encoding="utf-8")
    source_path.unlink()
    source_path.symlink_to(outside)

    reloaded = MissionRegistry()
    MissionFileLibrary(directory, reloaded).load()
    assert reloaded.list_metadata() == ()
    with pytest.raises(CrazySwarmError, match="unknown uploaded mission"):
        library.archive(record.mission_id)
