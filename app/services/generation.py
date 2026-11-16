"""Serverseitige Generierung: der LLM-Stream laeuft in einer Hintergrund-Task
und wird in die per-user SQLite persistiert.

Persistenz-Regel (Performance): Die per-user DB wird NICHT pro Chunk entschluesselt.
Bloecke akkumulieren im Speicher; ein Block wird erst persistiert, wenn er im Stream
abgeschlossen ist (Typwechsel bzw. Stream-Ende) - eine Zeile pro Block, sofort beim
Abschluss. Der offene Block wird bei Abort/Fehler verworfen (nie geschrieben).
Dadurch ueberlebt eine Generierung, dass der Client die Verbindung verliert; der
Client pollt einfach den Session-Stand.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..db import database as dbq
from ..db.database import Database
from .llm import stream_completion
from .sse import SseParser

_abort_events: dict[str, asyncio.Event] = {}
_abort_requested: set[str] = set()
_running: set[str] = set()


def _key(user: dict, sid: str) -> str:
    return f"{user['uid']}:{sid}"


def request_abort(user: dict, sid: str) -> bool:
    key = _key(user, sid)
    ev = _abort_events.get(key)
    if ev:
        ev.set()
        return True
    # Task registriert sein Event evtl. noch nicht (Race direkt nach POST /api/chat)
    _abort_requested.add(key)
    return False


def forget_abort_if_idle(user: dict, sid: str) -> None:
    """Abort-Request verwerfen, wenn keine Task laeuft (verwaistes generating-Flag nach
    Server-Neustart): eine spaeter gestartete Generierung derselben Session darf nicht
    durch den alten Request sofort abbrechen."""
    key = _key(user, sid)
    if key not in _running:
        _abort_requested.discard(key)


def is_running(user: dict, sid: str) -> bool:
    return _key(user, sid) in _running


async def run_generation(
    db: Database,
    user: dict,
    sid: str,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    settings: dict[str, bool] | None = None,
) -> None:
    """Streamt eine Chat-Completion und persistiert abgeschlossene Bloecke in die User-DB.

    Laeuft als asyncio-Task unabhaengig von der HTTP-Verbindung des Clients. Nur
    abgeschlossene Bloecke werden geschrieben (ein DB-Oeffnen pro Block-Abschluss plus
    eins am Ende); der offene Block bleibt im Speicher und wird bei Abort/Fehler
    verworfen.
    """
    key = _key(user, sid)
    ev = asyncio.Event()
    _abort_events[key] = ev
    _running.add(key)
    if key in _abort_requested:
        _abort_requested.discard(key)
        ev.set()
    # Blöcke in Stream-Reihenfolge (reasoning/message/toolcall/toolresult): jeder Block
    # wird zu einer eigenen Message-Zeile (keine Akkumulation ueber den ganzen Stream).
    # Der Abschluss-Zeitstempel (ms) wird beim Typwechsel im Stream bzw. am Stream-Ende
    # vergeben und als created_at persistiert.
    blocks: list[dict[str, Any]] = []
    tool_blocks: dict[tuple[str, int], dict[str, Any]] = {}
    last_kind: tuple[str, int | None] | None = None
    last_ts = 0
    error: str | None = None
    parser = SseParser()

    def _next_ts() -> int:
        nonlocal last_ts
        last_ts = max(dbq._now_ms(), last_ts + 1)
        return last_ts

    def _touch(kind: str, idx: int | None = None) -> None:
        # Typwechsel im Chunk-Stream: der bisher aktive Block ist abgeschlossen
        nonlocal last_kind
        if last_kind is not None and last_kind != (kind, idx):
            for b in blocks:
                if b["ts"] is None:
                    b["ts"] = _next_ts()
        last_kind = (kind, idx)

    def _text_block(kind: str) -> dict[str, Any]:
        if blocks and blocks[-1]["kind"] == kind and blocks[-1]["ts"] is None:
            return blocks[-1]
        b: dict[str, Any] = {"kind": kind, "ts": None, "id": None, "text": ""}
        blocks.append(b)
        return b

    def _tool_block(kind: str, idx: int) -> dict[str, Any]:
        b = tool_blocks.get((kind, idx))
        if b is None:
            b = {"kind": kind, "ts": None, "id": None, "name": "", "args": "", "result": ""}
            tool_blocks[(kind, idx)] = b
            blocks.append(b)
        return b

    def _block_text(b: dict[str, Any]) -> str:
        if b["kind"] == "toolcall":
            # Argumente sind JSON-String-Literale: literale "\n" als echte Umbrueche speichern
            return f"{b['name'] or 'tool'}({b['args']})".replace("\\n", "\n")
        if b["kind"] == "toolresult":
            text = f"{b['name']}: {b['result']}" if b["name"] else b["result"]
            return text.replace("\\n", "\n")
        return b["text"]

    def _message_row(b: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "type": b["kind"],
            "text": _block_text(b),
            "in_context": b["kind"] != "reasoning",
            "created_at": b["ts"] if b["ts"] is not None else _next_ts(),
        }

    async def _persist_closed_blocks() -> None:
        """Persistiert abgeschlossene Bloecke sofort (beim Typwechsel im Stream).
        Der offene Block wird nie geschrieben. Pro Batch genau ein DB-Oeffnen
        (blockierend -> to_thread)."""
        closed = [b for b in blocks if b["ts"] is not None and b["id"] is None and _block_text(b)]
        if not closed:
            return

        def _do() -> None:
            with db.user_db(user) as con:
                for b in closed:
                    b["id"] = dbq.q_add_message(con, sid, _message_row(b))["id"]

        await asyncio.to_thread(_do)

    async def _final_flush() -> None:
        """Ein einziges DB-Oeffnen am Stream-Ende: bei normalem Ende wird der letzte
        offene Block abgeschlossen und persistiert; bei Abort/Fehler wird er verworfen.
        Ausserdem Fehler-System-Message (falls error) und generating=0."""
        discard_open = ev.is_set() or error is not None

        def _do() -> None:
            with db.user_db(user) as con:
                if not discard_open:
                    for b in blocks:
                        if b["ts"] is None:
                            b["ts"] = _next_ts()
                    for b in blocks:
                        if b["id"] is None and _block_text(b):
                            b["id"] = dbq.q_add_message(con, sid, _message_row(b))["id"]
                if error:
                    dbq.q_add_message(
                        con, sid, {"role": "system", "type": "message", "text": "Fehler: " + error, "in_context": False}
                    )
                dbq.q_set_generating(con, sid, False)

        await asyncio.to_thread(_do)

    def _session_exists() -> bool:
        # nur Lesezugriff (kein Schreibzugriff -> Datei wird nicht neu verschluesselt);
        # das generating-Flag setzt bereits der Router atomar (q_try_start_generating)
        with db.user_db(user) as con:
            return dbq.q_get_session(con, sid) is not None

    try:
        if not await asyncio.to_thread(_session_exists):
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
                    b = _tool_block("toolresult", idx)
                    fn = tr.get("function") or {}
                    b["name"] += tr.get("name") or fn.get("name") or ""
                    b["result"] += (
                        tr.get("result") or tr.get("content") or tr.get("output") or tr.get("text")
                        or fn.get("result") or fn.get("arguments") or ""
                    )
            await _persist_closed_blocks()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - Fehler wird als System-Message persistiert
        error = error or str(exc)
    finally:
        await _final_flush()
        _abort_events.pop(key, None)
        _abort_requested.discard(key)
        _running.discard(key)
