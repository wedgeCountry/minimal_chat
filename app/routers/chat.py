from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..config import AppConfig
from ..db import database as dbq
from ..db.database import Database
from ..deps import get_config, get_current_user, get_db
from ..models import ChatRequest
from ..services.chat import stream_completion
from ..services.settings import BOOL_SETTINGS, resolve_base_url, stored_bool

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def chat(
    req: ChatRequest,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> StreamingResponse:
    with db.user_db(user) as con:
        stored = dbq.q_get_user_settings(con)
    base_url = resolve_base_url(stored, config)
    api_key = stored.get("api_key") or config.default_api_key
    flags = {key: stored_bool(stored, key) for key in BOOL_SETTINGS}
    messages = [m.model_dump() for m in req.messages]
    system_prompt = stored.get("system_prompt") or ""
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})
    payload = {
        "model": req.model,
        "stream": True,
        "messages": messages,
    }
    return StreamingResponse(
        stream_completion(base_url, api_key, payload, settings=flags),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
