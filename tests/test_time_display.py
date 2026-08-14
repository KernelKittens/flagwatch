from __future__ import annotations

from datetime import UTC, datetime

from flagwatch.domain import Event
from flagwatch.time_display import duration_label, format_central_range


def make_event(starts_at: datetime, finishes_at: datetime) -> Event:
    return Event(
        source="test",
        source_id="1",
        title="Time test",
        official_url="https://example.com/",
        ctftime_url="https://ctftime.org/event/1/",
        starts_at=starts_at,
        finishes_at=finishes_at,
        online=True,
    )


def test_formats_summer_event_as_cdt():
    event = make_event(
        datetime(2026, 8, 14, 12, tzinfo=UTC),
        datetime(2026, 8, 17, 12, tzinfo=UTC),
    )

    assert format_central_range(event).startswith("Fri, Aug 14 at 7:00 AM CDT")
    assert duration_label(event) == "72 hours"


def test_formats_winter_event_as_cst():
    event = make_event(
        datetime(2026, 12, 5, 15, tzinfo=UTC),
        datetime(2026, 12, 5, 21, tzinfo=UTC),
    )

    assert "9:00 AM CST" in format_central_range(event)
    assert "3:00 PM CST" in format_central_range(event)
