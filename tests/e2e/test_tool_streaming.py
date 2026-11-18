"""E2E-Regressionstest: Tool-Calls und Tool-Results werden live gestreamt.

Der Mock-LLM ("slowtool") streamt Reasoning -> Tool-Call -> Tool-Result -> Message
mit je ~0.8 s Pause. Die Tool-Bubbles muessen waehrend des laufenden Streams (Abort-
Button sichtbar) im Chat erscheinen - nicht erst nach Stream-Ende - und duerfen nach
Abwählen + erneutem Aktivieren von "Tool-Ausgabe anzeigen" (Settings speichern) nicht
verschwinden. Persistenz wird ausschliesslich ueber die oeffentliche API geprueft.

Alle Selektoren laufen ueber die ``data-testid``-Attribute der UI-Elemente.
"""

from __future__ import annotations

import pytest

from tests.e2e.test_user_journey import T, _bubble, _login, _new_named_session, _register_client

pytestmark = pytest.mark.e2e


def _set_show_tool_output(page, checked: bool) -> None:
    """Setzt die Checkbox 'Tool-Ausgabe anzeigen' in den Settings und speichert."""
    page.click(T["burger_btn"])
    page.click(T["settings_btn"])
    page.wait_for_selector(f'{T["settings_overlay"]}.open')
    (page.check if checked else page.uncheck)(T["set_show_tool"])
    page.click(T["set_save"])
    page.wait_for_selector(f'{T["settings_overlay"]}:not(.open)', state="attached")


def _streaming(page) -> bool:
    return page.locator(T["send_btn"]).evaluate("el => el.classList.contains('abort')")


def _count(page, type_: str) -> int:
    return page.locator(f'{T["chat"]} .bubble[data-type="{type_}"]').count()


def test_tool_calls_are_streamed_live_and_visible_after_settings_toggle(page, base_url, llm_expect):
    """Regression: Tool-Call/Tool-Result wurden nicht live gestreamt bzw. waren nach
    'Tool-Ausgabe anzeigen' + Speichern nicht sichtbar.

    Ablauf: Einstellung ueber die Settings-UI aktivieren + speichern, dann eine
    Nachricht senden, deren Mock-Antwort langsam streamt (Reasoning, Toolcall,
    Toolresult, Message). Die Tool-Bubbles muessen erscheinen, solange der Stream
    noch laeuft (Abort-Button aktiv), und nach Ab-/Wieder-Anwaehlen der Einstellung
    im Chat bleiben bzw. wieder erscheinen.
    """
    if llm_expect["default"] is None:
        pytest.skip("Tool-Streaming-Test braucht den Mock-LLM (Trigger 'slowtool')")
    email = "tool-stream-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    sid = _new_named_session(page, api_client)

    # Nutzer-Report: 'Tool-Ausgabe anzeigen' anhaken + Speichern muss serverseitig
    # ankommen und darf die Anzeige nicht verstecken
    _set_show_tool_output(page, True)
    assert api_client.get("/api/settings").json()["show_tool_output"] is True

    page.fill(T["chat_input"], "slowtool bitte")
    page.click(T["send_btn"])

    # Toolcall-Bubble erscheint, solange der Stream noch laeuft (Abort-Button aktiv)
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolcall"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )
    assert _streaming(page), "Toolcall-Bubble erst nach Stream-Ende erschienen - Tool-Call wurde nicht live gestreamt"
    toolcall_body = page.locator(_bubble("assistant", "toolcall")).first.locator('[data-testid="bubble-body"]')
    assert "web_search" in toolcall_body.inner_text()

    # Toolresult-Bubble erscheint ebenfalls noch waehrend des Streams
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolresult"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )
    assert _streaming(page), "Toolresult-Bubble erst nach Stream-Ende erschienen - Tool-Result wurde nicht live gestreamt"
    toolresult_body = page.locator(_bubble("assistant", "toolresult")).first.locator('[data-testid="bubble-body"]')
    assert "Ergebnis A" in toolresult_body.inner_text()

    # Stream-Ende abwarten: alle Bubbles bleiben sichtbar
    page.wait_for_function(
        '() => !document.querySelector(\'[data-testid="send-btn"]\').classList.contains("abort")',
        timeout=llm_expect["timeout_ms"],
    )
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-role="assistant"][data-type="message"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )
    assert _count(page, "toolcall") == 1
    assert _count(page, "toolresult") == 1

    # Persistenz (nur ueber oeffentliche API): Toolcall/Toolresult liegen in der Session
    detail = api_client.get(f"/api/sessions/{sid}").json()
    types = [m["type"] for m in detail["messages"]]
    assert "toolcall" in types and "toolresult" in types, types

    # 'Tool-Ausgabe anzeigen' abwaehlen + speichern -> Tool-Bubbles verschwinden
    _set_show_tool_output(page, False)
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolcall"]\').length === 0'
        ' && document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolresult"]\').length === 0',
        timeout=llm_expect["timeout_ms"],
    )
    assert api_client.get("/api/settings").json()["show_tool_output"] is False

    # Wieder aktivieren + speichern -> Tool-Bubbles muessen wieder sichtbar sein
    # (genau der gemeldete Fall: nach Anhaken + Speichern blieben sie weg)
    _set_show_tool_output(page, True)
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolcall"]\').length === 1'
        ' && document.querySelectorAll(\'[data-testid="chat"] .bubble[data-type="toolresult"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )
    assert api_client.get("/api/settings").json()["show_tool_output"] is True

    # Nach Reload: Einstellung persistiert, Tool-Bubbles weiterhin sichtbar
    page.reload()
    page.wait_for_selector(f'{T["session_tile"]}.active')
    page.wait_for_function(
        '() => document.querySelectorAll(\'[data-testid="chat"] .bubble[data-role="assistant"][data-type="message"]\').length === 1',
        timeout=llm_expect["timeout_ms"],
    )
    assert _count(page, "toolcall") == 1
    assert _count(page, "toolresult") == 1
