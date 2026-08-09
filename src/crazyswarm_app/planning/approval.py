from __future__ import annotations

from typing import Literal

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.missions.planning import MissionPlanReceipt


class MissionPlanApproval(ContractModel):
    schema_version: Literal[1] = 1
    approval_id: Identifier
    mission_id: Identifier
    plan_id: Identifier
    plan_sha256: SHA256
    safety_case_sha256: SHA256
    mission_source_sha256: SHA256
    deployment_sha256: SHA256
    plugin_manifest_sha256s: tuple[SHA256, ...]
    operator_client_id: Identifier
    acknowledged_finding_codes: frozenset[Identifier]
    created_at_monotonic_s: float = Field(ge=0.0)
    expires_at_monotonic_s: float = Field(gt=0.0)
    approval_sha256: SHA256

    @classmethod
    def create(
        cls,
        plan: MissionPlanReceipt,
        *,
        operator_client_id: str,
        acknowledged_finding_codes: frozenset[str],
        now_monotonic_s: float,
        validity_s: float = 300.0,
    ) -> MissionPlanApproval:
        payload = {
            "mission_id": plan.mission_id,
            "plan_id": plan.plan_id,
            "plan_sha256": plan.sha256,
            "safety_case_sha256": plan.planning.safety_case.safety_case_sha256,
            "mission_source_sha256": plan.mission_source_sha256,
            "deployment_sha256": plan.deployment_sha256,
            "plugin_manifest_sha256s": tuple(
                sorted(item.manifest_sha256 for item in plan.planning.plugin_selections)
            ),
            "operator_client_id": operator_client_id,
            "acknowledged_finding_codes": acknowledged_finding_codes,
            "created_at_monotonic_s": now_monotonic_s,
            "expires_at_monotonic_s": now_monotonic_s + validity_s,
        }
        digest = canonical_sha256(payload)
        return cls(
            approval_id=f"approval-{digest[:24]}",
            **payload,
            approval_sha256=digest,
        )

    def mismatch_reasons(
        self,
        plan: MissionPlanReceipt,
        *,
        operator_client_id: str,
        now_monotonic_s: float,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if now_monotonic_s > self.expires_at_monotonic_s:
            reasons.append("approval expired")
        if self.operator_client_id != operator_client_id:
            reasons.append("approval belongs to another operator client")
        if self.mission_id != plan.mission_id:
            reasons.append("mission identity changed")
        if self.plan_id != plan.plan_id or self.plan_sha256 != plan.sha256:
            reasons.append("mission plan changed")
        if self.safety_case_sha256 != plan.planning.safety_case.safety_case_sha256:
            reasons.append("safety case changed")
        if self.mission_source_sha256 != plan.mission_source_sha256:
            reasons.append("mission source changed")
        if self.deployment_sha256 != plan.deployment_sha256:
            reasons.append("deployment changed")
        manifests = tuple(sorted(item.manifest_sha256 for item in plan.planning.plugin_selections))
        if self.plugin_manifest_sha256s != manifests:
            reasons.append("selected plugin changed")
        return tuple(reasons)
