"""Service-Layer fuer Message-Content: einzige Quelle, aus der das Frontend seine
Chunks und Messages bekommt, und einziger Schreib-Funnel (Single Write Funnel).

``MessageService`` haelt pro "heisser" Session den vollstaendigen In-Memory-Zustand
(``_SessionState``: Message-Liste + seq + Lock + SSE-Subscriber + laufende Generierung).
Regel: jede Mutation wird zuerst auf den In-Memory-Messages ausgefuehrt (unter dem
per-session Lock), dann via ``UserStoreProtocol`` persistiert (Write-Through: die
HTTP-Antwort kommt erst nach erfolgreichem Persistieren) und dann als versioniertes
SSE-Event (``state`` mit seq) publiziert. Umgekehrt ist die Datenbank "at rest" die
Quelle der Wahrheit: beim ersten Touch wird der Zustand aus dem Store geladen
(``_hot``), nach dem TTL ohne Aktivitaet wird er evicted.

Das Frontend streamt die Live-Daten per SSE (``GET /api/chat/stream/{sid}``, Events
``state``/``done``/``idle``); die persistierten Messages kommen weiterhin ueber
``GET /api/sessions/{sid}`` (Poll bleibt Quelle der Wahrheit fuer den persistierten Stand).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from ..db.database import now_ms
from ..domain import Message, MessageType
from ..models import MessageIn, MessagePatch
from ..types import MessageInput, UserIdentity
from .llm import stream_completion
from .sse import SseParser
from .store import MessageNotFound, SessionNotFound, UserStoreProtocol

DEFAULT_HOT_TTL_S = 300.0

# Puffer pro SSE-Subscriber (Voll-Snapshot-Events); bei Ueberlauf Drop-Oldest, siehe _put
_SUBSCRIBER_QUEUE_MAX = 8


def _render_toolcall(a: dict[str, Any]) -> str:
    # Argumente sind JSON-String-Literale: literale "\n" als echte Umbrueche speichern
    return f"{a['name'] or 'tool'}({a['args']})".replace("\\n", "\n")


def _render_toolresult(a: dict[str, Any]) -> str:
    text = f"{a['name']}: {a['result']}" if a["name"] else a["result"]
    return text.replace("\\n", "\n")


def _to_message_input(m: Message) -> MessageInput:
    return {"role": m.role, "type": m.type, "text": m.text, "in_context": m.in_context, "created_at": m.ts}


class _StreamAccumulator:
    """Sammelt den LLM-Stream blockweise in Live-Messages (id=None; ts=0 = offener Block).

    Ein Typwechsel im Chunk-Stream schliesst den bisher offenen Block (ts wird zum
    Abschluss-Zeitstempel des Blocks).
    """

    def __init__(self, msgs: list[Message]) -> None:
        self._msgs = msgs
        self.block_msgs: list[Message] = []  # Live-Messages in Stream-Reihenfolge (Refs in msgs)
        self.tool_acc: dict[tuple[str, int], dict[str, Any]] = {}
        self._last_kind: tuple[str, int | None] | None = None
        self._last_ts = 0

    def next_ts(self) -> int:
        self._last_ts = max(now_ms(), self._last_ts + 1)
        return self._last_ts

    def touch(self, kind: MessageType, idx: int | None = None) -> None:
        # Typwechsel im Chunk-Stream: der bisher aktive Block ist abgeschlossen
        if self._last_kind is not None and self._last_kind != (kind, idx):
            for m in self.block_msgs:
                if m.ts == 0:
                    m.ts = self.next_ts()
        self._last_kind = (kind, idx)

    def live(self, kind: MessageType) -> Message:
        m = Message(id=None, role="assistant", type=kind, text="", in_context=kind != "reasoning")
        self._msgs.append(m)
        self.block_msgs.append(m)
        return m

    def text_block(self, kind: MessageType) -> Message:
        if self.block_msgs and self.block_msgs[-1].type == kind and self.block_msgs[-1].ts == 0:
            return self.block_msgs[-1]
        return self.live(kind)

    def tool_block(self, kind: MessageType, idx: int) -> dict[str, Any]:
        a = self.tool_acc.get((kind, idx))
        # idx startet pro Assistant-Runde wieder bei 0: erst ein geschlossener Block
        # (ts != 0) darf eine neue Runde auf demselben (kind, idx) eroeffnen
        if a is None or a["msg"].ts != 0:
            m = self.live(kind)
            a = {"kind": kind, "name": "", "args": "", "result": "", "msg": m}
            self.tool_acc[(kind, idx)] = a
        return a

    def sync_tool(self, a: dict[str, Any]) -> None:
        a["msg"].text = _render_toolcall(a) if a["kind"] == "toolcall" else _render_toolresult(a)

    def feed_event(self, j: dict[str, Any]) -> str | None:
        """Ein geparstes SSE-Event des LLM-Streams in die Bloecke einspeisen. Liefert die
        Fehlermeldung, wenn das Event ein ``error`` traegt, sonst None."""
        if j.get("error"):
            return str(j["error"])
        choices = j.get("choices") or [{}]
        delta = choices[0].get("delta") or {}
        reasoning = delta.get("reasoning_content")
        if reasoning is None:
            reasoning = delta.get("reasoning")
        if reasoning:
            self.touch("reasoning")
            self.text_block("reasoning").text += reasoning
        if delta.get("content"):
            self.touch("message")
            self.text_block("message").text += delta["content"]
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index")
            if idx is None:
                idx = sum(1 for m in self.block_msgs if m.type == "toolcall")
            self.touch("toolcall", idx)
            a = self.tool_block("toolcall", idx)
            fn = tc.get("function") or {}
            a["name"] += fn.get("name") or ""
            a["args"] += fn.get("arguments") or ""
            self.sync_tool(a)
        for tr in delta.get("tool_results") or []:
            idx = tr.get("index")
            if idx is None:
                idx = sum(1 for m in self.block_msgs if m.type == "toolresult")
            self.touch("toolresult", idx)
            if tr.get("signal"):
                # Signal-Chunk des LLM-Servers (z. B. "toolcall_done"): schliesst den
                # offenen Block, traegt aber keinen Toolresult-Inhalt
                continue
            a = self.tool_block("toolresult", idx)
            fn = tr.get("function") or {}
            a["name"] += tr.get("name") or fn.get("name") or ""
            a["result"] += (
                tr.get("result") or tr.get("content") or tr.get("output") or tr.get("text")
                or fn.get("result") or fn.get("arguments") or ""
            )
            self.sync_tool(a)
        return None

    def closed_unpersisted(self) -> list[Message]:
        """Abgeschlossene, noch nicht persistierte Bloecke (ein DB-Oeffnen pro Batch)."""
        return [m for m in self.block_msgs if m.ts != 0 and m.id is None and m.text]

    def close_open_blocks(self) -> None:
        for m in self.block_msgs:
            if m.ts == 0:
                m.ts = self.next_ts()

    def unpersisted(self) -> list[Message]:
        return [m for m in self.block_msgs if m.id is None and m.text]


class _SessionState:
    """In-Memory-Zustand einer heissen Session (Quelle der Wahrheit, solange hot)."""

    def __init__(self, messages: list[Message]) -> None:
        self.messages = messages
        self.seq = 0
        self.lock = asyncio.Lock()
        self.subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self.generation: asyncio.Event | None = None  # Abort-Event der laufenden Generierung
        self.last_touch = time.monotonic()


class _GenerationRun:
    """Ein laufender Generierungs-Durchlauf: LLM-Stream -> _StreamAccumulator -> persistierte
    Bloecke + SSE-Publish. Nur abgeschlossene Bloecke werden persistiert (ein DB-Oeffnen pro
    Block-Abschluss plus eins am Ende); der offene Block wird bei Abort/Fehler verworfen
    (aus dem Memory entfernt, nie persistiert)."""

    def __init__(
        self,
        store: UserStoreProtocol,
        user: UserIdentity,
        sid: str,
        state: _SessionState,
        abort: asyncio.Event,
        base_url: str,
        api_key: str,
        payload: dict[str, Any],
        settings: dict[str, bool] | None,
        publish: Callable[[_SessionState], None],
    ) -> None:
        self._store = store
        self._user = user
        self._sid = sid
        self._state = state
        self._abort = abort
        self._base_url = base_url
        self._api_key = api_key
        self._payload = payload
        self._settings = settings
        self._publish = publish
        self.acc = _StreamAccumulator(state.messages)
        self.error: str | None = None

    async def run(self) -> None:
        parser = SseParser()
        try:
            # Existenz ist ueber _hot beim Start geprueft; das generating-Flag setzt
            # der Aufrufer atomar (try_start_generating)
            async for chunk in stream_completion(self._base_url, self._api_key, self._payload, settings=self._settings, abort=self._abort):
                if self._abort.is_set():
                    break
                for j in parser.feed(chunk):
                    err = self.acc.feed_event(j)
                    if err is not None:
                        self.error = err
                        break
                self._state.seq += 1
                self._publish(self._state)
                await self._persist_closed()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Fehler wird als System-Message persistiert
            self.error = self.error or str(exc)
        finally:
            await self._final_flush()

    async def _persist_closed(self) -> None:
        """Persistiert abgeschlossene Bloecke sofort (beim Typwechsel im Stream).
        Der offene Block wird nie geschrieben. Pro Batch genau ein DB-Oeffnen."""
        closed = self.acc.closed_unpersisted()
        if not closed:
            return
        stored = await self._store.add_messages(self._user, self._sid, [_to_message_input(m) for m in closed])
        for m, s in zip(closed, stored):
            m.id = s.id
            m.ts = s.ts

    async def _final_flush(self) -> None:
        """Ein einziges DB-Oeffnen am Stream-Ende: bei normalem Ende wird der letzte
        offene Block abgeschlossen und persistiert; bei Abort/Fehler werden die
        verworfenen Live-Messages aus dem Memory entfernt. Ausserdem Fehler-System-
        Message (falls error) und generating=0."""
        state = self._state
        msgs = state.messages
        discard_open = self._abort.is_set() or self.error is not None
        targets: list[Message] = []
        rows: list[MessageInput] = []
        if not discard_open:
            self.acc.close_open_blocks()
            targets = self.acc.unpersisted()
            rows = [_to_message_input(m) for m in targets]
        stored = await self._store.finalize_generation(self._user, self._sid, rows, self.error)
        if discard_open:
            state.messages[:] = [m for m in msgs if m.id is not None]
        for m, s in zip(targets, stored[: len(targets)]):
            m.id = s.id
            m.ts = s.ts
        for s in stored[len(targets):]:  # Fehler-System-Message uebernehmen
            state.messages.append(s)
        state.seq += 1
        self._publish(state)


class MessageService:
    """In-Memory-Message-Store + Schreib-Funnel + Persistenz-Orchestrierung."""

    def __init__(self, store: UserStoreProtocol, hot_ttl_s: float = DEFAULT_HOT_TTL_S) -> None:
        self._store = store
        self._hot_ttl_s = hot_ttl_s
        self._sessions: dict[str, _SessionState] = {}
        self._abort_requested: set[str] = set()
        # Starke Referenzen auf laufende Hintergrund-Tasks, damit der GC sie nicht killt
        self._tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _key(user: UserIdentity, sid: str) -> str:
        return f"{user['uid']}:{sid}"

    # --- Hot-State-Lifecycle ---

    def _evict_idle(self) -> None:
        """Heisse Sessions ohne laufende Generierung, ohne Subscriber und abgelaufenem TTL evictieren."""
        now = time.monotonic()
        stale = [
            key
            for key, st in self._sessions.items()
            if st.generation is None and not st.subscribers and now - st.last_touch > self._hot_ttl_s
        ]
        for key in stale:
            del self._sessions[key]

    async def _hot(self, user: UserIdentity, sid: str) -> _SessionState:
        """Heissen Zustand liefern; beim ersten Touch aus dem Store (DB = truth at rest) laden."""
        self._evict_idle()
        key = self._key(user, sid)
        state = self._sessions.get(key)
        if state is None:
            detail = await self._store.get_session_detail(user, sid)
            if detail is None:
                raise SessionNotFound(sid)
            _session, messages = detail
            state = _SessionState(messages)
            self._sessions[key] = state
        state.last_touch = time.monotonic()
        return state

    def _state_event(self, state: _SessionState) -> dict[str, Any]:
        return {"type": "state", "seq": state.seq, "messages": [m.model_dump() for m in state.messages]}

    @staticmethod
    def _put(q: asyncio.Queue[dict[str, Any] | None], item: dict[str, Any] | None) -> None:
        """In die begrenzte Subscriber-Queue legen; bei Ueberlauf das aelteste state-Event
        verwerfen (Voll-Snapshot: das neueste genuegt, der Client merged per seq).
        Der None-Sentinel ('done') wird nie verworfen."""
        try:
            q.put_nowait(item)
            return
        except asyncio.QueueFull:
            rest: list[dict[str, Any] | None] = []
            dropped = False
            while not q.empty():
                old = q.get_nowait()
                if old is not None and not dropped:
                    dropped = True
                else:
                    rest.append(old)
            for old in rest:
                q.put_nowait(old)
            q.put_nowait(item)

    def _publish(self, state: _SessionState) -> None:
        """Aktuellen In-Memory-Zustand als versioniertes state-Event an alle SSE-Subscriber."""
        state.last_touch = time.monotonic()
        ev = self._state_event(state)
        for q in state.subscribers:
            self._put(q, ev)

    # --- Status / Abort ---

    def is_running(self, user: UserIdentity, sid: str) -> bool:
        state = self._sessions.get(self._key(user, sid))
        return state is not None and state.generation is not None

    def request_abort(self, user: UserIdentity, sid: str) -> bool:
        state = self._sessions.get(self._key(user, sid))
        if state is not None and state.generation is not None:
            state.generation.set()
            return True
        # Generierung hat ihr Event evtl. noch nicht registriert (Race direkt nach POST /api/chat)
        self._abort_requested.add(self._key(user, sid))
        return False

    def forget_abort_if_idle(self, user: UserIdentity, sid: str) -> None:
        """Abort-Request verwerfen, wenn keine Generierung laeuft (verwaistes
        generating-Flag nach Server-Neustart): eine spaeter gestartete Generierung
        derselben Session darf nicht durch den alten Request sofort abbrechen."""
        if not self.is_running(user, sid):
            self._abort_requested.discard(self._key(user, sid))

    # --- Schreib-Funnel: Mutationen (Memory zuerst, dann persistieren, dann publishen) ---

    async def add_message(self, user: UserIdentity, sid: str, msg: MessageIn) -> Message:
        state = await self._hot(user, sid)
        async with state.lock:
            live = Message(
                id=None, role=msg.role, type=msg.type, text=msg.text,
                in_context=msg.in_context, attachments=msg.attachments, ts=0,
            )
            state.messages.append(live)
            try:
                stored = await self._store.add_message(user, sid, msg.model_dump())
            except Exception:
                state.messages.remove(live)
                raise
            live.id = stored.id
            live.ts = stored.ts
            state.seq += 1
            self._publish(state)
            return stored

    async def update_message(self, user: UserIdentity, sid: str, mid: int, patch: MessagePatch) -> Message:
        state = await self._hot(user, sid)
        async with state.lock:
            idx = next((i for i, m in enumerate(state.messages) if m.id == mid), None)
            if idx is None:
                raise MessageNotFound(mid)
            m = state.messages[idx]
            backup = m.model_copy()
            if patch.in_context is not None:
                m.in_context = patch.in_context
            if patch.text is not None:
                m.text = patch.text
            if patch.attachments is not None:
                m.attachments = patch.attachments
            try:
                stored = await self._store.update_message(user, sid, mid, patch.model_dump(exclude_none=True))
            except Exception:
                state.messages[idx] = backup
                raise
            state.messages[idx] = stored
            state.seq += 1
            self._publish(state)
            return stored

    async def delete_message(self, user: UserIdentity, sid: str, mid: int) -> None:
        state = await self._hot(user, sid)
        async with state.lock:
            idx = next((i for i, m in enumerate(state.messages) if m.id == mid), None)
            if idx is None:
                raise MessageNotFound(mid)
            removed = state.messages.pop(idx)
            try:
                await self._store.delete_message(user, sid, mid)
            except Exception:
                state.messages.insert(idx, removed)
                raise
            state.seq += 1
            self._publish(state)

    async def delete_messages_after(self, user: UserIdentity, sid: str, mid: int) -> None:
        state = await self._hot(user, sid)
        async with state.lock:
            idx = next((i for i, m in enumerate(state.messages) if m.id == mid), None)
            if idx is None:
                raise MessageNotFound(mid)
            removed = state.messages[idx + 1 :]
            del state.messages[idx + 1 :]
            try:
                await self._store.delete_messages_after(user, sid, mid)
            except Exception:
                state.messages.extend(removed)
                raise
            state.seq += 1
            self._publish(state)

    # --- Start / Lauf der Generierung ---

    async def start_generation(
        self,
        user: UserIdentity,
        sid: str,
        base_url: str,
        api_key: str,
        payload: dict[str, Any],
        settings: dict[str, bool] | None = None,
    ) -> str:
        """Heissen Zustand anlegen und die Generierung als Hintergrund-Task starten.

        Rueckgabe: "ok" (Task gestartet) | "busy" (bereits laufende Generierung) |
        "missing" (Session unbekannt). Das generating-Flag wird atomar unter dem
        Session-Lock gesetzt (TOCTOU-frei bei parallelen POSTs). Ein verwaistes Flag
        (z. B. Server-Neustart mitten in der Generierung) wird geheilt: unter dem Lock
        laeuft bei generation=None sicher keine Task, dann ist ein gesetztes DB-Flag stale.
        """
        state = await self._hot(user, sid)  # SessionNotFound -> Router mappt auf 404
        key = self._key(user, sid)
        async with state.lock:
            if state.generation is not None:
                return "busy"
            status = await self._store.try_start_generating(user, sid)
            if status == "busy":
                await self._store.set_generating(user, sid, False)
                status = await self._store.try_start_generating(user, sid)
            if status != "ok":
                return status
            abort = asyncio.Event()
            state.generation = abort
            if key in self._abort_requested:
                self._abort_requested.discard(key)
                abort.set()
            task = asyncio.create_task(self._run_task(user, sid, key, state, abort, base_url, api_key, payload, settings))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return "ok"

    async def generate(
        self,
        user: UserIdentity,
        sid: str,
        base_url: str,
        api_key: str,
        payload: dict[str, Any],
        settings: dict[str, bool] | None = None,
    ) -> None:
        """Direkter Lauf ohne Task-Registrierung (Tests). Unbekannte Session = No-Op."""
        try:
            state = await self._hot(user, sid)
        except SessionNotFound:
            return
        key = self._key(user, sid)
        abort = asyncio.Event()
        state.generation = abort
        if key in self._abort_requested:
            self._abort_requested.discard(key)
            abort.set()
        try:
            await self._generate(user, sid, state, abort, base_url, api_key, payload, settings)
        finally:
            state.generation = None
            self._finish(key, state)

    async def _run_task(
        self,
        user: UserIdentity,
        sid: str,
        key: str,
        state: _SessionState,
        abort: asyncio.Event,
        base_url: str,
        api_key: str,
        payload: dict[str, Any],
        settings: dict[str, bool] | None,
    ) -> None:
        try:
            await self._generate(user, sid, state, abort, base_url, api_key, payload, settings)
        finally:
            state.generation = None
            self._finish(key, state)

    def _finish(self, key: str, state: _SessionState) -> None:
        self._abort_requested.discard(key)
        # None-Sentinel -> stream() schickt 'done' und beendet den SSE-Stream
        for q in state.subscribers:
            self._put(q, None)

    # --- SSE-Stream an das Frontend ---

    async def stream(self, user: UserIdentity, sid: str) -> AsyncIterator[dict[str, Any]]:
        """SSE-Event-Stream einer Session aus dem In-Memory-State.

        ``state`` (seq + vollstaendige Message-Liste inkl. Live-Messages mit id=null),
        ``done`` (Generierung beendet), ``idle`` (Session nicht hot / keine laufende
        Generierung - Client faellt auf GET /api/sessions/{sid} zurueck).
        """
        state = self._sessions.get(self._key(user, sid))
        if state is None or state.generation is None:
            yield {"type": "idle"}
            return
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAX)
        state.subscribers.add(q)
        state.last_touch = time.monotonic()
        try:
            yield self._state_event(state)
            while True:
                ev = await q.get()
                if ev is None:
                    yield {"type": "done"}
                    return
                yield ev
        finally:
            state.subscribers.discard(q)

    # --- Generierungs-Loop ---

    async def _generate(
        self,
        user: UserIdentity,
        sid: str,
        state: _SessionState,
        abort: asyncio.Event,
        base_url: str,
        api_key: str,
        payload: dict[str, Any],
        settings: dict[str, bool] | None,
    ) -> None:
        """Streamt eine Chat-Completion in den In-Memory-State (Live-Messages mit id=None,
        SSE-Quelle) und persistiert abgeschlossene Bloecke write-through ueber den Store.

        Laeuft als asyncio-Task unabhaengig von der HTTP-Verbindung des Clients. Nur
        abgeschlossene Bloecke werden geschrieben (ein DB-Oeffnen pro Block-Abschluss plus
        eins am Ende); der offene Block bleibt im Speicher und wird bei Abort/Fehler
        verworfen (aus dem Memory entfernt, nie persistiert).
        """
        run = _GenerationRun(self._store, user, sid, state, abort, base_url, api_key, payload, settings, publish=self._publish)
        await run.run()
