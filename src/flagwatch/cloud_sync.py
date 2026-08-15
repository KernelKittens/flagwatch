from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from flagwatch.public_snapshot import build_public_snapshot
from flagwatch.storage import Database


class BlobStore(Protocol):
    def download(self, name: str) -> bytes | None: ...

    def upload(self, name: str, value: bytes, *, content_type: str) -> None: ...

    def delete(self, name: str) -> None: ...


class CloudSnapshotService:
    database_blob = "state/flagwatch.db"
    public_blob = "public/events.json"

    def __init__(
        self,
        blobs: BlobStore,
        sync: Callable[[Database], object],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.blobs = blobs
        self.sync = sync
        self.now = now

    def refresh(self) -> None:
        with TemporaryDirectory(prefix="flagwatch-") as directory:
            workdir = Path(directory)
            database_path = workdir / "flagwatch.db"
            previous = self.blobs.download(self.database_blob)
            if previous is not None:
                database_path.write_bytes(previous)

            database = Database(database_path)
            database.initialize()
            self.sync(database)
            snapshot = build_public_snapshot(database, self.now())

            backup_path = workdir / "flagwatch-backup.db"
            database.backup_to(backup_path)
            database_bytes = backup_path.read_bytes()
            public_bytes = snapshot.model_dump_json().encode("utf-8")

            # Publish JSON last so the public endpoint never points at a failed refresh.
            self.blobs.upload(
                self.database_blob,
                database_bytes,
                content_type="application/vnd.sqlite3",
            )
            try:
                self.blobs.upload(
                    self.public_blob,
                    public_bytes,
                    content_type="application/json; charset=utf-8",
                )
            except Exception:
                if previous is None:
                    self.blobs.delete(self.database_blob)
                else:
                    self.blobs.upload(
                        self.database_blob,
                        previous,
                        content_type="application/vnd.sqlite3",
                    )
                raise
