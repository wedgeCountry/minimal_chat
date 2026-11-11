from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..config import AppConfig
from ..db import database as dbq
from ..db.database import Database
from ..deps import get_config, get_current_user, get_db
from ..models import ChatRequest
from ..services.chat import stream_completion

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def chat(
    req: ChatRequest,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> StreamingResponse:
    with db.user_db(user) as con:
        stored = dbq.q_get_settings(con)
    base_url = stored.get("base") or config.default_llm_base
    api_key = stored.get("api_key") or config.default_api_key
    payload = {
        "model": req.model,
        "stream": True,
        "messages": [m.model_dump() for m in req.messages],
    }
    return StreamingResponse(
        stream_completion(base_url, api_key, payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
