from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from flagwatch.analysis.evidence import EvidenceDocument
from flagwatch.analysis.facts import extract_event_facts
from flagwatch.domain import Event, EventFacts
from flagwatch.fetching import FetchedPage, FetchError
from flagwatch.matching import match_event
from flagwatch.notifications import queue_alert
from flagwatch.rule_pages import discover_rule_links
from flagwatch.storage import Database


class EventSource(Protocol):
    def fetch_events(self, start: datetime, finish: datetime) -> list[tuple[Event, EventFacts]]: ...


class PageFetcher(Protocol):
    def get_page(self, url: str) -> FetchedPage: ...


class SyncReport(BaseModel):
    imported: int = 0
    analyzed: int = 0
    queued: int = 0
    failures: list[str] = Field(default_factory=list)


class SyncService:
    def __init__(
        self,
        database: Database,
        source: EventSource,
        fetcher: PageFetcher,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        lookahead_days: int = 90,
    ) -> None:
        self.database = database
        self.source = source
        self.fetcher = fetcher
        self.now = now
        self.lookahead_days = lookahead_days

    def _documents_for(self, event: Event, failures: list[str]) -> list[EvidenceDocument]:
        source_text = "\n\n".join(part for part in [event.description, event.prizes] if part)
        documents = [EvidenceDocument(str(event.ctftime_url), source_text)]
        try:
            homepage = self.fetcher.get_page(str(event.official_url))
        except (FetchError, httpx.HTTPError, OSError) as error:
            failures.append(f"{event.title}: {error}")
            return documents
        documents.append(EvidenceDocument(homepage.url, homepage.text))
        if homepage.html:
            for rule_url in discover_rule_links(homepage.url, homepage.html):
                try:
                    rule_page = self.fetcher.get_page(rule_url)
                except (FetchError, httpx.HTTPError, OSError) as error:
                    failures.append(f"{event.title}: {rule_url}: {error}")
                    continue
                documents.append(EvidenceDocument(rule_page.url, rule_page.text))
        return documents

    def run(self) -> SyncReport:
        report = SyncReport()
        start = self.now()
        finish = start + timedelta(days=self.lookahead_days)
        criteria = self.database.get_criteria()
        for event, seed in self.source.fetch_events(start, finish):
            self.database.upsert_event(event)
            report.imported += 1
            documents = self._documents_for(event, report.failures)
            facts = extract_event_facts(documents, seed)
            self.database.save_facts(event.key, facts)
            report.analyzed += 1
            match = match_event(event, facts, criteria)
            if queue_alert(self.database, event, facts, match, criteria.version):
                report.queued += 1
        return report
