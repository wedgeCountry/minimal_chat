"""Service-Layer fuer Message-Content: die einzige Quelle, aus der das Frontend
seine Chunks und Messages bekommt.

``MessageService`` haelt den In-Memory-Zustand der laufenden Generierungen
(offene Stream-Bloecke, Abort-Event, Subscriber) und orchestriert die Persistenz
ueber ``UserStore``: abgeschlossene Bloecke werden blockweise in die per-user DB
geschrieben, der finale Flush setzt ``generating=0``. Das Frontend streamt die
Live-Chunks per SSE (``GET /api/chat/stream/{sid}``, Events siehe ``stream()``);
die persistierten Messages kommen weiterhin ueber ``GET /api/sessions/{sid}``
(Poll bleibt Quelle der Wahrheit und ueberschreibt den lokalen Stand).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..db.database import now_ms
from ..types import MessageInput, StreamBlock, UserIdentity
from .llm import stream_completion
from .sse import SseParser
from .store import UserStoreProtocol


def _block_text(b: StreamBlock) -> str:
    if b["kind"] == "toolcall":
        # Argumente sind JSON-String-Literale: literale "\n" als echte Umbrueche speichern
        return f"{b.get('name') or 'tool'}({b.get('args') or ''})".replace("\\n", "\n")
    if b["kind"] == "toolresult":
        name = b.get("name") or ""
        result = b.get("result") or ""
        text = f"{name}: {result}" if name else result
        return text.replace("\\n", "\n")
    return b.get("text") or ""


class _ActiveGeneration:
    """In-Memory-Zustand einer laufenden Generierung (pro user:session)."""

    def __init__(self) -> None:
        self.blocks: list[StreamBlock] = []
        self.tool_blocks: dict[tuple[str, int], StreamBlock] = {}
        self.abort = asyncio.Event()
        self.subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()


class MessageService:
    """In-Memory-Message-Store + Persistenz-Orchestrierung fuer laufende Generierungen."""

    def __init__(self, store: UserStoreProtocol) -> None:
        self._store = store
        self._active: dict[str, _ActiveGeneration] = {}
        self._abort_requested: set[str] = set()
        # Starke Referenzen auf laufende Hintergrund-Tasks, damit der GC sie nicht killt
        self._tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _key(user: UserIdentity, sid: str) -> str:
        return f"{user['uid']}:{sid}"

    # --- Status / Abort ---

    def is_running(self, user: UserIdentity, sid: str) -> bool:
        return self._key(user, sid) in self._active

    def request_abort(self, user: UserIdentity, sid: str) -> bool:
        key = self._key(user, sid)
        active = self._active.get(key)
        if active is not None:
            active.abort.set()
            return True
        # Task hat ihr Event evtl. noch nicht registriert (Race direkt nach POST /api/chat)
        self._abort_requested.add(key)
        return False

    def forget_abort_if_idle(self, user: UserIdentity, sid: str) -> None:
        """Abort-Request verwerfen, wenn keine Generierung laeuft (verwaistes
        generating-Flag nach Server-Neustart): eine spaeter gestartete Generierung
        derselben Session darf nicht durch den alten Request sofort abbrechen."""
        key = self._key(user, sid)
        if key not in self._active:
            self._abort_requested.discard(key)

    # --- Start / Lauf ---

    def start_generation(
        self,
        user: UserIdentity,
        sid: str,
        base_url: str,
        api_key: str,
        payload: dict[str, Any],
        settings: dict[str, bool] | None = None,
    ) -> None:
        """Registriert die Generierung (In-Memory) und startet die Hintergrund-Task."""
        key = self._key(user, sid)
        active = _ActiveGeneration()
        self._active[key] = active
        if key in self._abort_requested:
            self._abort_requested.discard(key)
            active.abort.set()
        task = asyncio.create_task(self._run_task(user, sid, key, active, base_url, api_key, payload, settings))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def generate(
        self,
        user: UserIdentity,
        sid: str,
        base_url: str,
        api_key: str,
        payload: dict[str, Any],
        settings: dict[str, bool] | None = None,
    ) -> None:
        """Direkter Lauf ohne Task-Registrierung (Tests)."""
        key = self._key(user, sid)
        active = self._active.setdefault(key, _ActiveGeneration())
        if key in self._abort_requested:
            self._abort_requested.discard(key)
            active.abort.set()
        try:
            await self._generate(user, sid, active, base_url, api_key, payload, settings)
        finally:
            self._finish(key, active)

    async def _run_task(
        self,
        user: UserIdentity,
        sid: str,
        key: str,
        active: _ActiveGeneration,
        base_url: str,
        api_key: str,
        payload: dict[str, Any],
        settings: dict[str, bool] | None,
    ) -> None:
        try:
            await self._generate(user, sid, active, base_url, api_key, payload, settings)
        finally:
            self._finish(key, active)

    def _finish(self, key: str, active: _ActiveGeneration) -> None:
        self._active.pop(key, None)
        self._abort_requested.discard(key)
        # None-Sentinel -> stream() schickt 'done' und beendet den SSE-Stream
        for q in active.subscribers:
            q.put_nowait(None)

    def _publish(self, active: _ActiveGeneration) -> None:
        """Aktuellen In-Memory-Blockstand an alle SSE-Subscriber schicken."""
        ev: dict[str, Any] = {"type": "blocks", "blocks": self._blocks_payload(active.blocks)}
        for q in active.subscribers:
            q.put_nowait(ev)

    @staticmethod
    def _blocks_payload(blocks: list[StreamBlock]) -> list[dict[str, Any]]:
        return [
            {"bid": i, "id": b.get("id"), "kind": b["kind"], "text": _block_text(b)}
            for i, b in enumerate(blocks)
            if _block_text(b)
        ]

    async def stream(self, user: UserIdentity, sid: str) -> AsyncIterator[dict[str, Any]]:
        """SSE-Event-Stream einer Session: snapshot + blocks bis done/idle.

        ``idle``: keine laufende Generierung (Client faellt auf GET /api/sessions/{sid} zurueck).
        """
        key = self._key(user, sid)
        active = self._active.get(key)
        if active is None:
            yield {"type": "idle"}
            return
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        active.subscribers.add(q)
        try:
            yield {"type": "snapshot", "blocks": self._blocks_payload(active.blocks)}
            while True:
                ev = await q.get()
                if ev is None:
                    yield {"type": "done"}
                    return
                yield ev
        finally:
            active.subscribers.discard(q)

    # --- Generierungs-Loop (vormals run_generation) ---

    async def _generate(
        self,
        user: UserIdentity,
        sid: str,
        active: _ActiveGeneration,
        base_url: str,
        api_key: str,
        payload: dict[str, Any],
        settings: dict[str, bool] | None,
    ) -> None:
        """Streamt eine Chat-Completion, haelt die Bloecke im Speicher (SSE-Quelle)
        und persistiert abgeschlossene Bloecke ueber den UserStore in die User-DB.

        Laeuft als asyncio-Task unabhaengig von der HTTP-Verbindung des Clients. Nur
        abgeschlossene Bloecke werden geschrieben (ein DB-Oeffnen pro Block-Abschluss plus
        eins am Ende); der offene Block bleibt im Speicher und wird bei Abort/Fehler
        verworfen.
        """
        ev = active.abort
        blocks = active.blocks
        tool_blocks = active.tool_blocks
        last_kind: tuple[str, int | None] | None = None
        last_ts = 0
        error: str | None = None
        parser = SseParser()

        def _next_ts() -> int:
            nonlocal last_ts
            last_ts = max(now_ms(), last_ts + 1)
            return last_ts

        def _touch(kind: str, idx: int | None = None) -> None:
            # Typwechsel im Chunk-Stream: der bisher aktive Block ist abgeschlossen
            nonlocal last_kind
            if last_kind is not None and last_kind != (kind, idx):
                for b in blocks:
                    if b["ts"] is None:
                        b["ts"] = _next_ts()
            last_kind = (kind, idx)

        def _text_block(kind: str) -> StreamBlock:
            if blocks and blocks[-1]["kind"] == kind and blocks[-1]["ts"] is None:
                return blocks[-1]
            b: StreamBlock = {"kind": kind, "ts": None, "id": None, "text": ""}
            blocks.append(b)
            return b

        def _tool_block(kind: str, idx: int) -> StreamBlock:
            b = tool_blocks.get((kind, idx))
            if b is None:
                b = {"kind": kind, "ts": None, "id": None, "name": "", "args": "", "result": ""}
                tool_blocks[(kind, idx)] = b
                blocks.append(b)
            return b

        def _message_row(b: StreamBlock) -> MessageInput:
            return {
                "role": "assistant",
                "type": b["kind"],
                "text": _block_text(b),
                "in_context": b["kind"] != "reasoning",
                "created_at": b["ts"] if b["ts"] is not None else _next_ts(),
            }

        async def _persist_closed_blocks() -> None:
            """Persistiert abgeschlossene Bloecke sofort (beim Typwechsel im Stream).
            Der offene Block wird nie geschrieben. Pro Batch genau ein DB-Oeffnen."""
            closed = [b for b in blocks if b["ts"] is not None and b["id"] is None and _block_text(b)]
            if not closed:
                return
            stored = await self._store.add_messages(user, sid, [_message_row(b) for b in closed])
            for b, row in zip(closed, stored):
                b["id"] = row.id

        async def _final_flush() -> None:
            """Ein einziges DB-Oeffnen am Stream-Ende: bei normalem Ende wird der letzte
            offene Block abgeschlossen und persistiert; bei Abort/Fehler wird er verworfen.
            Ausserdem Fehler-System-Message (falls error) und generating=0."""
            discard_open = ev.is_set() or error is not None
            rows: list[MessageInput] = []
            if not discard_open:
                for b in blocks:
                    if b["ts"] is None:
                        b["ts"] = _next_ts()
                rows = [_message_row(b) for b in blocks if b["id"] is None and _block_text(b)]
            await self._store.finalize_generation(user, sid, rows, error)

        try:
            # nur Lesezugriff (kein Schreibzugriff -> Datei wird nicht neu verschluesselt);
            # das generating-Flag setzt bereits der Router atomar (try_start_generating)
            if not await self._store.session_exists(user, sid):
                return
            async for chunk in stream_completion(base_url, api_key, payload, settings=settings, abort=ev):
                if ev.is_set():
                    break
                for j in parser.feed(chunk):
                    if j.get("error"):
                        error = str(j["error"])
                        break
                    choices = j.get("choices") or [{}]
                    delta = choices[0].get("delta") or {}
                    reasoning = delta.get("reasoning_content")
                    if reasoning is None:
                        reasoning = delta.get("reasoning")
                    if reasoning:
                        _touch("reasoning")
                        _text_block("reasoning")["text"] += reasoning
                    if delta.get("content"):
                        _touch("message")
                        _text_block("message")["text"] += delta["content"]
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index")
                        if idx is None:
                            idx = sum(1 for b in blocks if b["kind"] == "toolcall")
                        _touch("toolcall", idx)
                        b = _tool_block("toolcall", idx)
                        fn = tc.get("function") or {}
                        b["name"] += fn.get("name") or ""
                        b["args"] += fn.get("arguments") or ""
                    for tr in delta.get("tool_results") or []:
                        idx = tr.get("index")
                        if idx is None:
                            idx = sum(1 for b in blocks if b["kind"] == "toolresult")
                        _touch("toolresult", idx)
                        if tr.get("signal"):
                            # Signal-Chunk des LLM-Servers (z. B. "toolcall_done"): schliesst den
                            # offenen Block, traegt aber keinen Toolresult-Inhalt
                            continue
                        b = _tool_block("toolresult", idx)
                        fn = tr.get("function") or {}
                        b["name"] += tr.get("name") or fn.get("name") or ""
                        b["result"] += (
                            tr.get("result") or tr.get("content") or tr.get("output") or tr.get("text")
                            or fn.get("result") or fn.get("arguments") or ""
                        )
                self._publish(active)
                await _persist_closed_blocks()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Fehler wird als System-Message persistiert
            error = error or str(exc)
        finally:
            await _final_flush()
            self._publish(active)
