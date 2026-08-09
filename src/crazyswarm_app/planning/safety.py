from __future__ import annotations

from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.planning.contracts import (
    MissionSafetyDeclaration,
    PluginManifest,
    RecoveryProposal,
    RecoveryRequest,
    SafetyAdmission,
    SafetyCaseFinding,
    SafetyCaseReceipt,
)
from crazyswarm_app.safety.policy import SafetyPolicy


class SafetyKernel:
    """Non-pluggable admission boundary around every strategic proposal."""

    def compile_safety_case(
        self,
        global_policy: SafetyPolicy,
        declaration: MissionSafetyDeclaration,
        manifests: tuple[PluginManifest, ...],
    ) -> SafetyCaseReceipt:
        effective = global_policy.tighten(declaration.policy_override)
        findings: list[SafetyCaseFinding] = []
        if not declaration.required_observations:
            findings.append(
                SafetyCaseFinding(
                    code="OBSERVATIONS_DECLARED_BY_GLOBAL_POLICY",
                    blocking=False,
                    message="mission declares no additional observation requirements",
                    owner="safety-kernel",
                    mitigation="global supervisor freshness and quality checks remain mandatory",
                )
            )
        payload = {
            "declaration_sha256": canonical_sha256(declaration),
            "global_policy_sha256": canonical_sha256(global_policy),
            "effective_policy_sha256": canonical_sha256(effective),
            "selected_plugin_manifest_sha256s": tuple(
                sorted(manifest.sha256 for manifest in manifests)
            ),
            "hazards": (
                "STALE_AUTHORITY",
                "STALE_OBSERVATION",
                "BOUNDARY_OR_DYNAMICS_VIOLATION",
                "UNDECLARED_RECOVERY",
            ),
            "mitigations": (
                "SafetySupervisor remains final command authority",
                "mission policy may only tighten the global policy",
                "recovery actions are declaration allow-listed",
                "plan and plugin manifests are hash-bound",
            ),
            "findings": tuple(findings),
        }
        return SafetyCaseReceipt(
            **payload,
            safety_case_sha256=canonical_sha256(payload),
        )

    def authorize_recovery(
        self,
        global_policy: SafetyPolicy,
        declaration: MissionSafetyDeclaration,
        request: RecoveryRequest,
        proposal: RecoveryProposal,
    ) -> SafetyAdmission:
        effective = global_policy.tighten(declaration.policy_override)
        reasons: list[str] = []
        if proposal.request_id != request.request_id:
            reasons.append("proposal request identity is stale")
        if proposal.role_id != request.role_id or proposal.vehicle_id != request.vehicle_id:
            reasons.append("proposal role or vehicle identity is stale")
        if proposal.action not in request.available_actions:
            reasons.append("proposal action is unavailable")
        if proposal.action not in declaration.allowed_recovery_actions:
            reasons.append("proposal action is outside the mission declaration")
        if not request.authority_current:
            reasons.append("execution authority is stale")
        if not request.observation_current:
            reasons.append("required observation is stale")
        return SafetyAdmission(
            authorized=not reasons,
            action=proposal.action,
            reason="; ".join(reasons) if reasons else "proposal admitted by Safety Kernel",
            effective_policy_sha256=canonical_sha256(effective),
            proposal_sha256=proposal.proposal_sha256,
        )
