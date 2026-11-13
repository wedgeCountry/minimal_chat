"""Unit- und Regression-Tests fuer app/services/generation.py.

Regression-Verhalten (README/SPEC): Beim Abbruch einer laufenden Generierung
bleibt die bis dahin gestreamte Teilausgabe in der Session erhalten.
"""

from __future__ import annotations

import asyncio

import pytest

from app.auth import user_identity
from app.db import database as dbq
from app.db.database import Database
from app.services import generation
from app.services.sse import parse_sse_buffer
from app.services.generation import is_running, request_abort, run_generation

SECRET = "test-secret"
EMAIL = "gen@example.com"


@pytest.fixture()
def user():
    return user_identity(SECRET, EMAIL)


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "data")


@pytest.fixture()
def sid(db, user):
    with db.user_db(user) as con:
        return dbq.q_create_session(con, "Gen-Test")["id"]


def _sse(*deltas) -> str:
    import json

    parts = []
    for d in deltas:
        parts.append("data: " + json.dumps({"choices": [{"delta": d}]}) + "\n\n")
    parts.append("data: [DONE]\n\n")
    return "".join(parts)


# --- parse_sse_buffer (Unit) ---


def test_parse_sse_buffer_skips_done_and_invalid_json():
    import json

    good = json.dumps({"choices": [{"delta": {"content": "x"}}]})
    events, rest = parse_sse_buffer(f"data: [DONE]\ndata: {{broken\ndata: {good}\ndata: partial")
    assert len(events) == 1
    assert events[0]["choices"][0]["delta"]["content"] == "x"
    assert rest == "data: partial"


def test_parse_sse_buffer_ignores_non_data_lines():
    events, rest = parse_sse_buffer(": ping\nevent: message\n")
    assert events == []
    assert rest == ""


# --- request_abort / is_running (Unit) ---


def test_request_abort_returns_false_when_nothing_running(user):
    assert request_abort(user, "sid-1") is False
    assert is_running(user, "sid-1") is False


def test_request_abort_sets_registered_event(user):
    key = generation._key(user, "sid-2")
    ev = asyncio.Event()
    generation._abort_events[key] = ev
    generation._running.add(key)
    try:
        assert is_running(user, "sid-2") is True
        assert request_abort(user, "sid-2") is True
        assert ev.is_set()
    finally:
        generation._abort_events.pop(key, None)
        generation._running.discard(key)


def test_abort_key_is_scoped_per_user(user):
    other = user_identity(SECRET, "other@example.com")
    key = generation._key(user, "sid-3")
    generation._abort_events[key] = asyncio.Event()
    try:
        # dieselbe Session-ID eines anderen Users darf nicht mit-abgebrochen werden
        assert request_abort(other, "sid-3") is False
    finally:
        generation._abort_events.pop(key, None)


# --- run_generation (Regression) ---


def test_run_generation_persists_content_reasoning_and_toolcalls(db, user, sid, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield _sse({"reasoning_content": "denke"}, {"content": "Hallo "}, {"content": "Welt"},
                   {"tool_calls": [{"index": 0, "function": {"name": "f", "arguments": "{\\n}"}}]},
                   {"tool_results": [{"index": 0, "name": "f", "result": "42\\nGrad"}]})

    monkeypatch.setattr("app.services.generation.stream_completion", fake_stream)
    asyncio.run(run_generation(db, user, sid, "http://llm.test/v1", "k", {"messages": []}))

    with db.user_db(user) as con:
        session = dbq.q_get_session(con, sid)
        messages = dbq.q_get_messages(con, sid)
    assert session["generating"] is False
    texts = {(m["role"], m["type"]): m["text"] for m in messages}
    assert texts[("assistant", "reasoning")] == "denke"
    assert texts[("assistant", "message")] == "Hallo Welt"
    # literale "\n" aus den JSON-String-Literalen werden als echte Umbrueche persistiert
    assert texts[("assistant", "toolcall")] == "f({\n})"
    assert texts[("assistant", "toolresult")] == "f: 42\nGrad"
    assert is_running(user, sid) is False


def test_abort_keeps_partial_output_and_clears_generating(db, user, sid, monkeypatch):
    """Regression: Abbruch mitten im Stream - Teilausgabe bleibt erhalten."""

    async def fake_stream(*args, **kwargs):
        yield 'data: {"choices":[{"delta":{"content":"Teil 1 "}}]}\n\n'
        # Abbruch wird von aussen angefordert, waehrend der Stream noch laeuft
        request_abort(user, sid)
        yield 'data: {"choices":[{"delta":{"content":"VERWORFEN"}}]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.services.generation.stream_completion", fake_stream)
    asyncio.run(run_generation(db, user, sid, "http://llm.test/v1", "k", {"messages": []}))

    with db.user_db(user) as con:
        session = dbq.q_get_session(con, sid)
        messages = dbq.q_get_messages(con, sid)
    assert session["generating"] is False
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert [m["text"] for m in assistant] == ["Teil 1 "]
    # Abbruch ist kein Fehler: keine System-Fehlermeldung
    assert not [m for m in messages if m["role"] == "system"]
    assert is_running(user, sid) is False
    assert request_abort(user, sid) is False


def test_run_generation_persists_error_event_as_system_message(db, user, sid, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield 'data: {"error": "LLM-Server nicht erreichbar"}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.services.generation.stream_completion", fake_stream)
    asyncio.run(run_generation(db, user, sid, "http://llm.test/v1", "k", {"messages": []}))

    with db.user_db(user) as con:
        session = dbq.q_get_session(con, sid)
        messages = dbq.q_get_messages(con, sid)
    assert session["generating"] is False
    system = [m for m in messages if m["role"] == "system"]
    assert len(system) == 1
    assert "LLM-Server nicht erreichbar" in system[0]["text"]


def test_partial_output_flushed_within_interval_without_new_chunk(db, user, sid, monkeypatch):
    """Regression: Teilausgabe muss nach spaetestens ~FLUSH_INTERVAL_S in der DB
    landen, auch wenn der LLM-Stream keinen weiteren Chunk schickt."""
    import time

    release = asyncio.Event()

    async def fake_stream(*args, **kwargs):
        yield 'data: {"choices":[{"delta":{"content":"Teil A "}}]}\n\n'
        await release.wait()  # kein weiterer Chunk, bis der Test freigibt
        yield 'data: {"choices":[{"delta":{"content":"Teil B"}}]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.services.generation.stream_completion", fake_stream)

    async def main():
        task = asyncio.create_task(run_generation(db, user, sid, "http://llm.test/v1", "k", {"messages": []}))
        deadline = time.monotonic() + 2.0  # deutlich unter der release-Wartezeit
        seen = []
        while time.monotonic() < deadline:
            with db.user_db(user) as con:
                seen = [m["text"] for m in dbq.q_get_messages(con, sid) if m["role"] == "assistant"]
            if seen:
                break
            await asyncio.sleep(0.05)
        assert seen == ["Teil A "], f"Teilausgabe wurde nicht ohne neuen Chunk geflusht: {seen}"
        release.set()
        await asyncio.wait_for(task, timeout=5)
        with db.user_db(user) as con:
            texts = [m["text"] for m in dbq.q_get_messages(con, sid) if m["role"] == "assistant"]
        assert texts == ["Teil A Teil B"]

    asyncio.run(main())


def test_run_generation_unknown_session_is_noop(db, user, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield _sse({"content": "x"})
        raise AssertionError("Stream darf bei unbekannter Session nicht konsumiert werden")

    monkeypatch.setattr("app.services.generation.stream_completion", fake_stream)
    asyncio.run(run_generation(db, user, "gibts-nicht", "http://llm.test/v1", "k", {"messages": []}))
    assert is_running(user, "gibts-nicht") is False
