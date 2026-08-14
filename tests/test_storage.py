from __future__ import annotations

from datetime import UTC, datetime

from flagwatch.domain import AiPolicy, Criteria, Event, EventFacts
from flagwatch.storage import Database


def test_database_keeps_incompatible_event_visible(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    event = Event(
        source="ctftime",
        source_id="3181",
        title="gaslightCTF 2026",
        official_url="https://gaslightctf.cooking/",
        ctftime_url="https://ctftime.org/event/3181/",
        starts_at=datetime(2026, 8, 14, 12, tzinfo=UTC),
        finishes_at=datetime(2026, 8, 17, 12, tzinfo=UTC),
        online=True,
    )
    database.upsert_event(event)
    database.save_facts(event.key, EventFacts(ai_policy=AiPolicy.HUMAN_ONLY))

    stored = database.list_events()[0]

    assert stored.event.title == "gaslightCTF 2026"
    assert stored.facts.ai_policy is AiPolicy.HUMAN_ONLY


def test_database_saves_versioned_criteria(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()

    assert database.get_criteria() == Criteria()

    saved = database.save_criteria(Criteria(max_team_size=6, version=1))

    assert saved.max_team_size == 6
    assert saved.version == 2
    assert database.get_criteria() == saved
