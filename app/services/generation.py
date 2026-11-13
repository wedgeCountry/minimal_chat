"""Serverseitige Generierung: der LLM-Stream laeuft in einer Hintergrund-Task
und wird direkt in die per-user SQLite persistiert.

 Dadurch ueberlebt eine Generierung, dass der Client (z.B. App im
Hintergrund) die Verbindung verliert; der Client pollt einfach den Session-Stand.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..db import database as dbq
from ..db.database import Database
from .chat import parse_sse_buffer, stream_completion

FLUSH_INTERVAL_S = 0.25

_abort_events: dict[str, asyncio.Event] = {}
_running: set[str] = set()


def _key(user: dict, sid: str) -> str:
    return f"{user['uid']}:{sid}"


def request_abort(user: dict, sid: str) -> bool:
    ev = _abort_events.get(_key(user, sid))
    if ev:
        ev.set()
        return True
    return False


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
    """Streamt eine Chat-Completion und persistiert jeden Stand in die User-DB.

    Laeuft als asyncio-Task unabhaengig von der HTTP-Verbindung des Clients.
    """
    key = _key(user, sid)
    ev = asyncio.Event()
    _abort_events[key] = ev
    _running.add(key)
    ai_text = ""
    think_text = ""
    tools: dict[int, dict[str, str]] = {}
    tool_results: dict[int, dict[str, str]] = {}
    ids: dict[str, Any] = {"ai": None, "think": None, "tool": {}, "toolres": {}}
    error: str | None = None
    buf = ""

    async def flush(final: bool = False) -> None:
        # DB-Zugriff (Dekodieren/Verschluesseln der per-user DB) ist blockierend
        # und darf nicht direkt auf dem Event-Loop laufen.
        def _flush() -> None:
            with db.user_db(user) as con:
                _flush_into(con, final)
        await asyncio.to_thread(_flush)

    def _flush_into(con, final: bool) -> None:
        if think_text:
            if ids["think"] is None:
                ids["think"] = dbq.q_add_message(
                    con, sid, {"role": "assistant", "type": "reasoning", "text": think_text, "in_context": False}
                )["id"]
            else:
                dbq.q_update_message(con, ids["think"], {"text": think_text})
        if ai_text:
            if ids["ai"] is None:
                ids["ai"] = dbq.q_add_message(
                    con, sid, {"role": "assistant", "type": "message", "text": ai_text, "in_context": True}
                )["id"]
            else:
                dbq.q_update_message(con, ids["ai"], {"text": ai_text})
        for idx, t in tools.items():
            # Argumente sind JSON-String-Literale: literale "\n" als echte Umbrueche speichern
            text = f"{t['name'] or 'tool'}({t['args']})".replace("\\n", "\n")
            if idx in ids["tool"]:
                dbq.q_update_message(con, ids["tool"][idx], {"text": text})
            else:
                ids["tool"][idx] = dbq.q_add_message(
                    con, sid, {"role": "assistant", "type": "toolcall", "text": text, "in_context": False}
                )["id"]
        for idx, r in tool_results.items():
            text = (f"{r['name']}: {r['result']}" if r["name"] else r["result"]).replace("\\n", "\n")
            if idx in ids["toolres"]:
                dbq.q_update_message(con, ids["toolres"][idx], {"text": text})
            else:
                ids["toolres"][idx] = dbq.q_add_message(
                    con, sid, {"role": "assistant", "type": "toolresult", "text": text, "in_context": False}
                )["id"]
        if final:
            if error:
                dbq.q_add_message(
                    con, sid, {"role": "system", "type": "message", "text": "Fehler: " + error, "in_context": False}
                )
            dbq.q_set_generating(con, sid, False)

    def _mark_generating() -> bool:
        with db.user_db(user) as con:
            if not dbq.q_get_session(con, sid):
                return False
            dbq.q_set_generating(con, sid, True)
            return True

    try:
        if not await asyncio.to_thread(_mark_generating):
            return
        # Periodisches Flushen: Teilausgabe landet auch ohne neuen Chunk
        # nach spaetestens FLUSH_INTERVAL_S in der DB (nicht nur bei Chunk-Eingang).
        stop_flush = asyncio.Event()

        async def _periodic_flush() -> None:
            while True:
                try:
                    await asyncio.wait_for(stop_flush.wait(), FLUSH_INTERVAL_S)
                    return
                except asyncio.TimeoutError:
                    await flush()

        flusher = asyncio.create_task(_periodic_flush())
        try:
            async for chunk in stream_completion(base_url, api_key, payload, settings=settings):
                if ev.is_set():
                    break
                buf += chunk
                events, buf = parse_sse_buffer(buf)
                for j in events:
                    if j.get("error"):
                        error = str(j["error"])
                        break
                    choices = j.get("choices") or [{}]
                    delta = choices[0].get("delta") or {}
                    reasoning = delta.get("reasoning_content")
                    if reasoning is None:
                        reasoning = delta.get("reasoning")
                    if reasoning:
                        think_text += reasoning
                    if delta.get("content"):
                        ai_text += delta["content"]
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", len(tools))
                        t = tools.setdefault(idx, {"name": "", "args": ""})
                        fn = tc.get("function") or {}
                        t["name"] += fn.get("name") or ""
                        t["args"] += fn.get("arguments") or ""
                    for tr in delta.get("tool_results") or []:
                        idx = tr.get("index", len(tool_results))
                        r = tool_results.setdefault(idx, {"name": "", "result": ""})
                        fn = tr.get("function") or {}
                        r["name"] += tr.get("name") or fn.get("name") or ""
                        r["result"] += (
                            tr.get("result") or tr.get("content") or tr.get("output") or tr.get("text")
                            or fn.get("result") or fn.get("arguments") or ""
                        )
        finally:
            stop_flush.set()
            flusher.cancel()
            try:
                await flusher
            except asyncio.CancelledError:
                pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - Fehler wird als System-Message persistiert
        error = error or str(exc)
    finally:
        await flush(final=True)
        _abort_events.pop(key, None)
        _running.discard(key)
