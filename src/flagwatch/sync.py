from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from flagwatch.analysis.evidence import EvidenceDocument
from flagwatch.analysis.facts import extract_event_facts
from flagwatch.analysis.llm import LlmPolicyResponse
from flagwatch.domain import AiPolicy, Event, EventFacts
from flagwatch.fetching import FetchedPage, FetchError
from flagwatch.matching import match_event
from flagwatch.notifications import queue_alert
from flagwatch.rule_pages import discover_rule_links
from flagwatch.sources import EventBatch
from flagwatch.storage import Database


class EventSource(Protocol):
    def fetch_events(self, start: datetime, finish: datetime) -> EventBatch: ...


class PageFetcher(Protocol):
    def get_page(self, url: str) -> FetchedPage: ...


class PolicyExtractor(Protocol):
    def try_extract(self, documents: Sequence[EvidenceDocument]) -> LlmPolicyResponse | None: ...


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
        policy_extractor: PolicyExtractor | None = None,
    ) -> None:
        self.database = database
        self.source = source
        self.fetcher = fetcher
        self.now = now
        self.lookahead_days = lookahead_days
        self.policy_extractor = policy_extractor

    def _apply_model_policy(
        self,
        facts: EventFacts,
        documents: Sequence[EvidenceDocument],
    ) -> EventFacts:
        if (
            self.policy_extractor is None
            or facts.ai_policy is not AiPolicy.UNKNOWN
            or facts.ai_policy_conflicting
        ):
            return facts
        result = self.policy_extractor.try_extract(documents)
        if result is None:
            return facts
        evidence = " ".join(result.evidence.split()).casefold()
        source = next(
            (
                document.source_url
                for document in documents
                if evidence in " ".join(document.text.split()).casefold()
            ),
            None,
        )
        if source is None:
            return facts
        return facts.model_copy(
            update={
                "ai_policy": result.policy,
                "ai_policy_reason": result.reason,
                "ai_policy_source": source,
                "ai_policy_evidence": result.evidence,
                "ai_policy_confidence": result.confidence,
            }
        )

    def _documents_for(self, event: Event) -> tuple[list[EvidenceDocument], list[str]]:
        failures: list[str] = []
        source_text = "\n\n".join(part for part in [event.description, event.prizes] if part)
        documents = [EvidenceDocument(str(event.ctftime_url), source_text)]
        try:
            homepage = self.fetcher.get_page(str(event.official_url))
        except (FetchError, httpx.HTTPError, OSError) as error:
            failures.append(f"{event.title}: {error}")
            return documents, failures
        documents.append(EvidenceDocument(homepage.url, homepage.text))
        if homepage.html:
            for rule_url in discover_rule_links(homepage.url, homepage.html):
                try:
                    rule_page = self.fetcher.get_page(rule_url)
                except (FetchError, httpx.HTTPError, OSError) as error:
                    failures.append(f"{event.title}: {rule_url}: {error}")
                    continue
                documents.append(EvidenceDocument(rule_page.url, rule_page.text))
        return documents, failures

    def run(self) -> SyncReport:
        report = SyncReport()
        start = self.now()
        finish = start + timedelta(days=self.lookahead_days)
        criteria = self.database.get_criteria()
        batch = self.source.fetch_events(start, finish)
        report.failures.extend(batch.failures)
        for event, seed in batch.events:
            try:
                previous = self.database.get_event(event.key)
                self.database.upsert_event(event)
                report.imported += 1
                documents, fetch_failures = self._documents_for(event)
                report.failures.extend(fetch_failures)
                if fetch_failures:
                    facts = (
                        previous.facts
                        if previous is not None
                        else extract_event_facts(documents, seed)
                    )
                    facts = facts.model_copy(
                        update={
                            "analysis_stale": True,
                            "analysis_error": "; ".join(fetch_failures)[:1000],
                        }
                    )
                else:
                    facts = extract_event_facts(documents, seed)
                    facts = self._apply_model_policy(facts, documents)
                    facts = facts.model_copy(
                        update={
                            "analyzed_at": self.now(),
                            "analysis_stale": False,
                            "analysis_error": None,
                        }
                    )
                self.database.save_facts(event.key, facts)
                report.analyzed += 1
                match = match_event(event, facts, criteria)
                if queue_alert(self.database, event, facts, match, criteria.version):
                    report.queued += 1
            except Exception as error:
                report.failures.append(f"{event.title}: {type(error).__name__}: {error}")
        return report
