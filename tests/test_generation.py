"""Unit- und Regression-Tests fuer app/services/chat.py (MessageService).

Regression-Verhalten (README/SPEC): Beim Abbruch einer laufenden Generierung bleibt
nur der bereits abgeschlossene Block persistiert; der offene (in-flight) Block wird
verworfen. Die DB wird nicht pro Chunk geoeffnet.
"""

from __future__ import annotations

import asyncio

import pytest

from app.auth import user_identity
from app.db import database as dbq
from app.db.database import Database
from app.services.sse import parse_sse_buffer
from app.services.chat import MessageService, _SessionState
from app.services.store import SqliteUserStore

SECRET = "test-secret"
EMAIL = "gen@example.com"


@pytest.fixture()
def user():
    return user_identity(SECRET, EMAIL)


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "data")


@pytest.fixture()
def svc(db):
    return MessageService(SqliteUserStore(db))


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


def test_request_abort_returns_false_when_nothing_running(svc, user):
    assert svc.request_abort(user, "sid-1") is False
    assert svc.is_running(user, "sid-1") is False


def test_request_abort_sets_registered_event(svc, user):
    key = svc._key(user, "sid-2")
    state = _SessionState([])
    state.generation = asyncio.Event()
    svc._sessions[key] = state
    try:
        assert svc.is_running(user, "sid-2") is True
        assert svc.request_abort(user, "sid-2") is True
        assert state.generation is not None and state.generation.is_set()
    finally:
        svc._sessions.pop(key, None)


def test_abort_key_is_scoped_per_user(svc, user):
    other = user_identity(SECRET, "other@example.com")
    state = _SessionState([])
    state.generation = asyncio.Event()
    svc._sessions[svc._key(user, "sid-3")] = state
    try:
        # dieselbe Session-ID eines anderen Users darf nicht mit-abgebrochen werden
        assert svc.request_abort(other, "sid-3") is False
    finally:
        svc._sessions.pop(svc._key(user, "sid-3"), None)


# --- generate (Regression) ---


def test_run_generation_persists_content_reasoning_and_toolcalls(svc, db, user, sid, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield _sse({"reasoning_content": "denke"}, {"content": "Hallo "}, {"content": "Welt"},
                   {"tool_calls": [{"index": 0, "function": {"name": "f", "arguments": "{\\n}"}}]},
                   {"tool_results": [{"index": 0, "name": "f", "result": "42\\nGrad"}]})

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    asyncio.run(svc.generate(user, sid, "http://llm.test/v1", "k", {"messages": []}))

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
    assert svc.is_running(user, sid) is False


def test_run_generation_keeps_repeated_block_cycles_separate_with_switch_timestamps(svc, db, user, sid, monkeypatch):
    """Zwei volle Zyklen (reasoning, toolcall, toolresult, message) in einem Stream:
    8 eigene Zeilen in Stream-Reihenfolge (keine Akkumulation), jeder Block mit seinem
    Abschluss-Zeitstempel (ms) beim Typwechsel im Stream."""

    async def fake_stream(*args, **kwargs):
        yield _sse(
            {"reasoning_content": "denke 1 "},
            {"tool_calls": [{"index": 0, "function": {"name": "f", "arguments": "{}"}}]},
            {"tool_results": [{"index": 0, "name": "f", "result": "42"}]},
            {"content": "Antwort 1"},
            {"reasoning_content": "denke 2 "},
            {"tool_calls": [{"index": 1, "function": {"name": "g", "arguments": "{}"}}]},
            {"tool_results": [{"index": 1, "name": "g", "result": "43"}]},
            {"content": "Antwort 2"},
        )

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    asyncio.run(svc.generate(user, sid, "http://llm.test/v1", "k", {"messages": []}))

    with db.user_db(user) as con:
        messages = dbq.q_get_messages(con, sid)
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert [m["type"] for m in assistant] == ["reasoning", "toolcall", "toolresult", "message"] * 2
    assert [m["text"] for m in assistant] == [
        "denke 1 ",
        "f({})",
        "f: 42",
        "Antwort 1",
        "denke 2 ",
        "g({})",
        "g: 43",
        "Antwort 2",
    ]
    ts = [m["ts"] for m in assistant]
    assert all(a < b for a, b in zip(ts, ts[1:])), f"jeder Block braucht eigenen, steigenden Ts: {ts}"


def test_toolcall_done_signal_closes_toolcall_block_without_toolresult_row(svc, db, user, sid, monkeypatch):
    """Signal-Dummy des LLM-Servers ({"tool_results":[{"index":0,"signal":"toolcall_done"}]}):
    schliesst den offenen Toolcall-Block sofort (Zeile wird persistiert, bevor das echte
    Toolresult eintrifft), legt aber keinen Toolresult-Block an."""

    release = asyncio.Event()

    async def fake_stream(*args, **kwargs):
        yield _sse({"tool_calls": [{"index": 0, "function": {"name": "f", "arguments": "{}"}}]})
        yield _sse({"tool_results": [{"index": 0, "signal": "toolcall_done"}]})
        await release.wait()  # serverseitige Tool-Ausfuehrung: keine Chunks
        yield _sse({"tool_results": [{"index": 0, "name": "f", "result": "42"}]})
        yield _sse({"content": "Antwort"})

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        task = asyncio.create_task(svc.generate(user, sid, "http://llm.test/v1", "k", {"messages": []}))
        await asyncio.sleep(0.5)  # Pause wie bei echter Tool-Ausfuehrung
        with db.user_db(user) as con:
            during = [(m["type"], m["text"]) for m in dbq.q_get_messages(con, sid) if m["role"] == "assistant"]
        assert during == [("toolcall", "f({})")], f"Toolcall muss vor dem Toolresult persistiert sein: {during}"
        release.set()
        await asyncio.wait_for(task, timeout=5)
        with db.user_db(user) as con:
            after = [(m["type"], m["text"]) for m in dbq.q_get_messages(con, sid) if m["role"] == "assistant"]
        # kein leerer Signal-Block; das echte Toolresult landet in eigener Zeile
        assert after == [("toolcall", "f({})"), ("toolresult", "f: 42"), ("message", "Antwort")]

    asyncio.run(main())


def test_abort_discards_inflight_block_and_clears_generating(svc, db, user, sid, monkeypatch):
    """Abbruch mitten im Stream: bereits abgeschlossene Bloecke bleiben persistiert,
    der offene (in-flight) Block wird verworfen; kein Fehler-System-Message; generating=0."""

    async def fake_stream(*args, **kwargs):
        yield _sse({"reasoning_content": "denke "})  # Block 1
        yield _sse({"content": "Teil 1 "})  # schliesst Block 1, oeffnet Block 2 (message)
        # Abbruch wird von aussen angefordert, waehrend der Stream noch laeuft
        svc.request_abort(user, sid)
        yield _sse({"content": "VERWORFEN"})  # wird verworfen
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    asyncio.run(svc.generate(user, sid, "http://llm.test/v1", "k", {"messages": []}))

    with db.user_db(user) as con:
        session = dbq.q_get_session(con, sid)
        messages = dbq.q_get_messages(con, sid)
    assert session["generating"] is False
    assistant = [m for m in messages if m["role"] == "assistant"]
    # nur der abgeschlossene reasoning-Block ist persistiert; der offene Message-Block nicht
    assert [(m["type"], m["text"]) for m in assistant] == [("reasoning", "denke ")]
    # Abbruch ist kein Fehler: keine System-Fehlermeldung
    assert not [m for m in messages if m["role"] == "system"]
    assert svc.is_running(user, sid) is False
    assert svc.request_abort(user, sid) is False


def test_run_generation_persists_error_event_as_system_message(svc, db, user, sid, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield 'data: {"error": "LLM-Server nicht erreichbar"}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    asyncio.run(svc.generate(user, sid, "http://llm.test/v1", "k", {"messages": []}))

    with db.user_db(user) as con:
        session = dbq.q_get_session(con, sid)
        messages = dbq.q_get_messages(con, sid)
    assert session["generating"] is False
    system = [m for m in messages if m["role"] == "system"]
    assert len(system) == 1
    assert "LLM-Server nicht erreichbar" in system[0]["text"]


def test_inflight_block_not_persisted_until_block_completes(svc, db, user, sid, monkeypatch):
    """Performance-Regression: die per-user DB wird nicht pro Chunk geoeffnet/geschrieben.
    Der offene Block landet erst als eine Zeile mit komplettem Text, wenn der Block
    abgeschlossen ist (hier: Stream-Ende)."""
    from app.db.database import Database

    opens = []
    orig_user_db = Database.user_db

    def spy_user_db(self, u):
        opens.append(1)
        return orig_user_db(self, u)

    monkeypatch.setattr(Database, "user_db", spy_user_db)

    writes = []
    orig_add = dbq.q_add_message

    def spy_add(con, s, data):
        writes.append(data.get("text"))
        return orig_add(con, s, data)

    monkeypatch.setattr(dbq, "q_add_message", spy_add)

    release = asyncio.Event()

    async def fake_stream(*args, **kwargs):
        yield 'data: {"choices":[{"delta":{"content":"Teil A "}}]}\n\n'
        await release.wait()  # kein weiterer Chunk, bis der Test freigibt
        yield 'data: {"choices":[{"delta":{"content":"Teil B"}}]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        task = asyncio.create_task(svc.generate(user, sid, "http://llm.test/v1", "k", {"messages": []}))
        await asyncio.sleep(0.5)  # laenger als das alte FLUSH_INTERVAL_S (0.25 s)
        with orig_user_db(db, user) as con:  # am Spy vorbei, damit nur Task-Oeffnen zaehlen
            assert dbq.q_get_messages(con, sid) == [], "offener Block darf nicht in die DB"
        assert writes == [], f"offener Block darf nicht pro Chunk persistiert werden: {writes}"
        release.set()
        await asyncio.wait_for(task, timeout=5)
        with orig_user_db(db, user) as con:
            texts = [m["text"] for m in dbq.q_get_messages(con, sid) if m["role"] == "assistant"]
        assert texts == ["Teil A Teil B"]  # eine Zeile, kompletter Text
        assert writes == ["Teil A Teil B"]

    asyncio.run(main())
    # DB-Oeffnen: 1x Hot-State-Load (_hot) + 1x finaler Flush (keine Zwischen-Flushes pro Chunk)
    assert len(opens) == 2, opens


def test_run_generation_unknown_session_is_noop(svc, db, user, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield _sse({"content": "x"})
        raise AssertionError("Stream darf bei unbekannter Session nicht konsumiert werden")

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    asyncio.run(svc.generate(user, "gibts-nicht", "http://llm.test/v1", "k", {"messages": []}))
    assert svc.is_running(user, "gibts-nicht") is False
