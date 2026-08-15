from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, model_validator


class AiPolicy(StrEnum):
    AI_NATIVE = "ai_native"
    AI_ASSISTED = "ai_assisted"
    HUMAN_ONLY = "human_only"
    UNKNOWN = "unknown"


class ScheduleMode(StrEnum):
    FIXED = "fixed"
    ROLLING = "rolling"
    STAGGERED = "staggered"
    MULTI_STAGE = "multi_stage"
    UNKNOWN = "unknown"


class Event(BaseModel):
    source: str
    source_id: str
    title: str
    official_url: HttpUrl
    ctftime_url: HttpUrl
    starts_at: datetime
    finishes_at: datetime
    online: bool
    onsite: bool = False
    format: str | None = None
    description: str = ""
    prizes: str = ""
    weight: Decimal | None = None
    organizers: list[str] = Field(default_factory=list)
    participants: int | None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def finish_must_follow_start(self) -> Event:
        if self.finishes_at <= self.starts_at:
            raise ValueError("Event finish must follow its start")
        return self

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"


class EventFacts(BaseModel):
    ai_policy: AiPolicy = AiPolicy.UNKNOWN
    ai_policy_reason: str = "No clear AI policy found"
    ai_policy_source: str | None = None
    ai_policy_evidence: str | None = None
    ai_policy_confidence: float = 0.0
    ai_policy_conflicting: bool = False
    team_max: int | None = None
    divisions: list[str] = Field(default_factory=list)
    schedule_mode: ScheduleMode = ScheduleMode.UNKNOWN
    prize_summary: str | None = None
    registration_status: str | None = None
    categories: list[str] = Field(default_factory=list)
    analyzed_at: datetime | None = None
    analysis_stale: bool = False
    analysis_error: str | None = None


class Criteria(BaseModel):
    require_online: bool = True
    allow_hybrid: bool = True
    max_team_size: int | None = None
    min_duration_hours: int | None = None
    max_duration_hours: int | None = None
    require_prize: bool = False
    minimum_cash_prize: Decimal | None = None
    allowed_schedule_modes: set[ScheduleMode] = Field(default_factory=set)
    minimum_ctftime_weight: Decimal | None = None
    version: int = 1


class MatchResult(BaseModel):
    alert_eligible: bool
    match_reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)


class EventView(BaseModel):
    event: Event
    facts: EventFacts
