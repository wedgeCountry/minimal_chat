"""GUI-Tests der User Journey mit Playwright (gegen lokales uvicorn + Mock-LLM).

Alle Selektoren laufen ueber die ``data-testid``-Attribute der UI-Elemente.
"""

from __future__ import annotations

import base64
import os

import httpx
import pytest

pytestmark = pytest.mark.e2e

USER = {"username": "journey-user", "password": "geheim123"}
SYSTEM_PROMPT = "Du bist ein hilfsbereiter Assistent (Journey-System-Prompt)."

T = {
    "auth_overlay": '[data-testid="auth-overlay"]',
    "auth_username": '[data-testid="auth-username"]',
    "auth_password": '[data-testid="auth-password"]',
    "auth_submit": '[data-testid="auth-submit"]',
    "auth_switch": '[data-testid="auth-switch"]',
    "auth_error": '[data-testid="auth-error"]',
    "new_session": '[data-testid="new-session-tile"]',
    "session_tile": '[data-testid^="session-tile-"]',
    "chat": '[data-testid="chat"]',
    "chat_input": '[data-testid="chat-input"]',
    "send_btn": '[data-testid="send-btn"]',
    "burger_btn": '[data-testid="burger-btn"]',
    "settings_btn": '[data-testid="settings-btn"]',
    "logout_btn": '[data-testid="logout-btn"]',
    "settings_overlay": '[data-testid="settings-overlay"]',
    "set_show_system": '[data-testid="set-show-system"]',
    "set_save": '[data-testid="set-save"]',
}


def _bubble(role, type_="message"):
    return f'[data-testid="chat"] .bubble[data-role="{role}"][data-type="{type_}"]'


def _register_api(base_url, username, password):
    """Registriert einen User direkt per API und gibt das Token zurueck."""
    key = base64.b64encode(os.urandom(32)).decode()
    res = httpx.post(
        f"{base_url}/api/auth/register",
        json={"username": username, "password": password, "key": key},
        timeout=10,
    )
    assert res.status_code == 201, res.text
    return res.json()["token"]


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _login(page, base_url, username, password):
    page.goto(base_url)
    page.wait_for_selector(f'{T["auth_overlay"]}.open')
    page.fill(T["auth_username"], username)
    page.fill(T["auth_password"], password)
    page.click(T["auth_submit"])
    page.wait_for_selector(f'{T["auth_overlay"]}:not(.open)', state="attached")


def _chat_once(page, text, n):
    """Schickt die n-te Nachricht und wartet, bis der Mock-LLM geantwortet hat."""
    page.fill(T["chat_input"], text)
    page.click(T["send_btn"])
    page.wait_for_function(
        f"() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === {n}"
    )
    page.wait_for_function(
        f"() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === {n}"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')"
    )
    page.wait_for_function(
        """() => {
          const msgs = [...document.querySelectorAll('[data-testid="chat"] .bubble[data-role="assistant"][data-type="message"]')];
          const last = msgs[msgs.length - 1];
          return !!last && last.querySelector('[data-testid="bubble-body"]').textContent.includes('Hallo Welt');
        }"""
    )


def test_full_user_journey(page, base_url):
    # Setup: User per API anlegen, System-Prompt-Anzeige serverseitig deaktivieren
    # (damit er in der Journey "am Anfang versteckt" ist).
    token = _register_api(base_url, USER["username"], USER["password"])
    res = httpx.put(
        f"{base_url}/api/settings",
        headers=_auth_headers(token),
        json={"show_system_prompt": False},
        timeout=10,
    )
    assert res.status_code == 200, res.text

    # Alle confirm()-Dialoge (Session/Nachricht loeschen) automatisch bestaetigen.
    page.on("dialog", lambda d: d.accept())

    # 1. Anmelden
    _login(page, base_url, USER["username"], USER["password"])

    # 2. Neue Session eroeffnen
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')

    # System-Prompt als erste Nachricht der Session seeden (ueber API, id 1 -> ganz oben).
    sessions = httpx.get(f"{base_url}/api/sessions", headers=_auth_headers(token), timeout=10).json()
    sid = next(s["id"] for s in sessions if s["name"] == "Neue Session")
    res = httpx.post(
        f"{base_url}/api/sessions/{sid}/messages",
        headers=_auth_headers(token),
        json={"role": "system", "type": "message", "text": SYSTEM_PROMPT, "in_context": True},
        timeout=10,
    )
    assert res.status_code == 201, res.text

    # 3. Dreimal mit dem Agenten chatten (Mock-LLM antwortet "Hallo Welt")
    for i in (1, 2, 3):
        _chat_once(page, f"Nachricht {i}", i)
    assert page.locator(_bubble("user")).count() == 3
    assert page.locator(_bubble("assistant")).count() == 3

    # 4. Neue Session erstellen und einmal chatten
    page.click(T["new_session"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid^=\"session-tile-\"]').length === 2"
    )
    _chat_once(page, "Zweite Nachricht", 1)
    assert page.locator(_bubble("user")).count() == 1

    # 5. Erste Session umbenennen, zweite Session loeschen
    tile_first = page.locator(T["session_tile"], has_text="Nachricht 1")
    tile_first.locator('[data-testid^="session-rename-btn-"]').click()
    rename_input = page.locator('[data-testid^="session-rename-input-"]')
    rename_input.fill("Journey Eins")
    rename_input.press("Enter")
    page.wait_for_selector(f'{T["session_tile"]}:has-text("Journey Eins")')

    tile_second = page.locator(T["session_tile"], has_text="Zweite Nachricht")
    tile_second.locator('[data-testid^="session-delete-btn-"]').click()
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid^=\"session-tile-\"]').length === 1"
    )

    # 6. In die erste Session gehen und die letzten zwei Nachrichten loeschen
    #    (einmal Nutzernachricht, einmal LLM-Antwort)
    page.locator(T["session_tile"], has_text="Journey Eins").locator('[data-testid^="session-name-"]').click()
    page.wait_for_selector(_bubble("user"))
    assert page.locator(_bubble("user")).count() == 3
    page.locator(_bubble("user")).last.locator('[data-testid="bubble-delete-btn"]').click()
    page.wait_for_function(
        f"() => document.querySelectorAll('{T['chat']} .bubble[data-role=\"user\"]').length === 2"
    )
    page.locator(_bubble("assistant")).last.locator('[data-testid="bubble-delete-btn"]').click()
    page.wait_for_function(
        f"() => document.querySelectorAll('{T['chat']} .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 2"
    )
    assert page.locator(_bubble("user")).count() == 2
    assert page.locator(_bubble("assistant")).count() == 2

    # 7. Settings oeffnen: System-Prompt ist am Anfang versteckt, nach dem
    #    Aktivieren erscheint er als Message ganz oben im Chat
    page.click(T["burger_btn"])
    page.click(T["settings_btn"])
    page.wait_for_selector(f'{T["settings_overlay"]}.open')
    assert page.locator(_bubble("system")).count() == 0
    page.check(T["set_show_system"])
    page.click(T["set_save"])
    page.wait_for_selector(f'{T["settings_overlay"]}:not(.open)', state="attached")
    system_bubble = page.locator(_bubble("system"))
    system_bubble.wait_for()
    first_bubble = page.locator(f'{T["chat"]} > .bubble').first
    assert first_bubble.get_attribute("data-role") == "system"
    assert SYSTEM_PROMPT in system_bubble.locator('[data-testid="bubble-body"]').inner_text()

    # 8. Logout
    page.click(T["burger_btn"])
    page.click(T["logout_btn"])
    page.wait_for_selector(f'{T["auth_overlay"]}.open')


def test_login_rejects_wrong_password(page, base_url):
    _register_api(base_url, "journey-user-2", "geheim123")
    page.goto(base_url)
    page.wait_for_selector(f'{T["auth_overlay"]}.open')
    page.fill(T["auth_username"], "journey-user-2")
    page.fill(T["auth_password"], "falsches-passwort")
    page.click(T["auth_submit"])
    page.wait_for_selector(f'{T["auth_error"]}:not(:empty)')
    assert page.locator(f'{T["auth_overlay"]}.open').count() == 1
