from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal, TypeVar

from pydantic import Field

from crazyswarm_app.domain.models import ContractModel, Identifier
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256
from crazyswarm_app.planning.contracts import PluginManifest

InputT = TypeVar("InputT", bound=ContractModel)
OutputT = TypeVar("OutputT", bound=ContractModel)


class PluginContractQualification(ContractModel):
    schema_version: Literal[1] = 1
    plugin_id: Identifier
    implementation_version: str
    manifest_sha256: SHA256
    canonical_input_sha256: SHA256
    canonical_output_sha256: SHA256
    deterministic: bool
    bounded: bool
    budget_s: float = Field(gt=0.0)
    invocation_count: Literal[2] = 2
    cleanup_required: bool = False
    passed: bool


def qualify_plugin_contract(
    manifest: PluginManifest,
    canonical_input: InputT,
    invoke: Callable[[InputT], OutputT],
    *,
    budget_s: float = 1.0,
) -> PluginContractQualification:
    """Shared deterministic/bounded contract check used by every plugin kind."""

    started = time.monotonic()
    first = invoke(canonical_input)
    second = invoke(canonical_input)
    elapsed_s = time.monotonic() - started
    first_sha256 = canonical_sha256(first)
    second_sha256 = canonical_sha256(second)
    deterministic = first_sha256 == second_sha256
    bounded = elapsed_s <= budget_s
    return PluginContractQualification(
        plugin_id=manifest.plugin_id,
        implementation_version=manifest.implementation_version,
        manifest_sha256=manifest.sha256,
        canonical_input_sha256=canonical_sha256(canonical_input),
        canonical_output_sha256=first_sha256,
        deterministic=deterministic,
        bounded=bounded,
        budget_s=budget_s,
        passed=deterministic and bounded and manifest.deterministic and manifest.bounded,
    )
