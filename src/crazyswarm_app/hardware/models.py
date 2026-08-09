from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.commands import CommandKind
from crazyswarm_app.domain.models import ContractModel, Identifier, Vector3
from crazyswarm_app.domain.simulation import SHA256


class QualificationStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    CONFIGURED_UNQUALIFIED = "CONFIGURED_UNQUALIFIED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class PermitScope(StrEnum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    PROPS_OFF_BENCH = "PROPS_OFF_BENCH"
    CONTAINED_FLIGHT = "CONTAINED_FLIGHT"


class VersionPin(ContractModel):
    component: Identifier
    expected_version: str | None = None
    expected_sha256: SHA256 | None = None
    observed_version: str | None = None
    observed_sha256: SHA256 | None = None
    status: QualificationStatus = QualificationStatus.CONFIGURED_UNQUALIFIED

    @property
    def verified(self) -> bool:
        version_matches = (
            self.expected_version is None or self.observed_version == self.expected_version
        )
        hash_matches = self.expected_sha256 is None or self.observed_sha256 == self.expected_sha256
        return (
            self.status is QualificationStatus.PASSED
            and (self.expected_version is not None or self.expected_sha256 is not None)
            and self.observed_version is not None
            and version_matches
            and hash_matches
        )


class DeckObservation(ContractModel):
    parameter: Literal["deck.bcFlow2", "deck.bcMultiranger"]
    observed_value: int | None = Field(default=None, ge=0)
    revision: str | None = None
    self_test: str | None = None
    status: QualificationStatus = QualificationStatus.NOT_RUN

    @property
    def present_and_verified(self) -> bool:
        return self.status is QualificationStatus.PASSED and bool(self.observed_value)


class AirframeInspection(ContractModel):
    takeoff_mass_kg: Annotated[float, Field(gt=0.0)] | None = None
    center_of_mass_body_m: Vector3 | None = None
    deck_mounting_passed: bool = False
    propeller_configuration: str | None = None
    motor_configuration: str | None = None
    battery_ids: tuple[Identifier, ...] = ()
    no_visible_damage: bool = False
    no_contamination: bool = False
    inspected_by: Identifier | None = None
    inspected_at_utc: datetime | None = None

    @property
    def passed(self) -> bool:
        return all(
            (
                self.takeoff_mass_kg is not None,
                self.center_of_mass_body_m is not None,
                self.deck_mounting_passed,
                self.propeller_configuration is not None,
                self.motor_configuration is not None,
                bool(self.battery_ids),
                self.no_visible_damage,
                self.no_contamination,
                self.inspected_by is not None,
                self.inspected_at_utc is not None,
            )
        )


class BenchQualificationRecord(ContractModel):
    schema_version: Literal[1] = 1
    record_id: Identifier
    vehicle_id: Identifier
    selected_uri: str = Field(pattern=r"^radio://[0-9]+/[0-9]{1,3}/(?:250K|1M|2M)/[A-Fa-f0-9]{10}$")
    repository_commit: str | None = Field(default=None, pattern=r"^[a-f0-9]{40,64}$")
    repository_dirty: bool
    versions: tuple[VersionPin, ...]
    decks: tuple[DeckObservation, DeckObservation]
    airframe: AirframeInspection
    connect_cycles_completed: int = Field(default=0, ge=0)
    telemetry_matrix_status: QualificationStatus = QualificationStatus.NOT_RUN
    static_sensor_matrix_status: QualificationStatus = QualificationStatus.NOT_RUN
    props_off_command_status: QualificationStatus = QualificationStatus.NOT_RUN
    reconnect_status: QualificationStatus = QualificationStatus.NOT_RUN
    timing_and_resource_status: QualificationStatus = QualificationStatus.NOT_RUN
    anomalies_open: tuple[Identifier, ...] = ()
    evidence_sha256: SHA256 | None = None
    reviewed_by: Identifier | None = None
    reviewed_at_utc: datetime | None = None

    @model_validator(mode="after")
    def required_decks_are_unique(self) -> BenchQualificationRecord:
        names = {deck.parameter for deck in self.decks}
        if names != {"deck.bcFlow2", "deck.bcMultiranger"}:
            raise ValueError("bench record requires one Flow2 and one Multi-ranger observation")
        return self

    @property
    def accepted(self) -> bool:
        required_versions = {
            "cflib",
            "crazyflie-stm32-firmware",
            "crazyflie-nrf-firmware",
            "stabilizer-controller",
            "stabilizer-estimator",
            "crazyradio-firmware",
        }
        observed_version_components = {version.component for version in self.versions}
        statuses = (
            self.telemetry_matrix_status,
            self.static_sensor_matrix_status,
            self.props_off_command_status,
            self.reconnect_status,
            self.timing_and_resource_status,
        )
        return all(
            (
                self.connect_cycles_completed >= 100,
                required_versions.issubset(observed_version_components),
                all(version.verified for version in self.versions),
                all(deck.present_and_verified for deck in self.decks),
                self.airframe.passed,
                all(status is QualificationStatus.PASSED for status in statuses),
                not self.anomalies_open,
                self.evidence_sha256 is not None,
                self.reviewed_by is not None,
                self.reviewed_at_utc is not None,
            )
        )


class PhysicalFlightEntryRecord(ContractModel):
    schema_version: Literal[1] = 1
    record_id: Identifier
    vehicle_id: Identifier
    operator_id: Identifier
    observer_id: Identifier
    bench_record_id: Identifier
    bench_evidence_sha256: SHA256
    site_risk_assessment_sha256: SHA256
    containment_procedure_sha256: SHA256
    emergency_plan_sha256: SHA256
    stop_criteria_sha256: SHA256
    exact_source_hashes: dict[Identifier, SHA256]
    dry_run_receipt_hashes: tuple[SHA256, ...]
    external_reference_id: Identifier | None = None
    external_reference_qualification_sha256: SHA256 | None = None
    operator_present: bool = False
    observer_present: bool = False
    exclusion_zone_clear: bool = False
    inspection_passed: bool = False
    explicitly_authorized: bool = False
    authorized_at_utc: datetime | None = None
    expires_at_utc: datetime | None = None

    @model_validator(mode="after")
    def external_reference_fields_are_paired(self) -> PhysicalFlightEntryRecord:
        if (self.external_reference_id is None) != (
            self.external_reference_qualification_sha256 is None
        ):
            raise ValueError("external reference identity and qualification must be paired")
        if (
            self.authorized_at_utc is not None
            and self.expires_at_utc is not None
            and self.expires_at_utc <= self.authorized_at_utc
        ):
            raise ValueError("flight-entry expiry must follow authorization")
        return self

    def accepted(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return all(
            (
                self.operator_present,
                self.observer_present,
                self.exclusion_zone_clear,
                self.inspection_passed,
                self.explicitly_authorized,
                self.authorized_at_utc is not None,
                self.authorized_at_utc is not None and self.authorized_at_utc <= current,
                self.expires_at_utc is not None and self.expires_at_utc > current,
                bool(self.exact_source_hashes),
                bool(self.dry_run_receipt_hashes),
            )
        )


class CommandPermit(ContractModel):
    """Short-lived, explicit authority installed into a physical adapter."""

    schema_version: Literal[1] = 1
    permit_id: Identifier
    vehicle_id: Identifier
    selected_uri: str
    operator_id: Identifier
    scope: PermitScope
    issued_at_utc: datetime
    expires_at_utc: datetime
    operator_present: bool
    props_removed: bool
    physically_restrained: bool
    flight_entry_record_id: Identifier | None = None
    flight_entry_evidence_sha256: SHA256 | None = None

    @model_validator(mode="after")
    def scope_has_safe_physical_state(self) -> CommandPermit:
        if self.expires_at_utc <= self.issued_at_utc:
            raise ValueError("permit expiry must follow issuance")
        if self.scope is PermitScope.PROPS_OFF_BENCH and not (
            self.operator_present and self.props_removed and self.physically_restrained
        ):
            raise ValueError("bench permits require operator, removed props, and restraint")
        if self.scope is PermitScope.CONTAINED_FLIGHT:
            if not self.operator_present or self.props_removed:
                raise ValueError("flight permits require present operator and installed props")
            if self.flight_entry_record_id is None or self.flight_entry_evidence_sha256 is None:
                raise ValueError("flight permits require an accepted flight-entry record")
        return self

    def allows(
        self,
        command: CommandKind,
        *,
        vehicle_id: str,
        selected_uri: str,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        if (
            not self.operator_present
            or current >= self.expires_at_utc
            or self.vehicle_id != vehicle_id
            or self.selected_uri != selected_uri
        ):
            return False
        if self.scope is PermitScope.OBSERVE_ONLY:
            return False
        if self.scope is PermitScope.PROPS_OFF_BENCH:
            return command in {
                CommandKind.ARM,
                CommandKind.DISARM,
                CommandKind.EMERGENCY_STOP,
            }
        return command in {
            CommandKind.ARM,
            CommandKind.DISARM,
            CommandKind.TAKEOFF,
            CommandKind.HOVER,
            CommandKind.MOVE_RELATIVE,
            CommandKind.STOP_AND_HOLD,
            CommandKind.LAND,
            CommandKind.ABORT,
            CommandKind.EMERGENCY_STOP,
        }
