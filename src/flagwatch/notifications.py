from __future__ import annotations

import hashlib
import json
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx
from pydantic import BaseModel

from flagwatch.domain import Event, EventFacts, MatchResult
from flagwatch.storage import Database
from flagwatch.time_display import duration_label, format_central_range


class AlertMessage(BaseModel):
    title: str
    body: str
    url: str


class NotificationSender(Protocol):
    def send(self, message: AlertMessage) -> None: ...


class DiscordWebhookSender:
    def __init__(self, webhook_url: str, client: httpx.Client | None = None) -> None:
        self.webhook_url = webhook_url
        self.client = client or httpx.Client(timeout=10.0)

    def send(self, message: AlertMessage) -> None:
        content = f"**{message.title}**\n{message.body}\n{message.url}"
        response = self.client.post(
            self.webhook_url,
            headers={"User-Agent": "Flagwatch/0.1 personal CTF alerts"},
            json={"content": content[:2000]},
        )
        response.raise_for_status()


class SmtpSender:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        recipient: str,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.recipient = recipient

    def send(self, message: AlertMessage) -> None:
        email = EmailMessage()
        email["Subject"] = f"Flagwatch match: {message.title}"
        email["From"] = self.sender
        email["To"] = self.recipient
        email.set_content(f"{message.body}\n\n{message.url}")
        with smtplib.SMTP(self.host, self.port, timeout=10.0) as smtp:
            smtp.starttls()
            smtp.login(self.username, self.password)
            smtp.send_message(email)


def render_alert(event: Event, facts: EventFacts, match: MatchResult) -> AlertMessage:
    details = [
        format_central_range(event),
        duration_label(event),
        f"AI policy: {facts.ai_policy.value.replace('_', ' ')}",
    ]
    if facts.team_max is not None:
        details.append(f"Team maximum: {facts.team_max}")
    if facts.divisions:
        details.append(f"Divisions: {', '.join(facts.divisions)}")
    if facts.prize_summary:
        details.append(f"Prizes: {facts.prize_summary}")
    details.append(f"Matched because: {', '.join(match.match_reasons)}")
    return AlertMessage(title=event.title, body="\n".join(details), url=str(event.official_url))


def _dedupe_key(event: Event, facts: EventFacts, criteria_version: int, channel: str) -> str:
    material = {
        "event": {
            "key": event.key,
            "title": event.title,
            "official_url": str(event.official_url),
            "starts_at": event.starts_at.isoformat(),
            "finishes_at": event.finishes_at.isoformat(),
            "online": event.online,
            "onsite": event.onsite,
            "format": event.format,
            "weight": str(event.weight) if event.weight is not None else None,
            "prizes": event.prizes,
        },
        "facts": {
            "ai_policy": facts.ai_policy.value,
            "team_max": facts.team_max,
            "divisions": facts.divisions,
            "schedule_mode": facts.schedule_mode.value,
            "prize_summary": facts.prize_summary,
            "registration_status": facts.registration_status,
            "categories": facts.categories,
        },
        "criteria_version": criteria_version,
        "channel": channel,
    }
    serialized = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def queue_alert(
    database: Database,
    event: Event,
    facts: EventFacts,
    match: MatchResult,
    criteria_version: int,
    channel: str = "discord",
) -> bool:
    if not match.alert_eligible:
        return False
    message = render_alert(event, facts, match)
    return database.queue_outbox(
        dedupe_key=_dedupe_key(event, facts, criteria_version, channel),
        event_key=event.key,
        channel=channel,
        payload_json=message.model_dump_json(),
    )


def deliver_pending(
    database: Database,
    sender: NotificationSender,
    sending_enabled: bool,
) -> int:
    if not sending_enabled:
        return 0
    delivered = 0
    for record in database.list_pending_outbox():
        try:
            sender.send(AlertMessage.model_validate_json(record.payload_json))
        except Exception as error:
            database.mark_outbox_failed(record.record_id, str(error))
            continue
        database.mark_outbox_sent(record.record_id)
        delivered += 1
    return delivered
