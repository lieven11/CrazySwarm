from __future__ import annotations

import pytest

from crazyswarm_app.domain.errors import CrazySwarmError
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.planning.builtins import DirectRoutePlanner, default_recovery_registry
from crazyswarm_app.planning.contracts import (
    MissionSafetyDeclaration,
    PluginSelection,
    RecoveryAction,
    RecoveryRequest,
    RecoveryTrigger,
    RouteCapability,
    RoutePlanArtifact,
    RoutePlanRequest,
    RouteTarget,
)
from crazyswarm_app.planning.intent import (
    IntentPhase,
    IntentTransition,
    MissionIntent,
    TransitionKind,
    compile_execution_graph,
)
from crazyswarm_app.planning.safety import SafetyKernel
from crazyswarm_app.safety.policy import SafetyPolicy, SafetyPolicyOverride


def _declaration() -> MissionSafetyDeclaration:
    return MissionSafetyDeclaration(
        declaration_id="safety-test",
        policy_override=SafetyPolicyOverride(max_horizontal_speed_m_s=0.4),
        required_observations=frozenset({"battery", "link"}),
        allowed_recovery_actions=frozenset(
            {RecoveryAction.HOLD, RecoveryAction.HANDOVER, RecoveryAction.LAND}
        ),
    )


def _route() -> RoutePlanArtifact:
    planner = DirectRoutePlanner()
    return planner.plan(
        RoutePlanRequest(
            request_id="route-survey",
            role_id="survey",
            capability=RouteCapability.DIRECT,
            start_m=Vector3(),
            targets=(RouteTarget(position_m=Vector3(x=0.2, z=0.2)),),
            flight_volume_minimum_m=Vector3(x=-2.0, y=-2.0, z=0.0),
            flight_volume_maximum_m=Vector3(x=2.0, y=2.0, z=1.0),
            cruise_speed_m_s=0.2,
            maximum_duration_s=10.0,
        )
    )


def test_mission_override_can_tighten_but_never_relax_global_policy() -> None:
    kernel = SafetyKernel()
    case = kernel.compile_safety_case(
        SafetyPolicy(),
        _declaration(),
        (DirectRoutePlanner().manifest,),
    )

    assert case.effective_policy_sha256 != case.global_policy_sha256
    with pytest.raises(ValueError, match="relax"):
        kernel.compile_safety_case(
            SafetyPolicy(),
            _declaration().model_copy(
                update={"policy_override": SafetyPolicyOverride(max_horizontal_speed_m_s=0.6)}
            ),
            (DirectRoutePlanner().manifest,),
        )


def test_safety_kernel_rejects_stale_recovery_authority() -> None:
    strategy = default_recovery_registry().resolve(
        "recovery.low-battery",
        "1.0.0",
    )
    request = RecoveryRequest(
        request_id="recovery-request",
        mission_id="mission",
        trigger=RecoveryTrigger.LOW_BATTERY,
        role_id="survey",
        vehicle_id="drone-1",
        available_actions=frozenset({RecoveryAction.HANDOVER, RecoveryAction.LAND}),
        observation_current=True,
        authority_current=False,
        deadline_s=5.0,
    )

    admission = SafetyKernel().authorize_recovery(
        SafetyPolicy(),
        _declaration(),
        request,
        strategy.propose(request),
    )

    assert admission.authorized is False
    assert "authority is stale" in admission.reason


def test_intent_compiler_emits_immutable_graph_and_rejects_cycles() -> None:
    route = _route()
    selection = PluginSelection.from_manifest(
        DirectRoutePlanner().manifest,
        capabilities_used=frozenset({RouteCapability.DIRECT.value}),
    )
    phase = IntentPhase(
        phase_id="survey-phase",
        objective="survey the target",
        role_ids=("survey",),
        route_capability=RouteCapability.DIRECT,
        completion_conditions=("target reached",),
        maximum_duration_s=10.0,
    )
    base = MissionIntent(
        intent_id="intent-test",
        mission_id="mission",
        objective="survey",
        success_criteria=("survey completes",),
        role_ids=("survey",),
        phases=(phase,),
        entry_phase_id=phase.phase_id,
        transitions=(
            IntentTransition(
                transition_id="complete",
                from_phase_id=phase.phase_id,
                kind=TransitionKind.COMPLETE,
            ),
        ),
        safety_declaration=_declaration(),
        source_compatibility="DECLARED_INTENT",
    )

    graph = compile_execution_graph(base, (route,), (selection,))

    assert graph.entry_node_id == "node-survey-phase"
    assert graph.graph_sha256
    cyclic = base.model_copy(
        update={
            "transitions": (
                IntentTransition(
                    transition_id="cycle",
                    from_phase_id=phase.phase_id,
                    to_phase_id=phase.phase_id,
                    kind=TransitionKind.RESUME,
                ),
            )
        }
    )
    with pytest.raises(CrazySwarmError, match="cycle"):
        compile_execution_graph(cyclic, (route,), (selection,))
