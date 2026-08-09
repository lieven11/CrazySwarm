from __future__ import annotations

from dataclasses import dataclass

from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import Vector3, VehicleCapability
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    BackendVehicleBinding,
    CompletionPolicy,
    DeploymentManifest,
    DeploymentTaskDefinition,
    ExecutionBackend,
    FleetConstraints,
    FleetFailurePolicy,
    FleetMemberDefinition,
    InitialFleetRole,
    ZoneDefinition,
    ZoneGeometry,
)
from crazyswarm_app.missions.script import MissionFileRecord, MissionRoleSpec


@dataclass(frozen=True, slots=True)
class MissionDeploymentPlan:
    """Backend-neutral logical plan derived from one immutable mission artifact."""

    deployment: DeploymentManifest
    binding: BackendBindingProfile
    assignments: dict[str, str]


def mission_role_estimated_energy_percent(
    record: MissionFileRecord,
    role: MissionRoleSpec,
) -> float:
    """Return the task-energy estimate used by planning and start admission."""

    if role.task.estimated_energy_percent is not None:
        return role.task.estimated_energy_percent
    estimated_duration_s = max(0.01, record.planned_duration_s)
    return min(90.0, max(1.0, estimated_duration_s * 0.03))


def mission_role_required_battery_percent(
    record: MissionFileRecord,
    role: MissionRoleSpec,
) -> float:
    return mission_role_estimated_energy_percent(record, role) + role.task.energy_margin_percent


def plan_mission_deployment(
    record: MissionFileRecord,
    *,
    required_capabilities: frozenset[VehicleCapability],
    backend: ExecutionBackend,
    implicit_vehicle_id: str,
    implicit_display_name: str,
    implicit_home: Vector3,
    implicit_backend_identifier: str | None = None,
    world_minimum_m: Vector3,
    world_maximum_m: Vector3,
    approved_binding_profile: BackendBindingProfile | None = None,
) -> MissionDeploymentPlan:
    """Derive stable logical identities/tasks; only the binding varies by backend."""

    roles = record.roles or (
        MissionRoleSpec(
            role_id="primary",
            logical_vehicle_id=implicit_vehicle_id,
            display_name=implicit_display_name,
            home_m=(implicit_home.x, implicit_home.y, implicit_home.z),
        ),
    )
    _validate_homes(roles, world_minimum_m, world_maximum_m)
    package = record.package
    constraints = FleetConstraints(
        warning_separation_m=(package.warning_separation_m if package else 0.75),
        critical_separation_m=(package.critical_separation_m if package else 0.5),
        observation_freshness_s=(package.observation_freshness_s if package else 1.0),
        child_failure_policy=FleetFailurePolicy(
            package.child_failure_policy if package else "CONTINUE_HEALTHY"
        ),
    )
    members = tuple(
        FleetMemberDefinition(
            vehicle_id=role.logical_vehicle_id,
            display_name=role.display_name or role.logical_vehicle_id,
            home=_vector(role.home_m),
            initial_role=InitialFleetRole(role.initial_role),
            required=role.required,
            required_capabilities=required_capabilities | role.required_capabilities,
        )
        for role in roles
    )
    zones = tuple(
        ZoneDefinition(
            zone_id=f"zone-{role.role_id}",
            geometry=(
                ZoneGeometry(
                    minimum_m=_vector(role.zone.minimum_m),
                    maximum_m=_vector(role.zone.maximum_m),
                )
                if role.zone is not None
                else ZoneGeometry(
                    minimum_m=world_minimum_m,
                    maximum_m=world_maximum_m,
                )
            ),
        )
        for role in roles
        if role.initial_role == "ACTIVE"
    )
    estimated_duration_s = max(0.01, record.planned_duration_s)
    tasks = tuple(
        DeploymentTaskDefinition(
            task_id=role.role_id,
            task_type=role.task.task_type,
            zone_id=f"zone-{role.role_id}",
            priority=role.task.priority,
            mission_id=record.mission_id,
            required_capabilities=required_capabilities | role.required_capabilities,
            estimated_duration_s=estimated_duration_s,
            estimated_energy_percent=mission_role_estimated_energy_percent(record, role),
            energy_margin_percent=role.task.energy_margin_percent,
        )
        for role in roles
        if role.initial_role == "ACTIVE"
    )
    deployment = DeploymentManifest(
        deployment_id=f"mission-{record.source_sha256[:24]}",
        fleet=members,
        zones=zones,
        tasks=tasks,
        constraints=constraints,
        completion_policy=CompletionPolicy(require_all_tasks=True, allow_partial_fleet=False),
    )
    if approved_binding_profile is not None:
        if approved_binding_profile.backend is not backend:
            raise CrazySwarmError(ErrorCode.IDENTITY_MISMATCH, "approved backend binding mismatch")
        approved_binding_profile.validate_for(deployment)
        binding = approved_binding_profile
    elif backend is ExecutionBackend.CRAZYFLIE:
        raise CrazySwarmError(
            ErrorCode.MODE_NOT_AUTHORIZED,
            "physical execution requires an explicitly approved binding profile",
        )
    else:
        binding = BackendBindingProfile(
            binding_id=f"{backend.value.lower()}-{record.source_sha256[:20]}",
            backend=backend,
            vehicles=tuple(
                BackendVehicleBinding(
                    vehicle_id=member.vehicle_id,
                    expected_vehicle_id=member.vehicle_id,
                    backend_identifier=(
                        implicit_backend_identifier
                        if record.package_schema_version == 1
                        and member.vehicle_id == implicit_vehicle_id
                        and implicit_backend_identifier is not None
                        else _backend_identifier(backend, member.vehicle_id)
                    ),
                    operator_selected=False,
                )
                for member in members
            ),
        )
    assignments = {
        role.role_id: role.logical_vehicle_id for role in roles if role.initial_role == "ACTIVE"
    }
    return MissionDeploymentPlan(
        deployment=deployment,
        binding=binding,
        assignments=assignments,
    )


def _backend_identifier(backend: ExecutionBackend, vehicle_id: str) -> str:
    return {
        ExecutionBackend.FAST_SIM: f"fast-sim/{vehicle_id}",
        ExecutionBackend.MOCK_ISAAC: f"/World/Fleet/{vehicle_id}",
        ExecutionBackend.ISAAC: f"/World/Fleet/{vehicle_id}",
        ExecutionBackend.CRAZYFLIE: f"unbound/{vehicle_id}",
    }[backend]


def _validate_homes(
    roles: tuple[MissionRoleSpec, ...],
    minimum: Vector3,
    maximum: Vector3,
) -> None:
    outside = [
        role.logical_vehicle_id
        for role in roles
        if not (
            minimum.x <= role.home_m[0] <= maximum.x
            and minimum.y <= role.home_m[1] <= maximum.y
            and minimum.z <= role.home_m[2] <= maximum.z
        )
    ]
    if outside:
        raise CrazySwarmError(
            ErrorCode.PREFLIGHT_FAILED,
            "mission-declared home is outside the configured environment",
            details={"vehicle_ids": sorted(outside)},
        )


def _vector(value: tuple[float, float, float]) -> Vector3:
    return Vector3(x=value[0], y=value[1], z=value[2])
