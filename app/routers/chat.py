from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..config import AppConfig
from ..deps import get_config, get_current_user, get_message_service, get_store
from ..models import ChatAbortRequest, ChatRequest
from ..services.chat import MessageService, build_generation_request
from ..services.sse import sse_event
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

    Bei laufender Generierung derselben Session: ohne ``streaming_behavior`` -> 409;
    mit ``streaming_behavior`` ("followUp"/"steer") -> 202 ``queued``, die Nachricht wird
    nach der laufenden Generierung als eigener Lauf abgearbeitet (MessageService._settle);
    "steer" bricht den laufenden Lauf zusaetzlich ab. Das Verhalten wird als
    ``streamingBehavior`` an den Upstream durchgereicht (Agent-Gateways wie pi-Bridges
    queuen damit agentenseitig, reine OpenAI-Server ignorieren das Feld).
    """
    try:
        gen_req = await build_generation_request(store, user, req.session_id, config, streaming_behavior=req.streaming_behavior)
    except ValueError as exc:
        # SSRF-Validierung der LLM-Ziel-URL fehlgeschlagen
        raise HTTPException(status_code=400, detail=str(exc))
    if gen_req is None:
        raise SessionNotFound(req.session_id)
    # generating-Flag atomar unter dem Session-Lock setzen (TOCTOU-frei); ein verwaistes
    # Flag nach Server-Neustart wird im Service geheilt
    status = await service.start_generation(
        user,
        req.session_id,
        gen_req["base_url"],
        gen_req["api_key"],
        gen_req["payload"],
        gen_req["flags"],
        streaming_behavior=req.streaming_behavior,
    )
    if status == "missing":
        raise SessionNotFound(req.session_id)
    if status == "busy":
        raise HTTPException(status_code=409, detail="Es laeuft bereits eine Generierung fuer diese Session")
    if status == "queued":
        return {"status": "queued", "streaming_behavior": req.streaming_behavior or ""}
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
