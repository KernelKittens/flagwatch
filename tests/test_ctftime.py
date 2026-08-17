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


def test_normalizes_ctftime_html_prizes_to_readable_text(gaslight_payload):
    gaslight_payload["prizes"] = (
        "<b>NOTE:</b> prizes require the separate scoreboard.<br>"
        "<b>1st place</b><br>3,000 DKK gift card<script>ignore()</script>"
    )

    event, seed = normalize_ctftime_event(gaslight_payload)

    assert event.prizes == (
        "NOTE:\nprizes require the separate scoreboard.\n1st place\n3,000 DKK gift card"
    )
    assert seed.prize_summary == event.prizes
    assert "<b>" not in event.prizes
    assert "ignore" not in event.prizes


def test_source_uses_bounded_official_events_endpoint(gaslight_payload):
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json=[gaslight_payload])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = CtftimeSource(client=client)
    start = datetime(2026, 8, 14, tzinfo=UTC)

    batch = source.fetch_events(start, start + timedelta(days=90))

    assert len(batch.events) == 1
    assert batch.failures == []
    assert requested[0].url.path == "/api/v1/events/"
    assert requested[0].url.params["limit"] == "100"
    assert requested[0].headers["user-agent"].startswith("Flagwatch/")


def test_source_skips_malformed_record_and_keeps_valid_event(gaslight_payload):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 999}, gaslight_payload])

    source = CtftimeSource(client=httpx.Client(transport=httpx.MockTransport(handler)))
    start = datetime(2026, 8, 14, tzinfo=UTC)

    batch = source.fetch_events(start, start + timedelta(days=90))

    assert [event.source_id for event, _facts in batch.events] == ["3181"]
    assert len(batch.failures) == 1
    assert "record 1" in batch.failures[0]
