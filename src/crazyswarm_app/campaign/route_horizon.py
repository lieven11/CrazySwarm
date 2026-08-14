from __future__ import annotations

import math
from enum import StrEnum
from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from crazyswarm_app.campaign.models import (
    MotionContractAmendment,
    MotionQualityContract,
    RouteNodeMode,
)
from crazyswarm_app.domain.models import ContractModel, Vector3
from crazyswarm_app.domain.simulation import SHA256, canonical_sha256


class CanonicalRouteNode(ContractModel):
    path_state_index: int = Field(ge=0)
    position_m: Vector3
    mode: RouteNodeMode
    authored_indices: tuple[int, ...] = Field(min_length=1)
    repeated_coordinate: bool = False


class RouteHorizon(ContractModel):
    schema_version: Literal[1] = 1
    nodes: tuple[CanonicalRouteNode, ...] = Field(min_length=2)
    segment_lengths_m: tuple[float, ...] = Field(min_length=1)
    target_knot_speeds_m_s: tuple[float, ...] = Field(min_length=2)
    contract_sha256: SHA256
    horizon_sha256: SHA256

    @model_validator(mode="after")
    def aligned(self) -> RouteHorizon:
        if len(self.segment_lengths_m) != len(self.nodes) - 1:
            raise ValueError("route-horizon segment count is inconsistent")
        if len(self.target_knot_speeds_m_s) != len(self.nodes):
            raise ValueError("route-horizon knot-speed count is inconsistent")
        return self


class MotionAmendmentDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_AUTHORITY = "REJECTED_AUTHORITY"
    REJECTED_UNSAFE = "REJECTED_UNSAFE"


class MotionSuffixReplacement(ContractModel):
    prior_accepted_program_sha256: SHA256
    replacement_accepted_program_sha256: SHA256
    prior_trajectory_sha256: SHA256
    suffix_trajectory_sha256: SHA256
    prior_contract_sha256: SHA256
    replacement_contract_sha256: SHA256
    amendment_sha256: SHA256
    effective_source_s: float = Field(ge=0.0)
    disposition: MotionAmendmentDisposition


class MotionIntentController:
    """Atomic authority boundary for an in-flight motion-contract suffix."""

    def __init__(
        self,
        *,
        contract: MotionQualityContract,
        accepted_program_sha256: SHA256,
        active_trajectory_sha256: SHA256,
    ) -> None:
        self.contract = contract
        self.accepted_program_sha256 = accepted_program_sha256
        self.active_trajectory_sha256 = active_trajectory_sha256
        self._last_sequence_by_source: dict[str, int] = {}
        self._last_source_timestamp_by_source: dict[str, float] = {}
        self._seen_amendments: set[SHA256] = set()

    def apply(
        self,
        amendment: MotionContractAmendment,
        *,
        source_now_s: float,
        suffix_trajectory_sha256: SHA256,
        safe_suffix: bool,
        authorized_program_sha256: SHA256,
    ) -> MotionSuffixReplacement:
        disposition = self._disposition(
            amendment,
            source_now_s=source_now_s,
            safe_suffix=safe_suffix,
            authorized_program_sha256=authorized_program_sha256,
        )
        prior_program = self.accepted_program_sha256
        prior_trajectory = self.active_trajectory_sha256
        replacement_program = prior_program
        if disposition is MotionAmendmentDisposition.ACCEPTED:
            replacement_program = canonical_sha256(
                {
                    "prior_accepted_program_sha256": prior_program,
                    "prior_trajectory_sha256": prior_trajectory,
                    "suffix_trajectory_sha256": suffix_trajectory_sha256,
                    "amendment_sha256": amendment.amendment_sha256,
                    "effective_source_s": amendment.effective_source_s,
                }
            )
            self.contract = amendment.replacement
            self.accepted_program_sha256 = replacement_program
            self.active_trajectory_sha256 = suffix_trajectory_sha256
            self._last_sequence_by_source[amendment.source_id] = amendment.sequence
            self._last_source_timestamp_by_source[amendment.source_id] = (
                amendment.source_timestamp_s
            )
            self._seen_amendments.add(amendment.amendment_sha256)
        return MotionSuffixReplacement(
            prior_accepted_program_sha256=prior_program,
            replacement_accepted_program_sha256=replacement_program,
            prior_trajectory_sha256=prior_trajectory,
            suffix_trajectory_sha256=suffix_trajectory_sha256,
            prior_contract_sha256=amendment.prior_contract_sha256,
            replacement_contract_sha256=amendment.replacement.contract_sha256,
            amendment_sha256=amendment.amendment_sha256,
            effective_source_s=amendment.effective_source_s,
            disposition=disposition,
        )

    def _disposition(
        self,
        amendment: MotionContractAmendment,
        *,
        source_now_s: float,
        safe_suffix: bool,
        authorized_program_sha256: SHA256,
    ) -> MotionAmendmentDisposition:
        if amendment.amendment_sha256 in self._seen_amendments:
            return MotionAmendmentDisposition.REJECTED_DUPLICATE
        if (
            not amendment.authenticated
            or authorized_program_sha256 != self.accepted_program_sha256
            or amendment.prior_contract_sha256 != self.contract.contract_sha256
        ):
            return MotionAmendmentDisposition.REJECTED_AUTHORITY
        if (
            amendment.sequence
            <= self._last_sequence_by_source.get(amendment.source_id, 0)
            or amendment.source_timestamp_s
            <= self._last_source_timestamp_by_source.get(amendment.source_id, -1.0)
            or amendment.effective_source_s < source_now_s
        ):
            return MotionAmendmentDisposition.REJECTED_STALE
        if not safe_suffix:
            return MotionAmendmentDisposition.REJECTED_UNSAFE
        return MotionAmendmentDisposition.ACCEPTED


def compile_route_horizon(
    positions: tuple[Vector3, ...],
    modes: tuple[RouteNodeMode, ...],
    contract: MotionQualityContract,
    *,
    maximum_speed_m_s: float,
    maximum_acceleration_m_s2: float,
    collinear_tolerance_m: float = 1e-9,
) -> RouteHorizon:
    """Normalize sampling knots and allocate one forward/backward speed envelope.

    Repeated coordinates remain distinct path states. Only an ordinary fly-through
    sample on a same-direction collinear segment may collapse.
    """

    if len(positions) != len(modes) or len(positions) < 2:
        raise ValueError("route positions and modes must have one shared length >= 2")
    coordinate_counts = {
        _coordinate_key(position): sum(
            1 for candidate in positions if _coordinate_key(candidate) == _coordinate_key(position)
        )
        for position in positions
    }
    retained: list[tuple[int, Vector3, RouteNodeMode, list[int]]] = []
    for index, (position, mode) in enumerate(zip(positions, modes, strict=True)):
        if (
            0 < index < len(positions) - 1
            and mode is RouteNodeMode.FLY_THROUGH
            and coordinate_counts[_coordinate_key(position)] == 1
            and _same_direction_collinear(
                positions[index - 1],
                position,
                positions[index + 1],
                tolerance=collinear_tolerance_m,
            )
        ):
            if retained:
                retained[-1][3].append(index)
            continue
        retained.append((index, position, mode, [index]))

    nodes = tuple(
        CanonicalRouteNode(
            path_state_index=path_index,
            position_m=position,
            mode=mode,
            authored_indices=tuple(authored_indices),
            repeated_coordinate=coordinate_counts[_coordinate_key(position)] > 1,
        )
        for path_index, (_original, position, mode, authored_indices) in enumerate(retained)
    )
    lengths = tuple(
        _distance(before.position_m, after.position_m) for before, after in pairwise(nodes)
    )
    if any(length <= 1e-9 for length in lengths):
        raise ValueError("canonical route cannot contain zero-length consecutive path states")

    target = min(contract.target_speed_m_s or maximum_speed_m_s, maximum_speed_m_s)
    curve_caps = [target] * len(nodes)
    curve_caps[0] = 0.0
    curve_caps[-1] = 0.0
    for index in range(1, len(nodes) - 1):
        node = nodes[index]
        if node.mode in {
            RouteNodeMode.CAPTURE_AND_HOLD,
            RouteNodeMode.REVERSAL,
        }:
            curve_caps[index] = 0.0
            continue
        curvature = _curvature(
            nodes[index - 1].position_m,
            node.position_m,
            nodes[index + 1].position_m,
        )
        if curvature > 1e-12:
            curve_caps[index] = min(
                target,
                math.sqrt(maximum_acceleration_m_s2 / curvature),
            )

    speeds = list(curve_caps)
    for index, length in enumerate(lengths):
        speeds[index + 1] = min(
            speeds[index + 1],
            math.sqrt(max(0.0, speeds[index] ** 2 + 2.0 * maximum_acceleration_m_s2 * length)),
        )
    for index in range(len(lengths) - 1, -1, -1):
        speeds[index] = min(
            speeds[index],
            math.sqrt(
                max(0.0, speeds[index + 1] ** 2 + 2.0 * maximum_acceleration_m_s2 * lengths[index])
            ),
        )

    payload = {
        "nodes": nodes,
        "segment_lengths_m": lengths,
        "target_knot_speeds_m_s": tuple(speeds),
        "contract_sha256": contract.contract_sha256,
    }
    return RouteHorizon(**payload, horizon_sha256=canonical_sha256(payload))


def _coordinate_key(point: Vector3) -> tuple[float, float, float]:
    return (round(point.x, 12), round(point.y, 12), round(point.z, 12))


def _same_direction_collinear(
    before: Vector3,
    current: Vector3,
    after: Vector3,
    *,
    tolerance: float,
) -> bool:
    incoming = _subtract(current, before)
    outgoing = _subtract(after, current)
    cross = Vector3(
        x=incoming.y * outgoing.z - incoming.z * outgoing.y,
        y=incoming.z * outgoing.x - incoming.x * outgoing.z,
        z=incoming.x * outgoing.y - incoming.y * outgoing.x,
    )
    return _norm(cross) <= tolerance and _dot(incoming, outgoing) > 0.0


def _curvature(before: Vector3, current: Vector3, after: Vector3) -> float:
    first = _distance(before, current)
    second = _distance(current, after)
    third = _distance(before, after)
    denominator = first * second * third
    if denominator <= 1e-12:
        return 0.0
    cross = _cross(_subtract(current, before), _subtract(after, current))
    return 2.0 * _norm(cross) / denominator


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(
        x=left.y * right.z - left.z * right.y,
        y=left.z * right.x - left.x * right.z,
        z=left.x * right.y - left.y * right.x,
    )


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(x=left.x - right.x, y=left.y - right.y, z=left.z - right.z)


def _dot(left: Vector3, right: Vector3) -> float:
    return left.x * right.x + left.y * right.y + left.z * right.z


def _norm(value: Vector3) -> float:
    return math.sqrt(value.x * value.x + value.y * value.y + value.z * value.z)


def _distance(left: Vector3, right: Vector3) -> float:
    return _norm(_subtract(left, right))
