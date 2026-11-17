from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..config import AppConfig
from ..deps import get_config, get_current_user, get_store
from ..models import ChatAbortRequest, ChatRequest
from ..services.context import build_llm_context
from ..services.generation import forget_abort_if_idle, is_running, request_abort, run_generation
from ..services.settings import BOOL_SETTINGS, resolve_base_url, stored_bool
from ..services.ssrf import validate_llm_base_url
from ..services.store import UserStore
from ..types import UserIdentity

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Starke Referenzen auf laufende Hintergrund-Tasks, damit der GC sie nicht
# mitten in der Generierung einsammelt.
_background_tasks: set[asyncio.Task[None]] = set()


@router.post("", status_code=202)
async def chat(
    req: ChatRequest,
    user: UserIdentity = Depends(get_current_user),
    store: UserStore = Depends(get_store),
    config: AppConfig = Depends(get_config),
) -> dict[str, str]:
    """Startet eine serverseitige Generierung als Hintergrund-Task.

    Der LLM-Stream wird nicht mehr an den Client durchgereicht, sondern in der
    per-user DB persistiert; der Client pollt ``GET /api/sessions/{id}``.
    """
    ctx = await store.load_chat_context(user, req.session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    _session, stored, attachments, session_messages = ctx
    base_url = resolve_base_url(stored, config)
    try:
        # DNS-Lookup in validate_llm_base_url ist blockierend -> nicht auf dem Event-Loop
        await asyncio.to_thread(validate_llm_base_url, base_url, config.allow_private_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # vor Task-Start atomar setzen, sonst TOCTOU-Race bei parallelen POSTs
    status = await store.try_start_generating(user, req.session_id)
    if status == "missing":
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    if status == "busy":
        raise HTTPException(status_code=409, detail="Es laeuft bereits eine Generierung fuer diese Session")
    api_key = stored.get("api_key") or config.default_api_key
    flags = {key: stored_bool(stored, key) for key in BOOL_SETTINGS}
    # Chat-History serverseitig aus der DB bauen (gueltiges Format inkl. Tool-Calls),
    # nicht aus dem Client-Request uebernehmen
    llm_ctx = build_llm_context(session_messages, system_prompt=stored.get("system_prompt") or "", attachments_by_id=attachments)
    payload = {
        "model": req.model,
        "stream": True,
        "messages": llm_ctx.compile(),
    }
    task = asyncio.create_task(run_generation(store, user, req.session_id, base_url, api_key, payload, flags))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started"}


@router.post("/abort")
async def abort(
    req: ChatAbortRequest,
    user: UserIdentity = Depends(get_current_user),
    store: UserStore = Depends(get_store),
) -> dict[str, str]:
    if not await store.session_exists(user, req.session_id):
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    request_abort(user, req.session_id)
    # Ohne laufende Task ist generating verwaist (z. B. Server-Neustart mitten in einer
    # Generierung): Abbrechen setzt das Flag zurueck, sonst pollt der Client endlos.
    # Bei laufender Task setzt der finale Flush der Task das Flag.
    await store.clear_generating_if_idle(user, req.session_id, is_running(user, req.session_id))
    forget_abort_if_idle(user, req.session_id)
    return {"status": "aborted"}
