from crazyswarm_app.campaign.models import MotionContractAmendment, MotionQualityContract
from crazyswarm_app.campaign.route_horizon import (
    MotionAmendmentDisposition,
    MotionIntentController,
)


def test_motion_contract_amendment_is_atomic_and_hash_bound() -> None:
    before = MotionQualityContract(target_speed_m_s=0.2)
    after = MotionQualityContract(target_speed_m_s=0.3)
    controller = MotionIntentController(
        contract=before,
        accepted_program_sha256="a" * 64,
        active_trajectory_sha256="b" * 64,
    )
    amendment = MotionContractAmendment(
        amendment_id="faster-clear-route",
        source_id="mission-intent",
        sequence=1,
        source_timestamp_s=2.0,
        effective_source_s=2.5,
        prior_contract_sha256=before.contract_sha256,
        replacement=after,
    )
    accepted = controller.apply(
        amendment,
        source_now_s=2.2,
        suffix_trajectory_sha256="c" * 64,
        safe_suffix=True,
        authorized_program_sha256="a" * 64,
    )
    assert accepted.disposition is MotionAmendmentDisposition.ACCEPTED
    assert controller.contract == after
    assert controller.accepted_program_sha256 != "a" * 64

    duplicate = controller.apply(
        amendment,
        source_now_s=2.3,
        suffix_trajectory_sha256="d" * 64,
        safe_suffix=True,
        authorized_program_sha256=controller.accepted_program_sha256,
    )
    assert duplicate.disposition is MotionAmendmentDisposition.REJECTED_DUPLICATE
    assert controller.active_trajectory_sha256 == "c" * 64


def test_unsafe_amendment_changes_no_active_authority() -> None:
    contract = MotionQualityContract(target_speed_m_s=0.2)
    controller = MotionIntentController(
        contract=contract,
        accepted_program_sha256="a" * 64,
        active_trajectory_sha256="b" * 64,
    )
    amendment = MotionContractAmendment(
        amendment_id="unsafe",
        source_id="mission-intent",
        sequence=1,
        source_timestamp_s=1.0,
        effective_source_s=1.2,
        prior_contract_sha256=contract.contract_sha256,
        replacement=MotionQualityContract(target_speed_m_s=0.5),
    )
    result = controller.apply(
        amendment,
        source_now_s=1.1,
        suffix_trajectory_sha256="c" * 64,
        safe_suffix=False,
        authorized_program_sha256="a" * 64,
    )
    assert result.disposition is MotionAmendmentDisposition.REJECTED_UNSAFE
    assert controller.accepted_program_sha256 == "a" * 64
    assert controller.active_trajectory_sha256 == "b" * 64
