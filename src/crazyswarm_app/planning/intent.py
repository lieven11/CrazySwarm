from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.planning.contracts import (
    MissionSafetyDeclaration,
    PluginSelection,
    RecoveryAction,
    RouteCapability,
    RoutePlanArtifact,
)


class TransitionKind(StrEnum):
    COMPLETE = "COMPLETE"
    HOLD = "HOLD"
    RESUME = "RESUME"
    REPLAN = "REPLAN"
    RETRY = "RETRY"
    HANDOVER = "HANDOVER"
    RETURN_HOME = "RETURN_HOME"
    LAND = "LAND"
    ABORT = "ABORT"


class IntentPhase(ContractModel):
    phase_id: Identifier
    objective: str = Field(min_length=1, max_length=500)
    role_ids: tuple[Identifier, ...]
    route_capability: RouteCapability
    completion_conditions: tuple[str, ...]
    maximum_duration_s: float = Field(gt=0.0)
    checkpoint_required: bool = False

    @model_validator(mode="after")
    def complete_and_owned(self) -> IntentPhase:
        if not self.role_ids:
            raise ValueError("intent phase requires at least one role")
        if not self.completion_conditions:
            raise ValueError("intent phase requires completion conditions")
        return self


class IntentTransition(ContractModel):
    transition_id: Identifier
    from_phase_id: Identifier
    kind: TransitionKind
    to_phase_id: Identifier | None = None
    maximum_retries: int = Field(default=0, ge=0, le=10)
    recovery_action: RecoveryAction | None = None

    @model_validator(mode="after")
    def bounded_retry(self) -> IntentTransition:
        if self.kind is TransitionKind.RETRY and self.maximum_retries < 1:
            raise ValueError("retry transition requires a positive retry bound")
        if self.kind is not TransitionKind.RETRY and self.maximum_retries:
            raise ValueError("retry bound is only valid for retry transitions")
        return self


class MissionIntent(ContractModel):
    schema_version: Literal[1] = 1
    intent_id: Identifier
    mission_id: Identifier
    objective: str = Field(min_length=1, max_length=500)
    success_criteria: tuple[str, ...]
    role_ids: tuple[Identifier, ...]
    phases: tuple[IntentPhase, ...]
    entry_phase_id: Identifier
    transitions: tuple[IntentTransition, ...]
    safety_declaration: MissionSafetyDeclaration
    source_compatibility: Literal["RESTRICTED_PYTHON_EXPLICIT_ACTIONS", "DECLARED_INTENT"]

    @model_validator(mode="after")
    def valid_shape(self) -> MissionIntent:
        if not self.success_criteria:
            raise ValueError("mission intent requires success criteria")
        if len(self.role_ids) != len(set(self.role_ids)):
            raise ValueError("mission intent role identities must be unique")
        phase_ids = [item.phase_id for item in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("mission intent phase identities must be unique")
        if self.entry_phase_id not in phase_ids:
            raise ValueError("mission intent entry phase is missing")
        declared_roles = set(self.role_ids)
        unknown_roles = sorted(
            {
                role_id
                for phase in self.phases
                for role_id in phase.role_ids
                if role_id not in declared_roles
            }
        )
        if unknown_roles:
            raise ValueError(f"intent phases reference unknown roles: {unknown_roles}")
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


class ExecutionNode(ContractModel):
    node_id: Identifier
    phase_id: Identifier
    role_ids: tuple[Identifier, ...]
    route_sha256s: tuple[SHA256, ...]
    maximum_duration_s: float = Field(gt=0.0)
    completion_conditions: tuple[str, ...]


class ExecutionEdge(ContractModel):
    edge_id: Identifier
    from_node_id: Identifier
    kind: TransitionKind
    to_node_id: Identifier | None = None
    maximum_retries: int = Field(ge=0, le=10)
    recovery_action: RecoveryAction | None = None


class ExecutionGraph(ContractModel):
    schema_version: Literal[1] = 1
    graph_id: Identifier
    intent_sha256: SHA256
    entry_node_id: Identifier
    nodes: tuple[ExecutionNode, ...]
    edges: tuple[ExecutionEdge, ...]
    selected_plugins: tuple[PluginSelection, ...]
    graph_sha256: SHA256

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"graph_sha256"})


def compile_execution_graph(
    intent: MissionIntent,
    routes: tuple[RoutePlanArtifact, ...],
    selections: tuple[PluginSelection, ...],
) -> ExecutionGraph:
    phases = {phase.phase_id: phase for phase in intent.phases}
    route_by_role = {route.role_id: route for route in routes}
    missing_routes = sorted(set(intent.role_ids) - set(route_by_role))
    if missing_routes:
        _reject("intent roles are missing compiled routes", missing=missing_routes)
    outgoing: dict[str, list[IntentTransition]] = {phase_id: [] for phase_id in phases}
    for transition in intent.transitions:
        if transition.from_phase_id not in phases:
            _reject("transition source phase is missing", transition=transition.transition_id)
        if transition.to_phase_id is not None and transition.to_phase_id not in phases:
            _reject("transition target phase is missing", transition=transition.transition_id)
        if (
            transition.recovery_action is not None
            and transition.recovery_action not in intent.safety_declaration.allowed_recovery_actions
        ):
            _reject(
                "transition recovery is outside the safety declaration",
                transition=transition.transition_id,
            )
        outgoing[transition.from_phase_id].append(transition)

    reachable: set[str] = set()
    visiting: set[str] = set()

    def visit(phase_id: str) -> None:
        if phase_id in visiting:
            _reject("execution graph contains a cycle", phase=phase_id)
        if phase_id in reachable:
            return
        visiting.add(phase_id)
        reachable.add(phase_id)
        for transition in outgoing[phase_id]:
            if transition.to_phase_id is not None:
                visit(transition.to_phase_id)
        visiting.remove(phase_id)

    visit(intent.entry_phase_id)
    unreachable = sorted(set(phases) - reachable)
    if unreachable:
        _reject("execution graph contains unreachable phases", phases=unreachable)
    for phase_id, transitions in outgoing.items():
        if not transitions:
            _reject("execution phase has no bounded terminal transition", phase=phase_id)

    nodes = tuple(
        ExecutionNode(
            node_id=f"node-{phase.phase_id}",
            phase_id=phase.phase_id,
            role_ids=phase.role_ids,
            route_sha256s=tuple(route_by_role[role_id].route_sha256 for role_id in phase.role_ids),
            maximum_duration_s=phase.maximum_duration_s,
            completion_conditions=phase.completion_conditions,
        )
        for phase in intent.phases
    )
    edges = tuple(
        ExecutionEdge(
            edge_id=f"edge-{transition.transition_id}",
            from_node_id=f"node-{transition.from_phase_id}",
            kind=transition.kind,
            to_node_id=(
                f"node-{transition.to_phase_id}" if transition.to_phase_id is not None else None
            ),
            maximum_retries=transition.maximum_retries,
            recovery_action=transition.recovery_action,
        )
        for transition in intent.transitions
    )
    payload = {
        "graph_id": f"graph-{intent.intent_id}",
        "intent_sha256": intent.sha256,
        "entry_node_id": f"node-{intent.entry_phase_id}",
        "nodes": nodes,
        "edges": edges,
        "selected_plugins": selections,
    }
    return ExecutionGraph(**payload, graph_sha256=canonical_sha256(payload))


def _reject(message: str, **details: object) -> None:
    raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, message, details=details)
