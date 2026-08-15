from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from flagwatch.public_snapshot import build_public_snapshot
from flagwatch.storage import Database


def build_seed_bundle(source: Path, destination: Path) -> None:
    database = Database(source)
    events = database.list_events()
    if not events:
        raise ValueError("Seed database has no events")
    destination.mkdir(parents=True, exist_ok=True)
    database.backup_to(destination / "flagwatch.db")
    snapshot = build_public_snapshot(database, datetime.now(UTC))
    (destination / "events.json").write_text(
        snapshot.model_dump_json(),
        encoding="utf-8",
    )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m flagwatch.seed_bundle DATABASE DESTINATION")
    build_seed_bundle(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())


if __name__ == "__main__":
    main()
