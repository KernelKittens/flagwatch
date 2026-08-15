from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import httpx

from flagwatch.domain import AiPolicy, Event, EventFacts, MatchResult
from flagwatch.notifications import (
    AlertMessage,
    DiscordWebhookSender,
    SmtpSender,
    deliver_pending,
    queue_alert,
)
from flagwatch.storage import Database


class RecordingSender:
    def __init__(self) -> None:
        self.messages: list[AlertMessage] = []

    def send(self, message: AlertMessage) -> None:
        self.messages.append(message)


def test_delivery_is_disabled_by_default(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    event = Event(
        source="test",
        source_id="1",
        title="AI Friendly CTF",
        official_url="https://ctf.example/",
        ctftime_url="https://ctftime.org/event/1/",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
    )
    database.upsert_event(event)
    queued = queue_alert(
        database,
        event,
        EventFacts(ai_policy=AiPolicy.AI_NATIVE, team_max=4),
        MatchResult(alert_eligible=True, match_reasons=["AI is allowed"]),
        criteria_version=1,
    )
    sender = RecordingSender()

    delivered = deliver_pending(database, sender, sending_enabled=False)

    assert queued is True
    assert delivered == 0
    assert sender.messages == []


def test_failed_delivery_is_recorded_for_review(tmp_path):
    database = Database(tmp_path / "flagwatch.db")
    database.initialize()
    start = datetime(2026, 9, 5, 14, tzinfo=UTC)
    event = Event(
        source="test",
        source_id="failed",
        title="Failed delivery CTF",
        official_url="https://ctf.example/",
        ctftime_url="https://ctftime.org/event/1/",
        starts_at=start,
        finishes_at=start + timedelta(hours=24),
        online=True,
    )
    database.upsert_event(event)
    queue_alert(
        database,
        event,
        EventFacts(ai_policy=AiPolicy.AI_NATIVE),
        MatchResult(alert_eligible=True),
        criteria_version=1,
    )

    class BrokenSender:
        def send(self, _message: AlertMessage) -> None:
            raise RuntimeError("webhook rejected the request")

    delivered = deliver_pending(database, BrokenSender(), sending_enabled=True)
    record = database.list_outbox()[0]

    assert delivered == 0
    assert record.status == "pending"
    assert record.attempts == 1
    assert record.last_error == "webhook rejected the request"


def test_discord_sender_posts_plain_alert():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    sender = DiscordWebhookSender(
        webhook_url="https://discord.example/webhook",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    sender.send(AlertMessage(title="Test CTF", body="AI policy: ai assisted", url="https://ctf.example"))

    payload = requests[0].read().decode()
    assert "Test CTF" in payload
    assert "AI policy: ai assisted" in payload
    assert requests[0].headers["user-agent"].startswith("Flagwatch/")


def test_smtp_sender_uses_tls_and_login(monkeypatch):
    actions: list[object] = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            actions.append((host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def starttls(self) -> None:
            actions.append("tls")

        def login(self, username: str, password: str) -> None:
            actions.append((username, password))

        def send_message(self, message: EmailMessage) -> None:
            actions.append(message)

    monkeypatch.setattr("flagwatch.notifications.smtplib.SMTP", FakeSmtp)
    sender = SmtpSender(
        host="smtp.example",
        port=587,
        username="moo",
        password="secret",
        sender="alerts@example.com",
        recipient="moo@example.com",
    )

    sender.send(AlertMessage(title="Test CTF", body="Starts Friday", url="https://ctf.example"))

    assert "tls" in actions
    assert ("moo", "secret") in actions
    message = next(action for action in actions if isinstance(action, EmailMessage))
    assert message["Subject"] == "Flagwatch match: Test CTF"
