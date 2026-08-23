from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from flagwatch.domain import (
    Event,
    EventAnalytics,
    EventFacts,
    SourceConflict,
    SourceKind,
    SourceRef,
)
from flagwatch.public_snapshot import build_public_snapshot
from flagwatch.storage import Database


def test_generic_event_does_not_require_ctftime() -> None:
    starts_at = datetime(2026, 9, 1, 12, tzinfo=UTC)

    event = Event(
        source="official-htb",
        source_id="cyber-apocalypse-2027",
        title="Cyber Apocalypse 2027",
        official_url="https://www.hackthebox.com/events/cyber-apocalypse-2027",
        starts_at=starts_at,
        finishes_at=starts_at + timedelta(days=5),
        online=True,
        registration_url="https://ctf.hackthebox.com/register",
        platform="CTFd",
        primary_source_url="https://www.hackthebox.com/events/cyber-apocalypse-2027",
        source_refs=[
            SourceRef(
                source="Hack The Box events",
                kind=SourceKind.ORGANIZER_PAGE,
                url="https://www.hackthebox.com/events",
                record_id="cyber-apocalypse-2027",
                collected_at=datetime(2026, 8, 23, 15, tzinfo=UTC),
            )
        ],
        analytics=EventAnalytics(
            challenges_total=42,
            visible_solves=9001,
            scoreboard_entries=311,
            categories={"web": 9, "pwn": 8},
        ),
    )

    assert event.ctftime_url is None
    assert str(event.primary_source_url) == (
        "https://www.hackthebox.com/events/cyber-apocalypse-2027"
    )
    assert event.source_refs[0].kind is SourceKind.ORGANIZER_PAGE
    assert event.analytics.categories == {"web": 9, "pwn": 8}


def test_source_collection_time_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        SourceRef(
            source="Official calendar",
            kind=SourceKind.ICS,
            url="https://example.test/events.ics",
            collected_at=datetime(2026, 8, 23, 15),
        )


def test_conflict_requires_distinct_source_urls() -> None:
    with pytest.raises(ValidationError, match="distinct"):
        SourceConflict(
            field="starts_at",
            chosen_value="2026-09-01T12:00:00Z",
            other_value="2026-09-01T13:00:00Z",
            chosen_source_url="https://example.test/rules",
            other_source_url="https://example.test/rules",
            detected_at=datetime(2026, 8, 23, 15, tzinfo=UTC),
            suppresses_alert=True,
        )


def test_public_snapshot_exposes_provenance_conflicts_and_safe_analytics(tmp_path) -> None:
    database = Database(tmp_path / "flagwatch.sqlite3")
    database.initialize()
    starts_at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    event = Event(
        source="official-feed",
        source_id="example",
        title="Example CTF",
        official_url="https://example.test/event",
        starts_at=starts_at,
        finishes_at=starts_at + timedelta(days=1),
        online=True,
        primary_source_url="https://example.test/rules",
        source_refs=[
            SourceRef(
                source="Official feed",
                kind=SourceKind.JSON_FEED,
                url="https://example.test/feed.json",
                collected_at=datetime(2026, 8, 23, 15, tzinfo=UTC),
            )
        ],
        conflicts=[
            SourceConflict(
                field="team_max",
                chosen_value="4",
                other_value="5",
                chosen_source_url="https://example.test/rules",
                other_source_url="https://example.test/feed.json",
                detected_at=datetime(2026, 8, 23, 15, tzinfo=UTC),
                suppresses_alert=True,
            )
        ],
        analytics=EventAnalytics(
            challenges_total=12,
            visible_solves=48,
            scoreboard_entries=7,
            categories={"crypto": 4, "web": 8},
        ),
        raw={"token": "must-not-leak"},
    )
    database.upsert_event(event)
    database.save_facts(event.key, EventFacts())

    payload = build_public_snapshot(database, generated_at=starts_at).model_dump(mode="json")
    public_event = payload["events"][0]

    assert public_event["ctftime_url"] is None
    assert public_event["primary_source_url"] == "https://example.test/rules"
    assert public_event["source_refs"][0]["kind"] == "json_feed"
    assert public_event["conflicts"][0]["field"] == "team_max"
    assert public_event["conflicts"][0]["suppresses_alert"] is True
    assert public_event["analytics"]["visible_solves"] == 48
    assert "must-not-leak" not in str(payload)
