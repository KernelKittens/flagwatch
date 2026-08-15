from datetime import UTC, datetime, timedelta

from flagwatch.domain import Event
from flagwatch.ics import render_ics


def test_calendar_uses_utc_and_escapes_text():
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    event = Event(
        source="test",
        source_id="1",
        title="CTF, Rules; Matter",
        official_url="https://ctf.example/",
        ctftime_url="https://ctftime.org/event/1/",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
    )

    calendar = render_ics(event)

    assert "DTSTART:20260905T140000Z\r\n" in calendar
    assert "DTEND:20260906T140000Z\r\n" in calendar
    assert "SUMMARY:CTF\\, Rules\\; Matter\r\n" in calendar
    assert calendar.endswith("END:VCALENDAR\r\n")
