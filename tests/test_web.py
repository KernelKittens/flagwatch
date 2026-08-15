from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from flagwatch.config import Settings
from flagwatch.domain import AiPolicy, Event, EventFacts
from flagwatch.storage import Database
from flagwatch.sync import SyncReport
from flagwatch.web import create_app


def seeded_client(tmp_path) -> tuple[TestClient, Database, Event]:
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 8, 14, 12, tzinfo=UTC)
    event = Event(
        source="ctftime",
        source_id="3181",
        title="gaslightCTF 2026",
        official_url="https://gaslightctf.cooking/",
        ctftime_url="https://ctftime.org/event/3181/",
        starts_at=start,
        finishes_at=start + timedelta(hours=72),
        online=True,
        format="Jeopardy",
        prizes="Open Division: 1st: $100",
    )
    facts = EventFacts(
        ai_policy=AiPolicy.HUMAN_ONLY,
        ai_policy_reason="AI-assisted challenge solving is prohibited",
        ai_policy_source="https://gaslightctf.cooking/rules",
        ai_policy_evidence="No LLMs or AI assistants for solving challenges in any way.",
        team_max=5,
        divisions=["Secondary School", "University", "Open"],
        prize_summary="Open Division: 1st: $100",
    )
    database.upsert_event(event)
    database.save_facts(event.key, facts)
    settings = Settings(database_path=database.path)
    return TestClient(create_app(settings, database)), database, event


def csrf_token(client: TestClient) -> str:
    return str(client.app.state.csrf_token)


def test_dashboard_keeps_human_only_event_and_suppresses_alert(tmp_path):
    client, _database, _event = seeded_client(tmp_path)

    response = client.get("/")
    soup = BeautifulSoup(response.text, "html.parser")

    assert response.status_code == 200
    assert "gaslightCTF 2026" in response.text
    assert "Human only" in response.text
    assert "Alert suppressed" in response.text
    assert soup.select_one("a.skip-link[href='#main-content']")
    assert soup.select_one("main#main-content")
    assert soup.select_one("article[aria-labelledby]")


def test_event_page_shows_cited_ai_evidence(tmp_path):
    client, _database, event = seeded_client(tmp_path)

    response = client.get(f"/events/{event.key}")

    assert response.status_code == 200
    assert "AI-assisted challenge solving is prohibited" in response.text
    assert "gaslightctf.cooking/rules" in response.text
    assert "No LLMs or AI assistants" in response.text


def test_settings_saves_without_javascript(tmp_path):
    client, database, _event = seeded_client(tmp_path)

    response = client.post(
        "/settings",
        data={
            "csrf_token": csrf_token(client),
            "require_online": "on",
            "max_team_size": "6",
            "max_duration_hours": "72",
            "require_prize": "on",
            "allowed_schedule_modes": "fixed",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    saved = database.get_criteria()
    assert saved.max_team_size == 6
    assert saved.max_duration_hours == 72
    assert saved.require_prize is True


def test_health_is_plain_and_database_backed(tmp_path):
    client, _database, _event = seeded_client(tmp_path)

    assert client.get("/healthz").json() == {"status": "ok", "database": "ok"}


def test_calendar_route_downloads_event(tmp_path):
    client, _database, event = seeded_client(tmp_path)

    response = client.get(f"/events/{event.key}.ics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in response.text


def test_alert_history_has_directed_empty_state(tmp_path):
    client, _database, _event = seeded_client(tmp_path)

    response = client.get("/alerts")

    assert response.status_code == 200
    assert "No alert previews yet." in response.text


def test_sync_control_runs_injected_sync_and_reports_result(tmp_path):
    client, database, _event = seeded_client(tmp_path)
    calls = 0

    def run_sync() -> SyncReport:
        nonlocal calls
        calls += 1
        return SyncReport(imported=2, analyzed=2, queued=1)

    settings = Settings(database_path=database.path)
    client = TestClient(create_app(settings, database, sync_runner=run_sync))

    response = client.post(
        "/sync",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert calls == 1
    assert "Imported 2 events" in response.text
    assert "Queued 1 alert preview" in response.text


def test_sync_control_is_unavailable_without_a_runner(tmp_path):
    client, _database, _event = seeded_client(tmp_path)

    response = client.post("/sync", data={"csrf_token": csrf_token(client)})

    assert response.status_code == 503


def test_state_changes_reject_missing_or_invalid_csrf_token(tmp_path):
    client, database, _event = seeded_client(tmp_path)
    settings = Settings(database_path=database.path)
    client = TestClient(create_app(settings, database, sync_runner=lambda: SyncReport()))

    assert client.post("/sync").status_code == 403
    assert client.post("/sync", data={"csrf_token": "wrong"}).status_code == 403
    assert client.post("/settings", data={"require_online": "on"}).status_code == 403
