"""GUI-Tests der User Journey mit Playwright (gegen lokales uvicorn + Mock-LLM).

Alle Selektoren laufen ueber die ``data-testid``-Attribute der UI-Elemente.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e

USER = {"email": "journey-user@example.com", "password": "Geheim-123"}
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
    "confirm_overlay": '[data-testid="confirm-overlay"]',
    "confirm_ok": '[data-testid="confirm-ok"]',
}


def _confirm_delete(page):
    """Bestaetigt den Lösch-Overlay-Modal."""
    page.wait_for_selector(f'{T["confirm_overlay"]}.open')
    page.click(T["confirm_ok"])
    page.wait_for_selector(f'{T["confirm_overlay"]}:not(.open)', state="attached")


def _bubble(role, type_="message"):
    return f'[data-testid="chat"] .bubble[data-role="{role}"][data-type="{type_}"]'


def _register_client(base_url, email, password):
    """Registriert einen User direkt per API; der Client haelt danach den Session-Cookie."""
    client = httpx.Client(base_url=base_url, timeout=10)
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.text
    return client


def _login(page, base_url, email, password):
    page.goto(base_url)
    page.wait_for_selector(f'{T["auth_overlay"]}.open')
    page.fill(T["auth_username"], email)
    page.fill(T["auth_password"], password)
    page.click(T["auth_submit"])
    page.wait_for_selector(f'{T["auth_overlay"]}:not(.open)', state="attached")


def _chat_once(page, text, n, expect, timeout_ms, attach=None):
    """Schickt die n-te Nachricht (optional mit Datei-Anhang) und wartet auf die LLM-Antwort.

    ``expect=None`` wartet auf eine beliebige nicht-leere Antwort (echtes LLM).
    """
    if attach is not None:
        page.set_input_files('[data-testid="file-input"]', attach)
        page.wait_for_selector('[data-testid^="attachment-chip-"]')
    page.fill(T["chat_input"], text)
    page.click(T["send_btn"])
    page.wait_for_function(
        f"() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === {n}",
        timeout=timeout_ms,
    )
    page.wait_for_function(
        f"() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === {n}"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=timeout_ms,
    )
    if expect:
        page.wait_for_function(
            f"""() => {{
              const msgs = [...document.querySelectorAll('[data-testid="chat"] .bubble[data-role="assistant"][data-type="message"]')];
              const last = msgs[msgs.length - 1];
              return !!last && last.querySelector('[data-testid="bubble-body"]').textContent.includes({expect!r});
            }}""",
            timeout=timeout_ms,
        )
    else:
        page.wait_for_function(
            """() => {
              const msgs = [...document.querySelectorAll('[data-testid="chat"] .bubble[data-role="assistant"][data-type="message"]')];
              const last = msgs[msgs.length - 1];
              return !!last && last.querySelector('[data-testid="bubble-body"]').textContent.trim() !== '';
            }""",
            timeout=timeout_ms,
        )


def test_full_user_journey(page, base_url, tmp_path, llm_expect):
    # Setup: User per API anlegen, System-Prompt-Anzeige serverseitig deaktivieren
    # (damit er in der Journey "am Anfang versteckt" ist).
    api_client = _register_client(base_url, USER["email"], USER["password"])
    res = api_client.put("/api/settings", json={"show_system_prompt": False})
    assert res.status_code == 200, res.text

    # 1. Anmelden
    _login(page, base_url, USER["email"], USER["password"])

    # 2. Neue Session eroeffnen
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')

    # System-Prompt als erste Nachricht der Session seeden (ueber API, id 1 -> ganz oben).
    sessions = api_client.get("/api/sessions").json()
    sid = next(s["id"] for s in sessions if s["name"] == "Neue Session")
    res = api_client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "system", "type": "message", "text": SYSTEM_PROMPT, "in_context": True},
    )
    assert res.status_code == 201, res.text

    # 3. Dreimal mit dem Agenten chatten (Mock-LLM); beim zweiten Chat hängt der
    #    Nutzer eine Textdatei mit geheimem Wort an und fragt danach — das LLM
    #    antwortet mit dem Dateiinhalt.
    secret_file = tmp_path / "geheim.txt"
    secret_file.write_text("Krokodil-Ledertasche", encoding="utf-8")
    _chat_once(page, "Nachricht 1", 1, llm_expect["default"], llm_expect["timeout_ms"])
    _chat_once(page, "Was steht in der Datei?", 2, llm_expect["file"], llm_expect["timeout_ms"], attach=secret_file)
    _chat_once(page, "Nachricht 3", 3, llm_expect["default"], llm_expect["timeout_ms"])
    assert page.locator(_bubble("user")).count() == 3
    assert page.locator(_bubble("assistant")).count() == 3
    assert "Krokodil-Ledertasche" in (
        page.locator(_bubble("assistant")).nth(1).locator('[data-testid="bubble-body"]').inner_text()
    )

    # 4. Neue Session erstellen und einmal chatten
    page.click(T["new_session"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid^=\"session-tile-\"]').length === 2"
    )
    _chat_once(page, "Zweite Nachricht", 1, llm_expect["default"], llm_expect["timeout_ms"])
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
    _confirm_delete(page)
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid^=\"session-tile-\"]').length === 1"
    )

    # 6. In die erste Session gehen und die letzten zwei Nachrichten loeschen
    #    (einmal Nutzernachricht, einmal LLM-Antwort)
    page.locator(T["session_tile"], has_text="Journey Eins").locator('[data-testid^="session-name-"]').click()
    page.wait_for_selector(_bubble("user"))
    assert page.locator(_bubble("user")).count() == 3
    page.locator(_bubble("user")).last.locator('[data-testid="bubble-delete-btn"]').click()
    _confirm_delete(page)
    page.wait_for_function(
        f"() => document.querySelectorAll('{T['chat']} .bubble[data-role=\"user\"]').length === 2"
    )
    page.locator(_bubble("assistant")).last.locator('[data-testid="bubble-delete-btn"]').click()
    _confirm_delete(page)
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
    _register_client(base_url, "journey-user-2@example.com", "Geheim-123")
    page.goto(base_url)
    page.wait_for_selector(f'{T["auth_overlay"]}.open')
    page.fill(T["auth_username"], "journey-user-2@example.com")
    page.fill(T["auth_password"], "Falsch-123")
    page.click(T["auth_submit"])
    page.wait_for_selector(f'{T["auth_error"]}:not(:empty)')
    assert page.locator(f'{T["auth_overlay"]}.open').count() == 1
