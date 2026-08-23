from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from flagwatch.fetching import FetchedPage
from flagwatch.sources.feeds import IcsFeedSource, JsonFeedSource


class StaticFetcher:
    def __init__(self, page: FetchedPage) -> None:
        self.page = page
        self.requested: list[str] = []

    def get_page(self, url: str) -> FetchedPage:
        self.requested.append(url)
        return self.page


class ErrorFetcher:
    def get_page(self, url: str) -> FetchedPage:
        request = httpx.Request("GET", url)
        raise httpx.ConnectError("upstream unavailable", request=request)


def test_ics_feed_normalizes_events_with_provenance() -> None:
    body = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//KernelKittens//Flagwatch tests//EN
BEGIN:VEVENT
UID:kitten-ctf-2026
DTSTART:20260829T120000Z
DTEND:20260830T120000Z
SUMMARY:Kitten CTF 2026
DESCRIPTION:Jeopardy CTF with open registration.
LOCATION:Online
URL:https://ctf.example/events/kitten-ctf
ORGANIZER;CN=Kernel Kittens:mailto:events@example.com
END:VEVENT
END:VCALENDAR
"""
    fetcher = StaticFetcher(
        FetchedPage(
            url="https://events.example/calendar.ics",
            text=body,
            html=None,
        )
    )
    source = IcsFeedSource(
        url="https://events.example/calendar.ics",
        fetcher=fetcher,
        name="official-ics",
        now=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    batch = source.fetch_events(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert batch.failures == []
    event, _facts = batch.events[0]
    assert event.source_id == "kitten-ctf-2026"
    assert event.title == "Kitten CTF 2026"
    assert event.online is True
    assert event.onsite is False
    assert event.organizers == ["Kernel Kittens"]
    assert str(event.official_url) == "https://ctf.example/events/kitten-ctf"
    assert str(event.source_refs[0].url) == "https://events.example/calendar.ics"
    assert event.source_refs[0].record_id == "kitten-ctf-2026"


def test_ics_feed_keeps_valid_events_when_one_record_is_malformed() -> None:
    body = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:bad
SUMMARY:Missing dates
END:VEVENT
BEGIN:VEVENT
UID:good
DTSTART:20260829T120000Z
DTEND:20260829T180000Z
SUMMARY:Valid CTF
URL:https://ctf.example/valid
END:VEVENT
END:VCALENDAR
"""
    source = IcsFeedSource(
        url="https://events.example/calendar.ics",
        fetcher=StaticFetcher(
            FetchedPage(url="https://events.example/calendar.ics", text=body, html=None)
        ),
        name="official-ics",
    )

    batch = source.fetch_events(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert [event.source_id for event, _facts in batch.events] == ["good"]
    assert len(batch.failures) == 1
    assert "record 1" in batch.failures[0]


def test_json_feed_accepts_documented_white_label_schema() -> None:
    payload = {
        "events": [
            {
                "id": "json-1",
                "title": "JSON CTF",
                "start": "2026-08-26T18:00:00Z",
                "finish": "2026-08-27T18:00:00Z",
                "url": "https://json.example/ctf",
                "registration_url": "https://json.example/register",
                "description": "Online jeopardy CTF",
                "online": True,
                "organizers": ["JSON Org"],
                "format": "Jeopardy",
            }
        ]
    }
    fetcher = StaticFetcher(
        FetchedPage(
            url="https://events.example/events.json",
            text=json.dumps(payload),
            html=None,
        )
    )
    source = JsonFeedSource(
        url="https://events.example/events.json",
        fetcher=fetcher,
        name="official-json",
        now=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    batch = source.fetch_events(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert batch.failures == []
    event, facts = batch.events[0]
    assert event.source == "official-json"
    assert event.registration_url is not None
    assert event.organizers == ["JSON Org"]
    assert event.source_refs[0].source == "official-json"
    assert facts.schedule_mode.value == "fixed"


def test_json_feed_rejects_non_event_shapes_without_leaking_body() -> None:
    source = JsonFeedSource(
        url="https://events.example/events.json",
        fetcher=StaticFetcher(
            FetchedPage(
                url="https://events.example/events.json",
                text='{"secret":"do-not-copy"}',
                html=None,
            )
        ),
        name="official-json",
    )

    batch = source.fetch_events(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert batch.events == []
    assert len(batch.failures) == 1
    assert "do-not-copy" not in batch.failures[0]


def test_feed_reports_network_failure_without_raising() -> None:
    source = JsonFeedSource(
        url="https://events.example/events.json",
        fetcher=ErrorFetcher(),
        name="official-json",
    )

    batch = source.fetch_events(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert batch.events == []
    assert batch.failures == ["official-json: ConnectError: feed unavailable"]
