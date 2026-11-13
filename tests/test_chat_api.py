from __future__ import annotations

import asyncio
import json
import time

import httpx

from app.db import database as dbq
from app.services import generation

RealAsyncClient = httpx.AsyncClient

SSE_BODY = (
    b'data: {"choices":[{"delta":{"reasoning_content":"denke"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"Hallo"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":" Welt"}}]}\n\n'
    b'data: {"choices":[{"delta":{"tool_calls":[{"function":{"name":"f","arguments":"{}"}}]}}]}\n\n'
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

    async def fake_gen(db, user, sid, *args, **kwargs):
        with db.user_db(user) as con:
            dbq.q_set_generating(con, sid, True)
        try:
            await asyncio.wait_for(release.wait(), timeout=10)
        finally:
            with db.user_db(user) as con:
                dbq.q_set_generating(con, sid, False)

    monkeypatch.setattr("app.routers.chat.run_generation", fake_gen)
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


def test_chat_abort_endpoint(client, auth_headers, monkeypatch):
    observed = {}

    async def fake_gen(db, user, sid, *args, **kwargs):
        key = f"{user['uid']}:{sid}"
        ev = asyncio.Event()
        generation._abort_events[key] = ev
        try:
            await asyncio.wait_for(ev.wait(), timeout=10)
            observed["aborted"] = True
        finally:
            generation._abort_events.pop(key, None)

    monkeypatch.setattr("app.routers.chat.run_generation", fake_gen)
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202

    deadline = time.time() + 5
    while time.time() < deadline and not any(k.endswith(":" + sid) for k in generation._abort_events):
        time.sleep(0.05)
    assert any(k.endswith(":" + sid) for k in generation._abort_events)

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


def test_chat_abort_cancels_stalled_upstream_stream(client, auth_headers, monkeypatch):
    """Abort muss auch wirken, wenn das LLM (noch) keine Chunks liefert: der
    haengende Upstream-Read wird gecancelt, die Teilausgabe bleibt erhalten."""
    pause_s = 30.0

    async def handler(request: httpx.Request) -> httpx.Response:
        async def body():
            yield b'data: {"choices":[{"delta":{"content":"Teil A "}}]}\n\n'
            await asyncio.sleep(pause_s)
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

    deadline = time.time() + 5
    while time.time() < deadline:
        detail = client.get(f"/api/sessions/{sid}", headers=auth_headers).json()
        if any(m["text"] == "Teil A " for m in detail["messages"]):
            break
        time.sleep(0.05)
    assert detail["generating"] is True
    assert any(m["text"] == "Teil A " for m in detail["messages"])

    t0 = time.time()
    res = client.post("/api/chat/abort", json={"session_id": sid}, headers=auth_headers)
    assert res.status_code == 200
    detail = _wait_generation(client, auth_headers, sid, timeout=5)
    assert time.time() - t0 < pause_s  # Abort wirkt sofort, nicht erst nach der Pause
    texts = [m["text"] for m in detail["messages"]]
    assert "Teil A " in texts
    assert not any("Teil B" in t for t in texts)
    assert not any(m["role"] == "system" for m in detail["messages"]), "Abbruch darf keine Fehlermeldung erzeugen"
    assert generation._running == set()
    assert generation._abort_events == {}
    assert generation._abort_requested == set()


def test_chat_filters_reasoning_and_tool_output_server_side(client, auth_headers, monkeypatch):
    _mock_llm(monkeypatch)
    client.put(
        "/api/settings",
        json={"show_reasoning": False, "show_tool_output": False},
        headers=auth_headers,
    )
    sid = _new_session(client, auth_headers)
    _post_user_message(client, auth_headers, sid)
    assert _start_chat(client, auth_headers, sid).status_code == 202
    detail = _wait_generation(client, auth_headers, sid)
    types = [(m["role"], m["type"]) for m in detail["messages"]]
    assert ("assistant", "message") in types
    assert ("assistant", "reasoning") not in types
    assert ("assistant", "toolcall") not in types


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
