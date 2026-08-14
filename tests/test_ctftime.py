from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from flagwatch.sources.ctftime import CtftimeSource, normalize_ctftime_event


def test_normalizes_ctftime_event_and_description_facts(gaslight_payload):
    event, seed = normalize_ctftime_event(gaslight_payload)

    assert event.source_id == "3181"
    assert event.online is True
    assert event.starts_at == datetime(2026, 8, 14, 12, tzinfo=UTC)
    assert seed.team_max == 5
    assert seed.divisions == ["Secondary School", "University", "Open"]
    assert seed.prize_summary == "Open Division: 1st: $100"


def test_source_uses_bounded_official_events_endpoint(gaslight_payload):
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json=[gaslight_payload])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = CtftimeSource(client=client)
    start = datetime(2026, 8, 14, tzinfo=UTC)

    events = source.fetch_events(start, start + timedelta(days=90))

    assert len(events) == 1
    assert requested[0].url.path == "/api/v1/events/"
    assert requested[0].url.params["limit"] == "100"
    assert requested[0].headers["user-agent"].startswith("Flagwatch/")
