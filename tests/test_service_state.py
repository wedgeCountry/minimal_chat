"""Invarianten-Tests fuer den MessageService (app/services/chat.py) — die architektonischen
Regeln als executable Spec:

1. Schreib-Funnel: Mutationen landen ZUERST im In-Memory-State des Service (id=None),
   werden DANN persistiert (write-through: Antwort erst nach erfolgreichem Store-Schreiben)
   und DANN als versioniertes SSE-state-Event publiziert (seq steigt monoton).
2. Bei Persist-Fehler Rollback des Memory (nie divergenter Zustand).
3. Per-Session-Lock serialisiert konkurrierende Mutationen.
4. Hot-State wird nach TTL evictiert und aus der DB (truth at rest) neu geladen — nie
   waehrend eine Generierung laeuft.
5. Generierung: Live-Messages (id=None) erscheinen in state-Events, bekommen nach dem
   Persistieren echte ids; bei Abort werden verworfene Live-Messages aus dem Memory entfernt.

Laufen gegen InMemoryUserStore (kein SQLite noetig). Pro Test genau ein asyncio.run
(asyncio.Lock bindet an den Loop).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.auth import user_identity
from app.models import MessageIn, MessagePatch
from app.services.chat import MessageService
from app.services.memory_store import InMemoryUserStore

SECRET = "svc-secret"
EMAIL = "svc@example.com"


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


def test_write_through_memory_first_then_persist(svc, store, user, monkeypatch):
    """Mutation ist waehrend des Store-Schreibens schon im Memory (id=None), die Antwort
    kommt erst danach und das Memory uebernimmt die persistierte id."""
    observed = {}
    orig = store.add_message

    async def spy(u, s, msg):
        state = svc._sessions[svc._key(u, s)]
        observed["in_memory_during_persist"] = any(m.id is None and m.text == msg["text"] for m in state.messages)
        out = await orig(u, s, msg)
        observed["persisted_id"] = out.id
        return out

    monkeypatch.setattr(store, "add_message", spy)

    async def main():
        sid = (await store.create_session(user, "S")).id
        res = await svc.add_message(user, sid, MessageIn(role="user", text="Hallo"))
        state = svc._sessions[svc._key(user, sid)]
        detail = await store.get_session_detail(user, sid)
        return sid, res, state, detail

    sid, res, state, detail = asyncio.run(main())
    assert observed["in_memory_during_persist"] is True, "Memory zuerst (id=None waehrend Persist)"
    assert observed["persisted_id"] is not None
    assert res.id == observed["persisted_id"], "Antwort erst nach erfolgreichem Persistieren"
    assert state.messages[-1].id == res.id, "Memory uebernimmt die persistierte id"
    assert detail is not None and detail[1][-1].text == "Hallo", "Store enthaelt die Message ebenfalls"


def test_seq_monotonic_and_state_events_published(svc, store, user):
    async def main():
        sid = (await store.create_session(user, "S")).id
        state = await svc._hot(user, sid)
        q: asyncio.Queue = asyncio.Queue()
        state.subscribers.add(q)
        await svc.add_message(user, sid, MessageIn(role="user", text="eins"))
        await svc.add_message(user, sid, MessageIn(role="user", text="zwei"))
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        return sid, state, events

    sid, state, events = asyncio.run(main())
    assert state.seq == 2, "seq zaehlt jede Mutation"
    assert [e["type"] for e in events] == ["state", "state"]
    seqs = [e["seq"] for e in events]
    assert seqs == [1, 2], f"seq monoton steigend: {seqs}"
    assert events[-1]["messages"][-1]["text"] == "zwei"
    assert all(m["id"] is not None for m in events[-1]["messages"]), "persistierte Messages haben ids"


def test_lock_serializes_concurrent_updates(svc, store, user):
    async def main():
        sid = (await store.create_session(user, "S")).id
        res = await svc.add_message(user, sid, MessageIn(role="user", text="orig"))
        mid = res.id
        await asyncio.gather(
            svc.update_message(user, sid, mid, MessagePatch(text="A")),
            svc.update_message(user, sid, mid, MessagePatch(text="B")),
        )
        return svc._sessions[svc._key(user, sid)]

    state = asyncio.run(main())
    assert state.seq == 3, f"add + 2 updates = seq 3, war {state.seq}"
    assert len(state.messages) == 1, "kein Duplikat durch Race"
    assert state.messages[0].text in ("A", "B"), "letzter Writer gewinnt, deterministisch unter Lock"


def test_rollback_on_persist_failure(svc, store, user, monkeypatch):
    async def boom(u, s, msg):
        raise RuntimeError("DB down")

    monkeypatch.setattr(store, "add_message", boom)

    async def main():
        sid = (await store.create_session(user, "S")).id
        with pytest.raises(RuntimeError):
            await svc.add_message(user, sid, MessageIn(role="user", text="weg damit"))
        return svc._sessions[svc._key(user, sid)]

    state = asyncio.run(main())
    assert state.messages == [], "Memory bleibt bei Persist-Fehler unveraendert (Rollback)"


def test_eviction_reloads_from_store_but_never_during_generation(user, store):
    svc = MessageService(store, hot_ttl_s=0.0)

    async def main():
        sid = (await store.create_session(user, "S")).id
        await svc.add_message(user, sid, MessageIn(role="user", text="persistiert"))
        key = svc._key(user, sid)
        st1 = svc._sessions[key]
        # TTL abgelaufen, keine Generierung/Subscriber -> evict + reload aus dem Store
        st2 = await svc._hot(user, sid)
        assert st2 is not st1, "Hot-State wurde evictiert und neu geladen"
        assert [m.text for m in st2.messages] == [m.text for m in st1.messages], "Reload liefert DB-Stand"
        # laufende Generierung schuetzt vor Eviction
        st2.generation = asyncio.Event()
        st3 = await svc._hot(user, sid)
        assert svc._sessions[key] is st2 and st3 is st2, "keine Eviction waehrend Generierung"

    asyncio.run(main())


def test_generation_live_messages_get_persisted_ids(svc, store, user, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield _sse({"content": "Teil A "})
        yield _sse({"content": "Teil B"})

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        await svc.add_message(user, sid, MessageIn(role="user", text="Frage"))
        state = svc._sessions[svc._key(user, sid)]
        q: asyncio.Queue = asyncio.Queue()
        state.subscribers.add(q)
        await svc.generate(user, sid, "http://llm.test/v1", "k", {"messages": []})
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        detail = await store.get_session_detail(user, sid)
        return sid, state, events, detail

    sid, state, events, detail = asyncio.run(main())
    live_seen = any(
        any(m["id"] is None and m["role"] == "assistant" and "Teil A" in m["text"] for m in e["messages"])
        for e in events
        if e["type"] == "state"
    )
    assert live_seen, "Live-Message (id=null) muss in state-Events sichtbar sein, bevor sie persistiert ist"
    assistant = [m for m in state.messages if m.role == "assistant"]
    assert len(assistant) == 1 and assistant[0].id is not None and assistant[0].text == "Teil A Teil B"
    assert any(m.role == "assistant" and m.text == "Teil A Teil B" for m in detail[1]), "finaler Stand ist persistiert"


def test_abort_discards_live_messages_from_memory(svc, store, user, monkeypatch):
    release = asyncio.Event()

    async def fake_stream(*args, **kwargs):
        yield _sse({"reasoning_content": "denke "})  # Block 1 (schliesst sich beim naechsten Chunk)
        yield _sse({"content": "Teil 1 "})  # oeffnet message-Block
        await release.wait()
        yield _sse({"content": "VERWORFEN"})
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)

    async def main():
        sid = (await store.create_session(user, "S")).id
        task = asyncio.create_task(svc.generate(user, sid, "http://llm.test/v1", "k", {"messages": []}))
        await asyncio.sleep(0.1)
        assert svc.request_abort(user, sid) is True
        release.set()
        await asyncio.wait_for(task, timeout=5)
        state = svc._sessions[svc._key(user, sid)]
        detail = await store.get_session_detail(user, sid)
        return state, detail

    state, detail = asyncio.run(main())
    assert all(m.id is not None for m in state.messages), "keine Live-Messages (id=None) nach Abort im Memory"
    assert [m.text for m in state.messages if m.role == "assistant"] == ["denke "], "nur abgeschlossener Block bleibt"
    assert [m.text for m in detail[1] if m.role == "assistant"] == ["denke "], "... und in der DB"


def test_subscriber_queue_bounded_drop_oldest_keeps_done_sentinel(svc, store, user):
    """Subscriber-Queues sind begrenzt (maxsize): bei Ueberlauf wird das aelteste
    state-Event verworfen (Voll-Snapshot, das neueste genuegt), der None-Sentinel
    ('done') wird nie verworfen."""

    async def main():
        sid = (await store.create_session(user, "S")).id
        state = await svc._hot(user, sid)
        q: asyncio.Queue = asyncio.Queue(maxsize=3)
        state.subscribers.add(q)
        for _ in range(5):
            state.seq += 1
            svc._publish(state)
        assert q.qsize() == 3, "Queue bleibt begrenzt (Drop-Oldest)"
        svc._put(q, None)  # volle Queue + Sentinel -> aeltestes state-Event wird verworfen
        drained = []
        while not q.empty():
            drained.append(q.get_nowait())
        assert [e["seq"] for e in drained if e is not None] == [4, 5], "die neuesten state-Events bleiben erhalten"
        assert drained[-1] is None, "done-Sentinel ueberlebt die volle Queue"

    asyncio.run(main())
