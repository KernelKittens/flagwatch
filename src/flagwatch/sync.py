from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field

from flagwatch.analysis.evidence import EvidenceDocument
from flagwatch.analysis.facts import extract_event_facts
from flagwatch.analysis.llm import LlmPolicyResponse
from flagwatch.domain import AiPolicy, Event, EventFacts, SourceScanStatus
from flagwatch.fetching import FetchedPage, FetchError
from flagwatch.matching import match_event
from flagwatch.notifications import queue_alert
from flagwatch.rule_pages import discover_rule_links, discover_sitemap_rule_links, has_readable_body
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


@dataclass(frozen=True)
class SourceScan:
    documents: list[EvidenceDocument]
    failures: list[str]
    status: SourceScanStatus
    reason: str
    pages_checked: int
    rule_pages_found: int


MIN_READABLE_CHARACTERS = 40


class SyncService:
    def __init__(
        self,
        database: Database,
        source: EventSource,
        fetcher: PageFetcher,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        lookahead_days: int = 90,
        policy_extractor: PolicyExtractor | None = None,
        queue_notifications: bool = True,
    ) -> None:
        self.database = database
        self.source = source
        self.fetcher = fetcher
        self.now = now
        self.lookahead_days = lookahead_days
        self.policy_extractor = policy_extractor
        self.queue_notifications = queue_notifications

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

    def _documents_for(self, event: Event) -> SourceScan:
        failures: list[str] = []
        source_text = "\n\n".join(part for part in [event.description, event.prizes] if part)
        documents = [EvidenceDocument(str(event.ctftime_url), source_text)]
        try:
            homepage = self.fetcher.get_page(str(event.official_url))
        except (FetchError, httpx.HTTPError, OSError) as error:
            failures.append(f"{event.title}: {error}")
            return SourceScan(
                documents=documents,
                failures=failures,
                status=SourceScanStatus.FAILED,
                reason="Official site could not be reached",
                pages_checked=0,
                rule_pages_found=0,
            )
        documents.append(EvidenceDocument(homepage.url, homepage.text))
        rule_urls = discover_rule_links(homepage.url, homepage.html or "")

        try:
            sitemap = self.fetcher.get_page(urljoin(homepage.url, "/sitemap.xml"))
        except (FetchError, httpx.HTTPError, OSError):
            sitemap = None
        if sitemap is not None:
            for rule_url in discover_sitemap_rule_links(homepage.url, sitemap.text):
                if rule_url not in rule_urls:
                    rule_urls.append(rule_url)

        rule_pages_found = 0
        readable_rule_pages = 0
        for rule_url in rule_urls[:6]:
            if rule_url == homepage.url:
                continue
            try:
                rule_page = self.fetcher.get_page(rule_url)
            except (FetchError, httpx.HTTPError, OSError) as error:
                failures.append(f"{event.title}: {rule_url}: {error}")
                continue
            rule_pages_found += 1
            if len(rule_page.text.strip()) >= MIN_READABLE_CHARACTERS:
                readable_rule_pages += 1
            documents.append(EvidenceDocument(rule_page.url, rule_page.text))

        homepage_readable = len(homepage.text.strip()) >= MIN_READABLE_CHARACTERS and (
            homepage.html is None or has_readable_body(homepage.html, MIN_READABLE_CHARACTERS)
        )
        usable = homepage_readable or readable_rule_pages > 0
        status = SourceScanStatus.READ if usable and not failures else SourceScanStatus.LIMITED
        if not usable:
            reason = "Official site responded without readable rules content"
        elif failures:
            reason = "Some official source pages could not be read"
        elif rule_pages_found:
            suffix = "page" if rule_pages_found == 1 else "pages"
            reason = f"Official site and {rule_pages_found} rule {suffix} read"
        else:
            reason = "Official site read; no dedicated rules page found"
        return SourceScan(
            documents=documents,
            failures=failures,
            status=status,
            reason=reason,
            pages_checked=1 + rule_pages_found,
            rule_pages_found=rule_pages_found,
        )

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
                scan = self._documents_for(event)
                report.failures.extend(scan.failures)
                checked_at = self.now()
                if scan.status is SourceScanStatus.FAILED:
                    facts = (
                        previous.facts
                        if previous is not None
                        else extract_event_facts(scan.documents, seed)
                    )
                    facts = facts.model_copy(
                        update={
                            "analysis_stale": True,
                            "analysis_error": "; ".join(scan.failures)[:1000],
                            "source_scan_status": scan.status,
                            "source_scan_reason": scan.reason,
                            "source_pages_checked": scan.pages_checked,
                            "source_rule_pages_found": scan.rule_pages_found,
                            "source_checked_at": checked_at,
                        }
                    )
                else:
                    facts = extract_event_facts(scan.documents, seed)
                    facts = self._apply_model_policy(facts, scan.documents)
                    facts = facts.model_copy(
                        update={
                            "analyzed_at": checked_at,
                            "analysis_stale": scan.status is not SourceScanStatus.READ,
                            "analysis_error": (
                                "; ".join(scan.failures)[:1000] if scan.failures else None
                            ),
                            "source_scan_status": scan.status,
                            "source_scan_reason": scan.reason,
                            "source_pages_checked": scan.pages_checked,
                            "source_rule_pages_found": scan.rule_pages_found,
                            "source_checked_at": checked_at,
                        }
                    )
                self.database.save_facts(event.key, facts)
                report.analyzed += 1
                if self.queue_notifications:
                    match = match_event(event, facts, criteria)
                    if queue_alert(self.database, event, facts, match, criteria.version):
                        report.queued += 1
            except Exception as error:
                report.failures.append(f"{event.title}: {type(error).__name__}: {error}")
        return report
