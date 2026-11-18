from __future__ import annotations

import asyncio
import json
import time

import httpx
from fastapi.testclient import TestClient

from app.auth import user_identity
from app.db import database as dbq
from app.services.chat import MessageService

RealAsyncClient = httpx.AsyncClient

SSE_BODY = (
    b'data: {"choices":[{"delta":{"reasoning_content":"denke"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"Hallo"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":" Welt"}}]}\n\n'
    b'data: {"choices":[{"delta":{"tool_calls":[{"function":{"name":"f","arguments":"{}"}}]}}]}\n\n'
    b"data: [DONE]\n\n"
)

SSE_BODY_TOOLS = (
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"f","arguments":"{}"}}]}}]}\n\n'
    b'data: {"choices":[{"delta":{"tool_results":[{"index":0,"name":"f","result":"42 Grad"}]}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"Antwort"}}]}\n\n'
    b"data: [DONE]\n\n"
)


def _mock_llm(monkeypatch, body: bytes = SSE_BODY):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", factory)
    return seen


def _new_session(client, auth_headers, name="Test") -> str:
    res = client.post("/api/sessions", json={"name": name}, headers=auth_headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _post_user_message(client, auth_headers, sid: str, text="Hi") -> None:
    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "type": "message", "text": text, "in_context": True},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text


def _start_chat(client, auth_headers, sid: str, messages=None) -> httpx.Response:
    return client.post(
        "/api/chat",
        json={
            "session_id": sid,
            "model": "gpt-4o-mini",
            "messages": messages if messages is not None else [{"role": "user", "content": "Hi"}],
        },
        headers=auth_headers,
    )


def _wait_generation(client, auth_headers, sid: str, timeout: float = 10.0) -> dict:
    """Pollt die Session, bis die serverseitige Generierung fertig ist."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        res = client.get(f"/api/sessions/{sid}", headers=auth_headers)
        assert res.status_code == 200, res.text
        last = res.json()
        if not last["generating"]:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Generierung wurde nicht fertig ( letzter Stand: {last})")


def test_chat_starts_background_generation_and_persists(client, auth_headers, monkeypatch):
    seen = _mock_llm(monkeypatch)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)

    res = _start_chat(client, auth_headers, sid)
    assert res.status_code == 202
    assert res.json() == {"status": "started"}

    detail = _wait_generation(client, auth_headers, sid)
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer test-api-key"
    assert seen["body"]["stream"] is True
    assert seen["body"]["messages"] == [{"role": "user", "content": "Hi"}]

    texts = [(m["role"], m["type"], m["text"]) for m in detail["messages"]]
    assert ("user", "message", "Hi") in texts
    assert ("assistant", "reasoning", "denke") in texts
    assert ("assistant", "message", "Hallo Welt") in texts
    assert ("assistant", "toolcall", "f({})") in texts
    # Reasoning wurde vor der Antwort persistiert (id-Reihenfolge)
    ids = {m["type"]: m["id"] for m in detail["messages"] if m["role"] == "assistant"}
    assert ids["reasoning"] < ids["message"]


def test_chat_marks_session_generating_while_running(client, auth_headers, monkeypatch):
    release = asyncio.Event()

    async def fake_generate(self, user, sid, state, active, *args, **kwargs):
        await self._store.set_generating(user, sid, True)
        try:
            await asyncio.wait_for(release.wait(), timeout=10)
        finally:
            await self._store.set_generating(user, sid, False)

    monkeypatch.setattr(MessageService, "_generate", fake_generate)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)

    res = _start_chat(client, auth_headers, sid)
    assert res.status_code == 202

    deadline = time.time() + 5
    while time.time() < deadline:
        s = client.get(f"/api/sessions/{sid}", headers=auth_headers).json()
        if s["generating"]:
            break
        time.sleep(0.05)
    assert s["generating"] is True
    assert client.get("/api/sessions", headers=auth_headers).json()[0]["generating"] is True

    # zweite Generierung fuer dieselbe Session wird abgelehnt
    res = _start_chat(client, auth_headers, sid)
    assert res.status_code == 409

    release.set()
    _wait_generation(client, auth_headers, sid)


def test_chat_requires_auth(client):
    res = client.post("/api/chat", json={"session_id": "x", "model": "m", "messages": []})
    assert res.status_code == 401


def test_chat_unknown_session_404(client, auth_headers):
    res = _start_chat(client, auth_headers, "does-not-exist")
    assert res.status_code == 404


def test_chat_abort_endpoint(client, app, auth_headers, monkeypatch):
    observed = {}

    async def fake_generate(self, user, sid, state, active, *args, **kwargs):
        observed["active"] = active
        await asyncio.wait_for(active.abort.wait(), timeout=10)
        observed["aborted"] = True

    monkeypatch.setattr(MessageService, "_generate", fake_generate)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202

    deadline = time.time() + 5
    svc = app.state.message_service
    while time.time() < deadline and not any(
        k.endswith(":" + sid) and st.generation is not None for k, st in svc._sessions.items()
    ):
        time.sleep(0.05)
    assert any(k.endswith(":" + sid) and st.generation is not None for k, st in svc._sessions.items())

    res = client.post("/api/chat/abort", json={"session_id": sid}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"status": "aborted"}

    deadline = time.time() + 5
    while time.time() < deadline and not observed:
        time.sleep(0.05)
    assert observed.get("aborted") is True


def test_chat_abort_unknown_session_404(client, auth_headers):
    res = client.post("/api/chat/abort", json={"session_id": "nope"}, headers=auth_headers)
    assert res.status_code == 404


def test_chat_abort_clears_stale_generating_flag(client, app, auth_headers, monkeypatch):
    """Verwaistes generating=1 ohne laufende Task (z. B. Server-Neustart mitten in der
    Generierung): Abort setzt das Flag auf 0, sonst pollt der Client endlos. Der verworfene
    Abort-Request darf eine spaetere Generierung derselben Session nicht sofort abbrechen."""
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    user = user_identity("test-secret", "alice@example.com")
    asyncio.run(app.state.store.set_generating(user, sid, True))
    assert client.get(f"/api/sessions/{sid}", headers=auth_headers).json()["generating"] is True
    assert not any(st.generation for st in app.state.message_service._sessions.values())

    res = client.post("/api/chat/abort", json={"session_id": sid}, headers=auth_headers)
    assert res.status_code == 200
    assert client.get(f"/api/sessions/{sid}", headers=auth_headers).json()["generating"] is False
    assert app.state.message_service._abort_requested == set()

    # neue Generierung derselben Session laeuft normal durch (kein verwaister Abort-Request)
    _mock_llm(monkeypatch)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    detail = _wait_generation(client, auth_headers, sid)
    assert any(m["text"] == "Hallo Welt" for m in detail["messages"])


def test_chat_heals_stale_generating_flag_instead_of_409(client, app, auth_headers, monkeypatch):
    """Verwaistes generating=1 ohne laufende Task (z. B. Server-Neustart mitten in der
    Generierung): der naechste POST /api/chat heilt das Flag im Service (unter dem
    Session-Lock) und startet normal - statt dauerhaft 409 zu liefern."""
    seen = _mock_llm(monkeypatch)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    user = user_identity("test-secret", "alice@example.com")
    asyncio.run(app.state.store.set_generating(user, sid, True))
    assert client.get(f"/api/sessions/{sid}", headers=auth_headers).json()["generating"] is True
    assert not any(st.generation for st in app.state.message_service._sessions.values())

    res = _start_chat(client, auth_headers, sid)
    assert res.status_code == 202, res.text
    detail = _wait_generation(client, auth_headers, sid)
    assert detail["generating"] is False
    assert seen["body"]["messages"] == [{"role": "user", "content": "Hi"}]
    assert any(m["text"] == "Hallo Welt" for m in detail["messages"])


def test_chat_abort_without_generating_keeps_flag_zero(client, auth_headers):
    sid = _new_session(client, auth_headers)
    res = client.post("/api/chat/abort", json={"session_id": sid}, headers=auth_headers)
    assert res.status_code == 200
    assert client.get(f"/api/sessions/{sid}", headers=auth_headers).json()["generating"] is False


def test_chat_abort_cancels_stalled_upstream_stream(client, app, auth_headers, monkeypatch):
    """Abort muss auch wirken, wenn das LLM (noch) keine Chunks liefert: der haengende
    Upstream-Read wird gecancelt. Bereits abgeschlossene Bloecke bleiben persistiert,
    der offene (in-flight) Block wird verworfen."""
    pause_s = 30.0

    async def handler(request: httpx.Request) -> httpx.Response:
        async def body():
            yield b'data: {"choices":[{"delta":{"reasoning_content":"denke"}}]}\n\n'
            yield b'data: {"choices":[{"delta":{"content":"Teil A "}}]}\n\n'  # schliesst reasoning-Block
            await asyncio.sleep(pause_s)  # haengender Read: message-Block bleibt offen
            yield b'data: {"choices":[{"delta":{"content":"Teil B"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", factory)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid, "langsam")
    assert _start_chat(client, auth_headers, sid).status_code == 202

    # warten, bis der reasoning-Block abgeschlossen und persistiert ist (message-Block offen)
    deadline = time.time() + 5
    while time.time() < deadline:
        detail = client.get(f"/api/sessions/{sid}", headers=auth_headers).json()
        if detail["generating"] and any(m["type"] == "reasoning" for m in detail["messages"]):
            break
        time.sleep(0.05)
    assert detail["generating"] is True
    assert any(m["text"] == "denke" for m in detail["messages"])
    assert not any(m["type"] == "message" and m["role"] == "assistant" for m in detail["messages"])

    t0 = time.time()
    res = client.post("/api/chat/abort", json={"session_id": sid}, headers=auth_headers)
    assert res.status_code == 200
    detail = _wait_generation(client, auth_headers, sid, timeout=5)
    assert time.time() - t0 < pause_s  # Abort wirkt sofort, nicht erst nach der Pause
    texts = [m["text"] for m in detail["messages"]]
    assert "denke" in texts  # abgeschlossener Block bleibt erhalten
    assert not any("Teil A" in t or "Teil B" in t for t in texts)  # in-flight Block verworfen
    assert not any(m["role"] == "system" for m in detail["messages"]), "Abbruch darf keine Fehlermeldung erzeugen"
    svc = app.state.message_service
    assert not any(st.generation for st in svc._sessions.values())
    assert svc._abort_requested == set()


def test_display_settings_do_not_strip_messages_from_persistence(client, auth_headers, monkeypatch):
    """Anzeige-Settings (show_reasoning/show_tool_output = aus) duerfen den LLM-Stream nicht
    serverseitig ausduennen: Reasoning/Toolcall/Toolresult werden trotzdem persistiert und
    liegen danach in GET /api/sessions/{id} - sonst fehlen sie beim Wiedereinblenden."""
    _mock_llm(monkeypatch, SSE_BODY_TOOLS)
    client.put(
        "/api/settings",
        json={"show_reasoning": False, "show_tool_output": False},
        headers=auth_headers,
    )
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    detail = _wait_generation(client, auth_headers, sid)
    types = {(m["role"], m["type"]): m["text"] for m in detail["messages"]}
    assert types[("assistant", "message")] == "Antwort"
    assert types[("assistant", "toolcall")] == "f({})"
    assert types[("assistant", "toolresult")] == "f: 42 Grad"


def test_tool_results_persisted_in_db_even_when_tool_output_hidden(client, app, auth_headers, monkeypatch):
    """Regression: 'Tool-Ausgabe anzeigen' abwaehlen -> Tool-Ergebnisse MUESSEN trotzdem in der
    per-user DB landen; nach erneutem Einschalten erscheinen sie wieder (GET /api/sessions/{id}
    und der naechste LLM-Request lesen sie aus der DB)."""
    seen = _mock_llm(monkeypatch, SSE_BODY_TOOLS)
    client.put("/api/settings", json={"show_tool_output": False}, headers=auth_headers)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    detail = _wait_generation(client, auth_headers, sid)

    # oeffentliche API (Quelle der Wahrheit = persistierter Stand): Toolcall + Toolresult vorhanden
    types = {(m["role"], m["type"]): m["text"] for m in detail["messages"]}
    assert types[("assistant", "toolcall")] == "f({})"
    assert types[("assistant", "toolresult")] == "f: 42 Grad"

    # direkt in der per-user DB: eigene toolresult-Zeile mit dem Ergebnis-Text
    user = user_identity(app.state.config.secret, "alice@example.com")
    with app.state.db.user_db(user) as con:
        rows = dbq.q_get_messages(con, sid)
    db_types = {(m["role"], m["type"]): m["text"] for m in rows}
    assert db_types[("assistant", "toolcall")] == "f({})"
    assert db_types[("assistant", "toolresult")] == "f: 42 Grad"

    # Einstellung zurueck auf 'anzeigen' -> Daten stehen dem Client weiterhin zur Verfuegung
    res = client.put("/api/settings", json={"show_tool_output": True}, headers=auth_headers)
    assert res.status_code == 200, res.text
    detail = client.get(f"/api/sessions/{sid}", headers=auth_headers).json()
    assert ("assistant", "toolresult") in [(m["role"], m["type"]) for m in detail["messages"]]

    # naechster LLM-Request wird serverseitig aus der DB gebaut: gepaartes tool-Message inkl. Ergebnis
    assert _start_chat(client, auth_headers, sid).status_code == 202
    _wait_generation(client, auth_headers, sid)
    tool_msgs = [m for m in seen["body"]["messages"] if m.get("role") == "tool"]
    assert tool_msgs, "Tool-Ergebnis aus der DB fehlt im naechsten LLM-Request"
    assert any("42 Grad" in (m.get("content") or "") for m in tool_msgs)


def test_chat_filters_system_prompt_from_request_server_side(client, auth_headers, monkeypatch):
    seen = _mock_llm(monkeypatch)
    client.put("/api/settings", json={"show_system_prompt": False}, headers=auth_headers)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(
        client,
        auth_headers,
        sid,
        messages=[
            {"role": "system", "content": "Du bist ein Assistent."},
            {"role": "user", "content": "Hi"},
        ],
    ).status_code == 202
    _wait_generation(client, auth_headers, sid)
    assert seen["body"]["messages"] == [{"role": "user", "content": "Hi"}]


def test_chat_uses_per_user_settings_and_key(client, auth_headers, monkeypatch):
    seen = _mock_llm(monkeypatch)
    client.put(
        "/api/settings",
        json={"base": "http://per-user.test/v1", "api_key": "sk-user"},
        headers=auth_headers,
    )
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    _wait_generation(client, auth_headers, sid)
    assert seen["url"] == "http://per-user.test/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-user"


def test_chat_upstream_error_persisted_as_system_message(client, auth_headers, monkeypatch):
    def handler(request):
        return httpx.Response(500, content=b"boom")

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", factory)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    detail = _wait_generation(client, auth_headers, sid)
    errors = [m["text"] for m in detail["messages"] if m["role"] == "system"]
    assert any("HTTP 500" in e for e in errors)
    # Upstream-Response-Body darf nicht an den Client geleakt werden
    assert all("boom" not in e for e in errors)


def test_chat_upstream_422_persisted_with_hint_and_without_body_leak(client, auth_headers, monkeypatch):
    """422 vom LLM (z. B. zu großer Request-Body): persistierter Fehler mit Hinweis auf die
    Kontext-Checkbox; der Upstream-Body darf nicht durchgereicht werden."""
    def handler(request):
        return httpx.Response(422, content=b'{"detail":[{"loc":["body","messages"],"msg":"internal-secret-canary"}]}')

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", factory)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    detail = _wait_generation(client, auth_headers, sid)
    errors = [m["text"] for m in detail["messages"] if m["role"] == "system"]
    assert any("HTTP 422" in e and "Kontext-Checkbox" in e for e in errors)
    assert all("internal-secret-canary" not in e for e in errors)


def test_context_checkbox_on_toolcall_excludes_tool_pair_from_llm_request(client, auth_headers, monkeypatch):
    """Kontext-Checkbox auch auf Tool-Call-/Tool-Result-Bubbles: abwaehlen des Tool-Calls
    spart das Paar aus dem naechsten LLM-Request aus (kein ungueltiges orphan tool)."""
    seen = _mock_llm(monkeypatch)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid, "Wetter in Berlin?")
    r_tc = client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "assistant", "type": "toolcall", "text": 'get_weather({"city":"Berlin"})', "in_context": True},
        headers=auth_headers,
    )
    r_tr = client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "assistant", "type": "toolresult", "text": "get_weather: 21C", "in_context": True},
        headers=auth_headers,
    )
    assert r_tc.status_code == 201 and r_tr.status_code == 201
    tc_id = r_tc.json()["id"]
    _post_user_message(client, auth_headers, sid, "Und morgen?")

    res = client.patch(f"/api/sessions/{sid}/messages/{tc_id}", json={"in_context": False}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["in_context"] is False

    assert _start_chat(client, auth_headers, sid).status_code == 202
    _wait_generation(client, auth_headers, sid)
    msgs = seen["body"]["messages"]
    assert not any(m.get("tool_calls") for m in msgs)
    assert not any(m["role"] == "tool" for m in msgs)
    assert msgs[0] == {"role": "user", "content": "Wetter in Berlin?"}
    assert msgs[-1] == {"role": "user", "content": "Und morgen?"}


def test_chat_rejects_too_many_messages(client, auth_headers):
    sid = _new_session(client, auth_headers)
    res = client.post(
        "/api/chat",
        json={"session_id": sid, "model": "m", "messages": [{"role": "user", "content": "x"}] * 501},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_chat_server_unreachable_persisted_as_system_message(client, auth_headers, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("Connection refused")

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", factory)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    detail = _wait_generation(client, auth_headers, sid)
    errors = [m["text"] for m in detail["messages"] if m["role"] == "system"]
    assert any("Fehler" in e and "Connection refused" in e for e in errors)


def test_chat_prepends_system_prompt_from_settings(client, auth_headers, monkeypatch):
    seen = _mock_llm(monkeypatch)
    client.put("/api/settings", json={"system_prompt": "Sei freundlich."}, headers=auth_headers)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    _wait_generation(client, auth_headers, sid)
    msgs = seen["body"]["messages"]
    assert msgs[0] == {"role": "system", "content": "Sei freundlich."}
    assert msgs[1] == {"role": "user", "content": "Hi"}


def test_chat_system_prompt_filtered_when_disabled(client, auth_headers, monkeypatch):
    seen = _mock_llm(monkeypatch)
    client.put("/api/settings", json={"system_prompt": "Sei freundlich.", "show_system_prompt": False}, headers=auth_headers)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    _wait_generation(client, auth_headers, sid)
    assert seen["body"]["messages"] == [{"role": "user", "content": "Hi"}]


def test_chat_uses_host_port_computed_base_url(client, auth_headers, monkeypatch):
    """Regression: host/port settings must drive the chat URL (single source of truth)."""
    seen = _mock_llm(monkeypatch)
    client.put("/api/settings", json={"host": "192.168.1.10", "port": "8000"}, headers=auth_headers)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    _wait_generation(client, auth_headers, sid)
    assert seen["url"] == "http://192.168.1.10:8000/v1/chat/completions"


def test_chat_uses_env_default_llm_host_port(client, auth_headers, monkeypatch, app):
    """Server-Default host/port (LEANCHAT_LLM_HOST/PORT) drives the chat URL."""
    seen = _mock_llm(monkeypatch)
    app.state.config.default_llm_host = "10.9.8.7"
    app.state.config.default_llm_port = "9999"
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    _wait_generation(client, auth_headers, sid)
    assert seen["url"] == "http://10.9.8.7:9999/v1/chat/completions"


def _parse_sse_events(body: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


def test_chat_stream_sse_emits_state_events_and_done(client, auth_headers, monkeypatch):
    """GET /api/chat/stream/{sid}: versionierte state-Events aus dem In-Memory-State
    des MessageService (state mit seq + messages inkl. Live-Messages -> done)."""
    from app.domain import Message

    async def fake_generate(self, user, sid, state, active, *args, **kwargs):
        state.messages.append(Message(id=None, role="assistant", type="message", text="Hallo"))
        state.seq += 1
        self._publish(state)
        await asyncio.sleep(0.05)
        state.messages[-1].text = "Hallo Welt"
        state.seq += 1
        self._publish(state)

    monkeypatch.setattr(MessageService, "_generate", fake_generate)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202

    with client.stream("GET", f"/api/chat/stream/{sid}", headers=auth_headers) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        body = res.read().decode("utf-8")

    events = _parse_sse_events(body)
    state_events = [e for e in events if e["type"] == "state"]
    assert events[0]["type"] == "state"
    assert [e["seq"] for e in state_events] == sorted(e["seq"] for e in state_events), "seq muss steigen"
    last = state_events[-1]
    live = [m for m in last["messages"] if m["id"] is None]
    assert live and live[-1]["text"] == "Hallo Welt" and live[-1]["role"] == "assistant"
    assert events[-1]["type"] == "done"


def test_chat_stream_idle_when_nothing_running(client, auth_headers):
    sid = _new_session(client, auth_headers)
    with client.stream("GET", f"/api/chat/stream/{sid}", headers=auth_headers) as res:
        assert res.status_code == 200
        events = _parse_sse_events(res.read().decode("utf-8"))
    assert events == [{"type": "idle"}]


def test_chat_stream_requires_auth_and_known_session(client, app, auth_headers):
    anon = TestClient(app)  # kein Session-Cookie -> 401
    assert anon.get("/api/chat/stream/x").status_code == 401
    assert client.get("/api/chat/stream/does-not-exist", headers=auth_headers).status_code == 404


def test_chat_stream_publishes_each_chunk_progressively_before_done(client, auth_headers, monkeypatch):
    """Streaming-Nachweis serverseitig: jeder LLM-Chunk erzeugt ein eigenes state-Event
    (wachsender Text) — bevor das finale done-Event kommt."""
    from app.domain import Message

    async def fake_generate(self, user, sid, state, active, *args, **kwargs):
        m = Message(id=None, role="assistant", type="message", text="")
        state.messages.append(m)
        for part in ("Ha", "llo ", "Welt"):
            m.text += part
            state.seq += 1
            self._publish(state)
            await asyncio.sleep(0.02)

    monkeypatch.setattr(MessageService, "_generate", fake_generate)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202

    with client.stream("GET", f"/api/chat/stream/{sid}", headers=auth_headers) as res:
        assert res.status_code == 200
        body = res.read().decode("utf-8")

    events = _parse_sse_events(body)
    assert events[-1]["type"] == "done", "Stream endet mit done"
    state_events = [e for e in events if e["type"] == "state"]
    # Live-Message (id=None) wuchs in jedem Event um genau einen Chunk
    live_texts = [
        m["text"] for e in state_events for m in e["messages"] if m["id"] is None and m["role"] == "assistant"
    ]
    assert live_texts == ["Ha", "Hallo ", "Hallo Welt"], f"jeder Chunk einzeln publiziert: {live_texts}"
    seqs = [e["seq"] for e in state_events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "seq steigt pro Event"
