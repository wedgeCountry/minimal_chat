"""GUI-Tests der User Journey mit Playwright (gegen lokales uvicorn + Mock-LLM)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

USER = {"username": "journey-user", "password": "geheim123"}


def _register(page, base_url):
    page.goto(base_url)
    page.wait_for_selector("#authOverlay.open")
    page.click("#authSwitch")
    page.fill("#authUser", USER["username"])
    page.fill("#authPass", USER["password"])
    page.click("#authSubmit")
    page.wait_for_selector("#authOverlay:not(.open)")


def test_full_user_journey(page, base_url):
    _register(page, base_url)

    page.click("#newTile")
    page.wait_for_selector(".tile.active")

    page.fill("#input", "Hallo vom GUI-Test")
    page.click("#sendBtn")

    page.wait_for_selector(".bubble.assistant .bubbleBody", timeout=10000)
    page.wait_for_function(
        "document.querySelector('.bubble.assistant .bubbleBody')?.textContent.includes('Hallo Welt')"
    )
    assert page.locator(".bubble.reasoning .bubbleBody").inner_text().strip() != ""
    assert "get_weather" in page.locator(".bubble.toolcall .bubbleBody").inner_text()

    session_name = page.locator(".tile.active .sessionName").inner_text()
    assert session_name == "Hallo vom GUI-Test"

    page.click("#burgerBtn")
    page.click("#settingsBtn")
    page.select_option("#setTheme", "dark")
    page.click("#setSave")
    page.wait_for_function("document.documentElement.classList.contains('dark')")

    page.click("#burgerBtn")
    page.click("#logoutBtn")
    page.wait_for_selector("#authOverlay.open")

    page.fill("#authUser", USER["username"])
    page.fill("#authPass", USER["password"])
    page.click("#authSubmit")
    page.wait_for_selector("#authOverlay:not(.open)")
    page.wait_for_selector(".tile.active .sessionName")
    assert page.locator(".tile.active .sessionName").inner_text() == "Hallo vom GUI-Test"
    page.wait_for_selector(".bubble.assistant .bubbleBody")
    assert "Hallo Welt" in page.locator(".bubble.assistant .bubbleBody").inner_text()


def test_login_rejects_wrong_password(page, base_url):
    _register(page, base_url)
    page.click("#burgerBtn")
    page.click("#logoutBtn")
    page.wait_for_selector("#authOverlay.open")
    page.fill("#authUser", USER["username"])
    page.fill("#authPass", "falsches-passwort")
    page.click("#authSubmit")
    page.wait_for_selector("#authErr:not(:empty)")
    assert page.locator("#authOverlay.open").count() == 1
