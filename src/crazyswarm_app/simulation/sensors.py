from __future__ import annotations

import math
import random
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crazyswarm_app.campaign.models import Region3D
from crazyswarm_app.campaign.perception import (
    PerceptionChangeKind,
    PerceptionObservation,
    PerceptionObservationSource,
)
from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import canonical_sha256

if TYPE_CHECKING:
    from crazyswarm_app.simulation.world import DynamicWorldTimeline


class FlowModelConfig(BaseModel):
    """Configured-unqualified sampled optical-flow observation boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_rate_hz: float = Field(default=100.0, gt=0.0)
    latency_s: float = Field(default=0.0, ge=0.0, le=1.0)
    velocity_noise_std_m_s: float = Field(default=0.0, ge=0.0)
    mounting_yaw_rad: float = Field(default=0.0, ge=-math.pi, le=math.pi)
    maximum_height_m: float = Field(default=2.0, gt=0.0)
    maximum_tilt_rad: float = Field(default=math.radians(35.0), gt=0.0, lt=math.pi / 2.0)
    blur_speed_m_s: float = Field(default=1.5, gt=0.0)
    minimum_quality_percent: float = Field(default=5.0, ge=0.0, le=100.0)
    dropout_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    parameter_source: str = "CONFIGURED_UNQUALIFIED"


class RangeModelConfig(BaseModel):
    """Configured-unqualified sampled six-ray range observation boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_rate_hz: float = Field(default=100.0, gt=0.0)
    latency_s: float = Field(default=0.0, ge=0.0, le=1.0)
    bias_m: float = 0.0
    beam_half_angle_rad: float = Field(default=0.0, ge=0.0, lt=math.pi / 2.0)
    parameter_source: str = "CONFIGURED_UNQUALIFIED"


class PerceptionModelConfig(BaseModel):
    """Bounded deterministic depth/range solid observation contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sensor_id: str = "simulated-depth-range"
    latency_s: float = Field(default=0.12, ge=0.0, le=2.0)
    expiry_s: float = Field(default=0.50, gt=0.0, le=5.0)
    confidence: float = Field(default=0.98, ge=0.0, le=1.0)
    extent_bias_m: float = Field(default=0.0, ge=-0.05, le=0.05)
    parameter_source: str = "CONFIGURED_UNQUALIFIED"

    @property
    def configuration_sha256(self) -> str:
        return canonical_sha256(self)


class SimulatedPerceptionObservationSource(PerceptionObservationSource):
    """Sensor adapter is the only boundary that can inspect dynamic world truth."""

    def __init__(
        self,
        *,
        timeline: DynamicWorldTimeline,
        config: PerceptionModelConfig,
        mission_id: str,
        run_id: str,
        vehicle_id: str,
        on_release: Callable[[PerceptionObservation], None] | None = None,
    ) -> None:
        observations: list[PerceptionObservation] = []
        for sequence, event in enumerate(timeline.events, start=1):
            region = None
            if event.obstacle is not None:
                obstacle = event.obstacle
                bias = config.extent_bias_m
                region = Region3D(
                    region_id=obstacle.obstacle_id,
                    minimum_m=Vector3(
                        x=obstacle.minimum_m.x - bias,
                        y=obstacle.minimum_m.y - bias,
                        z=obstacle.minimum_m.z - bias,
                    ),
                    maximum_m=Vector3(
                        x=obstacle.maximum_m.x + bias,
                        y=obstacle.maximum_m.y + bias,
                        z=obstacle.maximum_m.z + bias,
                    ),
                )
            received_s = event.source_timestamp_s + config.latency_s
            raw_payload = {
                "sensor_id": config.sensor_id,
                "sequence": sequence,
                "source_timestamp_s": event.source_timestamp_s,
                "solid_id": event.solid_id,
                "region": region,
            }
            observations.append(
                PerceptionObservation.create(
                    observation_id=f"{config.sensor_id}.{sequence}.{event.event_id}",
                    source_event_id=event.event_id,
                    mission_id=mission_id,
                    run_id=run_id,
                    vehicle_id=vehicle_id,
                    sensor_id=config.sensor_id,
                    sensor_configuration_sha256=config.configuration_sha256,
                    world_revision=sequence,
                    prior_perceived_world_revision=sequence - 1,
                    sequence=sequence,
                    source_timestamp_s=event.source_timestamp_s,
                    received_timestamp_s=received_s,
                    effective_source_s=event.effective_source_s,
                    expires_source_s=received_s + config.expiry_s,
                    confidence=config.confidence,
                    change_kind=_PERCEPTION_KIND_BY_TRUTH[event.kind.value],
                    solid_id=event.solid_id,
                    region=region,
                    raw_payload_sha256=canonical_sha256(raw_payload),
                )
            )
        super().__init__(tuple(observations))
        self._on_release = on_release

    def pop_ready(self, source_now_s: float) -> PerceptionObservation | None:
        observation = super().pop_ready(source_now_s)
        if observation is not None and self._on_release is not None:
            self._on_release(observation)
        return observation


_PERCEPTION_KIND_BY_TRUTH = {
    "SOLID_APPEARED": PerceptionChangeKind.SOLID_APPEARED,
    "SOLID_MOVED": PerceptionChangeKind.SOLID_MOVED,
    "SOLID_DISAPPEARED": PerceptionChangeKind.SOLID_DISAPPEARED,
    "PASSAGE_CLOSED": PerceptionChangeKind.PASSAGE_CLOSED,
    "PASSAGE_OPENED": PerceptionChangeKind.PASSAGE_OPENED,
}


class ImuModelConfig(BaseModel):
    """Reduced-order sampled IMU errors; zero coefficients preserve exact truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_rate_hz: float = Field(default=100.0, gt=0.0)
    latency_s: float = Field(default=0.0, ge=0.0, le=1.0)
    acceleration_noise_std_m_s2: Vector3 = Field(default_factory=Vector3)
    angular_velocity_noise_std_rad_s: Vector3 = Field(default_factory=Vector3)
    acceleration_bias_m_s2: Vector3 = Field(default_factory=Vector3)
    angular_velocity_bias_rad_s: Vector3 = Field(default_factory=Vector3)
    acceleration_bias_random_walk_m_s2_sqrt_s: Vector3 = Field(default_factory=Vector3)
    angular_velocity_bias_random_walk_rad_s_sqrt_s: Vector3 = Field(default_factory=Vector3)
    acceleration_scale_error: Vector3 = Field(default_factory=Vector3)
    angular_velocity_scale_error: Vector3 = Field(default_factory=Vector3)
    misalignment_rad: Vector3 = Field(default_factory=Vector3)
    filter_time_constant_s: float = Field(default=0.0, ge=0.0)
    acceleration_clip_m_s2: float | None = Field(default=None, gt=0.0)
    angular_velocity_clip_rad_s: float | None = Field(default=None, gt=0.0)
    parameter_source: str = "CONFIGURED_UNQUALIFIED"

    @model_validator(mode="after")
    def nonnegative_standard_deviations(self) -> ImuModelConfig:
        for name, vector in (
            ("acceleration noise", self.acceleration_noise_std_m_s2),
            ("angular velocity noise", self.angular_velocity_noise_std_rad_s),
            (
                "acceleration bias random walk",
                self.acceleration_bias_random_walk_m_s2_sqrt_s,
            ),
            (
                "angular velocity bias random walk",
                self.angular_velocity_bias_random_walk_rad_s_sqrt_s,
            ),
        ):
            if any(value < 0.0 for value in vector.model_dump().values()):
                raise ValueError(f"{name} standard deviations cannot be negative")
        return self


@dataclass(frozen=True, slots=True)
class ImuSample:
    source_timestamp_s: float
    acceleration_body_m_s2: Vector3
    angular_velocity_body_rad_s: Vector3


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(
        x=left.y * right.z - left.z * right.y,
        y=left.z * right.x - left.x * right.z,
        z=left.x * right.y - left.y * right.x,
    )


def _add(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(x=left.x + right.x, y=left.y + right.y, z=left.z + right.z)


def _clip(value: Vector3, limit: float | None) -> Vector3:
    if limit is None:
        return value
    return Vector3(
        x=max(-limit, min(limit, value.x)),
        y=max(-limit, min(limit, value.y)),
        z=max(-limit, min(limit, value.z)),
    )


class SampledImuModel:
    def __init__(self, config: ImuModelConfig, random_source: random.Random) -> None:
        self.config = config
        self._random = random_source
        self._history: deque[ImuSample] = deque()
        self._next_sample_s = 0.0
        self._acceleration_bias = config.acceleration_bias_m_s2
        self._angular_velocity_bias = config.angular_velocity_bias_rad_s
        self._filtered_acceleration = Vector3()
        self._filtered_angular_velocity = Vector3()
        self.reading = ImuSample(0.0, Vector3(), Vector3())

    def reset(
        self,
        *,
        now_s: float,
        acceleration_body_m_s2: Vector3,
        angular_velocity_body_rad_s: Vector3,
    ) -> None:
        self._history.clear()
        self._acceleration_bias = self.config.acceleration_bias_m_s2
        self._angular_velocity_bias = self.config.angular_velocity_bias_rad_s
        self._filtered_acceleration = acceleration_body_m_s2
        self._filtered_angular_velocity = angular_velocity_body_rad_s
        self._next_sample_s = now_s
        self.update(
            now_s=now_s,
            acceleration_body_m_s2=acceleration_body_m_s2,
            angular_velocity_body_rad_s=angular_velocity_body_rad_s,
        )

    def update(
        self,
        *,
        now_s: float,
        acceleration_body_m_s2: Vector3,
        angular_velocity_body_rad_s: Vector3,
    ) -> None:
        period_s = 1.0 / self.config.sample_rate_hz
        if now_s + 1e-12 >= self._next_sample_s:
            self._acceleration_bias = self._walk_bias(
                self._acceleration_bias,
                self.config.acceleration_bias_random_walk_m_s2_sqrt_s,
                period_s,
            )
            self._angular_velocity_bias = self._walk_bias(
                self._angular_velocity_bias,
                self.config.angular_velocity_bias_random_walk_rad_s_sqrt_s,
                period_s,
            )
            acceleration = self._measure(
                acceleration_body_m_s2,
                self._acceleration_bias,
                self.config.acceleration_noise_std_m_s2,
                self.config.acceleration_scale_error,
            )
            angular_velocity = self._measure(
                angular_velocity_body_rad_s,
                self._angular_velocity_bias,
                self.config.angular_velocity_noise_std_rad_s,
                self.config.angular_velocity_scale_error,
            )
            if self.config.filter_time_constant_s > 0.0:
                alpha = 1.0 - math.exp(-period_s / self.config.filter_time_constant_s)
                acceleration = self._filter(self._filtered_acceleration, acceleration, alpha)
                angular_velocity = self._filter(
                    self._filtered_angular_velocity,
                    angular_velocity,
                    alpha,
                )
            self._filtered_acceleration = acceleration
            self._filtered_angular_velocity = angular_velocity
            sample = ImuSample(
                source_timestamp_s=now_s,
                acceleration_body_m_s2=_clip(
                    acceleration,
                    self.config.acceleration_clip_m_s2,
                ),
                angular_velocity_body_rad_s=_clip(
                    angular_velocity,
                    self.config.angular_velocity_clip_rad_s,
                ),
            )
            self._history.append(sample)
            skipped_periods = max(1, math.floor((now_s - self._next_sample_s) / period_s) + 1)
            self._next_sample_s += skipped_periods * period_s

        latency_boundary_s = now_s - self.config.latency_s
        selected = self._history[0]
        for sample in self._history:
            if sample.source_timestamp_s <= latency_boundary_s:
                selected = sample
            else:
                break
        self.reading = selected
        while len(self._history) > 2 and self._history[1].source_timestamp_s <= latency_boundary_s:
            self._history.popleft()

    def _walk_bias(self, bias: Vector3, density: Vector3, dt: float) -> Vector3:
        scale = math.sqrt(dt)
        return Vector3(
            x=bias.x + self._noise(density.x * scale),
            y=bias.y + self._noise(density.y * scale),
            z=bias.z + self._noise(density.z * scale),
        )

    def _measure(
        self,
        truth: Vector3,
        bias: Vector3,
        noise: Vector3,
        scale_error: Vector3,
    ) -> Vector3:
        scaled = Vector3(
            x=truth.x * (1.0 + scale_error.x),
            y=truth.y * (1.0 + scale_error.y),
            z=truth.z * (1.0 + scale_error.z),
        )
        misaligned = _add(scaled, _cross(self.config.misalignment_rad, scaled))
        return Vector3(
            x=misaligned.x + bias.x + self._noise(noise.x),
            y=misaligned.y + bias.y + self._noise(noise.y),
            z=misaligned.z + bias.z + self._noise(noise.z),
        )

    def _noise(self, standard_deviation: float) -> float:
        if standard_deviation == 0.0:
            return 0.0
        return self._random.gauss(0.0, standard_deviation)

    @staticmethod
    def _filter(previous: Vector3, current: Vector3, alpha: float) -> Vector3:
        return Vector3(
            x=previous.x + alpha * (current.x - previous.x),
            y=previous.y + alpha * (current.y - previous.y),
            z=previous.z + alpha * (current.z - previous.z),
        )
