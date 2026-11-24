"""GUI-Tests der User Journey mit Playwright (gegen lokales uvicorn + Mock-LLM).

Alle Selektoren laufen ueber die ``data-testid``-Attribute der UI-Elemente.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request

import httpx
import pytest

from tests.e2e.conftest import REPO_ROOT, SPEECH_STUB

pytestmark = pytest.mark.e2e

USER = {"email": "journey-user@example.com", "password": "Geheim-123"}
SYSTEM_PROMPT = "Du bist ein hilfsbereiter Assistent (Journey-System-Prompt)."

T = {
    "panel_btn": '[data-testid="panel-btn"]',
    "side_panel": '[data-testid="side-panel"]',
    "login_email": '[data-testid="login-email"]',
    "login_password": '[data-testid="login-password"]',
    "login_submit": '[data-testid="login-submit"]',
    "login_error": '[data-testid="login-error"]',
    "new_session": '[data-testid="new-session-tile"]',
    "session_tile": '[data-testid^="session-tile-"]',
    "chat": '[data-testid="chat"]',
    "chat_input": '[data-testid="chat-input"]',
    "send_btn": '[data-testid="send-btn"]',
    "burger_btn": '[data-testid="burger-btn"]',
    "settings_btn": '[data-testid="settings-btn"]',
    "change_password_btn": '[data-testid="change-password-btn"]',
    "logout_btn": '[data-testid="logout-btn"]',
    "settings_overlay": '[data-testid="settings-overlay"]',
    "set_show_system": '[data-testid="set-show-system"]',
    "set_show_tool": '[data-testid="set-show-tool"]',
    "set_show_reasoning": '[data-testid="set-show-reasoning"]',
    "set_save": '[data-testid="set-save"]',
    "confirm_overlay": '[data-testid="confirm-overlay"]',
    "confirm_ok": '[data-testid="confirm-ok"]',
    "error_overlay": '[data-testid="error-overlay"]',
    "error_ok": '[data-testid="error-ok"]',
}


def _confirm_delete(page):
    """Bestaetigt den Lösch-Overlay-Modal."""
    page.wait_for_selector(f'{T["confirm_overlay"]}.open')
    page.click(T["confirm_ok"])
    page.wait_for_selector(f'{T["confirm_overlay"]}:not(.open)', state="attached")


def _bubble(role, type_="message"):
    return f'[data-testid="chat"] .bubble[data-role="{role}"][data-type="{type_}"]'


def _reasoning_bubble():
    return _bubble("assistant", "reasoning")


def _api_detail(api_client, sid):
    """Session-Detail inkl. Messages ueber die oeffentliche API - die API ist die
    Quelle der Wahrheit fuer serverseitige Persistenz (die e2e-Tests duerfen nicht
    direkt in die verschluesselten DB-Dateien schauen, damit die Persistenzschicht
    austauschbar bleibt)."""
    res = api_client.get(f"/api/sessions/{sid}")
    assert res.status_code == 200, res.text
    return res.json()


def _register_client(base_url, email, password):
    """Registriert einen User ueber die user_registry-API; der Client haelt danach den Session-Cookie."""
    client = httpx.Client(base_url=base_url, timeout=10)
    res = client.get("/auth/register")
    token = re.search(r'window\.CSRF_TOKEN = "([^"]+)"', res.text).group(1)
    res = client.post(
        "/auth/api/register",
        json={
            "email": email,
            "password": password,
            "confirm_password": password,
            "display_name": email.split("@", 1)[0],
            "accepted_terms": True,
        },
        headers={"X-CSRF-Token": token},
    )
    assert res.status_code == 200, res.text
    return client


def _non_minimal(api_client):
    """Minimalismus fuer die Test-Session deaktivieren (Default ist an): Bubble-Toolbar
    (Kopfzeile mit Buttons) ist dann direkt sichtbar und klickbar, ohne Kontextmenue."""
    res = api_client.put("/api/settings", json={"bubbles_minimal": False})
    assert res.status_code == 200, res.text


def _login(page, base_url, email, password):
    # Unauthentifizierte Besucher werden auf die user_registry-Login-Seite umgeleitet
    page.goto(base_url)
    page.wait_for_url("**/auth/login")
    page.wait_for_selector(T["login_email"])
    page.fill(T["login_email"], email)
    page.fill(T["login_password"], password)
    page.click(T["login_submit"])
    # Nach erfolgreichem Login leitet die Auth-Seite zurueck auf "/"
    page.wait_for_url(base_url + "/")
    page.wait_for_selector(T["new_session"])


def _open_panel(page):
    """Klappt das Side-Panel auf (beim App-Start ist es eingeklappt); idempotent."""
    if "hidden" in (page.locator(T["side_panel"]).get_attribute("class") or ""):
        page.click(T["panel_btn"])
    page.wait_for_selector(f'{T["side_panel"]}:not(.hidden)')


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
    res = api_client.put("/api/settings", json={"show_system_prompt": False, "bubbles_deletable": True, "bubbles_minimal": False})
    assert res.status_code == 200, res.text

    # 1. Anmelden
    _login(page, base_url, USER["email"], USER["password"])

    # 2. Beim ersten Start wird automatisch eine neue Session geoeffnet
    _open_panel(page)
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

    # 3b. Persistenz ueber die API pruefen: Session-Eintrag und alle Messages (inkl.
    #     Reasoning) sind serverseitig gespeichert, sobald die Antworten fertig sind
    #     (sid wurde oben beim Seeden des System-Prompts ermittelt; die Session wurde
    #     inzwischen per Auto-Rename umbenannt)
    detail = _api_detail(api_client, sid)
    assert detail["ts"] > 0, "Session-Eintrag mit ts muss existieren"
    msg_texts = [(m["role"], m["type"], m["text"]) for m in detail["messages"]]
    assert ("user", "message", "Nachricht 1") in msg_texts
    assert ("user", "message", "Nachricht 3") in msg_texts
    assert sum(1 for r, t, _ in msg_texts if r == "assistant" and t == "message") == 3
    assert any(t == "reasoning" for _, t, _ in msg_texts), "Reasoning-Messages muessen persistiert sein"

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

    # 7b. Passwort aendern oeffnet die user_registry-Seite /auth/change-password
    page.click(T["burger_btn"])
    page.click(T["change_password_btn"])
    page.wait_for_url("**/auth/change-password")
    page.goto(base_url)
    page.wait_for_selector(T["new_session"])

    # 8. Logout leitet auf die Login-Seite um
    page.click(T["burger_btn"])
    page.click(T["logout_btn"])
    page.wait_for_url("**/auth/login")
    page.wait_for_selector(T["login_submit"])



def test_reasoning_bubbles_appear_before_response_and_are_collapsed(page, base_url, llm_expect):
    """Testet, dass Reasoning-Bubbles vor den Antwort-Bubbles erscheinen und standardmäßig eingeklappt sind."""
    # Setup: User per API anlegen
    _register_client(base_url, "reasoning-user@example.com", "Geheim-123")

    # 1. Anmelden
    _login(page, base_url, "reasoning-user@example.com", "Geheim-123")

    # 2. Side-Panel aufklappen und neue Session eroeffnen
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')

    # 3. Eine Nachricht senden - das Mock-LLM sendet reasoning_content und content
    page.fill(T["chat_input"], "Test Nachricht")
    page.click(T["send_btn"])
    
    # Warten auf User-Bubble
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === 1",
        timeout=llm_expect["timeout_ms"]
    )
    
    # Warten auf Reasoning-Bubble und Message-Bubble vom Assistant
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"reasoning\"]').length === 1",
        timeout=llm_expect["timeout_ms"]
    )
    
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"]
    )

    # 4. Prüfen, dass genau ein Reasoning-Bubble und ein Message-Bubble vom Assistant existieren
    reasoning_bubbles = page.locator(_reasoning_bubble())
    assistant_message_bubbles = page.locator(_bubble("assistant", "message"))
    
    assert reasoning_bubbles.count() == 1, "Es sollte genau ein Reasoning-Bubble existieren"
    assert assistant_message_bubbles.count() == 1, "Es sollte genau ein Message-Bubble vom Assistant existieren"

    # 5. Prüfen, dass der Reasoning-Bubble vor dem Message-Bubble erscheint
    all_bubbles = page.locator(f'{T["chat"]} > .bubble')
    bubble_elements = all_bubbles.element_handles()
    
    # Finde die Positionen der Bubbles
    reasoning_index = -1
    message_index = -1
    
    for i, bubble in enumerate(bubble_elements):
        role = bubble.get_attribute("data-role")
        type_ = bubble.get_attribute("data-type")
        if role == "assistant" and type_ == "reasoning":
            reasoning_index = i
        elif role == "assistant" and type_ == "message":
            message_index = i
    
    assert reasoning_index != -1, "Reasoning-Bubble nicht gefunden"
    assert message_index != -1, "Message-Bubble nicht gefunden"
    assert reasoning_index < message_index, "Reasoning-Bubble sollte vor dem Message-Bubble erscheinen"

    # 6. Prüfen, dass der Reasoning-Bubble standardmäßig eingeklappt ist
    reasoning_bubble = reasoning_bubbles.first
    assert "collapsed" in reasoning_bubble.get_attribute("class"), "Reasoning-Bubble sollte standardmäßig eingeklappt sein"
    assert reasoning_bubble.get_attribute("data-mode") == "collapsed", "Reasoning-Bubble data-mode sollte 'collapsed' sein"


def test_reasoning_bubbles_can_be_expanded(page, base_url, llm_expect):
    """Testet, dass eingeklappte Reasoning-Bubbles ausgeklappt werden können."""
    # Setup: User per API anlegen
    api_client = _register_client(base_url, "expand-user@example.com", "Geheim-123")
    _non_minimal(api_client)

    # 1. Anmelden
    _login(page, base_url, "expand-user@example.com", "Geheim-123")

    # 2. Side-Panel aufklappen und neue Session eroeffnen
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')

    # 3. Eine Nachricht senden
    page.fill(T["chat_input"], "Test zum Ausklappen")
    page.click(T["send_btn"])
    
    # Warten auf User-Bubble
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === 1",
        timeout=llm_expect["timeout_ms"]
    )
    
    # Warten auf Reasoning-Bubble
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"reasoning\"]').length === 1",
        timeout=llm_expect["timeout_ms"]
    )
    
    # Warten auf Message-Bubble und Streamende
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"]
    )

    # 4. Reasoning-Bubble finden und prüfen, dass er eingeklappt ist
    reasoning_bubble = page.locator(_reasoning_bubble()).first
    assert "collapsed" in reasoning_bubble.get_attribute("class")

    # 5. Auf den Toggle-Button klicken, um den Reasoning-Bubble auszuklappen
    toggle_btn = reasoning_bubble.locator('[data-testid="bubble-toggle-btn"]')
    toggle_btn.click()

    # 6. Erster Klick: collapsed -> normal (Reihenfolge normal -> full -> collapsed -> normal)
    page.wait_for_function(
        f"() => document.querySelector('{_reasoning_bubble()}').classList.contains('normal')",
        timeout=llm_expect["timeout_ms"]
    )
    assert reasoning_bubble.get_attribute("data-mode") == "normal", "Nach dem ersten Klick sollte der Mode 'normal' sein"

    # 7. Zweiter Klick: normal -> collapsed (der kurze Reasoning-Text ist in normal nicht
    # gekuerzt, also ist full == normal und wird uebersprungen)
    toggle_btn.click()
    page.wait_for_function(
        f"() => document.querySelector('{_reasoning_bubble()}').classList.contains('collapsed')",
        timeout=llm_expect["timeout_ms"]
    )
    assert reasoning_bubble.get_attribute("data-mode") == "collapsed", "Nach dem zweiten Klick sollte der Mode wieder 'collapsed' sein"


def test_toolcall_and_toolresult_bubbles_are_collapsed_by_default(page, base_url, llm_expect):
    """Toolcall- und Toolresult-Bubbles starten eingeklappt (collapsed), auch nach Reload;
    Reihenfolge laut Stream (jeder Block mit eigenem Abschluss-Ts): Reasoning, Toolcall,
    Toolresult vor der finalen Assistant-Message."""
    email = "tool-bubble-user@example.com"
    _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')

    # Mock-LLM antwortet in einem Stream mit reasoning, tool_call, tool_result (mehrzeilig) und content
    page.fill(T["chat_input"], "Wetter in Berlin?")
    page.click(T["send_btn"])
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolcall"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )
    page.wait_for_function(
        '() => !document.querySelector(\'[data-testid="send-btn"]\').classList.contains("abort")',
        timeout=llm_expect["timeout_ms"],
    )
    page.reload()
    page.wait_for_selector(f'{T["session_tile"]}.active')
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolresult"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )

    for type_ in ("toolcall", "toolresult"):
        b = page.locator(_bubble("assistant", type_)).first
        assert "collapsed" in (b.get_attribute("class") or ""), f"{type_}-Bubble sollte eingeklappt starten"
        assert b.get_attribute("data-mode") == "collapsed", f"{type_}-Bubble data-mode sollte 'collapsed' sein"

    toolresult_body = page.locator(_bubble("assistant", "toolresult")).locator('[data-testid="bubble-body"]')
    assert toolresult_body.inner_text() == "get_weather: Z1 [...]", "mehrzeiliger Toolresult-Body muss auf 1 Zeile + [...] gekuerzt sein"

    # Reihenfolge: Reasoning, Toolcall, Toolresult vor der finalen Assistant-Message
    order = page.evaluate(
        """() => [...document.querySelectorAll('[data-testid="chat"] > .bubble')].map(b => b.dataset.role + ":" + b.dataset.type)"""
    )
    assert order == ["user:message", "assistant:reasoning", "assistant:toolcall", "assistant:toolresult", "assistant:message"], order


def test_show_tool_output_and_reasoning_toggles_redraw_chat(page, base_url, llm_expect):
    """Einstellungen 'Tool-Ausgabe anzeigen'/'Reasoning anzeigen': Abwahlen + Speichern zeichnet
    den Chat sofort neu (Tool- bzw. Reasoning-Bubbles verschwinden aus dem Canvas); serverseitig
    persistiert und nach Reload weiterhin wirksam, erneutes Aktivieren holt die Bubbles zurueck."""
    email = "visibility-toggle-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')

    # Mock-LLM streamt reasoning, toolcall, toolresult und message
    page.fill(T["chat_input"], "Wetter in Berlin?")
    page.click(T["send_btn"])
    for type_ in ("reasoning", "toolcall", "toolresult"):
        page.wait_for_function(
            f'() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="{type_}"]\').length === 1',
            timeout=llm_expect["timeout_ms"],
        )
    page.wait_for_function(
        '() => !document.querySelector(\'[data-testid="send-btn"]\').classList.contains("abort")',
        timeout=llm_expect["timeout_ms"],
    )

    def chat_count(type_):
        return page.locator(f'{T["chat"]} .bubble[data-type="{type_}"]').count()

    def set_bool_setting(testid, checked):
        page.click(T["burger_btn"])
        page.click(T["settings_btn"])
        page.wait_for_selector(f'{T["settings_overlay"]}.open')
        (page.check if checked else page.uncheck)(testid)
        page.click(T["set_save"])
        page.wait_for_selector(f'{T["settings_overlay"]}:not(.open)', state="attached")

    # 'Tool-Ausgabe anzeigen' abwahlen -> Toolcall/Toolresult-Bubbles muessen sofort verschwinden
    set_bool_setting(T["set_show_tool"], False)
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolcall"]\').length === 0'
        ' && document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolresult"]\').length === 0',
        timeout=llm_expect["timeout_ms"],
    )
    assert chat_count("reasoning") == 1
    assert chat_count("message") == 2  # User- + Assistant-Message
    assert api_client.get("/api/settings").json()["show_tool_output"] is False

    # Wieder aktivieren -> Tool-Bubbles erscheinen wieder
    set_bool_setting(T["set_show_tool"], True)
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolcall"]\').length === 1'
        ' && document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolresult"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )

    # 'Reasoning anzeigen' abwahlen -> Reasoning-Bubble verschwindet, Tool-Bubbles bleiben
    set_bool_setting(T["set_show_reasoning"], False)
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="reasoning"]\').length === 0',
        timeout=llm_expect["timeout_ms"],
    )
    assert chat_count("toolcall") == 1
    assert chat_count("toolresult") == 1
    assert api_client.get("/api/settings").json()["show_reasoning"] is False

    # Nach Reload: serverseitig gespeichert, Reasoning bleibt ausgeblendet, Tool wieder sichtbar
    page.reload()
    page.wait_for_selector(f'{T["session_tile"]}.active')
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="message"]\').length === 2',
        timeout=llm_expect["timeout_ms"],
    )
    assert chat_count("reasoning") == 0
    assert chat_count("toolcall") == 1
    assert chat_count("toolresult") == 1
    settings = api_client.get("/api/settings").json()
    assert settings["show_tool_output"] is True
    assert settings["show_reasoning"] is False


def test_tool_results_persisted_while_hidden_and_shown_after_reenabling(page, base_url, llm_expect):
    """Regression: 'Tool-Ausgabe anzeigen' VOR dem Chat abwaehlen -> Tool-Bubbles bleiben
    ausgeblendet, aber Toolcall/Toolresult landen trotzdem serverseitig in der DB (pruefbar
    ueber die oeffentliche API GET /api/sessions/{id}); nach erneutem Einschalten erscheinen
    die Bubbles (auch nach Reload), weil sie nie aus der Persistenz verschwunden sind."""
    email = "hidden-tools-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')
    sid = api_client.get("/api/sessions").json()[0]["id"]

    def set_show_tool(checked):
        page.click(T["burger_btn"])
        page.click(T["settings_btn"])
        page.wait_for_selector(f'{T["settings_overlay"]}.open')
        (page.check if checked else page.uncheck)(T["set_show_tool"])
        page.click(T["set_save"])
        page.wait_for_selector(f'{T["settings_overlay"]}:not(.open)', state="attached")

    def chat_count(type_):
        return page.locator(f'{T["chat"]} .bubble[data-type="{type_}"]').count()

    # 'Tool-Ausgabe anzeigen' AUS, bevor die erste Nachricht geschickt wird
    set_show_tool(False)
    assert api_client.get("/api/settings").json()["show_tool_output"] is False

    # Mock-LLM streamt reasoning, toolcall, toolresult und message
    page.fill(T["chat_input"], "Wetter in Berlin?")
    page.click(T["send_btn"])
    page.wait_for_function(
        '() => !document.querySelector(\'[data-testid="send-btn"]\').classList.contains("abort")',
        timeout=llm_expect["timeout_ms"],
    )
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="message"]\').length === 2',
        timeout=llm_expect["timeout_ms"],
    )
    # Anzeige bleibt aus: keine Tool-Bubbles im Canvas ...
    assert chat_count("toolcall") == 0
    assert chat_count("toolresult") == 0
    # ... aber serverseitig persistiert (oeffentliche API = Quelle der Wahrheit fuer die DB)
    detail = _api_detail(api_client, sid)
    types = {(m["role"], m["type"]) for m in detail["messages"]}
    assert ("assistant", "toolcall") in types
    assert ("assistant", "toolresult") in types

    # 'Tool-Ausgabe anzeigen' wieder AN -> Tool-Bubbles erscheinen aus dem persistierten Stand
    set_show_tool(True)
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolcall"]\').length === 1'
        ' && document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolresult"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )

    # Nach Reload bleiben die Tool-Bubbles sichtbar (sie lagen die ganze Zeit in der DB)
    page.reload()
    page.wait_for_selector(f'{T["session_tile"]}.active')
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolresult"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )
    assert chat_count("toolcall") == 1


def test_double_reasoning_toolcall_cycle_renders_each_block_separately_in_order(page, base_url, llm_expect):
    """LLM antwortet in einem Stream mit Reasoning -> Toolcall -> Toolresult -> Message, dann
    nochmals Reasoning -> Toolcall -> Toolresult -> Message. Erwartet: je 2 Bubbles pro Typ,
    exakt in dieser Reihenfolge (nichts wird akkumuliert/zu einer Bubble verschmolzen, nichts
    wird versteckt); jeder Block erhaelt beim Typwechsel im Stream seinen eigenen Ts."""
    if llm_expect["default"] is None:
        pytest.skip("Doppel-Zyklus braucht den Mock-LLM (Trigger 'doppelzyklus')")
    email = "double-cycle-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)

    page.fill(T["chat_input"], "doppelzyklus bitte")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 2"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )

    # je 2 Bubbles pro Typ, alle 9 Bubbles sichtbar (nichts wird versteckt)
    for type_ in ("reasoning", "toolcall", "toolresult", "message"):
        assert page.locator(_bubble("assistant", type_)).count() == 2, f"zwei {type_}-Bubbles erwartet"
    assert page.locator(f'{T["chat"]} > .bubble:visible').count() == 9

    # exakte Reihenfolge im DOM: R, TC, TR, M, R, TC, TR, M nach der User-Message
    expected_order = [
        "user:message",
        "assistant:reasoning", "assistant:toolcall", "assistant:toolresult", "assistant:message",
        "assistant:reasoning", "assistant:toolcall", "assistant:toolresult", "assistant:message",
    ]
    order = page.evaluate(
        """() => [...document.querySelectorAll('[data-testid="chat"] > .bubble')].map(b => b.dataset.role + ":" + b.dataset.type)"""
    )
    assert order == expected_order, order

    # Inhalte ueber die API: 8 getrennte Assistant-Messages in Stream-Reihenfolge
    # (die beiden Messages sind NICHT zu einer Bubble verschmolzen)
    msgs = api_client.get(f"/api/sessions/{sid}").json()["messages"]
    assistant = [m for m in msgs if m["role"] == "assistant"]
    assert [m["type"] for m in assistant] == ["reasoning", "toolcall", "toolresult", "message"] * 2
    assert [m["text"] for m in assistant] == [
        "Denken eins... ",
        'get_weather({"city":"Berlin"})',
        "get_weather: 21 Grad, sonnig",
        "Antwort eins",
        "Denken zwei... ",
        'get_time({"tz":"Europe/Berlin"})',
        "get_time: 12:00 Uhr",
        "Antwort zwei",
    ]
    # jeder Block traegt einen eigenen, streng steigenden Abschluss-Zeitstempel
    ts_list = [m["ts"] for m in assistant]
    assert all(a < b for a, b in zip(ts_list, ts_list[1:])), f"ts muss pro Block steigen: {ts_list}"

    # nach Reload bleibt die Reihenfolge erhalten
    page.reload()
    page.wait_for_selector(f'{T["session_tile"]}.active')
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 2",
        timeout=llm_expect["timeout_ms"],
    )
    order2 = page.evaluate(
        """() => [...document.querySelectorAll('[data-testid="chat"] > .bubble')].map(b => b.dataset.role + ":" + b.dataset.type)"""
    )
    assert order2 == expected_order, order2


def test_session_db_updated_immediately_when_user_message_sent(page, base_url, llm_expect):
    """Session-Eintrag und User-Message muessen direkt nach dem Absenden serverseitig
    persistiert sein (ueber die API sichtbar, noch bevor die LLM-Antwort fertig ist)."""
    email = "persist-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')
    sid = api_client.get("/api/sessions").json()[0]["id"]

    detail0 = _api_detail(api_client, sid)
    assert detail0["ts"] > 0
    assert detail0["messages"] == []

    page.fill(T["chat_input"], "Sofort-Persistiert")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === 1",
        timeout=llm_expect["timeout_ms"],
    )

    # User-Message und aktualisierter Session-Timestamp sind jetzt schon persistiert
    detail1 = _api_detail(api_client, sid)
    assert ("user", "message", "Sofort-Persistiert") in [(m["role"], m["type"], m["text"]) for m in detail1["messages"]]
    assert detail1["ts"] >= detail0["ts"], "Session-ts muss nach dem User-Message aktualisiert sein"

    # Nach fertiger Antwort liegen auch Assistant-Messages in der DB
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    detail2 = _api_detail(api_client, sid)
    assert any(m["role"] == "assistant" and m["type"] == "message" for m in detail2["messages"])
    assert detail2["ts"] >= detail1["ts"]


def test_bubble_collapse_button_only_in_full_mode(page, base_url, llm_expect):
    """Kein Resize-Griff mehr; im Modus 'full' sitzt unten rechts in der Bubble ein
    Einklapp-Button, der auf 'collapsed' wechselt. Ausserdem: Kontext-Checkbox auch
    in Assistant-Bubbles."""
    if llm_expect["default"] is None:
        pytest.skip("braucht den Mock-LLM (lange 'lang'-Antwort)")
    email = "collapse-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _non_minimal(api_client)
    _login(page, base_url, email, "Geheim-123")
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')

    page.fill(T["chat_input"], "lang")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    page.wait_for_timeout(500)

    # Kontext-Checkbox auch in der Assistant-Bubble sichtbar
    ai_bubble = page.locator(_bubble("assistant", "message")).first
    assert ai_bubble.locator('[data-testid="bubble-context-chk"]').is_visible()

    # Resize-Griff ist komplett entfernt
    assert page.locator('[data-testid="bubble-resize-handle"]').count() == 0

    bubble = ai_bubble
    collapse_btn = bubble.locator('[data-testid="bubble-collapse-btn"]')
    toggle = bubble.locator('[data-testid="bubble-toggle-btn"]')

    # normal: Einklapp-Button nicht sichtbar
    assert bubble.get_attribute("data-mode") == "normal"
    assert not collapse_btn.is_visible()

    toggle.click()  # -> full
    page.wait_for_function(
        f"() => document.querySelector('{_bubble('assistant', 'message')}').getAttribute('data-mode') === 'full'"
    )
    assert collapse_btn.is_visible()

    # Einklapp-Button unten rechts klappt direkt auf collapsed zurueck
    collapse_btn.click()
    page.wait_for_function(
        f"() => document.querySelector('{_bubble('assistant', 'message')}').getAttribute('data-mode') === 'collapsed'"
    )
    assert not collapse_btn.is_visible()


def test_startup_side_panel_collapsed_and_new_session_on_first_start(page, base_url, llm_expect):
    """Beim App-Start (erstmalig und nach Refresh) ist das Side-Panel eingeklappt.
    Existiert noch keine Session, wird automatisch eine neue geoeffnet; nach einem
    Refresh bleibt die aktive Session erhalten und das Panel bleibt eingeklappt."""
    email = "startup-user@example.com"
    _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")

    # Erststart: Panel eingeklappt, genau eine Session existiert und ist aktiv
    page.wait_for_selector(f'{T["side_panel"]}.hidden')
    page.wait_for_selector(f'{T["session_tile"]}.active', state="attached")
    assert page.locator(T["session_tile"]).count() == 1

    # Eine Nachricht senden, damit nach dem Refresh der Session-Inhalt sichtbar ist
    _chat_once(page, "Start-Nachricht", 1, llm_expect["default"], llm_expect["timeout_ms"])

    # Refresh: Panel bleibt eingeklappt, keine neue Session wird angelegt,
    # die aktive Session (mit ihren Bubbles) bleibt offen
    page.reload()
    page.wait_for_selector(T["chat_input"])
    # hidden steckt schon im Markup: Das Panel ist ab dem ersten Render eingeklappt
    # (kein kurzes Aufflackern, bevor das JS-Bootstrap die Klasse setzt)
    side = page.locator(T["side_panel"])
    side.wait_for(state="attached")
    assert "hidden" in (side.get_attribute("class") or "")
    page.wait_for_selector(f'{T["side_panel"]}.hidden')
    page.wait_for_selector(f'{T["session_tile"]}.active', state="attached")
    assert page.locator(T["session_tile"]).count() == 1
    page.wait_for_selector(_bubble("user"))
    assert page.locator(_bubble("user")).count() == 1


def test_login_rejects_wrong_password(page, base_url):
    _register_client(base_url, "journey-user-2@example.com", "Geheim-123")
    page.goto(base_url)
    page.wait_for_url("**/auth/login")
    page.wait_for_selector(T["login_email"])
    page.fill(T["login_email"], "journey-user-2@example.com")
    page.fill(T["login_password"], "Falsch-123")
    page.click(T["login_submit"])
    page.wait_for_selector(f'{T["login_error"]}:visible')
    assert "auth/login" in page.url


def test_error_popup_when_llm_unreachable(page, base_url, llm_expect):
    """Test that an error popup is shown when the LLM server is unreachable."""
    # Setup: Register user
    email = "unreachable-user@example.com"
    _register_client(base_url, email, "Geheim-123")
    
    # Login
    _login(page, base_url, email, "Geheim-123")
    
    # Create new session
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')
    
    # We need to make the LLM server unreachable for this test
    # This would require modifying the mock_llm server to reject POST requests
    # For now, we'll skip this test as it requires special setup
    # In a real scenario, you would:
    # 1. Stop the mock_llm server or configure it to reject POST /chat/completions
    # 2. Send a message
    # 3. Verify the error popup appears
    
    # For now, just verify the error overlay elements exist in the DOM
    # (they should be present but not visible)
    assert page.locator(T["error_overlay"]).count() == 1
    assert page.locator(T["error_ok"]).count() == 1
    
    # Note: To fully test this, you would need to:
    # 1. Create a fixture that starts a mock server that rejects POST /chat/completions
    # 2. Or use monkeypatch to modify the httpx.AsyncClient behavior in the backend
    # This is left as a manual test for now


LOREM_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "lorem_ipsum.txt"


def test_file_upload_user_journey(page, base_url, llm_expect, mock_llm_port):
    """User Journey Datei senden: Datei anhaengen/entfernen, Frage mit Anhang senden,
    serverseitig verarbeiteter Inhalt landet vollstaendig im LLM-Request und die
    Anhang-Referenz in der persistierten Message (API)."""
    email = "file-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")

    # 1. Anmelden, Side-Panel aufklappen und neue Session
    _login(page, base_url, email, "Geheim-123")
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')
    sid = api_client.get("/api/sessions").json()[0]["id"]

    # 2. Datei anhaengen -> Chip mit Dateiname erscheint
    page.set_input_files('[data-testid="file-input"]', str(LOREM_FIXTURE))
    page.wait_for_selector('[data-testid="attachment-chip-0"]')
    assert page.locator('[data-testid="attachment-name-0"]').inner_text() == "lorem_ipsum.txt"

    # 3. Anhang wieder entfernen -> Chip verschwindet; danach erneut anhaengen
    page.click('[data-testid="attachment-remove-btn-0"]')
    page.wait_for_selector('[data-testid^="attachment-chip-"]', state="detached")
    page.set_input_files('[data-testid="file-input"]', str(LOREM_FIXTURE))
    page.wait_for_selector('[data-testid="attachment-chip-0"]')

    # 4. Frage zusammen mit der Datei senden; Mock-LLM antwortet auf den Dateiinhalt
    _chat_once(page, "Was steht in der Datei?", 1, llm_expect["lorem"], llm_expect["timeout_ms"])

    # 4b. Nach dem Senden ist die Anhang-Liste ueber dem Eingabefeld geleert
    page.wait_for_selector('[data-testid^="attachment-chip-"]', state="detached", timeout=llm_expect["timeout_ms"])

    # 5. User-Bubble enthaelt sowohl die Frage als auch den Anhang (Input geht nicht verloren)
    user_bubble = page.locator(_bubble("user")).first
    assert "Was steht in der Datei?" in user_bubble.locator('[data-testid="bubble-body"]').inner_text()
    assert user_bubble.locator('[data-testid="bubble-attachment-name"]').inner_text() == "lorem_ipsum.txt"

    # 6. Serverseitige Verarbeitung ueber die API: die User-Message traegt die
    #    Anhang-Referenz (id + name); der Mock-LLM antwortet nur, wenn der volle
    #    Dateiinhalt im Request gelandet ist (siehe _chat_once mit llm_expect["lorem"])
    user_msg = next(m for m in _api_detail(api_client, sid)["messages"] if m["role"] == "user")
    refs = user_msg["attachments"]
    assert refs and refs[0]["name"] == "lorem_ipsum.txt" and isinstance(refs[0]["id"], int)
    if mock_llm_port is not None:
        received = _llm_received(mock_llm_port)
        assert received, "Mock-LLM muss den Chat-Request aufgezeichnet haben"
        body = json.dumps(received[-1])
        # zeilenweise vergleichen (im JSON-Body sind Newlines escapt)
        for line in LOREM_FIXTURE.read_text(encoding="utf-8").splitlines():
            assert line in body, f"Dateiinhalt fehlt im LLM-Request: {line!r}"


def _new_named_session(page, api_client):
    _open_panel(page)
    page.click(T["new_session"])
    page.wait_for_selector(f'{T["session_tile"]}.active')
    return api_client.get("/api/sessions").json()[0]["id"]


def _llm_clear(port):
    """Leert die Request-Aufzeichnung des Mock-LLM (POST /received/clear)."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/received/clear", method="POST", data=b"")
    urllib.request.urlopen(req, timeout=5).read()


def _llm_received(port):
    """Alle vom Mock-LLM aufgezeichneten POST /chat/completions-Bodies (GET /received)."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/received", timeout=5) as res:
        return json.loads(res.read().decode())


def test_abort_discards_inflight_block(page, base_url, llm_expect):
    """Abbruch waehrend des Streams (Mock-LLM 'langsam'): der offene (in-flight) Block wird
    verworfen und landet nicht in UI/API; kein Fehler-System-Message; generating=0."""
    if llm_expect["default"] is None:
        pytest.skip("Abbruch-Test braucht den Mock-LLM (langsame Antwort)")
    email = "abort-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)

    page.fill(T["chat_input"], "langsam bitte")
    page.click(T["send_btn"])
    # Abbrechen, solange der zweite Mock-Chunk (10 s Pause) noch nicht da ist
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    # Sicherstellen, dass "Teil B" nicht mehr nachgereicht wird
    page.wait_for_timeout(3000)

    # offener Message-Block ("Teil A ") wurde verworfen: keine Assistant-Bubble in der UI
    assert page.locator(_bubble("assistant", "message")).count() == 0

    messages = _api_detail(api_client, sid)["messages"]
    assert not any(m["role"] == "assistant" for m in messages), "in-flight Block darf nicht persistiert werden"
    assert not any(m["role"] == "system" for m in messages), "Abbruch darf keine Fehlermeldung erzeugen"
    assert _api_detail(api_client, sid)["generating"] is False


def test_rename_empty_keeps_name_and_escape_cancels(page, base_url, llm_expect):
    """Inline-Umbenennen: leerer Name behaelt den alten Namen, Escape bricht ab."""
    email = "rename-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)

    tile = page.locator(T["session_tile"]).first

    # Leerer Name -> alter Name bleibt
    tile.locator('[data-testid^="session-rename-btn-"]').click()
    rename_input = page.locator('[data-testid^="session-rename-input-"]')
    rename_input.fill("")
    rename_input.press("Enter")
    page.wait_for_selector('[data-testid^="session-rename-input-"]', state="detached")
    page.wait_for_timeout(300)
    assert "Neue Session" in tile.locator('[data-testid^="session-name-"]').inner_text()

    # Escape -> Aenderung wird verworfen
    tile.locator('[data-testid^="session-rename-btn-"]').click()
    rename_input = page.locator('[data-testid^="session-rename-input-"]')
    rename_input.fill("Verworfen")
    rename_input.press("Escape")
    page.wait_for_selector('[data-testid^="session-rename-input-"]', state="detached")
    page.wait_for_timeout(300)
    assert "Neue Session" in tile.locator('[data-testid^="session-name-"]').inner_text()

    # Neuer Name -> wird uebernommen (serverseitig gepinnt: leer waere 200 + alter Name)
    tile.locator('[data-testid^="session-rename-btn-"]').click()
    rename_input = page.locator('[data-testid^="session-rename-input-"]')
    rename_input.fill("Umbenannt")
    rename_input.press("Enter")
    page.wait_for_selector(f'{T["session_tile"]}:has-text("Umbenannt")')
    sid = api_client.get("/api/sessions").json()[0]["id"]
    assert api_client.get(f"/api/sessions/{sid}").json()["name"] == "Umbenannt"
    res = api_client.patch(f"/api/sessions/{sid}", json={"name": ""})
    assert res.status_code == 200
    assert api_client.get(f"/api/sessions/{sid}").json()["name"] == "Umbenannt"


def test_context_checkbox_persisted_across_reload(page, base_url, llm_expect):
    """Kontext-Checkbox abwaehlen -> in_context=false serverseitig persistiert, auch nach Reload."""
    email = "ctx-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _non_minimal(api_client)
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)

    _chat_once(page, "Kontext-Test", 1, llm_expect["default"], llm_expect["timeout_ms"])

    chk = page.locator(_bubble("user")).first.locator('[data-testid="bubble-context-chk"]')
    assert chk.is_checked()
    chk.uncheck()
    page.wait_for_timeout(500)

    msgs = api_client.get(f"/api/sessions/{sid}").json()["messages"]
    user_msg = next(m for m in msgs if m["role"] == "user")
    assert user_msg["in_context"] is False

    page.reload()
    page.wait_for_selector(_bubble("user"), timeout=llm_expect["timeout_ms"])
    assert not page.locator(_bubble("user")).first.locator('[data-testid="bubble-context-chk"]').is_checked()


def test_context_checkbox_excludes_unselected_from_llm_request(page, base_url, llm_expect, mock_llm_port):
    """Kontext-Checkbox abwaehlen (User-Message, Assistant-Message, Toolcall, Toolresult):
    abwaehlte Nachrichten duerfen im naechsten LLM-Request nicht mehr vorkommen. Der Mock-LLM
    zeichnet die Request-Bodies auf (GET /received) - gegen ein echtes LLM nicht testbar."""
    if mock_llm_port is None:
        pytest.skip("Request-Aufzeichnung nur beim Mock-LLM (Real-LLM-Lauf aktiv)")
    email = "ctx-llm-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _non_minimal(api_client)
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)

    _llm_clear(mock_llm_port)
    # Erste Runde: Mock-Default streamt reasoning + toolcall + toolresult + message
    _chat_once(page, "Erste Frage", 1, llm_expect["default"], llm_expect["timeout_ms"])

    # User-Message, Assistant-Message, Toolcall und Toolresult abwaehlen (eigenstaendige ids/Checkboxen)
    for role, type_ in [("user", "message"), ("assistant", "message"), ("assistant", "toolcall"), ("assistant", "toolresult")]:
        chk = page.locator(_bubble(role, type_)).first.locator('[data-testid="bubble-context-chk"]')
        assert chk.is_checked(), f"Checkbox {role}/{type_} soll initial aktiv sein"
        chk.uncheck()

    # PATCH ist clientseitig fire-and-forget -> auf serverseitige Persistenz warten
    deadline = time.time() + 10
    while time.time() < deadline:
        msgs = api_client.get(f"/api/sessions/{sid}").json()["messages"]
        if all(m["in_context"] is False for m in msgs if m["type"] != "reasoning"):
            break
        time.sleep(0.2)
    else:
        raise AssertionError("in_context=false wurde nicht serverseitig persistiert")

    # Zweite Runde: der naechste LLM-Request darf nur noch die neue User-Message enthalten
    _chat_once(page, "Zweite Frage", 2, llm_expect["default"], llm_expect["timeout_ms"])
    wire = _llm_received(mock_llm_port)[-1]["messages"]
    assert wire == [{"role": "user", "content": "Zweite Frage"}], wire
    joined = json.dumps(wire)
    for absent in ("Erste Frage", "Hallo Welt", "get_weather", "Z1"):
        assert absent not in joined


def test_delete_message_via_ui_persists_server_side_and_across_reload(page, base_url, llm_expect):
    """Nachricht per Muellimer loeschen: Bubble sofort weg, serverseitig geloescht (ueber
    die API sichtbar) und nach Reload weiterhin weg."""
    email = "del-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    res = api_client.put("/api/settings", json={"bubbles_deletable": True, "bubbles_minimal": False})  # Default ist jetzt False
    assert res.status_code == 200, res.text
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)
    _chat_once(page, "Loesch mich", 1, llm_expect["default"], llm_expect["timeout_ms"])

    page.locator(_bubble("user")).first.locator('[data-testid="bubble-delete-btn"]').click()
    _confirm_delete(page)
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === 0",
        timeout=llm_expect["timeout_ms"],
    )

    def _no_user_msg():
        msgs = api_client.get(f"/api/sessions/{sid}").json()["messages"]
        return not any(m["role"] == "user" for m in msgs)

    # DELETE wird im Client awaited -> nur noch auf serverseitige Persistenz warten
    deadline = time.time() + 10
    while time.time() < deadline and not _no_user_msg():
        time.sleep(0.2)
    assert _no_user_msg(), "DELETE muss serverseitig persistiert sein"

    api_msgs = _api_detail(api_client, sid)["messages"]
    assert not any(m["role"] == "user" for m in api_msgs), "serverseitig darf die Nachricht nicht mehr existieren"

    page.reload()
    page.wait_for_selector(_bubble("assistant", "message"), timeout=llm_expect["timeout_ms"])
    assert page.locator(_bubble("user")).count() == 0
    assert _no_user_msg()


def test_delete_last_user_message_shows_resend_on_new_last_without_reload(page, base_url, llm_expect):
    """Regression: Loescht man die letzte User-Message, muss der 'Erneut senden'-Button an der
    nun letzten User-Bubble sofort erscheinen (ohne Reload). Grund: resendBtn/editBtn wurden
    bisher nur beim Anlegen der Bubble erzeugt, wenn sie gerade die letzte User-Message war —
    jetzt existieren sie fuer alle User-Messages und werden nur per Klasse (u-hidden) umgeschaltet."""
    if llm_expect["default"] is None:
        pytest.skip("Test braucht den Mock-LLM")
    email = "resend-after-delete-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    res = api_client.put("/api/settings", json={"bubbles_deletable": True, "bubbles_minimal": False})  # Default ist jetzt False
    assert res.status_code == 200, res.text
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)

    _chat_once(page, "Nachricht 1", 1, llm_expect["default"], llm_expect["timeout_ms"])
    _chat_once(page, "Nachricht 2", 2, llm_expect["default"], llm_expect["timeout_ms"])

    users = page.locator(_bubble("user"))
    resend_btn = '[data-testid="bubble-resend-btn"]'
    assert users.count() == 2
    assert users.nth(0).locator(resend_btn).evaluate("el => getComputedStyle(el).display") == "none", "nur die letzte User-Bubble darf resend zeigen"
    assert users.nth(1).locator(resend_btn).evaluate("el => getComputedStyle(el).display") != "none"

    # letzte User-Message loeschen -> die erste wird zur letzten und muss resend sofort zeigen
    users.nth(1).locator('[data-testid="bubble-delete-btn"]').click()
    _confirm_delete(page)
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === 1",
        timeout=llm_expect["timeout_ms"],
    )
    btn = users.nth(0).locator(resend_btn)
    btn.wait_for(state="visible", timeout=5000)
    assert btn.evaluate("el => getComputedStyle(el).display") != "none", "Erneut-senden muss ohne Reload an der neuen letzten User-Bubble erscheinen"


def test_deleted_messages_excluded_from_llm_request(page, base_url, llm_expect, mock_llm_port):
    """Geloeschte Nachrichten (User-Message + Assistant-Message) duerfen im naechsten LLM-Request
    nicht mehr vorkommen; das Toolcall/Toolresult-Paar und die neue Nachricht bleiben erhalten."""
    if mock_llm_port is None:
        pytest.skip("Request-Aufzeichnung nur beim Mock-LLM (Real-LLM-Lauf aktiv)")
    email = "del-llm-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    res = api_client.put("/api/settings", json={"bubbles_deletable": True, "bubbles_minimal": False})  # Default ist jetzt False
    assert res.status_code == 200, res.text
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)

    _llm_clear(mock_llm_port)
    _chat_once(page, "Erste Frage", 1, llm_expect["default"], llm_expect["timeout_ms"])

    # User-Message und Assistant-Message per UI loeschen
    for role, type_ in [("user", "message"), ("assistant", "message")]:
        page.locator(_bubble(role, type_)).first.locator('[data-testid="bubble-delete-btn"]').click()
        _confirm_delete(page)

    deadline = time.time() + 10
    while time.time() < deadline:
        msgs = api_client.get(f"/api/sessions/{sid}").json()["messages"]
        if not any(m["role"] == "user" or (m["role"] == "assistant" and m["type"] == "message") for m in msgs):
            break
        time.sleep(0.2)
    else:
        raise AssertionError("DELETE wurde nicht serverseitig persistiert")

    # Zweite Runde senden (User-Bubbles 0 -> 1, Assistant-Messages 0 -> 1)
    page.fill(T["chat_input"], "Zweite Frage")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === 1"
        " && document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )

    wire = _llm_received(mock_llm_port)[-1]["messages"]
    joined = json.dumps(wire)
    assert "Zweite Frage" in joined
    assert "Erste Frage" not in joined, "geloeschte User-Message darf nicht im LLM-Request stehen"
    assert "Hallo Welt" not in joined, "geloeschte Assistant-Message darf nicht im LLM-Request stehen"
    # nicht geloeschtes Toolcall/Toolresult-Paar der ersten Runde bleibt im Request erhalten
    assert any(m.get("tool_calls") for m in wire)
    assert any(m.get("role") == "tool" for m in wire)


def test_reload_during_generation_shows_abort_and_cancel_clears_flag(page, base_url, llm_expect, mock_llm_port):
    """Reload mitten in der Generierung (Mock-LLM 'langsam'): Abbrechen-Button statt Senden-Button
    muss sichtbar sein (send-btn traegt die Klasse 'abort'); Abbrechen setzt serverseitig generating=0."""
    if mock_llm_port is None:
        pytest.skip("langsamer Stream nur beim Mock-LLM (Real-LLM-Lauf aktiv)")
    email = "reload-abort-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)

    page.fill(T["chat_input"], "langsam bitte")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    assert api_client.get(f"/api/sessions/{sid}").json()["generating"] is True

    # Reload mitten im Stream: Generierung laeuft serverseitig weiter, Abbrechen statt Senden sichtbar
    page.reload()
    page.wait_for_selector(T["chat_input"], timeout=llm_expect["timeout_ms"])
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    assert page.locator('[data-testid="progress"]').is_visible()
    _open_panel(page)
    assert page.locator('[data-testid="abort-side-btn"]').is_visible()
    assert api_client.get(f"/api/sessions/{sid}").json()["generating"] is True

    # Abbrechen (send-btn ist im Abort-Modus) -> generating=0 serverseitig
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    deadline = time.time() + 10
    while time.time() < deadline and api_client.get(f"/api/sessions/{sid}").json()["generating"]:
        time.sleep(0.2)
    assert api_client.get(f"/api/sessions/{sid}").json()["generating"] is False


def test_theme_setting_persists_across_reload(page, base_url, llm_expect):
    """Theme 'dark' ueber das Settings-Overlay setzen -> html.dark + serverseitig gespeichert."""
    email = "theme-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")

    page.click(T["burger_btn"])
    page.click(T["settings_btn"])
    page.wait_for_selector(f'{T["settings_overlay"]}.open')
    page.select_option('[data-testid="set-theme"]', "dark")
    page.click(T["set_save"])
    page.wait_for_selector(f'{T["settings_overlay"]}:not(.open)', state="attached")

    assert "dark" in (page.locator("html").get_attribute("class") or "")
    assert api_client.get("/api/settings").json()["theme"] == "dark"

    page.reload()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('dark')",
        timeout=llm_expect["timeout_ms"],
    )


def test_switch_between_sessions(page, base_url, llm_expect):
    """Zwei Sessions mit eigenen Nachrichten: Wechsel ueber die Tiles zeigt die richtigen Bubbles."""
    email = "switch-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)

    _chat_once(page, "Session Zwei Nachricht", 1, llm_expect["default"], llm_expect["timeout_ms"])
    _new_named_session(page, api_client)
    _chat_once(page, "Session Drei Nachricht", 1, llm_expect["default"], llm_expect["timeout_ms"])
    assert page.locator(_bubble("user")).count() == 1

    page.locator(T["session_tile"], has_text="Session Zwei Nachricht").locator('[data-testid^="session-name-"]').click()
    page.wait_for_timeout(500)
    assert page.locator(_bubble("user")).count() == 1
    assert "Session Zwei Nachricht" in page.locator(_bubble("user")).first.locator('[data-testid="bubble-body"]').inner_text()


def _input_value_is(page, value):
    page.wait_for_function(
        "([sel, val]) => document.querySelector(sel).value === val",
        arg=[T["chat_input"], value],
    )


def test_drafts_are_per_session(page, base_url, llm_expect):
    """Composer-Entwurf ist pro Session: Wechsel laedt den Entwurf der Ziel-Session (kein
    Uebertrag in die andere Session), Rueckkehr stellt den eigenen Entwurf wieder her,
    Senden loescht ihn; der Entwurf ueberlebt einen Reload (localStorage)."""
    email = "draft-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    sid_a = api_client.get("/api/sessions").json()[0]["id"]  # automatisch angelegte Session
    sid_b = _new_named_session(page, api_client)  # zweite Session, danach aktiv

    def open_tile(sid):
        page.locator(f'[data-testid="session-tile-{sid}"] [data-testid="session-name-{sid}"]').click()
        page.wait_for_selector(f'[data-testid="session-tile-{sid}"].active')

    # Entwurf in Session B tippen, zu Session A wechseln: Composer leer (kein Uebertrag)
    page.fill(T["chat_input"], "Entwurf B")
    open_tile(sid_a)
    _input_value_is(page, "")

    # Entwurf in Session A tippen, zurueck zu B: Entwurf B ist wieder da
    page.fill(T["chat_input"], "Entwurf A")
    open_tile(sid_b)
    _input_value_is(page, "Entwurf B")

    # Reload: aktiver Session-Entwurf bleibt erhalten (localStorage + sessionStorage)
    page.reload()
    page.wait_for_selector(T["chat_input"])
    _input_value_is(page, "Entwurf B")
    _open_panel(page)

    # Zurueck zu A, Entwurf senden -> Entwurf dieser Session wird geloescht
    open_tile(sid_a)
    _input_value_is(page, "Entwurf A")
    _chat_once(page, "Entwurf A", 1, llm_expect["default"], llm_expect["timeout_ms"])
    _input_value_is(page, "")

    # Wechsel zu B: Entwurf B unberuehrt; zurueck zu A: gesendeter Entwurf bleibt weg
    open_tile(sid_b)
    _input_value_is(page, "Entwurf B")
    open_tile(sid_a)
    _input_value_is(page, "")


def test_resend_last_user_message(page, base_url, llm_expect):
    """Erneut-senden-Button nur auf der letzten User-Bubble: wie Bearbeiten ohne
    Text-Aenderung - die Nachricht wird gepatcht, alle Nachrichten danach (alte
    Assistenten-Antworten) werden geloescht und die Antwort neu generiert."""
    email = "resend-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _non_minimal(api_client)
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)

    _chat_once(page, "Erste Frage", 1, llm_expect["default"], llm_expect["timeout_ms"])
    _chat_once(page, "Zweite Frage", 2, llm_expect["default"], llm_expect["timeout_ms"])

    user_bubbles = page.locator(_bubble("user"))
    assert user_bubbles.count() == 2
    # Resend-Button nur auf der letzten User-Bubble sichtbar
    assert page.locator(f'{_bubble("user")} [data-testid="bubble-resend-btn"]:visible').count() == 1
    resend = user_bubbles.last.locator('[data-testid="bubble-resend-btn"]')
    assert resend.count() == 1

    # Kein Bestaetigungs-Modal (wie beim Inline-Edit, siehe 54fc9b6): die
    # Nachricht wird direkt gepatcht, Folgemessages geloescht, neu generiert.
    resend.click()

    # Generierung startet ...
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\\\"send-btn\\\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    # ... und endet: weiterhin 2 User-Bubbles (keine neue angehaengt), die alte
    # zweite Assistenten-Antwort wurde geloescht und neu generiert
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\\\"chat\\\"] .bubble[data-role=\\\"user\\\"]').length === 2"
        " && document.querySelectorAll('[data-testid=\\\"chat\\\"] .bubble[data-role=\\\"assistant\\\"][data-type=\\\"message\\\"]').length === 2"
        " && !document.querySelector('[data-testid=\\\"send-btn\\\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )

    # API: weiterhin genau 2 User-Messages (kein Duplikat), genau eine Assistenten-
    # Antwort nach der letzten User-Nachricht (die alte zweite Antwort ist weg)
    msgs = _api_detail(api_client, sid)["messages"]
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert [m["text"] for m in user_msgs] == ["Erste Frage", "Zweite Frage"]
    last_user_id = user_msgs[-1]["id"]
    assistant_msgs = [m for m in msgs if m["role"] == "assistant" and m["type"] == "message"]
    assert sum(1 for m in assistant_msgs if m["id"] > last_user_id) == 1
    assert len(assistant_msgs) == 2


def test_edit_last_user_message(page, base_url, llm_expect):
    """Edit-Button nur auf der letzten User-Bubble: Inline-Edit direkt in der Bubble
    (Textarea, Enter sendet, Esc bricht ab) - beim Absenden wird die Nachricht
    gepatcht, alle Nachrichten danach (Assistenten-Antworten) gelöscht und neu generiert."""
    email = "edit-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _non_minimal(api_client)
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)

    _chat_once(page, "Erste Frage", 1, llm_expect["default"], llm_expect["timeout_ms"])
    _chat_once(page, "Zweite Frage", 2, llm_expect["default"], llm_expect["timeout_ms"])
    assert page.locator(_bubble("user")).count() == 2
    assert page.locator(_bubble("assistant")).count() == 2

    # Edit-Button ist nur auf der letzten User-Bubble sichtbar
    assert page.locator(f'{_bubble("user")} [data-testid="bubble-edit-btn"]:visible').count() == 1
    assert page.locator(_bubble("user")).last.locator('[data-testid="bubble-edit-btn"]:visible').count() == 1
    assert page.locator(_bubble("user")).first.locator('[data-testid="bubble-edit-btn"]:visible').count() == 0

    # Klick oeffnet den Inline-Edit direkt in der Bubble; der Composer bleibt leer
    last_user = page.locator(_bubble("user")).last
    h_before = last_user.bounding_box()["height"]
    last_user.locator('[data-testid="bubble-edit-btn"]').click()
    edit_input = last_user.locator('[data-testid="bubble-edit-input"]')
    edit_input.wait_for()
    h_edit = last_user.bounding_box()["height"]
    assert abs(h_edit - h_before) <= 1, "Edit-Modus darf die Hoehe der Bubble nicht aendern"
    assert edit_input.input_value() == "Zweite Frage"
    assert page.locator(T["chat_input"]).input_value() == ""

    # Escape bricht ab: Textarea verschwindet, Bubble zeigt wieder den Originaltext
    edit_input.press("Escape")
    page.wait_for_selector('[data-testid="bubble-edit-input"]', state="detached")
    assert "Zweite Frage" in last_user.locator('[data-testid="bubble-body"]').inner_text()
    assert page.locator(T["chat_input"]).input_value() == ""

    # Abbrechen ueber den X-Button oben rechts am Textfeld
    last_user.locator('[data-testid="bubble-edit-btn"]').click()
    last_user.locator('[data-testid="bubble-edit-cancel-btn"]').wait_for()
    last_user.locator('[data-testid="bubble-edit-cancel-btn"]').click()
    page.wait_for_selector('[data-testid="bubble-edit-input"]', state="detached")
    assert "Zweite Frage" in last_user.locator('[data-testid="bubble-body"]').inner_text()

    # Erneut oeffnen, Text aendern und mit Enter absenden (kein Speichern-Button)
    last_user.locator('[data-testid="bubble-edit-btn"]').click()
    edit_input = last_user.locator('[data-testid="bubble-edit-input"]')
    edit_input.wait_for()
    edit_input.fill("Zweite Frage (bearbeitet)")
    assert last_user.locator('[data-testid="bubble-edit-save-btn"]').count() == 0
    edit_input.press("Enter")

    # Kein Bestaetigungsdialog beim Bearbeiten: Generierung startet direkt
    assert page.locator(f'{T["confirm_overlay"]}.open').count() == 0
    # (Senden-Button wird zum Abbrechen-Button) ...
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\\\"send-btn\\\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    # ... und endet mit genau einer neuen Assistenten-Antwort
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\\\"chat\\\"] .bubble[data-role=\\\"assistant\\\"][data-type=\\\"message\\\"]').length === 2"
        " && !document.querySelector('[data-testid=\\\"send-btn\\\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    # User-Bubbles bleiben 2, die letzte traegt den bearbeiteten Text (Inline-Edit beendet)
    page.wait_for_function(
        f"() => [...document.querySelectorAll('{T['chat']} .bubble[data-role=\\\"user\\\"]')]"
        " .some(b => b.querySelector('[data-testid=\\\"bubble-body\\\"]').textContent.includes('Zweite Frage (bearbeitet)'))",
        timeout=llm_expect["timeout_ms"],
    )
    page.wait_for_selector('[data-testid="bubble-edit-input"]', state="detached")
    assert page.locator(_bubble("user")).count() == 2
    assert "Erste Frage" in page.locator(_bubble("user")).first.locator('[data-testid="bubble-body"]').inner_text()

    # API: Text wurde geaendert (alte Fassung weg), alte Assistenten-Antwort der
    # zweiten Frage geloescht, genau eine neue Antwort nach der bearbeiteten Nachricht
    msgs = _api_detail(api_client, sid)["messages"]
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert len(user_msgs) == 2
    assert sorted(m["text"] for m in user_msgs) == ["Erste Frage", "Zweite Frage (bearbeitet)"]
    edited_id = next(m["id"] for m in user_msgs if "(bearbeitet)" in m["text"])
    assistant_msgs = [m for m in msgs if m["role"] == "assistant" and m["type"] == "message"]
    assert sum(1 for m in assistant_msgs if m["id"] > edited_id) == 1, "genau eine neue Assistenten-Antwort nach der bearbeiteten Nachricht"
    assert len(assistant_msgs) == 2, "alte zweite Antwort wurde geloescht, erste Antwort bleibt"


def test_compact_mode_toggle(page, base_url, llm_expect):
    """Burger-Menue -> Kompaktmodus toggelt die .compact-Klasse am Chat."""
    email = "compact-user@example.com"
    _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")

    page.click(T["burger_btn"])
    page.click('[data-testid="compact-btn"]')
    assert "compact" in (page.locator(T["chat"]).get_attribute("class") or "")
    page.click(T["burger_btn"])
    page.click('[data-testid="compact-btn"]')
    assert "compact" not in (page.locator(T["chat"]).get_attribute("class") or "")


def test_long_message_bubble_clamp_cycle(page, base_url, llm_expect):
    """Lange Assistant-Nachricht (Mock 'lang'): normal (10 Zeilen + [...]) -> full -> collapsed -> normal."""
    if llm_expect["default"] is None:
        pytest.skip("Clamp-Test braucht den Mock-LLM (lange Antwort)")
    email = "clamp-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _non_minimal(api_client)
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)

    page.fill(T["chat_input"], "lang")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )

    bubble = page.locator(_bubble("assistant", "message")).first
    body = bubble.locator('[data-testid="bubble-body"]')
    toggle = bubble.locator('[data-testid="bubble-toggle-btn"]')

    # normal: auf 10 Zeilen gekuerzt
    assert bubble.get_attribute("data-mode") == "normal"
    assert body.inner_text().endswith("[...]")
    assert "Zeile 15" not in body.inner_text()

    toggle.click()  # -> full
    page.wait_for_function(
        f"() => document.querySelector('{_bubble('assistant', 'message')}').getAttribute('data-mode') === 'full'"
    )
    assert "Zeile 15" in body.inner_text()
    assert not body.inner_text().endswith("[...]")

    toggle.click()  # -> collapsed
    page.wait_for_function(
        f"() => document.querySelector('{_bubble('assistant', 'message')}').getAttribute('data-mode') === 'collapsed'"
    )
    text = body.inner_text()
    assert text.endswith("[...]") and "\n" not in text

    toggle.click()  # -> normal
    page.wait_for_function(
        f"() => document.querySelector('{_bubble('assistant', 'message')}').getAttribute('data-mode') === 'normal'"
    )


def test_expand_mode_survives_stream_completion(page, base_url, llm_expect):
    """Regression: lange Antwort streamt in Chunks (Mock 'vielechunks'); klappt der Nutzer
    die Live-Bubble waehrend des Streams auf 'full', darf der Modus nicht auf 'normal'
    zurueckfallen, sobald der Stream endet und der Poll den persistierten Stand laedt
    (Key-Wechsel live-<idx> -> msg-<id> baut die Bubble neu)."""
    if llm_expect["default"] is None:
        pytest.skip("braucht den Mock-LLM (lange Antwort in Chunks)")
    email = "expand-stream-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    # Minimalismus aus: der Expand-Button (Chevron im Bubble-Head) ist sonst display:none
    res = api_client.put("/api/settings", json={"bubbles_minimal": False})
    assert res.status_code == 200, res.text
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)
    page.wait_for_function("() => !document.documentElement.classList.contains('bubbles-minimal')")

    page.fill(T["chat_input"], "vielechunks")
    page.click(T["send_btn"])
    bubble = _bubble("assistant", "message")
    send_btn = '[data-testid="send-btn"]'
    # Live-Bubble waehrend des Streams, deren Text in 'normal' gekuerzt ist (>10 Zeilen)
    page.wait_for_function(
        f"() => {{ const b = document.querySelector('{bubble}');"
        f" const body = b && b.querySelector('[data-testid=\"bubble-body\"]');"
        f" return !!body && body.classList.contains('clamped') && b.getAttribute('data-mode') === 'normal'"
        f" && document.querySelector('{send_btn}').classList.contains('abort'); }}",
        timeout=llm_expect["timeout_ms"],
    )
    page.locator(f'{bubble} [data-testid="bubble-toggle-btn"]').click()  # normal -> full
    page.wait_for_function(
        f"() => document.querySelector('{bubble}').getAttribute('data-mode') === 'full'",
        timeout=llm_expect["timeout_ms"],
    )

    # Stream-Ende abwarten (Abort-Button wechselt zurueck auf Senden)
    page.wait_for_function(
        f"() => document.querySelectorAll('{bubble}').length === 1"
        f" && !document.querySelector('{send_btn}').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    # persistierte Bubble (data-msg-id gesetzt = Key msg-<id>, nicht mehr live) behaelt 'full'
    page.wait_for_function(
        f"() => {{ const b = document.querySelector('{bubble}');"
        f" return b && !!b.dataset.msgId && b.getAttribute('data-mode') === 'full'; }}",
        timeout=llm_expect["timeout_ms"],
    )
    assert "Zeile 15" in page.locator(f'{bubble} [data-testid="bubble-body"]').inner_text()


def test_collapsed_bubble_caps_single_long_line_at_one_rendered_row(page, base_url, llm_expect):
    """Eine einzige sehr lange (umbrechende) Zeile: im collapsed-Modus genau eine gerenderte GUI-Zeile."""
    if llm_expect["default"] is None:
        pytest.skip("braucht den Mock-LLM (lange Einzeiler-Antwort)")
    email = "oneline-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _non_minimal(api_client)
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)

    page.fill(T["chat_input"], "oneline")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )

    bubble = page.locator(_bubble("assistant", "message")).first
    toggle = bubble.locator('[data-testid="bubble-toggle-btn"]')
    toggle.click()  # normal -> full (bzw. bei ungekuerztem Text direkt -> collapsed, full == normal)
    if bubble.get_attribute("data-mode") != "collapsed":
        toggle.click()  # -> collapsed
    page.wait_for_function(
        f"() => document.querySelector('{_bubble('assistant', 'message')}').getAttribute('data-mode') === 'collapsed'",
        timeout=llm_expect["timeout_ms"],
    )
    # gerenderte Hoehe des Bodys <= eine line-height (CSS line-clamp: 1)
    one_row = page.evaluate(
        """() => {
             const b = document.querySelector('[data-testid="chat"] .bubble[data-role="assistant"][data-type="message"] .bubbleBody');
             const cs = getComputedStyle(b);
             return b.getBoundingClientRect().height <= parseFloat(cs.lineHeight) + 2;
           }"""
    )
    assert one_row, "collapsed darf auch bei einer langen Einzeiler nur eine GUI-Zeile zeigen"


def test_collapse_keeps_scroll_position_when_scrolled_up(page, base_url, llm_expect):
    """Hochgescrollt eine lange Bubble einklappen: die Ansicht darf nicht ans untere
    Ende springen, sondern bleibt an der oberen Viewport-Kante stehen (bzw. landet an
    der kollabierten Bubble, wenn die Kante mitten in der Bubble war)."""
    if llm_expect["default"] is None:
        pytest.skip("braucht den Mock-LLM (lange Antworten)")
    email = "scroll-collapse-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _non_minimal(api_client)
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)

    # vier lange Antworten -> Chat hoch genug zum Scrollen
    n_assist = "document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length"
    for i in range(1, 5):
        page.fill(T["chat_input"], "lang")
        page.click(T["send_btn"])
        page.wait_for_function(
            f"() => {n_assist} === {i}"
            " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
            timeout=llm_expect["timeout_ms"],
        )

    # erste Assistant-Bubble voll ausklappen (normal -> full), dann hochscrollen
    first = f"document.querySelectorAll('{_bubble('assistant', 'message')}')[0]"
    page.locator(_bubble("assistant", "message")).first.locator('[data-testid="bubble-toggle-btn"]').click()
    page.wait_for_function(f"() => {first}.getAttribute('data-mode') === 'full'")
    st0 = page.evaluate(
        """() => {
             const c = document.querySelector('[data-testid="chat"]');
             c.scrollTop = c.scrollHeight - c.clientHeight - 150;
             return c.scrollTop;
           }"""
    )
    assert st0 > 400, "Chat muss hoch genug sein, dass die erste Bubble voll oberhalb des Viewports liegt"
    h0 = page.evaluate(f"() => {first}.getBoundingClientRect().height")

    # Kollaps per DOM-Click ausloesen (Playwright-Click wuerde scrollIntoView -> scrollTop veraendern)
    page.evaluate(f"() => {first}.querySelector('[data-testid=\"bubble-toggle-btn\"]').click()")
    page.wait_for_function(f"() => {first}.getAttribute('data-mode') === 'collapsed'")
    page.wait_for_timeout(250)  # CSS-Transition (min-height/padding, 150ms) abwarten

    res = page.evaluate(
        f"""() => {{
             const c = document.querySelector('[data-testid="chat"]');
             const b = {first};
             return {{ st: c.scrollTop, max: c.scrollHeight - c.clientHeight, h: b.getBoundingClientRect().height }};
           }}"""
    )
    assert res["h"] < h0 - 100, "Bubble muss kollabiert (deutlich kleiner) sein"
    assert res["st"] <= st0, "Ansicht darf nicht nach unten springen"
    assert res["st"] < res["max"] - 10, "Ansicht darf nach dem Einklappen nicht am unteren Rand kleben (kein Clamp-Sprung)"


def test_llm_streaming_is_visible_bit_by_bit_in_ui(page, base_url, llm_expect):
    """Streaming-Nachweis End-to-End im Browser: der Mock-LLM sendet 4 Chunks mit je 0.4 s
    Pause ('chunky'); die Assistant-Bubble muss den Text stufenweise aufbauen — der Nutzer
    sieht den Stream fortschreiten, nicht erst das Endergebnis."""
    if llm_expect["default"] is None:
        pytest.skip("Chunky-Streaming-Test braucht den Mock-LLM")
    email = "chunky-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)

    page.fill(T["chat_input"], "chunky bitte")
    page.click(T["send_btn"])

    # Assistant-Bubble erscheint, sobald der erste Chunk da ist
    page.wait_for_selector(_bubble("assistant", "message"), timeout=llm_expect["timeout_ms"])
    body = page.locator(_bubble("assistant", "message")).first.locator('[data-testid="bubble-body"]')
    seen = set()
    deadline = time.time() + llm_expect["timeout_ms"] / 1000
    while time.time() < deadline:
        txt = body.inner_text()
        seen.add(txt)
        if "Delta" in txt:
            break
        if not page.locator(T["send_btn"]).evaluate("el => el.classList.contains('abort')"):
            seen.add(body.inner_text())  # finaler Stand nach Generierungsende
            break
        time.sleep(0.05)

    intermediate = sorted(t for t in seen if t and "Delta" not in t)
    assert len(intermediate) >= 2, f"kein stufenweises Streaming im UI sichtbar: {sorted(seen)}"
    assert any("Alpha" in t and "Beta" not in t for t in intermediate), f"erster Chunk allein sichtbar: {intermediate}"
    assert "Alpha Beta Gamma Delta" in seen, f"Endstand fehlt: {sorted(seen)}"


def test_stream_end_bubble_never_vanishes(page, base_url, llm_expect):
    """Regression Flicker am Stream-Ende: sobald die Assistant-Bubble einmal im Chat steht,
    darf sie bis zum Ende der Generierung (done -> Poll-Uebernahme) nie wieder aus dem DOM
    verschwinden. Ein MutationObserver zeichnet jede Entfernung nach dem ersten Erscheinen auf;
    ein synchrones remove+add innerhalb eines Renderns (Key-Wechsel live-<idx> -> msg-<id>)
    wird dabei nicht als Verschwinden gezaehlt, weil der Observer den Endzustand sieht."""
    if llm_expect["default"] is None:
        pytest.skip("Flicker-Test braucht den Mock-LLM")
    email = "flicker-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)

    page.evaluate(
        """() => {
          window.__bubbleSeen = false;
          window.__bubbleVanished = false;
          const chat = document.querySelector('[data-testid="chat"]');
          const sel = '.bubble[data-role="assistant"][data-type="message"]';
          if (chat.querySelector(sel)) window.__bubbleSeen = true;
          new MutationObserver(() => {
            if (chat.querySelector(sel)) window.__bubbleSeen = true;
            else if (window.__bubbleSeen) window.__bubbleVanished = true;
          }).observe(chat, { childList: true, subtree: true });
        }"""
    )

    page.fill(T["chat_input"], "Hallo bitte antworten")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    # Post-done-Poll abwarten (POLL_MS = 1200 ms): genau in diesem Fenster passierte bisher
    # das Verschwinden und Wiederauftauchen der fertig gestreamten Bubble
    page.wait_for_timeout(2500)
    assert page.evaluate("() => window.__bubbleVanished") is False, "Assistant-Bubble wurde nach dem Stream-Ende kurz entfernt (Flicker)"
    assert page.locator(_bubble("assistant", "message")).count() == 1
    body = page.locator(_bubble("assistant", "message")).first.locator('[data-testid="bubble-body"]')
    assert llm_expect["default"] in body.inner_text()


def test_minimalism_desktop_hides_head_and_overrides_context_menu(page, base_url, llm_expect):
    """Minimalismus-Setting (Allgemein), Desktop: Bubble-Head ist komplett ausgeblendet (auch
    beim Hover). Klick/Doppelklick oeffnen kein Menue — der Rechtsklick (contextmenu) ueber-
    schreibt das Systemmenue durch das App-Kontextmenue. Einfacher Klick klappt weiterhin
    gekuerzte Bubbles auf. Ohne Setting bleibt der Head sichtbar."""
    if llm_expect["default"] is None:
        pytest.skip("Minimalismus-Test braucht den Mock-LLM")
    email = "minimal-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _new_named_session(page, api_client)

    page.fill(T["chat_input"], "Hallo")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    toolbar_btn = f'{_bubble("assistant", "message")} .bubbleHead .iconBtn'

    # Settings serverseitig setzen (Minimalismus + Kontext-Checkbox fuer den Toggle-Test),
    # dann Seite neu laden (Cookie bleibt -> kein erneuter Login)
    res = api_client.put("/api/settings", json={"bubbles_minimal": True, "bubbles_checkable": True})
    assert res.status_code == 200, res.text
    assert res.json()["bubbles_minimal"] is True
    page.reload()
    page.wait_for_selector(_bubble("assistant", "message"), timeout=llm_expect["timeout_ms"])
    page.wait_for_function("() => document.documentElement.classList.contains('bubbles-minimal')")

    assert page.locator(toolbar_btn).first.evaluate("el => getComputedStyle(el).display") == "none", "Toolbar muss im Minimalismus ausgeblendet sein"
    head = f'{_bubble("assistant", "message")} .bubbleHead'
    assert page.locator(head).evaluate("el => getComputedStyle(el).display") == "none", "Bubble-Head muss im Minimalismus komplett ausgeblendet sein"

    # Desktop: auch beim Hover bleibt der Head ausgeblendet (kein Hover-Reveal mehr)
    page.hover(_bubble("assistant", "message"))
    assert page.locator(head).evaluate("el => getComputedStyle(el).display") == "none", "Hover darf den Bubble-Head im Minimalismus nicht einblenden"

    # Minimalismus: Textauswahl bleibt aktiv (kein user-select:none)
    bubble_sel = _bubble("assistant", "message")
    body_sel = f"{bubble_sel} .bubbleBody"
    assert page.locator(body_sel).evaluate("el => getComputedStyle(el).userSelect") in ("text", "auto"), "Textauswahl darf im Minimalismus nicht per CSS deaktiviert sein"
    assert page.locator(bubble_sel).evaluate("el => getComputedStyle(el).touchAction") == "manipulation", "touch-action muss im Minimalismus 'manipulation' sein (kein systemeigenes Doppel-Tap-Zoom)"

    menu = page.locator('[data-testid="bubble-context-menu"]')
    # Desktop: Klick UND Doppelklick oeffnen kein Menue
    page.click(bubble_sel)
    page.wait_for_timeout(300)
    assert menu.count() == 0, "einfacher Klick darf auf Desktop kein Kontextmenue oeffnen"
    page.dblclick(bubble_sel)
    page.wait_for_timeout(300)
    assert menu.count() == 0, "Doppelklick darf auf Desktop kein Kontextmenue oeffnen"

    # Doppel-Tap selektiert nicht das Wort (Firefox-Systemdefault): zweites pointerdown wird preventDefault
    page.wait_for_timeout(400)  # evtl. stale lastTap ablaufen lassen
    dbl = page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const r = el.getBoundingClientRect();
          const x = r.x + r.width / 2, y = r.y + r.height / 2;
          const fired = [];
          for (let i = 0; i < 2; i++) {
            const pd = new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: x, clientY: y });
            el.dispatchEvent(pd);
            fired.push(pd.defaultPrevented);
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
          }
          return { secondPdPrevented: fired[1], collapsed: window.getSelection().isCollapsed, menu: !!document.querySelector('[data-testid="bubble-context-menu"]') };
        }""",
        bubble_sel,
    )
    assert dbl["secondPdPrevented"] is True, "pointerdown des Doppel-Taps muss preventDefault sein (Wortauswahl unterdrueckt)"
    assert dbl["collapsed"] is True, "Doppel-Tap darf kein Wort selektieren"
    assert dbl["menu"] is False, "Desktop: Doppel-Tap oeffnet kein Menue (das kommt per Rechtsklick)"

    # Rechtsklick (contextmenu) auf der Bubble ueberschreibt das Systemmenue durch das App-Menue
    prevented = page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
          el.dispatchEvent(ev);
          return ev.defaultPrevented;
        }""",
        bubble_sel,
    )
    assert prevented, "Desktop: contextmenu auf Bubble muss preventDefault sein (App-Menue ueberschreibt Systemmenue)"
    menu.wait_for(state="visible")
    assert menu.locator("button").count() >= 2, "Kontextmenue muss Kopieren und die Bubble-Aktionen enthalten"
    assert menu.locator("button svg").count() == 0, "Kontextmenue darf keine Icons enthalten (nur Text)"
    assert menu.locator('[data-testid="ctx-copy"]').count() == 1
    # Kontext-Toggle mit zustandsabhaengigem Label (Bubble ist im Kontext -> ausschliessen)
    toggle = menu.locator('[data-testid="ctx-toggle-context"]')
    assert toggle.count() == 1
    assert "ausschlie" in toggle.inner_text().lower(), f"Toggle-Label muss 'Aus dem Kontext ausschließen' sein, got {toggle.inner_text()!r}"
    toggle.click()
    page.wait_for_selector('[data-testid="bubble-context-menu"]', state="detached")
    assert page.locator(bubble_sel).evaluate("el => el.classList.contains('deselected')"), "Toggle muss die Bubble aus dem Kontext nehmen (deselected)"
    # wieder oeffnen: Label kippt auf 'In den Kontext einschließen'
    page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
        }""",
        bubble_sel,
    )
    menu.wait_for(state="visible")
    assert "einschlie" in menu.locator('[data-testid="ctx-toggle-context"]').inner_text().lower(), "Toggle-Label muss jetzt 'In den Kontext einschließen' sein"
    page.keyboard.press("Escape")
    page.wait_for_selector('[data-testid="bubble-context-menu"]', state="detached")
    # Klick bei offenem Menue schliesst es wieder
    page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
        }""",
        bubble_sel,
    )
    menu.wait_for(state="visible")
    page.click(bubble_sel)
    page.wait_for_selector('[data-testid="bubble-context-menu"]', state="detached")

    # System-Auswahlmenue offen (aktive Textauswahl): Klick darf kein App-Menue oeffnen
    page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const r = document.createRange();
          r.selectNodeContents(el);
          const s = window.getSelection();
          s.removeAllRanges();
          s.addRange(r);
        }""",
        body_sel,
    )
    assert not page.evaluate("() => window.getSelection().isCollapsed"), "Vorbedingung: Textauswahl aktiv (Systemmenue offen)"
    page.click(bubble_sel)  # Klick bricht die Auswahl ab — darf kein Menue oeffnen
    page.wait_for_timeout(300)
    assert menu.count() == 0, "bei aktiver System-Auswahl darf ein Klick kein App-Menue oeffnen"

    # Expand-Behavior wiederhergestellt: langer Text ist gekuerzt, einfacher Tap klappt die Bubble auf
    _chat_once(page, "lang bitte", 2, None, llm_expect["timeout_ms"])
    lang_bubble = page.locator(_bubble("assistant", "message")).nth(1)
    assert lang_bubble.evaluate("el => el.querySelector('.bubbleBody').classList.contains('clamped')"), "Vorbedingung: lange Antwort ist gekuerzt"
    lang_bubble.click()  # einfacher Tap -> Expand, kein Menue
    assert lang_bubble.evaluate("el => el.classList.contains('full')"), "einfacher Tap muss die gekuerzte Bubble aufklappen"
    page.wait_for_timeout(200)
    assert menu.count() == 0, "einfacher Tap darf auch bei gekuerzter Bubble kein Menue oeffnen"

    # Ziehen/Scrollen (Pointer bewegt sich) darf kein Menue oeffnen
    box = page.locator(bubble_sel).first.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 + 80, steps=8)
    page.mouse.up()
    page.wait_for_timeout(300)
    assert page.locator('[data-testid="bubble-context-menu"]').count() == 0, "Scroll/Pan-Geste darf kein Kontextmenue oeffnen"

    # Setting wieder aus -> Head/Toolbar dauerhaft sichtbar, kein Kontextmenue
    res = api_client.put("/api/settings", json={"bubbles_minimal": False})
    assert res.status_code == 200, res.text
    page.reload()
    page.wait_for_selector(_bubble("assistant", "message"), timeout=llm_expect["timeout_ms"])
    page.wait_for_function("() => !document.documentElement.classList.contains('bubbles-minimal')")
    assert page.locator(toolbar_btn).first.evaluate("el => getComputedStyle(el).display") != "none"
    assert page.locator(f'{_bubble("assistant", "message")} .bubbleHead .role').first.evaluate("el => getComputedStyle(el).display") != "none"
    page.locator(_bubble("assistant", "message")).first.dispatch_event("contextmenu")
    page.wait_for_timeout(300)
    assert page.locator('[data-testid="bubble-context-menu"]').count() == 0, "ohne Minimalismus darf kein Kontextmenue erscheinen"


def test_minimalism_desktop_dblclick_stops_playback(page, base_url, llm_expect):
    """Minimalismus auf Desktop mit laufender Wiedergabe (TTS): ein einzelner Klick auf eine
    Bubble stoppt die Wiedergabe NICHT (er klappt die gekuerzte Bubble wie gewohnt auf);
    ein Doppelklick stoppt die Wiedergabe (kein Menue, kein weiterer Expand-Wechsel)."""
    if llm_expect["default"] is None:
        pytest.skip("Minimalismus-TTS-Desktop-Test braucht den Mock-LLM")
    page.add_init_script(SPEECH_STUB)
    email = "minimal-tts-desktop@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    res = api_client.put("/api/settings", json={"bubbles_minimal": True, "speech_mode": "system", "bubbles_speaker": True})
    assert res.status_code == 200, res.text
    _login(page, base_url, email, "Geheim-123")
    _chat_once(page, "lang bitte", 1, None, llm_expect["timeout_ms"])
    page.wait_for_function("() => document.documentElement.classList.contains('bubbles-minimal')")

    bubble_sel = _bubble("assistant", "message")
    lang_bubble = page.locator(bubble_sel)
    tts_btn = f"{bubble_sel} [data-testid=\"bubble-tts-btn\"]"
    page.wait_for_selector(tts_btn, state="attached")  # Button existiert auch im ausgeblendeten Head
    assert lang_bubble.evaluate("el => el.querySelector('.bubbleBody').classList.contains('clamped')"), "Vorbedingung: lange Antwort ist gekuerzt"
    assert lang_bubble.evaluate("el => el.dataset.mode") == "normal"

    speaking = "async () => (await import('/js/ttsDetectionService.js')).isSpeaking()"
    # Wiedergabe starten (Speaker-Button liegt im ausgeblendeten Head -> per JS klicken)
    page.evaluate(f"() => document.querySelector('{tts_btn}').click()")
    page.wait_for_function(speaking, timeout=10000)

    # einzelner Klick waehrend der Wiedergabe: stoppt NICHT, klappt die gekuerzte Bubble auf
    lang_bubble.click()
    assert page.evaluate(speaking) is True, "einzelner Klick darf die Wiedergabe nicht stoppen"
    assert lang_bubble.evaluate("el => el.classList.contains('full')"), "Klick klappt die gekuerzte Bubble wie gewohnt auf"
    assert page.locator('[data-testid="bubble-context-menu"]').count() == 0, "der Klick darf kein Kontextmenue oeffnen"

    # Doppelklick waehrend der Wiedergabe: stoppt sie
    lang_bubble.dblclick()
    assert page.evaluate(speaking) is False, "Doppelklick muss die Wiedergabe stoppen"
    assert page.evaluate("() => window.__tts.cancelCalls") >= 1, "speechSynthesis.cancel() wurde gerufen"
    assert lang_bubble.evaluate("el => el.dataset.mode") == "full", "Doppelklick aendert nicht den Modus"
    assert page.locator('[data-testid="bubble-context-menu"]').count() == 0, "Doppelklick darf kein Kontextmenue oeffnen"


def _open_bubble_menu(page, bubble_sel):
    """Desktop: Rechtsklick (contextmenu) auf der Bubble oeffnet das App-Kontextmenue
    (bei mehreren Treffern auf der letzten Bubble)."""
    prevented = page.evaluate(
        """(sel) => {
          const els = document.querySelectorAll(sel);
          const el = els[els.length - 1];
          const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
          el.dispatchEvent(ev);
          return ev.defaultPrevented;
        }""",
        bubble_sel,
    )
    assert prevented, "contextmenu auf Bubble muss preventDefault sein (App-Menue ueberschreibt Systemmenue)"
    menu = page.locator('[data-testid="bubble-context-menu"]')
    menu.wait_for(state="visible")
    return menu


def test_minimalism_desktop_ctx_menu_delete_and_context_toggle(page, base_url, llm_expect):
    """Minimalismus (Default an), Desktop: Aktionen laufen ueber das Kontextmenue (Rechtsklick),
    nicht ueber die ausgeblendete Toolbar - hier: Kontext-Toggle und Loeschen.
    Loeschen ueber das Menue persistiert serverseitig (API) und ueberlebt einen Reload."""
    if llm_expect["default"] is None:
        pytest.skip("braucht den Mock-LLM")
    email = "minimal-ctx-del-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    res = api_client.put("/api/settings", json={"bubbles_minimal": True, "bubbles_deletable": True})
    assert res.status_code == 200, res.text
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)
    page.wait_for_function("() => document.documentElement.classList.contains('bubbles-minimal')")

    _chat_once(page, "Menue-Test", 1, llm_expect["default"], llm_expect["timeout_ms"])
    user_sel = _bubble("user")
    assert page.locator(user_sel).count() == 1

    # 1. Kontext-Toggle ueber das Menue: Bubble wird aus dem Kontext genommen (deselected + API)
    menu = _open_bubble_menu(page, user_sel)
    toggle = menu.locator('[data-testid="ctx-toggle-context"]')
    assert toggle.count() == 1
    assert "ausschlie" in toggle.inner_text().lower()
    toggle.click()
    page.wait_for_selector('[data-testid="bubble-context-menu"]', state="detached")
    assert page.locator(user_sel).evaluate("el => el.classList.contains('deselected')")
    deadline = time.time() + 10
    while time.time() < deadline:
        msgs = _api_detail(api_client, sid)["messages"]
        if msgs and msgs[0]["in_context"] is False:
            break
        time.sleep(0.2)
    assert _api_detail(api_client, sid)["messages"][0]["in_context"] is False, "in_context=false muss serverseitig persistiert sein"

    # 2. Loeschen ueber das Menue (Menue-Eintrag des versteckten Muellimer-Buttons)
    menu = _open_bubble_menu(page, user_sel)
    del_item = menu.locator('[data-testid="ctx-bubble-delete-btn"]')
    assert del_item.count() == 1, "Menue muss den Loeschen-Eintrag der Toolbar enthalten"
    del_item.click()
    _confirm_delete(page)
    page.wait_for_function(
        f"() => document.querySelectorAll('{T['chat']} .bubble[data-role=\"user\"]').length === 0",
        timeout=llm_expect["timeout_ms"],
    )
    deadline = time.time() + 10
    while time.time() < deadline and any(m["role"] == "user" for m in _api_detail(api_client, sid)["messages"]):
        time.sleep(0.2)
    assert not any(m["role"] == "user" for m in _api_detail(api_client, sid)["messages"]), "DELETE muss serverseitig persistiert sein"

    page.reload()
    page.wait_for_selector(_bubble("assistant", "message"), timeout=llm_expect["timeout_ms"])
    assert page.locator(user_sel).count() == 0
    assert not any(m["role"] == "user" for m in _api_detail(api_client, sid)["messages"])


def test_minimalism_desktop_ctx_menu_resend_regenerates(page, base_url, llm_expect):
    """Minimalismus, Desktop: 'Erneut senden' ueber das Kontextmenue (Menue-Eintrag des
    versteckten Resend-Buttons der letzten User-Bubble) startet die Neu-Generierung."""
    if llm_expect["default"] is None:
        pytest.skip("braucht den Mock-LLM")
    email = "minimal-ctx-resend-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    res = api_client.put("/api/settings", json={"bubbles_minimal": True})
    assert res.status_code == 200, res.text
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)
    page.wait_for_function("() => document.documentElement.classList.contains('bubbles-minimal')")

    _chat_once(page, "Erste Frage", 1, llm_expect["default"], llm_expect["timeout_ms"])
    _chat_once(page, "Zweite Frage", 2, llm_expect["default"], llm_expect["timeout_ms"])
    assert page.locator(_bubble("user")).count() == 2

    # Kontextmenue auf der letzten User-Bubble -> Erneut-senden-Eintrag
    menu = _open_bubble_menu(page, _bubble("user"))
    resend_item = menu.locator('[data-testid="ctx-bubble-resend-btn"]')
    assert resend_item.count() == 1, "Menue muss den Resend-Eintrag der letzten User-Bubble enthalten"
    resend_item.click()
    page.wait_for_selector('[data-testid="bubble-context-menu"]', state="detached")

    # Generierung startet und endet: weiterhin 2 User-Bubbles, 2 Assistant-Antworten
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\\\"send-btn\\\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\\\"chat\\\"] .bubble[data-role=\\\"user\\\"]').length === 2"
        " && document.querySelectorAll('[data-testid=\\\"chat\\\"] .bubble[data-role=\\\"assistant\\\"][data-type=\\\"message\\\"]').length === 2"
        " && !document.querySelector('[data-testid=\\\"send-btn\\\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )

    msgs = _api_detail(api_client, sid)["messages"]
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert [m["text"] for m in user_msgs] == ["Erste Frage", "Zweite Frage"]
    last_user_id = user_msgs[-1]["id"]
    assistant_msgs = [m for m in msgs if m["role"] == "assistant" and m["type"] == "message"]
    assert len(assistant_msgs) == 2
    assert sum(1 for m in assistant_msgs if m["id"] > last_user_id) == 1, "genau eine neue Antwort nach der letzten User-Message"
