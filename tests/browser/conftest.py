from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import uvicorn

from flagwatch.config import Settings
from flagwatch.domain import AiPolicy, Event, EventFacts
from flagwatch.storage import Database
from flagwatch.sync import SyncReport
from flagwatch.web import create_app


def _bound_socket() -> socket.socket:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    return listener


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, object]) -> dict[str, object]:
    return {**browser_type_launch_args, "headless": True}


@pytest.fixture()
def live_server(tmp_path) -> Iterator[str]:
    database = Database(tmp_path / "browser.db")
    database.initialize()
    start = datetime(2026, 8, 21, 23, tzinfo=UTC)
    event = Event(
        source="ctftime",
        source_id="browser-fixture",
        title="Midwest Signal CTF 2026",
        official_url="https://example.com/ctf",
        ctftime_url="https://ctftime.org/event/9999/",
        starts_at=start,
        finishes_at=start + timedelta(hours=48),
        online=True,
        format="Jeopardy",
        prizes="$2,500 prize pool",
    )
    database.upsert_event(event)
    database.save_facts(
        event.key,
        EventFacts(
            ai_policy=AiPolicy.AI_ASSISTED,
            ai_policy_reason="Interactive AI help is allowed, but automated solvers are not.",
            ai_policy_source="https://example.com/ctf/rules",
            ai_policy_evidence=(
                "Teams may use interactive AI assistants. "
                "Fully automated solving agents are prohibited."
            ),
            team_max=4,
            divisions=["Open"],
            prize_summary="$2,500 prize pool",
        ),
    )
    app = create_app(
        Settings(database_path=database.path),
        database,
        sync_runner=lambda: SyncReport(),
    )
    listener = _bound_socket()
    port = int(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("Browser test server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
