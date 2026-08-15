"""Event source adapters."""

from __future__ import annotations

from dataclasses import dataclass, field

from flagwatch.domain import Event, EventFacts


@dataclass(frozen=True)
class EventBatch:
    events: list[tuple[Event, EventFacts]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
