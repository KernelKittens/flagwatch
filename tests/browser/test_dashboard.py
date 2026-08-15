from __future__ import annotations

from pathlib import Path

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

ARTIFACTS = Path(__file__).parents[2] / "artifacts"


def test_dashboard_keyboard_accessibility_and_desktop_layout(page: Page, live_server: str):
    page.set_viewport_size({"width": 1440, "height": 1100})
    page.goto(live_server)

    page.keyboard.press("Tab")
    assert page.locator(":focus").get_attribute("href") == "#main-content"
    results = Axe().run(page)
    assert results.violations_count == 0, results.generate_report()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    ARTIFACTS.mkdir(exist_ok=True)
    page.screenshot(path=ARTIFACTS / "flagwatch-dashboard-1440.png", full_page=True)


def test_dashboard_has_no_mobile_overflow(page: Page, live_server: str):
    page.set_viewport_size({"width": 320, "height": 900})
    page.goto(live_server)

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    ARTIFACTS.mkdir(exist_ok=True)
    page.screenshot(path=ARTIFACTS / "flagwatch-dashboard-320.png", full_page=True)


@pytest.mark.parametrize(
    "path",
    ["/", "/events/ctftime:browser-fixture", "/settings", "/alerts"],
)
def test_every_page_has_no_axe_violations(page: Page, live_server: str, path: str):
    page.goto(f"{live_server}{path}")

    results = Axe().run(page)

    assert results.violations_count == 0, results.generate_report()
