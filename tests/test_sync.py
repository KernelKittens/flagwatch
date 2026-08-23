from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flagwatch.domain import AiPolicy, Event, EventFacts, SourceScanStatus
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


def test_non_ctftime_event_uses_primary_source_for_seed_evidence(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    event = Event(
        source="official-json",
        source_id="event-1",
        title="Official Feed CTF",
        official_url="https://ctf.example/",
        primary_source_url="https://feed.example/events.json",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
        description="Official event description",
    )
    service = SyncService(
        database=database,
        source=FakeSource(event, EventFacts()),
        fetcher=FakeFetcher(),
    )

    scan = service._documents_for(event)

    assert scan.documents[0].source_url == "https://feed.example/events.json"
    assert scan.documents[0].source_url != "None"


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


def test_model_intelligence_cannot_classify_unknown_policy_for_alerting(tmp_path):
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

    assert report.queued == 0
    assert report.unverified_policies == 1
    assert facts.ai_policy is AiPolicy.UNKNOWN
    assert facts.ai_policy_source is None
    assert facts.ai_policy_evidence is None


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
    assert any(failure == "Event bad: RuntimeError" for failure in report.failures)
    assert all("analysis crashed" not in failure for failure in report.failures)


def test_empty_javascript_shell_is_limited_not_successful(tmp_path):
    class ShellFetcher:
        def get_page(self, url: str) -> FetchedPage:
            if url.endswith("sitemap.xml"):
                return FetchedPage(url=url, text="not xml", html=None)
            return FetchedPage(
                url=url,
                text="BrunnerCTF 2026",
                html='<html><body><div id="app"></div></body></html>',
            )

    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    event = _event("shell")
    service = SyncService(database, FakeSource(event, EventFacts()), ShellFetcher())

    service.run()
    facts = database.list_events()[0].facts

    assert facts.source_scan_status is SourceScanStatus.LIMITED
    assert facts.analysis_stale is True
    assert facts.source_pages_checked == 1
    assert facts.source_rule_pages_found == 0


def test_sitemap_rule_page_is_discovered_and_analyzed(tmp_path):
    class SitemapFetcher:
        def get_page(self, url: str) -> FetchedPage:
            if url.endswith("sitemap.xml"):
                return FetchedPage(
                    url=url,
                    text=("<urlset><url><loc>https://ctf.example/rules</loc></url></urlset>"),
                    html=None,
                )
            if url.endswith("/rules"):
                return FetchedPage(
                    url=url,
                    text="Interactive AI assistance is allowed for every challenge.",
                    html=None,
                )
            return FetchedPage(
                url=url,
                text="A public online security competition with teams from around the world.",
                html="<html><body><main>Event home</main></body></html>",
            )

    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    event = _event("sitemap")
    service = SyncService(database, FakeSource(event, EventFacts()), SitemapFetcher())

    service.run()
    facts = database.list_events()[0].facts

    assert facts.ai_policy is AiPolicy.AI_ASSISTED
    assert facts.source_scan_status is SourceScanStatus.READ
    assert facts.analysis_stale is False
    assert facts.source_pages_checked == 2
    assert facts.source_rule_pages_found == 1


def test_optional_rule_failure_keeps_current_homepage_facts_but_fails_closed(tmp_path):
    class PartialFetcher:
        def get_page(self, url: str) -> FetchedPage:
            from flagwatch.fetching import FetchError

            if url.endswith("sitemap.xml"):
                return FetchedPage(url=url, text="not xml", html=None)
            if url.endswith("/rules"):
                raise FetchError("rules temporarily unavailable")
            return FetchedPage(
                url=url,
                text=(
                    "Interactive AI assistance is allowed for challenge solving. "
                    "Read the complete competition rules before playing."
                ),
                html='<html><body><a href="/rules">Rules</a></body></html>',
            )

    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    event = _event("partial")
    service = SyncService(database, FakeSource(event, EventFacts()), PartialFetcher())

    report = service.run()
    facts = database.list_events()[0].facts

    assert report.queued == 0
    assert facts.ai_policy is AiPolicy.AI_ASSISTED
    assert facts.source_scan_status is SourceScanStatus.LIMITED
    assert facts.analysis_stale is True
    assert "rules temporarily unavailable" in (facts.analysis_error or "")


def test_readable_homepage_does_not_download_script_assets(tmp_path):
    class ReadablePageFetcher:
        def get_page(self, url: str) -> FetchedPage:
            if url.endswith("sitemap.xml"):
                return FetchedPage(url=url, text="not xml", html=None)
            if url.endswith(".js"):
                raise AssertionError("readable pages must not download script assets")
            return FetchedPage(
                url=url,
                text=(
                    "This competition has readable public rules and event information. "
                    "Interactive AI assistance is allowed for challenge solving."
                ),
                html=(
                    '<html><head><script src="/assets/app.js"></script></head>'
                    "<body><main>This competition has readable public rules and event "
                    "information.</main></body></html>"
                ),
            )

    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    event = _event("readable-policy")
    service = SyncService(database, FakeSource(event, EventFacts()), ReadablePageFetcher())

    report = service.run()
    facts = database.list_events()[0].facts

    assert report.analyzed == 1
    assert report.verified_policies == 1
    assert facts.ai_policy is AiPolicy.AI_ASSISTED
    assert facts.source_pages_checked == 1


def test_spa_bundle_discovers_external_rules_and_verifies_no_ai_policy(tmp_path):
    class SpaPolicyFetcher:
        def get_page(self, url: str) -> FetchedPage:
            if url.endswith("sitemap.xml"):
                return FetchedPage(url=url, text="not xml", html=None)
            if url.endswith("/assets/app.js"):
                return FetchedPage(
                    url=url,
                    text=(
                        'const copy="We have a strict no-AI policy for the Danish competition.";'
                        'const rules="https://danmark.brunnerctf.dk/rules";'
                    ),
                    html=None,
                )
            if url == "https://danmark.brunnerctf.dk/rules":
                return FetchedPage(
                    url=url,
                    text=(
                        "The use of AI tools is strictly prohibited in the Danish competition. "
                        "AI tools are not allowed for challenge work."
                    ),
                    html="<html><body><main>Rules</main></body></html>",
                )
            return FetchedPage(
                url=url,
                text="BrunnerCTF 2026",
                html=(
                    '<html><head><script type="module" src="/assets/app.js"></script></head>'
                    '<body><div id="root"></div></body></html>'
                ),
            )

    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    event = _event("spa-policy")
    service = SyncService(database, FakeSource(event, EventFacts()), SpaPolicyFetcher())

    report = service.run()
    facts = database.list_events()[0].facts

    assert report.queued == 0
    assert report.verified_policies == 1
    assert report.unverified_policies == 0
    assert facts.ai_policy is AiPolicy.HUMAN_ONLY
    assert facts.ai_policy_source == "https://danmark.brunnerctf.dk/rules"
    assert facts.source_scan_status is SourceScanStatus.READ
    assert facts.analysis_stale is False
    assert facts.source_pages_checked == 3
    assert facts.source_rule_pages_found == 1


def _event(source_id: str) -> Event:
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    return Event(
        source="ctftime",
        source_id=source_id,
        title=f"{source_id.title()} CTF",
        official_url="https://ctf.example/",
        ctftime_url=f"https://ctftime.org/event/{source_id}/",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
    )
