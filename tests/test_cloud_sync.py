from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from flagwatch.cloud_sync import CloudSnapshotService
from flagwatch.domain import Event
from flagwatch.storage import Database


class MemoryBlobs:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.fail_on: str | None = None

    def download(self, name: str) -> bytes | None:
        return self.values.get(name)

    def upload(self, name: str, value: bytes, *, content_type: str) -> None:
        if name == self.fail_on:
            raise RuntimeError("upload failed")
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def _event() -> Event:
    start = datetime(2026, 8, 21, 15, tzinfo=UTC)
    return Event(
        source="ctftime",
        source_id="cloud",
        title="Cloud CTF",
        official_url="https://example.com/cloud",
        ctftime_url="https://ctftime.org/event/3000",
        starts_at=start,
        finishes_at=start + timedelta(days=1),
        online=True,
        raw={"private": "must not publish"},
    )


def test_refresh_round_trips_stable_database_and_sanitized_snapshot(tmp_path: Path) -> None:
    blobs = MemoryBlobs()

    def sync(database: Database) -> None:
        database.upsert_event(_event())

    service = CloudSnapshotService(blobs, sync, now=lambda: datetime(2026, 8, 14, tzinfo=UTC))
    service.refresh()

    snapshot = json.loads(blobs.values[service.public_blob])
    assert snapshot["events"][0]["title"] == "Cloud CTF"
    assert "raw" not in snapshot["events"][0]
    assert b"Cloud CTF" in blobs.values[service.database_blob]

    restored = tmp_path / "restored.db"
    restored.write_bytes(blobs.values[service.database_blob])
    assert Database(restored).list_events()[0].event.title == "Cloud CTF"


def test_refresh_keeps_last_good_public_snapshot_when_sync_fails() -> None:
    blobs = MemoryBlobs()
    previous = b'{"generated_at":"old","events":[]}'
    blobs.values["public/events.json"] = previous
    service = CloudSnapshotService(
        blobs,
        lambda _database: (_ for _ in ()).throw(RuntimeError("sync failed")),
    )

    with pytest.raises(RuntimeError, match="sync failed"):
        service.refresh()

    assert blobs.values[service.public_blob] == previous


def test_snapshot_is_published_only_after_database_upload_succeeds() -> None:
    blobs = MemoryBlobs()
    previous = b'{"generated_at":"old","events":[]}'
    blobs.values["public/events.json"] = previous
    blobs.fail_on = "state/flagwatch.db"
    service = CloudSnapshotService(blobs, lambda database: database.upsert_event(_event()))

    with pytest.raises(RuntimeError, match="upload failed"):
        service.refresh()

    assert blobs.values[service.public_blob] == previous


def test_public_upload_failure_restores_previous_database(tmp_path: Path) -> None:
    blobs = MemoryBlobs()
    seed = Database(tmp_path / "previous.db")
    seed.initialize()
    seed.upsert_event(_event())
    backup = tmp_path / "previous-backup.db"
    seed.backup_to(backup)
    previous_database = backup.read_bytes()
    previous_snapshot = b'{"generated_at":"old","events":[]}'
    blobs.values["state/flagwatch.db"] = previous_database
    blobs.values["public/events.json"] = previous_snapshot
    blobs.fail_on = "public/events.json"
    service = CloudSnapshotService(blobs, lambda database: database.upsert_event(_event()))

    with pytest.raises(RuntimeError, match="upload failed"):
        service.refresh()

    assert blobs.values[service.database_blob] == previous_database
    assert blobs.values[service.public_blob] == previous_snapshot
