from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..config import AppConfig
from ..db import database as dbq
from ..db.database import Database
from ..deps import get_config, get_current_user, get_db
from ..models import ChatAbortRequest, ChatRequest
from ..services.files import expand_attachment_parts
from ..services.generation import request_abort, run_generation
from ..services.settings import BOOL_SETTINGS, resolve_base_url, stored_bool

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Starke Referenzen auf laufende Hintergrund-Tasks, damit der GC sie nicht
# mitten in der Generierungeinsammelt.
_background_tasks: set[asyncio.Task] = set()


def _load_chat_context(db: Database, user: dict, session_id: str):
    """Session + Settings + Attachments laden (blockierend -> via to_thread)."""
    with db.user_db(user) as con:
        session = dbq.q_get_session(con, session_id)
        if not session:
            return None
        stored = dbq.q_get_user_settings(con)
        attachments = {a["id"]: a for a in dbq.q_get_session_attachments(con, session_id)}
    return session, stored, attachments


def _session_exists(db: Database, user: dict, session_id: str) -> bool:
    with db.user_db(user) as con:
        return dbq.q_get_session(con, session_id) is not None


@router.post("", status_code=202)
async def chat(
    req: ChatRequest,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict:
    """Startet eine serverseitige Generierung als Hintergrund-Task.

    Der LLM-Stream wird nicht mehr an den Client durchgereicht, sondern in der
    per-user DB persistiert; der Client pollt ``GET /api/sessions/{id}``.
    """
    ctx = await asyncio.to_thread(_load_chat_context, db, user, req.session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    session, stored, attachments = ctx
    if session["generating"]:
        raise HTTPException(status_code=409, detail="Es läuft bereits eine Generierung für diese Session")
    base_url = resolve_base_url(stored, config)
    api_key = stored.get("api_key") or config.default_api_key
    flags = {key: stored_bool(stored, key) for key in BOOL_SETTINGS}
    messages = expand_attachment_parts([m.model_dump() for m in req.messages], attachments)
    system_prompt = stored.get("system_prompt") or ""
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})
    payload = {
        "model": req.model,
        "stream": True,
        "messages": messages,
    }
    task = asyncio.create_task(run_generation(db, user, req.session_id, base_url, api_key, payload, flags))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started"}


@router.post("/abort")
async def abort(
    req: ChatAbortRequest,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> dict:
    exists = await asyncio.to_thread(_session_exists, db, user, req.session_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    request_abort(user, req.session_id)
    return {"status": "aborted"}
