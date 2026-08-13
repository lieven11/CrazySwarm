from __future__ import annotations

from typing import Literal

from pydantic import Field

from crazyswarm_app.campaign.models import (
    CampaignCase,
    ScenarioEvent,
    ScenarioEventKind,
    ScenarioExpectedDisposition,
)
from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class ScenarioEventDecision(ContractModel):
    event_id: Identifier
    event_sha256: SHA256
    trigger_time_s: float = Field(gt=0.0)
    expected_disposition: ScenarioExpectedDisposition
    actual_disposition: ScenarioExpectedDisposition
    reason: str = Field(min_length=1, max_length=1000)
    causal_match: bool


class CampaignScenarioTrace(ContractModel):
    schema_version: Literal[1] = 1
    case_id: Identifier
    case_sha256: SHA256
    decisions: tuple[ScenarioEventDecision, ...]
    all_expected_dispositions_observed: bool
    trace_sha256: SHA256


def compile_scenario_trace(case: CampaignCase) -> CampaignScenarioTrace:
    """Statically admit bounded events; runtime traces must prove accepted cutovers."""

    events = case.semantics.scenario_events if case.semantics is not None else ()
    decisions: list[ScenarioEventDecision] = []
    seen_update_ids: set[str] = set()
    latest: dict[tuple[str, str], tuple[int, int]] = {}
    for event in events:
        actual, reason = _reduce_event(case, event, seen_update_ids, latest)
        decisions.append(
            ScenarioEventDecision(
                event_id=event.event_id,
                event_sha256=canonical_sha256(event),
                trigger_time_s=event.trigger_time_s,
                expected_disposition=event.expected_disposition,
                actual_disposition=actual,
                reason=reason,
                causal_match=actual is event.expected_disposition,
            )
        )
    payload = {
        "case_id": case.case_id,
        "case_sha256": case.case_sha256,
        "decisions": tuple(decisions),
        "all_expected_dispositions_observed": all(item.causal_match for item in decisions),
    }
    return CampaignScenarioTrace(**payload, trace_sha256=canonical_sha256(payload))


def _reduce_event(
    case: CampaignCase,
    event: ScenarioEvent,
    seen_update_ids: set[str],
    latest: dict[tuple[str, str], tuple[int, int]],
) -> tuple[ScenarioExpectedDisposition, str]:
    replanning_kinds = {
        ScenarioEventKind.GOAL_UPDATE,
        ScenarioEventKind.OBSTACLE_ADDED,
        ScenarioEventKind.OBSTACLE_MOVED,
        ScenarioEventKind.OBSTACLE_REMOVED,
        ScenarioEventKind.PASSAGE_CLOSED,
        ScenarioEventKind.PASSAGE_OPENED,
        ScenarioEventKind.PEER_TRAJECTORY_UPDATED,
    }
    if event.kind in replanning_kinds:
        identity = event.update_identity or event.event_id
        key = (event.source_id, event.role_id or "fleet")
        previous = latest.get(key, (0, 0))
        if identity in seen_update_ids:
            return (
                ScenarioExpectedDisposition.REJECTED_DUPLICATE,
                "The immutable update identity was already consumed; no second "
                "cutover is authorized.",
            )
        if event.sequence <= previous[0] or event.generation <= previous[1]:
            return (
                ScenarioExpectedDisposition.REJECTED_STALE,
                "The source sequence or generation is older than the accepted authority.",
            )
        if not event.authenticated:
            return (
                ScenarioExpectedDisposition.REJECTED_AUTHORITY,
                "The update lacks authenticated authority.",
            )
        environment_change_kinds = {
            ScenarioEventKind.OBSTACLE_ADDED,
            ScenarioEventKind.OBSTACLE_MOVED,
            ScenarioEventKind.OBSTACLE_REMOVED,
            ScenarioEventKind.PASSAGE_CLOSED,
            ScenarioEventKind.PASSAGE_OPENED,
        }
        environment_lead_too_short = (
            event.kind in environment_change_kinds
            and (
                event.duration_s is None
                or event.duration_s < case.hard_constraints.planning_budget_s + 0.10
            )
        )
        declared_search_over_budget = (
            event.kind is ScenarioEventKind.GOAL_UPDATE
            and event.duration_s is not None
            and event.duration_s > case.hard_constraints.planning_budget_s
        )
        if environment_lead_too_short or declared_search_over_budget:
            return (
                ScenarioExpectedDisposition.BLOCKED_BUDGET,
                "The event cannot preserve the frozen planning and cutover budget.",
            )
        if case.family in {"blocked_replan", "abort_and_land_goal_fallback"}:
            return (
                ScenarioExpectedDisposition.BLOCKED_INFEASIBLE,
                "The authored replacement is declared infeasible under the frozen volume/deadline.",
            )
        if event.acknowledgement_required and not event.acknowledgement_received:
            disposition = (
                ScenarioExpectedDisposition.REJECTED_AUTHORITY
                if case.family == "operator_approval_goal_replacement"
                else ScenarioExpectedDisposition.ZERO_PARTIAL_COMMIT
            )
            return disposition, "Required hash-bound approval or cutover acknowledgement is absent."
        if case.family in {"simultaneous_conflicting_updates", "partial_replacement_failure"}:
            return (
                ScenarioExpectedDisposition.ZERO_PARTIAL_COMMIT,
                "The bounded fleet update set is incompatible; no route subset commits.",
            )
        seen_update_ids.add(identity)
        latest[key] = (event.sequence, event.generation)
        return (
            ScenarioExpectedDisposition.ACCEPTED_UPDATE,
            "The current authenticated generation passes static bounded admission; "
            "runtime evidence must still prove an in-flight cutover.",
        )
    if event.kind in {ScenarioEventKind.TELEMETRY_LOSS, ScenarioEventKind.VEHICLE_LOSS}:
        return (
            ScenarioExpectedDisposition.SAFE_ROLE_RECOVERY,
            "The affected role leaves nominal authority and enters the declared bounded recovery.",
        )
    if event.kind is ScenarioEventKind.ASSIGNMENT_CONFLICT:
        return (
            ScenarioExpectedDisposition.REJECTED_ASSIGNMENT_CONFLICT,
            "Conflicting exclusive ownership is rejected before task authority changes.",
        )
    if event.kind is ScenarioEventKind.ACKNOWLEDGEMENT_LOSS:
        return (
            ScenarioExpectedDisposition.ZERO_PARTIAL_COMMIT,
            "The shared epoch lacks all acknowledgements; committed replacement "
            "count remains zero.",
        )
    if event.kind is ScenarioEventKind.BATTERY_DROP:
        return (
            ScenarioExpectedDisposition.RESERVE_HANDOVER,
            "The declared threshold selects the ready reserve and advances one "
            "ownership generation.",
        )
    if event.kind is ScenarioEventKind.ABORT_REQUEST:
        return (
            ScenarioExpectedDisposition.COORDINATED_ABORT,
            "The declared abort fallback applies individualized landing outcomes to the fleet.",
        )
    raise ValueError(f"unsupported campaign scenario event kind: {event.kind}")
