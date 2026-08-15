from __future__ import annotations

from datetime import UTC, datetime

from flagwatch.domain import Event


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def _utc_stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render_ics(event: Event) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Flagwatch//CTF Calendar//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{_escape(event.key)}@flagwatch.local",
        f"DTSTART:{_utc_stamp(event.starts_at)}",
        f"DTEND:{_utc_stamp(event.finishes_at)}",
        f"SUMMARY:{_escape(event.title)}",
        f"DESCRIPTION:{_escape(str(event.official_url))}",
        f"URL:{_escape(str(event.official_url))}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"
