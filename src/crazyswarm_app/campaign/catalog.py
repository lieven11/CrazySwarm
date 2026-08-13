from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from crazyswarm_app.campaign.models import (
    AuthorizationStatus,
    CampaignCase,
    EnvironmentKind,
    ImplementationStatus,
    LifecycleRecord,
    LifecycleState,
    MigrationReceipt,
)
from crazyswarm_app.campaign.semantic_audit import (
    CaseSemanticAudit,
    SemanticAuditClassification,
    audit_case,
    audit_catalog,
)
from crazyswarm_app.domain.models import CoordinateFrame, Vector3
from crazyswarm_app.domain.simulation import canonical_sha256
from crazyswarm_app.safety.policy import SafetyPolicy

_ALLOWED_CASE_SUFFIXES = {".json", ".yaml", ".yml"}
_IGNORED_NAMES = {"README.md", ".DS_Store"}


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    case: CampaignCase
    manifest_path: Path
    source_bytes: bytes


class CampaignCatalog:
    """Deterministic data-only catalog; discovery never imports or executes Python."""

    def __init__(
        self,
        root: Path,
        *,
        additional_roots: Iterable[Path] = (),
        policy: SafetyPolicy | None = None,
    ) -> None:
        self.root = root.resolve()
        self.roots = (self.root, *(item.resolve() for item in additional_roots))
        if len(set(self.roots)) != len(self.roots):
            raise ValueError("campaign catalog roots must be unique")
        self.policy = policy or SafetyPolicy()
        self._entries: dict[str, CatalogEntry] = {}
        self._semantic_audits: dict[str, CaseSemanticAudit] = {}

    def discover(self) -> tuple[CatalogEntry, ...]:
        existing_roots = tuple(root for root in self.roots if root.exists())
        if not existing_roots:
            self._entries = {}
            self._semantic_audits = {}
            return ()
        entries: dict[str, CatalogEntry] = {}
        for root in sorted(existing_roots, key=lambda item: item.as_posix()):
            paths = sorted(root.rglob("*"), key=lambda item: item.as_posix())
            for path in paths:
                if path.is_dir():
                    continue
                if path.name in _IGNORED_NAMES:
                    continue
                if path.is_symlink():
                    raise ValueError(f"catalog symlinks are forbidden: {path}")
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    raise ValueError(f"catalog path escapes root: {path}")
                if path.suffix.lower() not in _ALLOWED_CASE_SUFFIXES:
                    raise ValueError(f"unknown catalog file: {path}")
                source = path.read_bytes()
                raw = _load_manifest(path, source)
                values = raw.get("cases") if isinstance(raw, Mapping) and "cases" in raw else [raw]
                if not isinstance(values, list):
                    raise ValueError(f"catalog cases must be a list: {path}")
                for value in values:
                    case = CampaignCase.model_validate(value)
                    validate_case_against_policy(case, self.policy)
                    if case.case_id in entries:
                        raise ValueError(f"duplicate campaign case ID: {case.case_id}")
                    entries[case.case_id] = CatalogEntry(case, path, source)
        semantic_audit = audit_catalog(entry.case for entry in entries.values())
        self._semantic_audits = {item.case_id: item for item in semantic_audit.cases}
        invalid = tuple(
            item
            for item in semantic_audit.cases
            if item.classification is SemanticAuditClassification.PLACEHOLDER_QUARANTINED
            and entries[item.case_id].case.implementation_status is ImplementationStatus.EXECUTABLE
        )
        if invalid:
            details = "; ".join(
                f"{item.case_id}: {','.join(item.invariant_failures)}" for item in invalid
            )
            raise ValueError(f"executable campaign semantic audit failed: {details}")
        self._entries = entries
        return self.entries()

    def entries(self) -> tuple[CatalogEntry, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))

    def cases(self) -> tuple[CampaignCase, ...]:
        return tuple(entry.case for entry in self.entries())

    def semantic_audits(self) -> tuple[CaseSemanticAudit, ...]:
        return tuple(self._semantic_audits[key] for key in sorted(self._semantic_audits))

    def get(self, case_id: str) -> CampaignCase:
        try:
            return self._entries[case_id].case
        except KeyError as error:
            raise KeyError(f"unknown campaign case: {case_id}") from error

    def register(
        self,
        case: CampaignCase,
        *,
        manifest_path: Path,
        source_bytes: bytes,
    ) -> CatalogEntry:
        if case.case_id in self._entries:
            raise ValueError(f"duplicate campaign case ID: {case.case_id}")
        validate_case_against_policy(case, self.policy)
        entry = CatalogEntry(case=case, manifest_path=manifest_path, source_bytes=source_bytes)
        semantic_audit = audit_case(case)
        if (
            semantic_audit.classification is SemanticAuditClassification.PLACEHOLDER_QUARANTINED
            and case.implementation_status is ImplementationStatus.EXECUTABLE
        ):
            raise ValueError(
                f"executable campaign semantic audit failed: {case.case_id}: "
                f"{','.join(semantic_audit.invariant_failures)}"
            )
        self._entries[case.case_id] = entry
        self._semantic_audits[case.case_id] = semantic_audit
        return entry

    def hierarchy(
        self,
    ) -> dict[str, dict[str, dict[str, dict[str, tuple[str, ...]]]]]:
        result: dict[str, dict[str, dict[str, dict[str, list[str]]]]] = {}
        for case in self.cases():
            environment = "Simulation" if case.environment is EnvironmentKind.SIMULATION else "Real"
            fleet = {1: "one_drone", 2: "two_drones", 3: "three_drones"}[case.drone_count]
            result.setdefault(environment, {}).setdefault(case.cluster.value, {}).setdefault(
                fleet, {}
            ).setdefault(case.family, []).append(case.case_id)
        return {
            environment: {
                cluster: {
                    fleet: {
                        family: tuple(sorted(case_ids))
                        for family, case_ids in sorted(families.items())
                    }
                    for fleet, families in sorted(fleets.items())
                }
                for cluster, fleets in sorted(clusters.items())
            }
            for environment, clusters in sorted(result.items())
        }

    def initial_lifecycle(self) -> tuple[LifecycleRecord, ...]:
        return tuple(
            LifecycleRecord(
                case_id=case.case_id,
                case_sha256=case.case_sha256,
                state=LifecycleState.DEFINED_NOT_RUN,
            )
            for case in self.cases()
        )


def validate_case_against_policy(case: CampaignCase, policy: SafetyPolicy) -> None:
    constraints = case.hard_constraints
    volume = constraints.flight_volume
    if not (
        policy.flight_volume.contains(volume.minimum_m)
        and policy.flight_volume.contains(volume.maximum_m)
    ):
        raise ValueError("case flight volume would weaken the global policy")
    dynamics = constraints.dynamics
    limits = (
        (
            "maximum_horizontal_speed_m_s",
            dynamics.maximum_horizontal_speed_m_s,
            policy.max_horizontal_speed_m_s,
        ),
        (
            "maximum_vertical_speed_m_s",
            dynamics.maximum_vertical_speed_m_s,
            policy.max_vertical_speed_m_s,
        ),
        (
            "maximum_acceleration_m_s2",
            dynamics.maximum_acceleration_m_s2,
            policy.max_acceleration_m_s2,
        ),
        ("deadline_s", constraints.deadline_s, policy.max_mission_duration_s),
    )
    relaxed = [name for name, value, maximum in limits if value > maximum]
    if relaxed:
        raise ValueError(f"case would weaken global safety limits: {sorted(relaxed)}")
    if volume.maximum_m.z > policy.max_altitude_m:
        raise ValueError("case altitude would weaken the global policy")
    if any(
        drone.initial_battery_percent < policy.minimum_takeoff_battery_percent
        for drone in case.drones
    ):
        raise ValueError("case initial battery is below global takeoff minimum")


def compile_spatial_point(
    point: Mapping[str, Any], *, home_world_m: Vector3
) -> tuple[Vector3, dict[str, Any]]:
    """Compile world/home input into stored world geometry and retain the transform chain."""

    frame = CoordinateFrame(str(point["frame"]))
    value = Vector3.model_validate(point["value_m"])
    if frame is CoordinateFrame.WORLD:
        result = value
        transform = {"from": "world", "to": "world", "translation_m": Vector3()}
    elif frame is CoordinateFrame.HOME:
        result = Vector3(
            x=value.x + home_world_m.x,
            y=value.y + home_world_m.y,
            z=value.z + home_world_m.z,
        )
        transform = {"from": "home", "to": "world", "translation_m": home_world_m}
    else:
        raise ValueError("stored campaign geometry supports only world or home inputs")
    return result, transform


def migrate_case_bytes(source: bytes) -> MigrationReceipt:
    raw = yaml.safe_load(source)
    if not isinstance(raw, dict):
        raise ValueError("case migration source must be a mapping")
    source_version = int(raw.get("schema_version", 1))
    source_case_hash = canonical_sha256(raw)
    if source_version == 2:
        migrated = CampaignCase.model_validate(raw)
        implementation = "identity-v2"
    elif source_version == 1:
        migrated = CampaignCase.model_validate({**raw, "schema_version": 2})
        implementation = "campaign-case-v1-to-v2"
    else:
        raise ValueError(f"unsupported campaign case schema version: {source_version}")
    return MigrationReceipt(
        source_schema_version=source_version,
        target_schema_version=2,
        source_bytes_sha256=hashlib.sha256(source).hexdigest(),
        source_case_sha256=source_case_hash,
        migrated_case_sha256=migrated.case_sha256,
        migration_implementation_id=implementation,
        migration_implementation_version="1.0.0",
        migrated_case=migrated,
    )


def unauthorized_real_mirror(case: CampaignCase, *, case_id: str) -> CampaignCase:
    """Reference identical mission intent while keeping Real execution visibly disabled."""

    return CampaignCase.model_validate(
        case.model_copy(
            update={
                "case_id": case_id,
                "parent_case_sha256": case.case_sha256,
                "environment": EnvironmentKind.REAL,
                "authorization": AuthorizationStatus.NOT_AUTHORIZED,
                "execution_eligibility": "STATIC_VALIDATE_ONLY",
            }
        ).model_dump(mode="python")
    )


def _load_manifest(path: Path, source: bytes) -> Any:
    try:
        if path.suffix.lower() == ".json":
            return json.loads(source)
        # PyYAML's pure-Python SafeLoader dominates cold Campaign Lab startup for
        # the generated catalog. CSafeLoader has the same safe YAML contract and
        # is roughly an order of magnitude faster when libyaml is available.
        safe_loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        return yaml.load(source, Loader=safe_loader)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"invalid campaign manifest {path}: {error}") from error


def case_hashes(cases: Iterable[CampaignCase]) -> tuple[str, ...]:
    return tuple(case.case_sha256 for case in cases)
