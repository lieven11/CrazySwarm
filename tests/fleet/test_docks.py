from crazyswarm_app.fleet.artifacts import DockDefinition
from crazyswarm_app.fleet.docks import DockManager, DockOperationState


def manager(*, attempts: int = 2) -> DockManager:
    return DockManager(
        (DockDefinition(dock_id="dock-main", capacity=1),),
        maximum_attempts=attempts,
    )


def test_dock_capacity_queue_and_modeled_charge_progress() -> None:
    docks = manager()
    first = docks.reserve("cf01", battery_percent=80.0, now_s=10.0)
    second = docks.reserve("cf02", battery_percent=50.0, now_s=11.0)
    assert first.state is DockOperationState.RESERVED
    assert second.state is DockOperationState.QUEUED
    snapshot = docks.snapshot("dock-main")
    assert snapshot.occupied_vehicle_ids == ("cf01",)
    assert snapshot.queued_vehicle_ids == ("cf02",)

    reservation_id = first.reservation_id
    docks.transition(
        reservation_id,
        DockOperationState.RETURN_TO_DOCK_AREA,
        reason="handover complete",
        now_s=12.0,
    )
    docks.transition(
        reservation_id,
        DockOperationState.APPROACH_REQUESTED,
        reason="approach clear",
        now_s=13.0,
    )
    docks.transition(
        reservation_id,
        DockOperationState.DOCK_ATTEMPT,
        reason="modeled attempt",
        now_s=14.0,
    )
    docks.confirm_modeled_landing(reservation_id, modeled_contact=True, now_s=15.0)
    charging = docks.confirm_modeled_charging(reservation_id, confirmed=True, now_s=16.0)
    assert charging.state is DockOperationState.CHARGING_CONFIRMED
    assert charging.estimated_ready_at_monotonic_s == 76.0
    progress = docks.update_modeled_charge(reservation_id, now_s=46.0)
    assert progress.state is DockOperationState.CHARGING
    assert progress.battery_percent == 85.0
    ready = docks.update_modeled_charge(reservation_id, now_s=76.0)
    assert ready.state is DockOperationState.READY
    assert docks.reservation(second.reservation_id).state is DockOperationState.RESERVED


def test_failed_charging_confirmation_never_enters_charging() -> None:
    docks = manager(attempts=2)
    request = docks.reserve("cf01", battery_percent=40.0, now_s=10.0)
    docks.transition(
        request.reservation_id,
        DockOperationState.RETURN_TO_DOCK_AREA,
        reason="return",
        now_s=11.0,
    )
    docks.transition(
        request.reservation_id,
        DockOperationState.APPROACH_REQUESTED,
        reason="approach",
        now_s=12.0,
    )
    docks.transition(
        request.reservation_id,
        DockOperationState.DOCK_ATTEMPT,
        reason="attempt one",
        now_s=13.0,
    )
    docks.confirm_modeled_landing(request.reservation_id, modeled_contact=False, now_s=14.0)
    retry = docks.confirm_modeled_charging(request.reservation_id, confirmed=False, now_s=15.0)
    assert retry.state is DockOperationState.RETRY_PENDING
    assert not retry.modeled_charging_confirmed

    docks.transition(
        request.reservation_id,
        DockOperationState.APPROACH_REQUESTED,
        reason="retry approach",
        now_s=16.0,
    )
    docks.transition(
        request.reservation_id,
        DockOperationState.DOCK_ATTEMPT,
        reason="attempt two",
        now_s=17.0,
    )
    docks.confirm_modeled_landing(request.reservation_id, modeled_contact=True, now_s=18.0)
    failed = docks.confirm_modeled_charging(request.reservation_id, confirmed=False, now_s=19.0)
    assert failed.state is DockOperationState.FAILED
    assert failed.terminal_reason == "LANDED_NOT_CHARGING"
    assert all(event.state is not DockOperationState.CHARGING for event in failed.events)
