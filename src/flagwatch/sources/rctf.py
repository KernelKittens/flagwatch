from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import HttpUrl

from flagwatch.domain import Event, EventAnalytics, EventFacts, SourceKind, SourceRef
from flagwatch.fetching import FetchError, Resolver, resolve_public_addresses
from flagwatch.sources import EventBatch
from flagwatch.sources.http import ApiError, GuardedJsonClient


def _rctf_data(payload: Any) -> object:
    if not isinstance(payload, dict) or not str(payload.get("kind") or "").startswith("good"):
        raise ValueError("rCTF returned an unsuccessful response")
    if "data" not in payload:
        raise ValueError("rCTF returned an unexpected data shape")
    return payload["data"]


class RctfSource:
    source_name = "rctf"
    precedence = 85

    def __init__(
        self,
        base_url: str,
        event: Event,
        client: httpx.Client | None = None,
        token: str | None = None,
        resolver: Resolver = resolve_public_addresses,
        *,
        name: str = "rctf",
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.source_name = name
        self.base_url = base_url.rstrip("/") + "/"
        self.event = event
        self.now = now
        self.api = GuardedJsonClient(
            base_url=self.base_url + "api/v2/",
            client=client,
            resolver=resolver,
            token=token,
            auth_scheme="Bearer",
        )

    def fetch_events(self, start: datetime, finish: datetime) -> EventBatch:
        if finish <= self.event.starts_at or start >= self.event.finishes_at:
            return EventBatch()
        failures: list[str] = []
        challenges_total: int | None = None
        visible_solves: int | None = None
        categories: dict[str, int] = {}
        scoreboard_entries: int | None = None
        participants_total: int | None = None
        try:
            challenge_data = _rctf_data(self.api.get_json("challs"))
            if not isinstance(challenge_data, list):
                raise ValueError("rCTF returned an unexpected challenge shape")
            challenge_rows = [row for row in challenge_data if isinstance(row, dict)]
            challenges_total = len(challenge_rows)
            visible_solves = sum(
                max(0, int(row.get("solves") or 0)) for row in challenge_rows
            )
            for row in challenge_rows:
                category = str(row.get("category") or "Uncategorized").strip()[:80]
                categories[category] = categories.get(category, 0) + 1
        except (ApiError, FetchError, ValueError, TypeError) as error:
            failures.append(f"rCTF challenges: {type(error).__name__}: {error}")
        try:
            leaderboard_data = _rctf_data(
                self.api.get_json("leaderboard/now", params={"limit": 1, "offset": 0})
            )
            if not isinstance(leaderboard_data, dict):
                raise ValueError("rCTF returned an unexpected leaderboard shape")
            leaderboard = leaderboard_data.get("leaderboard")
            if not isinstance(leaderboard, list):
                raise ValueError("rCTF returned an unexpected leaderboard shape")
            scoreboard_entries = len(leaderboard)
            participants_total = max(0, int(leaderboard_data.get("total") or 0))
        except (ApiError, FetchError, ValueError, TypeError) as error:
            failures.append(f"rCTF leaderboard: {type(error).__name__}: {error}")

        event = self.event.model_copy(
            update={
                "source": self.source_name,
                "platform": "rCTF",
                "primary_source_url": HttpUrl(self.base_url),
                "source_refs": [
                    *self.event.source_refs,
                    SourceRef(
                        source=self.source_name,
                        kind=SourceKind.RCTF,
                        url=HttpUrl(self.base_url),
                        record_id=self.event.source_id,
                        collected_at=self.now(),
                    ),
                ],
                "analytics": EventAnalytics(
                    challenges_total=challenges_total,
                    visible_solves=visible_solves,
                    scoreboard_entries=scoreboard_entries,
                    participants_total=participants_total,
                    categories=categories,
                ),
            }
        )
        return EventBatch(events=[(event, EventFacts())], failures=failures)
