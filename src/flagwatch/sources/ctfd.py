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


def _ctfd_data(payload: Any) -> list[object]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("CTFd returned an unsuccessful response")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("CTFd returned an unexpected data shape")
    return data


class CtfdSource:
    source_name = "ctfd"
    precedence = 85

    def __init__(
        self,
        base_url: str,
        event: Event,
        client: httpx.Client | None = None,
        token: str | None = None,
        resolver: Resolver = resolve_public_addresses,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.event = event
        self.now = now
        self.api = GuardedJsonClient(
            base_url=self.base_url + "api/v1/",
            client=client,
            resolver=resolver,
            token=token,
            auth_scheme="Token",
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
            challenges = _ctfd_data(self.api.get_json("challenges"))
            challenge_rows = [row for row in challenges if isinstance(row, dict)]
            challenges_total = len(challenge_rows)
            visible_solves = sum(
                max(0, int(row.get("solves") or 0)) for row in challenge_rows
            )
            for row in challenge_rows:
                category = str(row.get("category") or "Uncategorized").strip()[:80]
                categories[category] = categories.get(category, 0) + 1
        except (ApiError, FetchError, ValueError, TypeError) as error:
            failures.append(f"CTFd challenges: {type(error).__name__}: {error}")
        try:
            scoreboard = _ctfd_data(self.api.get_json("scoreboard"))
            scoreboard_entries = len(scoreboard)
            participants_total = scoreboard_entries
        except (ApiError, FetchError, ValueError, TypeError) as error:
            failures.append(f"CTFd scoreboard: {type(error).__name__}: {error}")

        event = self.event.model_copy(
            update={
                "source": self.source_name,
                "platform": "CTFd",
                "primary_source_url": HttpUrl(self.base_url),
                "source_refs": [
                    *self.event.source_refs,
                    SourceRef(
                        source=self.source_name,
                        kind=SourceKind.CTFD,
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
