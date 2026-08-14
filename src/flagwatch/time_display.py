from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from flagwatch.domain import Event

CENTRAL = ZoneInfo("America/Chicago")


def _clock(value: datetime) -> str:
    return value.strftime("%I:%M %p %Z").lstrip("0")


def _date_and_clock(value: datetime) -> str:
    return f"{value:%a, %b} {value.day} at {_clock(value)}"


def format_central_range(event: Event) -> str:
    start = event.starts_at.astimezone(CENTRAL)
    finish = event.finishes_at.astimezone(CENTRAL)
    if start.date() == finish.date():
        return f"{_date_and_clock(start)} to {_clock(finish)}"
    return f"{_date_and_clock(start)} to {_date_and_clock(finish)}"


def duration_label(event: Event) -> str:
    total_minutes = int((event.finishes_at - event.starts_at).total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    if minutes == 0:
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    return f"{hours}h {minutes}m"
