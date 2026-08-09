from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from crazyswarm_app.domain.models import ContractModel, Identifier


class HostMeasurementClass(StrEnum):
    MEASURED_HOST = "MEASURED_HOST"
    REPORTED_NOT_MEASURED = "REPORTED_NOT_MEASURED"


class CompatibilityCheckerStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class HostGateDecision(StrEnum):
    GO_MINIMAL_EXPERIMENT = "GO_MINIMAL_EXPERIMENT"
    DEFER_RESOURCE_LIMIT = "DEFER_RESOURCE_LIMIT"
    WAITING_FOR_MEASURED_HOST_AND_CHECKER = "WAITING_FOR_MEASURED_HOST_AND_CHECKER"


class IsaacOfficialRequirements(ContractModel):
    schema_version: Literal[1] = 1
    requirements_id: Identifier
    captured_local_date: str
    documentation_release: str
    requirements_url: str
    workstation_install_url: str
    minimum_operating_systems: tuple[str, ...]
    minimum_physical_cpu_cores: Annotated[int, Field(ge=1)]
    minimum_system_ram_bytes: Annotated[int, Field(gt=0)]
    minimum_free_storage_bytes: Annotated[int, Field(gt=0)]
    minimum_gpu: str
    minimum_vram_bytes: Annotated[int, Field(gt=0)]
    tested_windows_driver: str
    official_checker_required_for_go: Literal[True] = True


class CompatibilityCheckerEvidence(ContractModel):
    status: CompatibilityCheckerStatus = CompatibilityCheckerStatus.NOT_RUN
    package_version: str | None = None
    command: str | None = None
    exit_code: int | None = None
    report_path: str | None = None
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def completed_checker_is_traceable(self) -> CompatibilityCheckerEvidence:
        if self.status is not CompatibilityCheckerStatus.NOT_RUN and (
            self.exit_code is None or not self.package_version or not self.report_path
        ):
            raise ValueError("completed compatibility checker evidence must be traceable")
        return self


class IsaacHostInventory(ContractModel):
    schema_version: Literal[1] = 1
    inventory_id: Identifier
    captured_at_utc: str
    measurement_class: HostMeasurementClass
    host_name: str
    manufacturer: str | None = None
    model: str | None = None
    sku: str | None = None
    operating_system: str
    os_build: str | None = None
    cpu: str
    physical_cpu_cores: int | None = Field(default=None, ge=1)
    logical_cpu_cores: int | None = Field(default=None, ge=1)
    system_ram_bytes: int
    gpu: str
    vram_bytes: int
    driver_version: str | None = None
    gpu_tgp_w: float | None = Field(default=None, gt=0.0)
    free_storage_bytes: int | None = Field(default=None, ge=0)
    power_mode: str | None = None
    gpu_temperature_c: float | None = None
    network_summary: str | None = None
    official_checker: CompatibilityCheckerEvidence = Field(
        default_factory=CompatibilityCheckerEvidence
    )


class HostGateFinding(ContractModel):
    check: Identifier
    passed: bool
    measured: str
    required: str
    blocking: bool


class IsaacHostGateReport(ContractModel):
    schema_version: Literal[1] = 1
    profile_id: Identifier
    classification: Literal["MEASURED_HOST_EVIDENCE", "REPORTED_PRECHECK_NOT_LIVE_EVIDENCE"]
    decision: HostGateDecision
    compatible: bool
    headless_gateway_authorized: bool
    host_kind: Literal["LOCAL_WINDOWS_VICTUS"] = "LOCAL_WINDOWS_VICTUS"
    operating_system: str
    cpu: str
    system_ram_bytes: int
    gpu: str
    vram_bytes: int
    driver_version: str
    free_storage_bytes: int | str
    isaac_runtime_version: str
    ros_distribution: str
    middleware: str
    network_path: str
    resource_and_thermal_results: str
    paid_cloud_approved: Literal[False] = False
    checker_status: CompatibilityCheckerStatus
    requirements_id: Identifier
    findings: tuple[HostGateFinding, ...]

    @model_validator(mode="after")
    def only_measured_passing_evidence_can_authorize(self) -> IsaacHostGateReport:
        if self.decision is HostGateDecision.GO_MINIMAL_EXPERIMENT:
            if self.classification != "MEASURED_HOST_EVIDENCE":
                raise ValueError("GO_MINIMAL_EXPERIMENT requires measured host evidence")
            if not self.compatible or not self.headless_gateway_authorized:
                raise ValueError("GO_MINIMAL_EXPERIMENT must explicitly authorize launch")
            if self.checker_status is not CompatibilityCheckerStatus.PASSED:
                raise ValueError("GO_MINIMAL_EXPERIMENT requires the official checker")
        elif self.compatible or self.headless_gateway_authorized:
            raise ValueError("a non-GO host profile cannot authorize Isaac launch")
        return self


def load_official_requirements(path: Path) -> IsaacOfficialRequirements:
    return IsaacOfficialRequirements.model_validate_json(path.read_text(encoding="utf-8"))


def load_host_inventory(path: Path) -> IsaacHostInventory:
    return IsaacHostInventory.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_isaac_host(
    inventory: IsaacHostInventory,
    requirements: IsaacOfficialRequirements,
) -> IsaacHostGateReport:
    findings = (
        _finding(
            "OPERATING_SYSTEM",
            any(
                item.lower() in inventory.operating_system.lower()
                for item in requirements.minimum_operating_systems
            ),
            inventory.operating_system,
            " or ".join(requirements.minimum_operating_systems),
        ),
        _optional_minimum_finding(
            "PHYSICAL_CPU_CORES",
            inventory.physical_cpu_cores,
            requirements.minimum_physical_cpu_cores,
        ),
        _minimum_finding(
            "SYSTEM_RAM_BYTES",
            inventory.system_ram_bytes,
            requirements.minimum_system_ram_bytes,
        ),
        _optional_minimum_finding(
            "FREE_STORAGE_BYTES",
            inventory.free_storage_bytes,
            requirements.minimum_free_storage_bytes,
        ),
        _minimum_finding("VRAM_BYTES", inventory.vram_bytes, requirements.minimum_vram_bytes),
        HostGateFinding(
            check="GPU_CLASS_OFFICIAL_CHECKER",
            passed=inventory.official_checker.status is CompatibilityCheckerStatus.PASSED,
            measured=inventory.gpu,
            required=requirements.minimum_gpu,
            blocking=True,
        ),
        HostGateFinding(
            check="OFFICIAL_COMPATIBILITY_CHECKER",
            passed=inventory.official_checker.status is CompatibilityCheckerStatus.PASSED,
            measured=inventory.official_checker.status.value,
            required=CompatibilityCheckerStatus.PASSED.value,
            blocking=True,
        ),
    )
    known_resource_failure = any(
        not finding.passed
        for finding in findings
        if finding.check
        in {
            "OPERATING_SYSTEM",
            "PHYSICAL_CPU_CORES",
            "SYSTEM_RAM_BYTES",
            "FREE_STORAGE_BYTES",
            "VRAM_BYTES",
        }
        and finding.measured != "NOT_MEASURED"
    )
    checker_failed = inventory.official_checker.status is CompatibilityCheckerStatus.FAILED
    measured = inventory.measurement_class is HostMeasurementClass.MEASURED_HOST
    all_passed = all(finding.passed for finding in findings)
    if known_resource_failure or checker_failed:
        decision = HostGateDecision.DEFER_RESOURCE_LIMIT
    elif measured and all_passed:
        decision = HostGateDecision.GO_MINIMAL_EXPERIMENT
    else:
        decision = HostGateDecision.WAITING_FOR_MEASURED_HOST_AND_CHECKER
    go = decision is HostGateDecision.GO_MINIMAL_EXPERIMENT
    return IsaacHostGateReport(
        profile_id=f"{inventory.inventory_id}-gate",
        classification=(
            "MEASURED_HOST_EVIDENCE" if measured else "REPORTED_PRECHECK_NOT_LIVE_EVIDENCE"
        ),
        decision=decision,
        compatible=go,
        headless_gateway_authorized=go,
        operating_system=inventory.operating_system,
        cpu=inventory.cpu,
        system_ram_bytes=inventory.system_ram_bytes,
        gpu=inventory.gpu,
        vram_bytes=inventory.vram_bytes,
        driver_version=inventory.driver_version or "NOT_MEASURED",
        free_storage_bytes=(
            inventory.free_storage_bytes
            if inventory.free_storage_bytes is not None
            else "NOT_MEASURED"
        ),
        isaac_runtime_version=("6.0.1" if go else "NOT_PINNED_RESOURCE_GATE_NOT_GO"),
        ros_distribution=("JAZZY" if go else "NOT_PINNED_RESOURCE_GATE_NOT_GO"),
        middleware=("FAST_DDS" if go else "NOT_PINNED_RESOURCE_GATE_NOT_GO"),
        network_path=inventory.network_summary or "NOT_MEASURED",
        resource_and_thermal_results="NOT_RUN",
        checker_status=inventory.official_checker.status,
        requirements_id=requirements.requirements_id,
        findings=findings,
    )


def _minimum_finding(check: str, measured: int, required: int) -> HostGateFinding:
    return HostGateFinding(
        check=check,
        passed=measured >= required,
        measured=str(measured),
        required=str(required),
        blocking=True,
    )


def _optional_minimum_finding(
    check: str,
    measured: int | None,
    required: int,
) -> HostGateFinding:
    if measured is None:
        return HostGateFinding(
            check=check,
            passed=False,
            measured="NOT_MEASURED",
            required=str(required),
            blocking=True,
        )
    return _minimum_finding(check, measured, required)


def _finding(check: str, passed: bool, measured: str, required: str) -> HostGateFinding:
    return HostGateFinding(
        check=check,
        passed=passed,
        measured=measured,
        required=required,
        blocking=True,
    )
