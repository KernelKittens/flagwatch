from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from flagwatch.domain import Criteria, Event, EventFacts, EventView


@dataclass(frozen=True)
class OutboxRecord:
    record_id: int
    event_key: str
    channel: str
    payload_json: str
    status: str
    attempts: int
    last_error: str | None


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    finishes_at TEXT NOT NULL,
                    online INTEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    UNIQUE(source, source_id)
                );
                CREATE INDEX IF NOT EXISTS events_starts_at_idx ON events(starts_at);

                CREATE TABLE IF NOT EXISTS event_facts (
                    event_key TEXT PRIMARY KEY REFERENCES events(event_key) ON DELETE CASCADE,
                    ai_policy TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS facts_ai_policy_idx ON event_facts(ai_policy);

                CREATE TABLE IF NOT EXISTS criteria (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    version INTEGER NOT NULL,
                    data_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    event_key TEXT NOT NULL REFERENCES events(event_key) ON DELETE CASCADE,
                    channel TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def upsert_event(self, event: Event) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events (
                    event_key, source, source_id, starts_at, finishes_at, online, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET
                    starts_at = excluded.starts_at,
                    finishes_at = excluded.finishes_at,
                    online = excluded.online,
                    data_json = excluded.data_json
                """,
                (
                    event.key,
                    event.source,
                    event.source_id,
                    event.starts_at.isoformat(),
                    event.finishes_at.isoformat(),
                    event.online,
                    event.model_dump_json(),
                ),
            )

    def save_facts(self, event_key: str, facts: EventFacts) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO event_facts (event_key, ai_policy, data_json)
                VALUES (?, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET
                    ai_policy = excluded.ai_policy,
                    data_json = excluded.data_json
                """,
                (event_key, facts.ai_policy.value, facts.model_dump_json()),
            )

    def list_events(self) -> list[EventView]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT events.data_json AS event_json, event_facts.data_json AS facts_json
                FROM events
                LEFT JOIN event_facts USING (event_key)
                ORDER BY starts_at, event_key
                """
            ).fetchall()
        return [
            EventView(
                event=Event.model_validate_json(row["event_json"]),
                facts=(
                    EventFacts.model_validate_json(row["facts_json"])
                    if row["facts_json"]
                    else EventFacts()
                ),
            )
            for row in rows
        ]

    def get_event(self, event_key: str) -> EventView | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT events.data_json AS event_json, event_facts.data_json AS facts_json
                FROM events
                LEFT JOIN event_facts USING (event_key)
                WHERE events.event_key = ?
                """,
                (event_key,),
            ).fetchone()
        if row is None:
            return None
        return EventView(
            event=Event.model_validate_json(row["event_json"]),
            facts=(
                EventFacts.model_validate_json(row["facts_json"])
                if row["facts_json"]
                else EventFacts()
            ),
        )

    def get_criteria(self) -> Criteria:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM criteria WHERE singleton = 1"
            ).fetchone()
        return Criteria.model_validate_json(row["data_json"]) if row else Criteria()

    def save_criteria(self, criteria: Criteria) -> Criteria:
        current = self.get_criteria()
        saved = criteria.model_copy(update={"version": current.version + 1})
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO criteria (singleton, version, data_json)
                VALUES (1, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    version = excluded.version,
                    data_json = excluded.data_json
                """,
                (saved.version, saved.model_dump_json()),
            )
        return saved

    def queue_outbox(
        self,
        dedupe_key: str,
        event_key: str,
        channel: str,
        payload_json: str,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO outbox (dedupe_key, event_key, channel, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (dedupe_key, event_key, channel, payload_json),
            )
            return cursor.rowcount == 1

    def count_outbox(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM outbox").fetchone()
        return int(row["count"])

    def list_pending_outbox(self) -> list[OutboxRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, event_key, channel, payload_json, status, attempts, last_error
                FROM outbox
                WHERE status = 'pending'
                ORDER BY id
                """
            ).fetchall()
        return [
            OutboxRecord(
                record_id=int(row["id"]),
                event_key=str(row["event_key"]),
                channel=str(row["channel"]),
                payload_json=str(row["payload_json"]),
                status=str(row["status"]),
                attempts=int(row["attempts"]),
                last_error=str(row["last_error"]) if row["last_error"] else None,
            )
            for row in rows
        ]

    def list_outbox(self) -> list[OutboxRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, event_key, channel, payload_json, status, attempts, last_error
                FROM outbox
                ORDER BY id DESC
                """
            ).fetchall()
        return [
            OutboxRecord(
                record_id=int(row["id"]),
                event_key=str(row["event_key"]),
                channel=str(row["channel"]),
                payload_json=str(row["payload_json"]),
                status=str(row["status"]),
                attempts=int(row["attempts"]),
                last_error=str(row["last_error"]) if row["last_error"] else None,
            )
            for row in rows
        ]

    def mark_outbox_sent(self, record_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE outbox SET status = 'sent', attempts = attempts + 1 WHERE id = ?",
                (record_id,),
            )

    def mark_outbox_suppressed(self, record_id: int, reason: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE outbox
                SET status = 'suppressed', last_error = ?
                WHERE id = ?
                """,
                (reason[:500], record_id),
            )

    def mark_outbox_failed(self, record_id: int, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE outbox
                SET attempts = attempts + 1, last_error = ?
                WHERE id = ?
                """,
                (error[:500], record_id),
            )
