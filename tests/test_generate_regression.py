"""Regression-Tests fuer den Generierungs-Durchlauf (MessageService._generate und die
Stream-Block-Akkumulation in app/services/chat.py). Sie pinnen das Verhalten, BEVOR der
Lauf weiter refactored wird: Block-Abschluss beim Typwechsel, ts-Monotonie, Tool-Akkus,
Abort/Fehler-Verhalten, Persistenz-Batching und das SSE-Event-Protokoll.

Laufen gegen InMemoryUserStore; der LLM-Stream wird gemockt. Pro Test genau ein
asyncio.run (asyncio.Lock bindet an den Loop).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.auth import user_identity
from app.services.chat import MessageService
from app.services.memory_store import InMemoryUserStore

SECRET = "reg-secret"
EMAIL = "reg@example.com"
BASE = "http://llm.test/v1"


@pytest.fixture()
def user():
    return user_identity(SECRET, EMAIL)


@pytest.fixture()
def store():
    return InMemoryUserStore()


@pytest.fixture()
def svc(store):
    return MessageService(store)


def _sse(*deltas) -> str:
    parts = []
    for d in deltas:
        parts.append("data: " + json.dumps({"choices": [{"delta": d}]}) + "\n\n")
    parts.append("data: [DONE]\n\n")
    return "".join(parts)


def _rows(detail) -> list[tuple[str, str, str, bool]]:
    return [(m.role, m.type, m.text, m.in_context) for m in detail[1]]


def test_reasoning_fallback_key_and_empty_deltas_create_no_blocks(svc, store, user, monkeypatch):
    """delta["reasoning"] (Fallback neben reasoning_content) erzeugt einen Reasoning-Block;
    leere/falsy Deltas (content "", leeres delta) erzeugen keinen Block."""

    async def fake_stream(*args, **kwargs):
        yield _sse({"reasoning": "alt-key"}, {"content": ""}, {}, {"content": "Antwort"})

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        await svc.generate(user, sid, BASE, "k", {"messages": []})
        return await store.get_session_detail(user, sid)

    detail = asyncio.run(main())
    assert _rows(detail) == [
        ("assistant", "reasoning", "alt-key", False),
        ("assistant", "message", "Antwort", True),
    ]


def test_toolcalls_without_index_get_sequential_block_ids(svc, store, user, monkeypatch):
    """Fehlt ``index``, wird er als Anzahl der bisherigen Bloecke des Typs gewaehlt:
    zwei Toolcalls ohne index in aufeinanderfolgenden Chunks landen in zwei Bloecken."""

    async def fake_stream(*args, **kwargs):
        yield _sse({"tool_calls": [{"function": {"name": "f", "arguments": "{}"}}]})
        yield _sse({"tool_calls": [{"function": {"name": "g", "arguments": "[]"}}]})
        yield _sse({"tool_results": [{"name": "f", "result": "1"}]})
        yield _sse({"tool_results": [{"name": "g", "result": "2"}]})

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        await svc.generate(user, sid, BASE, "k", {"messages": []})
        return await store.get_session_detail(user, sid)

    detail = asyncio.run(main())
    assert _rows(detail) == [
        ("assistant", "toolcall", "f({})", True),
        ("assistant", "toolcall", "g([])", True),
        ("assistant", "toolresult", "f: 1", True),
        ("assistant", "toolresult", "g: 2", True),
    ]


def test_toolresult_field_fallbacks(svc, store, user, monkeypatch):
    """Toolresult-Inhalt wird aus result ODER content/output/text ODER function.result/
    function.arguments gelesen; der Name aus name ODER function.name."""

    async def fake_stream(*args, **kwargs):
        yield _sse(
            {
                "tool_results": [
                    {"index": 0, "content": "via-content"},
                    {"index": 1, "output": "via-output"},
                    {"index": 2, "text": "via-text"},
                    {"index": 3, "function": {"name": "fn", "result": "via-fn-result"}},
                    {"index": 4, "function": {"arguments": "via-fn-args"}},
                    {"index": 5, "name": "named", "result": "R"},
                ]
            }
        )

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        await svc.generate(user, sid, BASE, "k", {"messages": []})
        return await store.get_session_detail(user, sid)

    detail = asyncio.run(main())
    assert [t for _r, _t, t, _c in _rows(detail)] == [
        "via-content",
        "via-output",
        "via-text",
        "fn: via-fn-result",
        "via-fn-args",
        "named: R",
    ]


def test_block_timestamps_stay_monotonic_with_frozen_clock(svc, store, user, monkeypatch):
    """ts je Block = max(now_ms, letzter+1): auch bei stehender Uhr steigen die
    Abschluss-Zeitstempel der Bloecke strikt."""
    monkeypatch.setattr("app.services.chat.now_ms", lambda: 1000)

    async def fake_stream(*args, **kwargs):
        yield _sse({"reasoning_content": "r"}, {"content": "m"}, {"tool_calls": [{"index": 0, "function": {"name": "f", "arguments": "{}"}}]})

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        await svc.generate(user, sid, BASE, "k", {"messages": []})
        detail = await store.get_session_detail(user, sid)
        return [m.ts for m in detail[1] if m.role == "assistant"]

    ts = asyncio.run(main())
    assert len(ts) == 3
    assert all(t >= 1000 for t in ts)
    assert ts == sorted(ts) and len(set(ts)) == len(ts), f"ts strikt steigend: {ts}"


def test_abort_requested_before_generate_discards_everything(svc, store, user, monkeypatch):
    """Abort-Request, der vor dem Start eintrifft (Race nach POST /api/chat), wird von der
    Generierung uebernommen: nichts wird persistiert, kein Fehler-System-Message."""

    async def fake_stream(*args, **kwargs):
        yield _sse({"content": "x"})

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        assert svc.request_abort(user, sid) is False  # nichts laeuft -> Request vorgemerkt
        await svc.generate(user, sid, BASE, "k", {"messages": []})
        detail = await store.get_session_detail(user, sid)
        return sid, detail

    sid, detail = asyncio.run(main())
    assert detail[1] == [], "bei sofortigem Abort landet nichts in der DB"
    assert svc.is_running(user, sid) is False
    assert svc._abort_requested == set(), "Abort-Request wurde konsumiert"


def test_error_event_mid_stream_keeps_closed_blocks_discards_open(svc, store, user, monkeypatch):
    """Error-Event mitten im Stream: abgeschlossene Bloecke bleiben persistiert, der offene
    Block wird verworfen, der Fehler landet als System-Message, generating=0."""

    async def fake_stream(*args, **kwargs):
        yield _sse({"reasoning_content": "denke"})  # Block 1
        yield _sse({"content": "Teil "})  # schliesst Block 1, oeffnet Block 2 (message)
        yield 'data: {"error": "kaputt"}\n\n' + "data: [DONE]\n\n"

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        await svc.generate(user, sid, BASE, "k", {"messages": []})
        detail = await store.get_session_detail(user, sid)
        session = await store.get_session(user, sid)
        return detail, session

    detail, session = asyncio.run(main())
    assert [(t, x) for r, t, x, _c in _rows(detail) if r == "assistant"] == [("reasoning", "denke")]
    system = [m for m in detail[1] if m.role == "system"]
    assert len(system) == 1 and "kaputt" in system[0].text and system[0].in_context is False
    assert session is not None and session.generating is False


def test_generate_passes_stream_contract_through(svc, store, user, monkeypatch):
    """stream_completion bekommt (base_url, api_key, payload) plus settings= und abort=;
    das abort-Event ist genau das Event, das request_abort setzt (state.generation)."""

    async def main():
        sid = (await store.create_session(user, "S")).id
        seen: dict = {}

        async def fake_stream(base_url, api_key, payload, settings=None, client_factory=None, abort=None):
            state = svc._sessions[svc._key(user, sid)]
            seen["call"] = (base_url, api_key, payload, settings)
            seen["abort_is_generation"] = abort is not None and abort is state.generation
            yield _sse({"content": "x"})

        monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
        await svc.generate(user, sid, BASE, "key-9", {"model": "m1"}, settings={"show_system_prompt": False})
        return seen

    seen = asyncio.run(main())
    assert seen["call"] == (BASE, "key-9", {"model": "m1"}, {"show_system_prompt": False})
    assert seen["abort_is_generation"] is True


def test_sse_stream_yields_state_events_with_rising_seq_then_done(svc, store, user, monkeypatch):
    """SSE-Protokoll des Service: initialer state-Snapshot, dann pro Chunk ein state-Event
    mit steigendem seq, am Ende genau ein done-Event (danach endet der Stream)."""
    release = asyncio.Event()

    async def fake_stream(*args, **kwargs):
        yield _sse({"content": "A"})
        await release.wait()
        yield _sse({"content": "B"})

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        task = asyncio.create_task(svc.generate(user, sid, BASE, "k", {"messages": []}))
        while not svc.is_running(user, sid):
            await asyncio.sleep(0.01)
        events: list[dict] = []

        async def collect():
            async for ev in svc.stream(user, sid):
                events.append(ev)

        col = asyncio.create_task(collect())
        while not svc._sessions[svc._key(user, sid)].subscribers:
            await asyncio.sleep(0.01)
        release.set()
        await asyncio.wait_for(task, timeout=5)
        await asyncio.wait_for(col, timeout=5)
        return events

    events = asyncio.run(main())
    assert events[-1] == {"type": "done"}
    states = events[:-1]
    assert states and all(e["type"] == "state" for e in states)
    seqs = [e["seq"] for e in states]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), f"seq strikt steigend: {seqs}"
    last = states[-1]["messages"]
    assert last and last[-1]["role"] == "assistant" and last[-1]["text"] == "AB" and last[-1]["id"] is not None


def test_persist_batches_and_rows_mapping(svc, store, user, monkeypatch):
    """Persistenz-Batching: beim Typwechsel werden die abgeschlossenen Bloecke in EINEM
    add_messages-Batch geschrieben (ein DB-Oeffnen), der offene Block erst im finalen
    Flush. Jede Zeile ist ein MessageInput (role/type/text/in_context/created_at=ts)."""
    batches: list[list[dict]] = []
    finals: list[tuple[list[dict], str | None]] = []
    orig_add_messages = store.add_messages
    orig_finalize = store.finalize_generation

    async def spy_add(u, s, messages):
        batches.append([dict(m) for m in messages])
        return await orig_add_messages(u, s, messages)

    async def spy_fin(u, s, messages, error):
        finals.append(([dict(m) for m in messages], error))
        return await orig_finalize(u, s, messages, error)

    monkeypatch.setattr(store, "add_messages", spy_add)
    monkeypatch.setattr(store, "finalize_generation", spy_fin)

    async def fake_stream(*args, **kwargs):
        yield _sse({"reasoning_content": "r1"}, {"content": "m1"}, {"tool_calls": [{"index": 0, "function": {"name": "f", "arguments": "{}"}}]})

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        await svc.generate(user, sid, BASE, "k", {"messages": []})

    asyncio.run(main())
    # ein Batch beim Typwechsel (reasoning + message geschlossen); der offene Toolcall-Block
    # erst im finalen Flush (dessen add_messages-Lauf taucht als zweiter Batch auf)
    assert [[(m["type"], m["text"]) for m in b] for b in batches] == [
        [("reasoning", "r1"), ("message", "m1")],
        [("toolcall", "f({})")],
    ]
    assert len(finals) == 1 and finals[0][1] is None, "genau ein finaler Flush, ohne Fehler"
    final_rows = finals[0][0]
    assert [(m["type"], m["text"]) for m in final_rows] == [("toolcall", "f({})")]
    all_rows = batches[0] + final_rows
    for m in all_rows:
        assert set(m) == {"role", "type", "text", "in_context", "created_at"}
        assert m["created_at"] > 0
    assert [m["created_at"] for m in all_rows] == sorted(m["created_at"] for m in all_rows)
    by_type = {m["type"]: m for m in all_rows}
    assert by_type["reasoning"]["in_context"] is False
    assert by_type["message"]["in_context"] is True
