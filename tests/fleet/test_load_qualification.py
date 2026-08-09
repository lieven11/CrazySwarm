from pathlib import Path

from crazyswarm_app.fleet.load_qualification import run_fleet_load_qualification

ROOT = Path(__file__).resolve().parents[2]


def test_three_vehicle_api_storage_replay_load_budget_and_cleanup() -> None:
    report = run_fleet_load_qualification(ROOT)
    assert report.decision == "PASS_SOFTWARE_ONLY", report.failures
    assert report.vehicle_count == 3
    assert report.measurements.remaining_fleet_tasks == 0
    assert report.measurements.remaining_mission_tasks == 0
    assert report.measurements.telemetry_tasks_after_shutdown == 0
    assert report.measurements.remaining_task_leases == 0
    assert report.measurements.bus_subscribers_after_shutdown == 0
    assert report.measurements.reserve_ready_disarmed_observed
    assert report.live_isaac == "NOT_RUN"
    assert report.physical_flight == "NOT_RUN"
