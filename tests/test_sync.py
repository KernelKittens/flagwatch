from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flagwatch.domain import AiPolicy, Event, EventFacts
from flagwatch.fetching import FetchedPage
from flagwatch.sources import EventBatch
from flagwatch.storage import Database
from flagwatch.sync import SyncService


class FakeSource:
    def __init__(self, event: Event, seed: EventFacts) -> None:
        self.event = event
        self.seed = seed

    def fetch_events(self, _start: datetime, _finish: datetime):
        return EventBatch(events=[(self.event, self.seed)])


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


class UnknownPolicyFetcher:
    def get_page(self, url: str) -> FetchedPage:
        return FetchedPage(
            url=url,
            text="You are welcome to consult an AI assistant while solving challenges.",
            html=None,
        )


class FailingFetcher:
    def get_page(self, _url: str) -> FetchedPage:
        from flagwatch.fetching import FetchError

        raise FetchError("temporary outage")


class FakePolicyResponse:
    policy = AiPolicy.AI_ASSISTED
    reason = "Interactive AI help is allowed."
    evidence = "You are welcome to consult an AI assistant while solving challenges."
    confidence = 0.92


class FakePolicyExtractor:
    def __init__(self, evidence: str | None = None) -> None:
        self.evidence = evidence

    def try_extract(self, _documents):
        result = FakePolicyResponse()
        if self.evidence is not None:
            result.evidence = self.evidence
        return result


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


def test_model_fallback_can_classify_unknown_policy_with_source_evidence(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    event = Event(
        source="ctftime",
        source_id="4002",
        title="Evidence CTF",
        official_url="https://ctf.example/",
        ctftime_url="https://ctftime.org/event/4002/",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
    )
    service = SyncService(
        database=database,
        source=FakeSource(event, EventFacts()),
        fetcher=UnknownPolicyFetcher(),
        policy_extractor=FakePolicyExtractor(),
    )

    report = service.run()
    facts = database.list_events()[0].facts

    assert report.queued == 1
    assert facts.ai_policy is AiPolicy.AI_ASSISTED
    assert facts.ai_policy_source == "https://ctf.example/"
    assert facts.ai_policy_evidence == FakePolicyResponse.evidence


def test_model_fallback_cannot_approve_hallucinated_evidence(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    event = Event(
        source="ctftime",
        source_id="4003",
        title="Unverified CTF",
        official_url="https://ctf.example/",
        ctftime_url="https://ctftime.org/event/4003/",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
    )
    service = SyncService(
        database=database,
        source=FakeSource(event, EventFacts()),
        fetcher=UnknownPolicyFetcher(),
        policy_extractor=FakePolicyExtractor("AI is definitely allowed."),
    )

    report = service.run()

    assert report.queued == 0
    assert database.list_events()[0].facts.ai_policy is AiPolicy.UNKNOWN


def test_fetch_failure_preserves_last_known_evidence_as_stale(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    event = Event(
        source="ctftime",
        source_id="4004",
        title="Stale Evidence CTF",
        official_url="https://ctf.example/",
        ctftime_url="https://ctftime.org/event/4004/",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
    )
    known = EventFacts(
        ai_policy=AiPolicy.AI_ASSISTED,
        ai_policy_reason="Interactive AI is allowed.",
        ai_policy_source="https://ctf.example/rules",
        ai_policy_evidence="Interactive AI assistance is allowed.",
    )
    database.upsert_event(event)
    database.save_facts(event.key, known)
    service = SyncService(
        database=database,
        source=FakeSource(event, EventFacts()),
        fetcher=FailingFetcher(),
    )

    report = service.run()
    facts = database.list_events()[0].facts

    assert report.queued == 0
    assert facts.ai_policy is AiPolicy.AI_ASSISTED
    assert facts.ai_policy_evidence == known.ai_policy_evidence
    assert facts.analysis_stale is True
    assert "temporary outage" in (facts.analysis_error or "")


def test_one_event_analysis_failure_does_not_block_later_events(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)

    def event(source_id: str) -> Event:
        return Event(
            source="ctftime",
            source_id=source_id,
            title=f"Event {source_id}",
            official_url="https://ctf.example/",
            ctftime_url=f"https://ctftime.org/event/{source_id}/",
            starts_at=start,
            finishes_at=start + timedelta(hours=24),
            online=True,
        )

    class TwoEventSource:
        def fetch_events(self, _start, _finish):
            return EventBatch(events=[(event("bad"), EventFacts()), (event("good"), EventFacts())])

    class FailOnceExtractor(FakePolicyExtractor):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def try_extract(self, documents):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("analysis crashed")
            return super().try_extract(documents)

    service = SyncService(
        database=database,
        source=TwoEventSource(),
        fetcher=UnknownPolicyFetcher(),
        policy_extractor=FailOnceExtractor(),
    )

    report = service.run()

    assert report.imported == 2
    assert report.analyzed == 1
    assert len(database.list_events()) == 2
    assert any(
        "Event bad" in failure and "analysis crashed" in failure for failure in report.failures
    )
