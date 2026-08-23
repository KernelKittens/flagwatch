from __future__ import annotations

from datetime import UTC, datetime

import httpx
from pydantic import HttpUrl

from flagwatch.domain import Event
from flagwatch.sources.ctfd import CtfdSource
from flagwatch.sources.rctf import RctfSource


def public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


def event_template() -> Event:
    return Event(
        source="seed",
        source_id="kitten-ctf-2026",
        title="Kitten CTF 2026",
        official_url=HttpUrl("https://ctf.example/"),
        starts_at=datetime(2026, 8, 29, 12, tzinfo=UTC),
        finishes_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        online=True,
        organizers=["Kernel Kittens"],
    )


def test_ctfd_enrichment_reads_public_challenges_and_scoreboard() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/challenges"):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "success": True,
                    "data": [
                        {"id": 1, "name": "Warmup", "category": "pwn", "solves": 12},
                        {"id": 2, "name": "Web", "category": "web", "solves": 5},
                    ],
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"success": True, "data": [{"pos": 1}, {"pos": 2}, {"pos": 3}]},
        )

    source = CtfdSource(
        base_url="https://ctf.example/",
        event=event_template(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        token="private-token",
        resolver=public_resolver,
        now=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    batch = source.fetch_events(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert batch.failures == []
    event, _facts = batch.events[0]
    assert event.platform == "CTFd"
    assert event.analytics.challenges_total == 2
    assert event.analytics.visible_solves == 17
    assert event.analytics.scoreboard_entries == 3
    assert event.analytics.participants_total == 3
    assert event.analytics.categories == {"pwn": 1, "web": 1}
    assert [request.url.path for request in requests] == [
        "/api/v1/challenges",
        "/api/v1/scoreboard",
    ]
    assert all(request.headers["authorization"] == "Token private-token" for request in requests)


def test_ctfd_keeps_challenge_counts_when_scoreboard_is_private() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/challenges"):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "success": True,
                    "data": [{"id": 1, "name": "Warmup", "category": "misc", "solves": 2}],
                },
            )
        return httpx.Response(
            403,
            headers={"content-type": "application/json"},
            json={"secret": "no"},
        )

    source = CtfdSource(
        base_url="https://ctf.example/",
        event=event_template(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        token="private-token",
        resolver=public_resolver,
    )

    batch = source.fetch_events(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert batch.events[0][0].analytics.challenges_total == 1
    assert len(batch.failures) == 1
    assert "private-token" not in batch.failures[0]
    assert "secret" not in batch.failures[0]


def test_rctf_enrichment_uses_v2_challenges_and_leaderboard() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/challs"):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "kind": "goodChallengesV2",
                    "data": [
                        {"id": "a", "name": "rev", "category": "rev", "solves": 9},
                        {"id": "b", "name": "pwn", "category": "pwn", "solves": 4},
                    ],
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "kind": "goodLeaderboardV2",
                "data": {"total": 42, "leaderboard": [{"id": "one"}]},
            },
        )

    source = RctfSource(
        base_url="https://rctf.example/",
        event=event_template(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        token="rctf-token",
        resolver=public_resolver,
        now=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    batch = source.fetch_events(
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert batch.failures == []
    event, _facts = batch.events[0]
    assert event.platform == "rCTF"
    assert event.analytics.challenges_total == 2
    assert event.analytics.visible_solves == 13
    assert event.analytics.scoreboard_entries == 1
    assert event.analytics.participants_total == 42
    assert event.analytics.categories == {"pwn": 1, "rev": 1}
    assert [request.url.path for request in requests] == [
        "/api/v2/challs",
        "/api/v2/leaderboard/now",
    ]
    assert dict(requests[1].url.params) == {"limit": "1", "offset": "0"}
    assert all(request.headers["authorization"] == "Bearer rctf-token" for request in requests)
