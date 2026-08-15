from __future__ import annotations

from pathlib import Path

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page, expect

ARTIFACTS = Path(__file__).parents[2] / "artifacts"
SAVED_ZONE_SCRIPT = "localStorage.setItem('flagwatch.timeZone', 'America/Chicago')"


def _open_august(page: Page, static_site_server: str) -> None:
    page.add_init_script(SAVED_ZONE_SCRIPT)
    page.goto(f"{static_site_server}/?month=2026-08")


def test_month_grid_navigation_multiday_and_crowded_dates(
    page: Page, static_site_server: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": 1100})
    _open_august(page, static_site_server)

    expect(page.get_by_role("heading", name="August 2026")).to_be_visible()
    headings = page.locator(".weekday")
    assert headings.all_text_contents() == ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    expect(page.get_by_role("grid", name="Month calendar")).to_be_visible()
    assert page.get_by_role("columnheader").count() == 7
    assert page.get_by_role("gridcell").count() == 42
    cells = page.locator(".calendar-cell")
    assert cells.count() == 42
    assert cells.first.get_attribute("data-date") == "2026-07-26"
    assert cells.last.get_attribute("data-date") == "2026-09-05"

    for date in ("2026-08-21", "2026-08-22", "2026-08-23"):
        expect(
            page.locator(f'[data-date="{date}"]').get_by_role(
                "button", name="Midwest Signal CTF", exact=True
            )
        ).to_be_visible()
    expect(page.locator('[data-date="2026-08-21"] .event-time').first).to_contain_text("10:00 AM")

    crowded = page.locator('[data-date="2026-08-22"]')
    expect(crowded.get_by_role("button", name="2 more events")).to_be_visible()
    crowded.get_by_role("button", name="2 more events").click()
    assert crowded.locator(".event-chip").count() == 5

    page.get_by_role("button", name="Next month").click()
    expect(page.get_by_role("heading", name="September 2026")).to_be_visible()
    assert "month=2026-09" in page.url
    page.get_by_role("button", name="Previous month").click()
    expect(page.get_by_role("heading", name="August 2026")).to_be_visible()

    ARTIFACTS.mkdir(exist_ok=True)
    page.screenshot(path=ARTIFACTS / "flagwatch-calendar-1440.png", full_page=True)


def test_direct_event_link_exposes_all_details_and_closes(
    page: Page, static_site_server: str
) -> None:
    page.add_init_script(SAVED_ZONE_SCRIPT)
    page.goto(f"{static_site_server}/?month=2026-08&event=ctftime%3Asignal-2026")

    dialog = page.get_by_role("dialog", name="Midwest Signal CTF")
    expect(dialog).to_be_visible()
    for text in (
        "AI assisted",
        "Teams may use interactive AI assistants.",
        "$2,500 prize pool",
        "4",
        "Open, Student",
        "Jeopardy",
        "42.50",
        "Fixed",
        "Online",
        "2 days 6 hours",
        "Signal Crew",
        "318",
        "Aug 21, 2026",
        "Aug 23, 2026",
    ):
        expect(dialog.get_by_text(text, exact=text in {"4", "42.50"})).to_be_visible()
    expect(dialog.get_by_role("link", name="Official event")).to_have_attribute(
        "href", "https://example.com/signal"
    )
    expect(dialog.get_by_role("link", name="CTFtime listing")).to_have_attribute(
        "href", "https://ctftime.org/event/2601"
    )
    expect(dialog.get_by_role("link", name="AI policy source")).to_have_attribute(
        "href", "https://example.com/signal/rules"
    )
    expect(dialog.get_by_role("link", name="Download ICS")).to_have_attribute(
        "download", "midwest-signal-ctf.ics"
    )

    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    assert "event=" not in page.url

    page.get_by_role("button", name="Midwest Signal CTF", exact=True).first.click()
    expect(dialog).to_be_visible()
    page.locator("#event-dialog").click(position={"x": 1, "y": 1})
    expect(dialog).not_to_be_visible()


def test_phone_layout_has_selected_day_list_and_no_overflow(
    page: Page, static_site_server: str
) -> None:
    page.set_viewport_size({"width": 320, "height": 900})
    _open_august(page, static_site_server)

    page.locator('[data-date="2026-08-22"] .day-select').click()
    expect(page.locator('[data-date="2026-08-22"] .mobile-markers')).to_be_visible()
    selected = page.get_by_role("region", name="Selected day")
    expect(selected.get_by_role("heading", name="Saturday, August 22")).to_be_visible()
    expect(selected.get_by_role("button", name="Midwest Signal CTF", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    ARTIFACTS.mkdir(exist_ok=True)
    page.screenshot(path=ARTIFACTS / "flagwatch-calendar-320.png", full_page=True)


def test_first_visit_confirms_detected_timezone(page: Page, static_site_server: str) -> None:
    page.add_init_script(
        """
        localStorage.clear();
        const original = Intl.DateTimeFormat.prototype.resolvedOptions;
        Intl.DateTimeFormat.prototype.resolvedOptions = function () {
          return {...original.call(this), timeZone: 'America/New_York'};
        };
        """
    )
    page.goto(f"{static_site_server}/?month=2026-08")

    dialog = page.get_by_role("dialog", name="Confirm timezone")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("America/New_York", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Use America/New_York").click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_role("button", name="Change timezone: America/New_York")).to_be_visible()
    assert page.evaluate("localStorage.getItem('flagwatch.timeZone')") == "America/New_York"


def test_saved_timezone_skips_confirmation_and_can_be_changed(
    page: Page, static_site_server: str
) -> None:
    _open_august(page, static_site_server)

    expect(page.get_by_role("dialog", name="Confirm timezone")).not_to_be_visible()
    page.get_by_role("button", name="Change timezone: America/Chicago").click()
    chooser = page.get_by_role("dialog", name="Change timezone")
    chooser.get_by_label("Timezone").select_option("Europe/London")
    chooser.get_by_role("button", name="Save timezone").click()
    expect(page.get_by_role("button", name="Change timezone: Europe/London")).to_be_visible()
    assert page.evaluate("localStorage.getItem('flagwatch.timeZone')") == "Europe/London"


def test_invalid_detection_falls_back_to_america_chicago(
    page: Page, static_site_server: str
) -> None:
    page.add_init_script(
        """
        localStorage.clear();
        Intl.DateTimeFormat.prototype.resolvedOptions = () => ({timeZone: ''});
        """
    )
    page.goto(f"{static_site_server}/?month=2026-08")

    dialog = page.get_by_role("dialog", name="Confirm timezone")
    expect(dialog.get_by_text("America/Chicago", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Use America/Chicago")).to_be_visible()


def test_invalid_saved_timezone_falls_back_safely(page: Page, static_site_server: str) -> None:
    page.add_init_script("localStorage.setItem('flagwatch.timeZone', 'Not/AZone')")
    page.goto(f"{static_site_server}/?month=2026-08")

    dialog = page.get_by_role("dialog", name="Confirm timezone")
    expect(dialog.get_by_text("America/Chicago", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="August 2026")).to_be_visible()


def test_browser_back_restores_previous_month_and_closes_event(
    page: Page, static_site_server: str
) -> None:
    _open_august(page, static_site_server)
    page.get_by_role("button", name="Next month").click()
    expect(page.get_by_role("heading", name="September 2026")).to_be_visible()
    page.go_back()
    expect(page.get_by_role("heading", name="August 2026")).to_be_visible()

    page.get_by_role("button", name="Midwest Signal CTF", exact=True).first.click()
    expect(page.get_by_role("dialog", name="Midwest Signal CTF")).to_be_visible()
    page.go_back()
    expect(page.get_by_role("dialog", name="Midwest Signal CTF")).not_to_be_visible()


def test_public_calendar_has_no_axe_violations(page: Page, static_site_server: str) -> None:
    _open_august(page, static_site_server)

    results = Axe().run(page)

    assert results.violations_count == 0, results.generate_report()
