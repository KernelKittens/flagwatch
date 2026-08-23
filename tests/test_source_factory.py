from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from flagwatch.config import Settings
from flagwatch.fetching import GuardedFetcher
from flagwatch.sources.composite import CompositeSource
from flagwatch.sources.factory import build_event_source, load_source_definitions

SOURCE_DOCUMENT = {
    "sources": [
        {
            "kind": "ics",
            "name": "community-calendar",
            "url": "https://events.example/calendar.ics",
        },
        {
            "kind": "json",
            "name": "organizer-json",
            "url": "https://events.example/events.json",
        },
        {
            "kind": "watch",
            "name": "organizer-watch",
            "url": "https://events.example/calendar",
            "organizers": ["Example Org"],
            "max_event_pages": 4,
        },
        {
            "kind": "ctfd",
            "name": "kitten-platform",
            "base_url": "https://ctf.example/",
            "token_env": "KITTEN_CTFD_TOKEN",
            "event": {
                "id": "kitten-ctf-2026",
                "title": "Kitten CTF 2026",
                "official_url": "https://ctf.example/",
                "starts_at": "2026-08-29T12:00:00Z",
                "finishes_at": "2026-08-30T12:00:00Z",
                "online": True,
                "organizers": ["Kernel Kittens"],
            },
        },
        {
            "kind": "rctf",
            "name": "other-platform",
            "base_url": "https://rctf.example/",
            "event": {
                "id": "other-ctf-2026",
                "title": "Other CTF 2026",
                "official_url": "https://rctf.example/",
                "starts_at": "2026-08-30T12:00:00Z",
                "finishes_at": "2026-08-31T12:00:00Z",
                "online": True,
                "organizers": ["Other Org"],
            },
        },
    ]
}


def public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


def test_loads_all_documented_source_definitions() -> None:
    definitions = load_source_definitions(json.dumps(SOURCE_DOCUMENT), None)

    assert [definition.kind for definition in definitions] == [
        "ics",
        "json",
        "watch",
        "ctfd",
        "rctf",
    ]
    assert definitions[3].event.starts_at == datetime(2026, 8, 29, 12, tzinfo=UTC)


def test_source_config_rejects_inline_tokens() -> None:
    document = {
        "sources": [
            {
                "kind": "ctfd",
                "name": "bad",
                "base_url": "https://ctf.example/",
                "token": "must-not-be-here",
                "event": SOURCE_DOCUMENT["sources"][3]["event"],
            }
        ]
    }

    try:
        load_source_definitions(json.dumps(document), None)
    except ValueError as error:
        assert "token" in str(error)
    else:
        raise AssertionError("Inline source tokens must be rejected")


def test_factory_builds_composite_and_resolves_token_by_environment_name() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/challenges"):
            return httpx.Response(200, json={"success": True, "data": []})
        if request.url.path.endswith("/scoreboard"):
            return httpx.Response(200, json={"success": True, "data": []})
        if request.url.path.endswith("/challs"):
            return httpx.Response(200, json={"kind": "goodChallengesV2", "data": []})
        if request.url.path.endswith("/leaderboard/now"):
            return httpx.Response(
                200,
                json={
                    "kind": "goodLeaderboardV2",
                    "data": {"total": 0, "leaderboard": []},
                },
            )
        if request.url.path.endswith(".ics"):
            return httpx.Response(
                200,
                headers={"content-type": "text/calendar"},
                text="BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR",
            )
        return httpx.Response(200, json={"events": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = Settings(
        ctftime_enabled=False,
        sources_json=json.dumps(SOURCE_DOCUMENT),
    )
    source = build_event_source(
        settings,
        source_client=client,
        fetcher=GuardedFetcher(client=client, resolver=public_resolver),
        environ={"KITTEN_CTFD_TOKEN": "env-only-secret"},
        resolver=public_resolver,
    )

    assert isinstance(source, CompositeSource)
    assert [item.source_name for item in source.sources] == [
        "community-calendar",
        "organizer-json",
        "organizer-watch",
        "kitten-platform",
        "other-platform",
    ]
    assert [item.precedence for item in source.sources] == [40, 45, 10, 20, 20]

    batch = source.fetch_events(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert len(batch.events) == 2
    ctfd_requests = [request for request in requests if request.url.host == "ctf.example"]
    assert ctfd_requests
    assert all(
        request.headers["authorization"] == "Token env-only-secret" for request in ctfd_requests
    )


def test_factory_keeps_ctftime_optional_and_backward_compatible() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[]))
    )
    fetcher = GuardedFetcher(client=client, resolver=public_resolver)

    enabled = build_event_source(Settings(ctftime_enabled=True), client, fetcher)
    disabled = build_event_source(Settings(ctftime_enabled=False), client, fetcher)

    assert [source.source_name for source in enabled.sources] == ["ctftime"]
    assert [source.precedence for source in enabled.sources] == [100]
    assert disabled.sources == []
