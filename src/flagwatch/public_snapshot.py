from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, HttpUrl, field_serializer, field_validator

from flagwatch.domain import AiPolicy, ScheduleMode
from flagwatch.storage import Database


class PublicEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_key: str
    title: str
    official_url: HttpUrl
    ctftime_url: HttpUrl
    starts_at: datetime
    finishes_at: datetime
    online: bool
    onsite: bool
    format: str | None
    weight: Decimal | None
    organizers: list[str]
    participants: int | None
    ai_policy: AiPolicy
    ai_policy_reason: str
    ai_policy_source: str | None
    ai_policy_evidence: str | None
    ai_policy_confidence: float
    ai_policy_conflicting: bool
    analysis_stale: bool
    team_max: int | None
    divisions: list[str]
    schedule_mode: ScheduleMode
    prize_summary: str | None
    registration_status: str | None
    categories: list[str]

    @field_validator("starts_at", "finishes_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Public timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_serializer("starts_at", "finishes_at", when_used="json")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")


class PublicSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    generated_at: datetime
    events: list[PublicEvent]

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Public timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_serializer("generated_at", when_used="json")
    def serialize_generated_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")


def build_public_snapshot(database: Database, generated_at: datetime) -> PublicSnapshot:
    events = [
        PublicEvent(
            event_key=view.event.key,
            title=view.event.title,
            official_url=view.event.official_url,
            ctftime_url=view.event.ctftime_url,
            starts_at=view.event.starts_at,
            finishes_at=view.event.finishes_at,
            online=view.event.online,
            onsite=view.event.onsite,
            format=view.event.format,
            weight=view.event.weight,
            organizers=view.event.organizers,
            participants=view.event.participants,
            ai_policy=view.facts.ai_policy,
            ai_policy_reason=view.facts.ai_policy_reason,
            ai_policy_source=view.facts.ai_policy_source,
            ai_policy_evidence=view.facts.ai_policy_evidence,
            ai_policy_confidence=view.facts.ai_policy_confidence,
            ai_policy_conflicting=view.facts.ai_policy_conflicting,
            analysis_stale=view.facts.analysis_stale,
            team_max=view.facts.team_max,
            divisions=view.facts.divisions,
            schedule_mode=view.facts.schedule_mode,
            prize_summary=view.facts.prize_summary,
            registration_status=view.facts.registration_status,
            categories=view.facts.categories,
        )
        for view in database.list_events()
    ]
    return PublicSnapshot(generated_at=generated_at, events=events)
