from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..config import AppConfig
from ..deps import get_config, get_current_user, get_message_service, get_store
from ..models import ChatAbortRequest, ChatRequest
from ..services.chat import MessageService
from ..services.context import build_llm_context
from ..services.settings import BOOL_SETTINGS, resolve_base_url, stored_bool
from ..services.sse import sse_event
from ..services.ssrf import validate_llm_base_url
from ..services.store import SessionNotFound, UserStoreProtocol
from ..types import UserIdentity

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", status_code=202)
async def chat(
    req: ChatRequest,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
    service: MessageService = Depends(get_message_service),
    config: AppConfig = Depends(get_config),
) -> dict[str, str]:
    """Startet eine serverseitige Generierung als Hintergrund-Task im MessageService.

    Der LLM-Stream wird in den In-Memory-State des Service gelesen (SSE-Quelle fuer
    den Client, siehe GET /stream/{sid}) und blockweise in der per-user DB persistiert;
    der Client pollt zusaetzlich ``GET /api/sessions/{id}``.
    """
    ctx = await store.load_chat_context(user, req.session_id)
    if ctx is None:
        raise SessionNotFound(req.session_id)
    _session, stored, attachments, session_messages = ctx
    base_url = resolve_base_url(stored, config)
    try:
        # DNS-Lookup in validate_llm_base_url ist blockierend -> nicht auf dem Event-Loop
        await asyncio.to_thread(validate_llm_base_url, base_url, config.allow_private_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    api_key = stored.get("api_key") or config.default_api_key
    flags = {key: stored_bool(stored, key) for key in BOOL_SETTINGS}
    # Chat-History serverseitig aus der DB bauen (gueltiges Format inkl. Tool-Calls),
    # nicht aus dem Client-Request uebernehmen
    llm_ctx = build_llm_context([m.model_dump() for m in session_messages], system_prompt=stored.get("system_prompt") or "", attachments_by_id=attachments)
    payload = {
        "model": req.model,
        "stream": True,
        "messages": llm_ctx.compile(),
    }
    # generating-Flag atomar unter dem Session-Lock setzen (TOCTOU-frei); ein verwaistes
    # Flag nach Server-Neustart wird im Service geheilt
    status = await service.start_generation(user, req.session_id, base_url, api_key, payload, flags)
    if status == "missing":
        raise SessionNotFound(req.session_id)
    if status == "busy":
        raise HTTPException(status_code=409, detail="Es laeuft bereits eine Generierung fuer diese Session")
    return {"status": "started"}


@router.get("/stream/{sid}")
async def chat_stream(
    sid: str,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
    service: MessageService = Depends(get_message_service),
) -> StreamingResponse:
    """SSE-Stream der Live-Daten aus dem In-Memory-State des MessageService.

    Events: ``state`` (versioniert: seq + vollstaendige Message-Liste inkl. Live-Messages
    mit id=null), ``done`` (Generierung beendet), ``idle`` (Session nicht hot / keine
    laufende Generierung - Client liest den Stand ueber GET /api/sessions/{sid}).
    """
    if not await store.session_exists(user, sid):
        raise SessionNotFound(sid)

    async def events() -> AsyncIterator[str]:
        async for ev in service.stream(user, sid):
            yield sse_event(ev)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/abort")
async def abort(
    req: ChatAbortRequest,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
    service: MessageService = Depends(get_message_service),
) -> dict[str, str]:
    if not await store.session_exists(user, req.session_id):
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    service.request_abort(user, req.session_id)
    # Ohne laufende Task ist generating verwaist (z. B. Server-Neustart mitten in einer
    # Generierung): Abbrechen setzt das Flag zurueck, sonst pollt der Client endlos.
    # Bei laufender Task setzt der finale Flush der Task das Flag.
    await store.clear_generating_if_idle(user, req.session_id, service.is_running(user, req.session_id))
    service.forget_abort_if_idle(user, req.session_id)
    return {"status": "aborted"}
