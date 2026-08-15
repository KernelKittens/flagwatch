from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from flagwatch.config import Settings
from flagwatch.domain import AiPolicy, Criteria, EventView, MatchResult, ScheduleMode
from flagwatch.ics import render_ics
from flagwatch.matching import match_event
from flagwatch.notifications import AlertMessage
from flagwatch.storage import Database, OutboxRecord
from flagwatch.sync import SyncReport
from flagwatch.time_display import duration_label, format_central_range

PACKAGE_ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=PACKAGE_ROOT / "templates")
POLICY_LABELS = {
    AiPolicy.AI_NATIVE: "AI native",
    AiPolicy.AI_ASSISTED: "AI assisted",
    AiPolicy.HUMAN_ONLY: "Human only",
    AiPolicy.UNKNOWN: "AI policy unknown",
}


@dataclass(frozen=True)
class DashboardRow:
    view: EventView
    match: MatchResult
    central_time: str
    duration: str
    policy_label: str
    policy_class: str
    alert_status: str
    prize_summary: str | None


def _shorten(value: str | None, limit: int = 180) -> str | None:
    if not value:
        return None
    first_line = next((line.strip() for line in value.splitlines() if line.strip()), "")
    return first_line if len(first_line) <= limit else f"{first_line[: limit - 3].rstrip()}..."


def _row(view: EventView, criteria: Criteria) -> DashboardRow:
    result = match_event(view.event, view.facts, criteria)
    return DashboardRow(
        view=view,
        match=result,
        central_time=format_central_range(view.event),
        duration=duration_label(view.event),
        policy_label=POLICY_LABELS[view.facts.ai_policy],
        policy_class=view.facts.ai_policy.value.replace("_", "-"),
        alert_status="Alert candidate" if result.alert_eligible else "Alert suppressed",
        prize_summary=_shorten(view.facts.prize_summary or view.event.prizes),
    )


def _optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text else None


def _template_context(request: Request, page_title: str) -> dict[str, object]:
    return {
        "request": request,
        "page_title": page_title,
        "csrf_token": request.app.state.csrf_token,
    }


def create_app(
    settings: Settings,
    database: Database,
    sync_runner: Callable[[], SyncReport] | None = None,
) -> FastAPI:
    app = FastAPI(title="Flagwatch", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.database = database
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.mount("/static", StaticFiles(directory=PACKAGE_ROOT / "static"), name="static")

    def require_csrf(candidate: str | None) -> None:
        if candidate is None or not hmac.compare_digest(candidate, app.state.csrf_token):
            raise HTTPException(status_code=403, detail="Invalid form token")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> Response:
        criteria = database.get_criteria()
        rows = [_row(view, criteria) for view in database.list_events()]
        context = _template_context(request, "Upcoming CTFs")
        context.update(
            {
                "events": rows,
                "candidate_count": sum(row.match.alert_eligible for row in rows),
                "suppressed_count": sum(not row.match.alert_eligible for row in rows),
                "sync_enabled": sync_runner is not None,
                "sync_result": request.query_params,
            }
        )
        return templates.TemplateResponse(request, "dashboard.html", context)

    @app.post("/sync")
    def run_sync(csrf_token: Annotated[str | None, Form()] = None) -> Response:
        require_csrf(csrf_token)
        if sync_runner is None:
            raise HTTPException(status_code=503, detail="Sync is not configured")
        report = sync_runner()
        query = urlencode(
            {
                "imported": report.imported,
                "analyzed": report.analyzed,
                "queued": report.queued,
                "failures": len(report.failures),
            }
        )
        return RedirectResponse(f"/?{query}", status_code=303)

    @app.get("/events/{event_key}.ics")
    def event_calendar(event_key: str) -> Response:
        view = database.get_event(event_key)
        if view is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return Response(
            render_ics(view.event),
            media_type="text/calendar",
            headers={"Content-Disposition": f'attachment; filename="{event_key}.ics"'},
        )

    @app.get("/events/{event_key}", response_class=HTMLResponse)
    def event_detail(request: Request, event_key: str) -> Response:
        view = database.get_event(event_key)
        if view is None:
            raise HTTPException(status_code=404, detail="Event not found")
        context = _template_context(request, view.event.title)
        context.update({"row": _row(view, database.get_criteria())})
        return templates.TemplateResponse(request, "event.html", context)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> Response:
        context = _template_context(request, "Matching settings")
        context.update({"criteria": database.get_criteria(), "errors": []})
        return templates.TemplateResponse(request, "settings.html", context)

    @app.post("/settings", response_class=HTMLResponse)
    def save_settings(
        request: Request,
        csrf_token: Annotated[str | None, Form()] = None,
        require_online: Annotated[str | None, Form()] = None,
        max_team_size: Annotated[str | None, Form()] = None,
        max_duration_hours: Annotated[str | None, Form()] = None,
        require_prize: Annotated[str | None, Form()] = None,
        allowed_schedule_modes: Annotated[list[str] | None, Form()] = None,
    ) -> Response:
        require_csrf(csrf_token)
        try:
            criteria = Criteria(
                require_online=require_online == "on",
                max_team_size=_optional_int(max_team_size),
                max_duration_hours=_optional_int(max_duration_hours),
                require_prize=require_prize == "on",
                allowed_schedule_modes={
                    ScheduleMode(value) for value in (allowed_schedule_modes or [])
                },
                version=database.get_criteria().version,
            )
        except (ValueError, ValidationError) as error:
            context = _template_context(request, "Matching settings")
            context.update({"criteria": database.get_criteria(), "errors": [str(error)]})
            return templates.TemplateResponse(request, "settings.html", context, status_code=400)
        database.save_criteria(criteria)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.get("/alerts", response_class=HTMLResponse)
    def alerts(request: Request) -> Response:
        records: list[tuple[OutboxRecord, AlertMessage]] = [
            (record, AlertMessage.model_validate_json(record.payload_json))
            for record in database.list_outbox()
        ]
        context = _template_context(request, "Alert history")
        context.update({"records": records, "send_enabled": settings.send_enabled})
        return templates.TemplateResponse(request, "alerts.html", context)

    @app.get("/healthz", response_class=JSONResponse)
    def health() -> dict[str, str]:
        database.get_criteria()
        return {"status": "ok", "database": "ok"}

    return app
