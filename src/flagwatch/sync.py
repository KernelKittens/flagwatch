from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field

from flagwatch.analysis.evidence import EvidenceDocument
from flagwatch.analysis.facts import extract_event_facts
from flagwatch.analysis.llm import LlmPolicyResponse, normalize_model_text
from flagwatch.domain import AiPolicy, Event, EventFacts, IntelClaim, SourceScanStatus
from flagwatch.fetching import FetchedPage, FetchError
from flagwatch.matching import match_event
from flagwatch.notifications import queue_alert
from flagwatch.rule_pages import (
    discover_embedded_rule_links,
    discover_rule_links,
    discover_script_links,
    discover_sitemap_rule_links,
    extract_javascript_evidence,
    has_readable_body,
)
from flagwatch.sources import EventBatch
from flagwatch.storage import Database


class EventSource(Protocol):
    def fetch_events(self, start: datetime, finish: datetime) -> EventBatch: ...


class PageFetcher(Protocol):
    def get_page(self, url: str) -> FetchedPage: ...


class PolicyExtractor(Protocol):
    model: str

    def try_extract(self, documents: Sequence[EvidenceDocument]) -> LlmPolicyResponse | None: ...


class SyncReport(BaseModel):
    imported: int = 0
    analyzed: int = 0
    queued: int = 0
    failures: list[str] = Field(default_factory=list)
    verified_policies: int = 0
    unverified_policies: int = 0


@dataclass(frozen=True)
class SourceScan:
    documents: list[EvidenceDocument]
    failures: list[str]
    status: SourceScanStatus
    reason: str
    pages_checked: int
    rule_pages_found: int


MIN_READABLE_CHARACTERS = 40


def _normalized_text(value: str) -> str:
    return " ".join(normalize_model_text(value).split()).casefold()


def _source_fingerprint(documents: Sequence[EvidenceDocument]) -> str:
    digest = hashlib.sha256()
    for document in documents:
        digest.update(document.source_url.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_normalized_text(document.text).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _matching_source(
    documents: Sequence[EvidenceDocument],
    source_url: str,
    evidence: str,
) -> str | None:
    normalized_evidence = _normalized_text(evidence)
    if not normalized_evidence:
        return None
    requested_url = source_url.rstrip("/")
    for document in documents:
        if document.source_url.rstrip("/") != requested_url:
            continue
        if normalized_evidence in _normalized_text(document.text):
            return document.source_url
    return None


class SyncService:
    def __init__(
        self,
        database: Database,
        source: EventSource,
        fetcher: PageFetcher,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        lookahead_days: int = 90,
        lookback_days: int = 31,
        policy_extractor: PolicyExtractor | None = None,
        queue_notifications: bool = True,
    ) -> None:
        self.database = database
        self.source = source
        self.fetcher = fetcher
        self.now = now
        self.lookahead_days = lookahead_days
        self.lookback_days = lookback_days
        self.policy_extractor = policy_extractor
        self.queue_notifications = queue_notifications

    def _validated_claims(
        self,
        claims: Sequence[IntelClaim],
        documents: Sequence[EvidenceDocument],
    ) -> list[IntelClaim]:
        validated: list[IntelClaim] = []
        seen: set[tuple[str, str, str]] = set()
        for claim in claims:
            source = _matching_source(documents, str(claim.source_url), claim.evidence)
            if source is None:
                continue
            key = (claim.topic.value, claim.label.casefold(), claim.value.casefold())
            if key in seen:
                continue
            seen.add(key)
            validated.append(
                claim.model_copy(
                    update={
                        "label": normalize_model_text(claim.label),
                        "value": normalize_model_text(claim.value),
                        "evidence": normalize_model_text(claim.evidence),
                    }
                )
            )
        return validated

    def _reuse_cached_analysis(self, facts: EventFacts, previous: EventFacts) -> EventFacts:
        updates: dict[str, object] = {
            "intel_claims": previous.intel_claims,
            "intel_source_fingerprint": previous.intel_source_fingerprint,
            "intel_model": previous.intel_model,
            "intel_analyzed_at": previous.intel_analyzed_at,
            "intel_stale": False,
        }
        return facts.model_copy(update=updates)

    def _preserve_previous_intel(
        self, facts: EventFacts, previous: EventFacts | None
    ) -> EventFacts:
        if previous is None or not previous.intel_claims:
            return facts
        return facts.model_copy(
            update={
                "intel_claims": previous.intel_claims,
                "intel_source_fingerprint": previous.intel_source_fingerprint,
                "intel_model": previous.intel_model,
                "intel_analyzed_at": previous.intel_analyzed_at,
                "intel_stale": True,
            }
        )

    def _apply_model_analysis(
        self,
        facts: EventFacts,
        documents: Sequence[EvidenceDocument],
        previous: EventFacts | None,
    ) -> EventFacts:
        fingerprint = _source_fingerprint(documents)
        if (
            previous is not None
            and previous.intel_source_fingerprint == fingerprint
            and previous.intel_analyzed_at is not None
        ):
            return self._reuse_cached_analysis(facts, previous)
        if self.policy_extractor is None:
            return self._preserve_previous_intel(facts, previous)
        result = self.policy_extractor.try_extract(documents)
        if result is None:
            return self._preserve_previous_intel(facts, previous)

        updates: dict[str, object] = {
            "intel_claims": self._validated_claims(getattr(result, "claims", []), documents),
            "intel_source_fingerprint": fingerprint,
            "intel_model": getattr(
                self.policy_extractor, "model", type(self.policy_extractor).__name__
            ),
            "intel_analyzed_at": self.now(),
            "intel_stale": False,
        }
        return facts.model_copy(update=updates)

    def _documents_for(self, event: Event) -> SourceScan:
        failures: list[str] = []
        source_text = "\n\n".join(part for part in [event.description, event.prizes] if part)
        source_url = event.primary_source_url or event.official_url
        documents = [EvidenceDocument(str(source_url), source_text)]
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
        homepage_readable = len(homepage.text.strip()) >= MIN_READABLE_CHARACTERS and (
            homepage.html is None or has_readable_body(homepage.html, MIN_READABLE_CHARACTERS)
        )
        rule_urls = discover_rule_links(
            homepage.url,
            homepage.html or "",
            allow_cross_origin=True,
        )
        script_documents: list[EvidenceDocument] = []
        script_pages_read = 0
        script_urls = (
            [] if homepage_readable else discover_script_links(homepage.url, homepage.html or "")
        )
        for script_url in script_urls:
            try:
                script_page = self.fetcher.get_page(script_url)
            except (FetchError, httpx.HTTPError, OSError) as error:
                failures.append(f"{event.title}: {script_url}: {error}")
                continue
            script_pages_read += 1
            script_evidence = extract_javascript_evidence(script_page.text)
            if script_evidence:
                script_documents.append(EvidenceDocument(script_page.url, script_evidence))
            for rule_url in discover_embedded_rule_links(homepage.url, script_page.text):
                if rule_url not in rule_urls:
                    rule_urls.append(rule_url)

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
        documents.extend(script_documents)

        usable = homepage_readable or readable_rule_pages > 0 or bool(script_documents)
        status = SourceScanStatus.READ if usable and not failures else SourceScanStatus.LIMITED
        if not usable:
            reason = "Official site responded without readable rules content"
        elif failures:
            reason = "Some official source pages could not be read"
        elif rule_pages_found:
            suffix = "page" if rule_pages_found == 1 else "pages"
            reason = f"Official site and {rule_pages_found} rule {suffix} read"
        elif script_documents:
            reason = "Official site and static policy evidence read"
        else:
            reason = "Official site read; no dedicated rules page found"
        return SourceScan(
            documents=documents,
            failures=failures,
            status=status,
            reason=reason,
            pages_checked=1 + script_pages_read + rule_pages_found,
            rule_pages_found=rule_pages_found,
        )

    def run(self) -> SyncReport:
        report = SyncReport()
        current = self.now()
        start = current - timedelta(days=self.lookback_days)
        finish = current + timedelta(days=self.lookahead_days)
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
                            "intel_stale": bool(facts.intel_claims),
                            "source_scan_status": scan.status,
                            "source_scan_reason": scan.reason,
                            "source_pages_checked": scan.pages_checked,
                            "source_rule_pages_found": scan.rule_pages_found,
                            "source_checked_at": checked_at,
                        }
                    )
                else:
                    facts = extract_event_facts(scan.documents, seed)
                    facts = self._apply_model_analysis(
                        facts,
                        scan.documents,
                        previous.facts if previous is not None else None,
                    )
                    facts = facts.model_copy(
                        update={
                            "analyzed_at": checked_at,
                            "analysis_stale": scan.status is not SourceScanStatus.READ,
                            "analysis_error": (
                                "; ".join(scan.failures)[:1000] if scan.failures else None
                            ),
                            "intel_stale": facts.intel_stale
                            or scan.status is not SourceScanStatus.READ,
                            "source_scan_status": scan.status,
                            "source_scan_reason": scan.reason,
                            "source_pages_checked": scan.pages_checked,
                            "source_rule_pages_found": scan.rule_pages_found,
                            "source_checked_at": checked_at,
                        }
                    )
                self.database.save_facts(event.key, facts)
                report.analyzed += 1
                if (
                    facts.ai_policy is not AiPolicy.UNKNOWN
                    and not facts.ai_policy_conflicting
                    and not facts.analysis_stale
                ):
                    report.verified_policies += 1
                else:
                    report.unverified_policies += 1
                if self.queue_notifications:
                    match = match_event(event, facts, criteria)
                    if queue_alert(self.database, event, facts, match, criteria.version):
                        report.queued += 1
            except Exception as error:
                report.failures.append(f"{event.title}: {type(error).__name__}")
        return report
