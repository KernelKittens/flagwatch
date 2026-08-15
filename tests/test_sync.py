from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flagwatch.domain import AiPolicy, Event, EventFacts
from flagwatch.fetching import FetchedPage
from flagwatch.storage import Database
from flagwatch.sync import SyncService


class FakeSource:
    def __init__(self, event: Event, seed: EventFacts) -> None:
        self.event = event
        self.seed = seed

    def fetch_events(self, _start: datetime, _finish: datetime):
        return [(self.event, self.seed)]


class FakeFetcher:
    def get_page(self, url: str) -> FetchedPage:
        return FetchedPage(
            url=url,
            text=(
                "Interactive AI assistance is allowed. "
                "Fully automated solving agents are prohibited."
            ),
            html=None,
        )


def test_repeated_sync_queues_one_alert(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    event = Event(
        source="ctftime",
        source_id="4000",
        title="AI Friendly CTF",
        official_url="https://ctf.example/",
        ctftime_url="https://ctftime.org/event/4000/",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
        prizes="$500",
    )
    service = SyncService(
        database=database,
        source=FakeSource(event, EventFacts(team_max=4, prize_summary="$500")),
        fetcher=FakeFetcher(),
        now=lambda: datetime(2026, 8, 14, 23, tzinfo=UTC),
    )

    first = service.run()
    second = service.run()

    assert first.imported == 1
    assert first.queued == 1
    assert second.queued == 0
    assert database.count_outbox() == 1
    assert database.list_events()[0].facts.ai_policy is AiPolicy.AI_ASSISTED


def test_participant_count_change_does_not_duplicate_alert(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    event = Event(
        source="ctftime",
        source_id="4001",
        title="Stable CTF",
        official_url="https://ctf.example/",
        ctftime_url="https://ctftime.org/event/4001/",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
        participants=1,
    )
    source = FakeSource(event, EventFacts(team_max=4))
    service = SyncService(
        database=database,
        source=source,
        fetcher=FakeFetcher(),
        now=lambda: datetime(2026, 8, 14, 23, tzinfo=UTC),
    )

    service.run()
    source.event = event.model_copy(update={"participants": 2})
    second = service.run()

    assert second.queued == 0
    assert database.count_outbox() == 1
