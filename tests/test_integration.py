"""Integrations-Tests ueber mehrere Endpunkte hinweg (TestClient + echte App).

- Gleichzeitige Generierungen zweier User duerfen sich nicht beeinflussen
  (pro-User generating-Flag / Abort-Key).
- Settings und Sessions muessen einen App-Neustart (neue App-Instanz auf
  demselben Datenverzeichnis) ueberleben.
- Abbruch ueber die API behaelt die gestreamte Teilausgabe (End-to-End).
"""

from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.chat import MessageService
from tests.conftest import login_client, login_via_api


def _new_session(client, headers, name="Int") -> str:
    res = client.post("/api/sessions", json={"name": name}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _start_chat(client, headers, sid: str):
    return client.post(
        "/api/chat",
        json={"session_id": sid, "model": "m", "messages": [{"role": "user", "content": "Hi"}]},
        headers=headers,
    )


def _wait_generating(client, headers, sid: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/api/sessions/{sid}", headers=headers).json()
        if not last["generating"]:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Generierung wurde nicht fertig: {last}")


def test_concurrent_generations_of_two_users_are_independent(client, auth_headers, app, monkeypatch):
    """Regression: generating-Flag und Abort-Key sind pro User+Session scoped."""
    gates = {}

    async def fake_generate(self, user, sid, state, active, *args, **kwargs):
        gate = asyncio.Event()
        gates[f"{user['uid']}:{sid}"] = gate
        await self._store.set_generating(user, sid, True)
        try:
            await asyncio.wait_for(gate.wait(), timeout=10)
        finally:
            await self._store.set_generating(user, sid, False)

    monkeypatch.setattr(MessageService, "_generate", fake_generate)

    alice = client  # auth_headers = alice
    sid_a = _new_session(alice, auth_headers, "Alice")
    # Context-Manager noetig, damit Bobs Hintergrund-Task nicht mit dem Request endet
    with login_client(app, "bob@example.com") as bob:
        sid_b = _new_session(bob, {}, "Bob")

        assert _start_chat(alice, auth_headers, sid_a).status_code == 202
        # Bob darf trotz laufender Alice-Generierung sofort starten (kein globales 409)
        assert _start_chat(bob, {}, sid_b).status_code == 202

        # Beide Sessions sind unabhaengig als "generating" markiert
        deadline = time.time() + 5
        while time.time() < deadline:
            gen_a = alice.get(f"/api/sessions/{sid_a}", headers=auth_headers).json()["generating"]
            gen_b = bob.get(f"/api/sessions/{sid_b}").json()["generating"]
            if gen_a and gen_b:
                break
            time.sleep(0.05)
        assert gen_a and gen_b

        for gate in gates.values():
            gate.set()
        assert _wait_generating(alice, auth_headers, sid_a)["generating"] is False
        assert _wait_generating(bob, {}, sid_b)["generating"] is False


def test_settings_and_sessions_survive_app_restart(config):
    """Neue App-Instanz auf demselben Datenverzeichnis sieht alte Daten."""
    app1 = create_app(config=config)
    client1 = login_client(app1, "restart@example.com")
    res = client1.put(
        "/api/settings",
        json={"theme": "dark", "model": "gpt-restart", "system_prompt": "Bleib dran."},
    )
    assert res.status_code == 200, res.text
    sid = _new_session(client1, {}, "Restart-Session")
    res = client1.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "text": "Hallo Restart"},
    )
    assert res.status_code == 201, res.text

    # "Neustart": frische App-Instanz, gleiche Registry + gleiche per-user DB
    app2 = create_app(config=config)
    client2 = TestClient(app2)
    login_via_api(client2, "restart@example.com")

    settings = client2.get("/api/settings").json()
    assert settings["theme"] == "dark"
    assert settings["model"] == "gpt-restart"
    assert settings["system_prompt"] == "Bleib dran."

    sessions = client2.get("/api/sessions").json()
    assert [s["id"] for s in sessions] == [sid]
    detail = client2.get(f"/api/sessions/{sid}").json()
    assert [m["text"] for m in detail["messages"]] == ["Hallo Restart"]


def test_abort_via_api_discards_inflight_block_end_to_end(client, app, auth_headers, monkeypatch):
    """End-to-end: POST /api/chat/abort mitten im Stream - der abgeschlossene Block bleibt
    persistiert, der offene (in-flight) Block wird verworfen (nicht in der Session)."""

    async def fake_stream(*args, **kwargs):
        yield 'data: {"choices":[{"delta":{"reasoning_content":"denke"}}]}\n\n'
        yield 'data: {"choices":[{"delta":{"content":"Teil "}}]}\n\n'  # schliesst reasoning-Block
        for _ in range(500):
            if any(st.generation and st.generation.abort.is_set() for st in app.state.message_service._sessions.values()):
                break
            await asyncio.sleep(0.01)
        yield 'data: {"choices":[{"delta":{"content":"VERWORFEN"}}]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    sid = _new_session(client, auth_headers)
    assert _start_chat(client, auth_headers, sid).status_code == 202

    deadline = time.time() + 5
    while time.time() < deadline:
        detail = client.get(f"/api/sessions/{sid}", headers=auth_headers).json()
        if detail["generating"] and any(m["type"] == "reasoning" for m in detail["messages"]):
            break
        time.sleep(0.05)
    assert any(m["text"] == "denke" for m in detail["messages"])

    res = client.post("/api/chat/abort", json={"session_id": sid}, headers=auth_headers)
    assert res.status_code == 200

    detail = _wait_generating(client, auth_headers, sid)
    texts = [m["text"] for m in detail["messages"] if m["role"] == "assistant"]
    assert texts == ["denke"]  # nur der abgeschlossene Block; "Teil "/"VERWORFEN" verworfen
    assert not any(m["role"] == "system" for m in detail["messages"])
