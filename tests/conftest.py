from __future__ import annotations

from datetime import UTC, datetime

import pytest


@pytest.fixture
def gaslight_payload() -> dict[str, object]:
    return {
        "id": 3181,
        "title": "gaslightCTF 2026",
        "url": "https://gaslightctf.cooking/",
        "ctftime_url": "https://ctftime.org/event/3181/",
        "start": "2026-08-14T12:00:00+00:00",
        "finish": "2026-08-17T12:00:00+00:00",
        "onsite": False,
        "format": "Jeopardy",
        "description": (
            "Players may participate in teams of up to five members. "
            "Teams may belong to the following divisions: Secondary School, University, and Open."
        ),
        "prizes": "Open Division: 1st: $100",
    }


@pytest.fixture
def utc_now() -> datetime:
    return datetime(2026, 8, 14, 23, 0, tzinfo=UTC)
