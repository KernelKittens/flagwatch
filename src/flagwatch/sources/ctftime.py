from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic import HttpUrl

from flagwatch.domain import Event, EventFacts, ScheduleMode

USER_AGENT = "Flagwatch/0.1 personal CTF research"
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _parse_team_max(description: str) -> int | None:
    match = re.search(
        r"teams?(?:\s+may|\s+can)?(?:\s+include|\s+consist\s+of|\s+of)?\s+up\s+to\s+"
        r"(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten)",
        description,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    raw = match.group("count").lower()
    return int(raw) if raw.isdigit() else NUMBER_WORDS[raw]


def _parse_divisions(description: str) -> list[str]:
    match = re.search(
        r"(?:following\s+)?divisions?\s*:\s*(?P<divisions>[^.\r\n]+)",
        description,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    normalized = re.sub(r"\s+and\s+", ", ", match.group("divisions"), flags=re.IGNORECASE)
    return [value.strip(" ,") for value in normalized.split(",") if value.strip(" ,")]


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def normalize_ctftime_event(payload: dict[str, Any]) -> tuple[Event, EventFacts]:
    description = str(payload.get("description") or "")
    prizes = str(payload.get("prizes") or "")
    onsite = bool(payload.get("onsite", False))
    organizers = [
        str(organizer.get("name"))
        for organizer in payload.get("organizers", [])
        if isinstance(organizer, dict) and organizer.get("name")
    ]
    event = Event(
        source="ctftime",
        source_id=str(payload["id"]),
        title=str(payload["title"]).strip(),
        official_url=HttpUrl(str(payload["url"])),
        ctftime_url=HttpUrl(str(payload["ctftime_url"])),
        starts_at=datetime.fromisoformat(str(payload["start"])),
        finishes_at=datetime.fromisoformat(str(payload["finish"])),
        online=not onsite,
        onsite=onsite,
        format=str(payload.get("format")) if payload.get("format") else None,
        description=description,
        prizes=prizes,
        weight=_decimal_or_none(payload.get("weight")),
        organizers=organizers,
        participants=(
            int(payload["participants"]) if payload.get("participants") is not None else None
        ),
        raw=dict(payload),
    )
    facts = EventFacts(
        team_max=_parse_team_max(description),
        divisions=_parse_divisions(description),
        schedule_mode=ScheduleMode.FIXED,
        prize_summary=prizes.strip() or None,
    )
    return event, facts


class CtftimeSource:
    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = "https://ctftime.org/api/v1",
    ) -> None:
        self.client = client or httpx.Client(timeout=10.0)
        self.base_url = base_url.rstrip("/")

    def fetch_events(
        self, start: datetime, finish: datetime
    ) -> list[tuple[Event, EventFacts]]:
        response = self.client.get(
            f"{self.base_url}/events/",
            params={
                "limit": 100,
                "start": int(start.timestamp()),
                "finish": int(finish.timestamp()),
            },
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("CTFtime returned an unexpected event response")
        return [normalize_ctftime_event(item) for item in payload if isinstance(item, dict)]
