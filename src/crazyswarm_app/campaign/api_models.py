from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from crazyswarm_app.campaign.service import CampaignRunMode, ReviewDecision
from crazyswarm_app.campaign.timing import TimingStage


class CampaignApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetActiveCaseRequest(CampaignApiModel):
    case_id: str = Field(min_length=1, max_length=96)
    reason: str = Field(min_length=1, max_length=1000)


class StaticValidateCaseRequest(CampaignApiModel):
    case_id: str = Field(min_length=1, max_length=96)


class CampaignRunRequest(CampaignApiModel):
    mode: CampaignRunMode


class ChildCaseRequest(CampaignApiModel):
    child_case_id: str = Field(min_length=1, max_length=96)
    updates: dict[str, Any]


class ReviewObservationRequest(CampaignApiModel):
    note: str = Field(min_length=1, max_length=2000)


class ReviewDecisionRequest(CampaignApiModel):
    decision: ReviewDecision
    reason: str = Field(min_length=1, max_length=1000)
    note: str | None = Field(default=None, max_length=2000)


class BrowserTimingEventRequest(CampaignApiModel):
    correlation_id: str = Field(min_length=1, max_length=128)
    stage: TimingStage
    source_timestamp_s: float = Field(ge=0.0)
    source_clock_id: str = Field(min_length=1, max_length=128)
    source_clock_epoch: int = Field(ge=0)
    observed_monotonic_s: float = Field(ge=0.0)
    playback_buffer_age_s: float | None = Field(default=None, ge=0.0)
    dropped_samples: int = Field(default=0, ge=0)
    coalesced_samples: int = Field(default=0, ge=0)
