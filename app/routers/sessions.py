from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..db import database as dbq
from ..db.database import Database
from ..deps import get_current_user, get_db
from ..models import AttachmentOut, MessageIn, MessageOut, MessagePatch, SessionDetail, SessionIn, SessionOut, SessionRename
from ..services.files import process_upload

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

DEFAULT_SESSION_NAME = "Neue Session"


@router.get("", response_model=list[SessionOut])
def list_sessions(user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    with db.user_db(user) as con:
        return dbq.q_list_sessions(con)


@router.post("", response_model=SessionDetail, status_code=201)
def create_session(body: SessionIn, user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    with db.user_db(user) as con:
        session = dbq.q_create_session(con, body.name.strip() or DEFAULT_SESSION_NAME)
        return SessionDetail(**session, messages=[])


@router.get("/{sid}", response_model=SessionDetail)
def get_session(sid: str, user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    with db.user_db(user) as con:
        session = dbq.q_get_session(con, sid)
        if not session:
            raise HTTPException(status_code=404, detail="Session nicht gefunden")
        messages = dbq.q_get_messages(con, sid)
    return SessionDetail(**session, messages=[MessageOut(**m) for m in messages])


@router.patch("/{sid}", response_model=SessionOut)
def rename_session(sid: str, body: SessionRename, user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    with db.user_db(user) as con:
        session = dbq.q_get_session(con, sid)
        if not session:
            raise HTTPException(status_code=404, detail="Session nicht gefunden")
        name = body.name.strip()
        if name:  # Leer/Whitespace-only behaelt den alten Namen
            dbq.q_rename_session(con, sid, name)
            session = dbq.q_get_session(con, sid)
    return SessionOut(**session)


@router.delete("/{sid}", status_code=204)
def delete_session(sid: str, user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    with db.user_db(user) as con:
        if not dbq.q_get_session(con, sid):
            raise HTTPException(status_code=404, detail="Session nicht gefunden")
        dbq.q_delete_session(con, sid)


@router.post("/{sid}/messages", response_model=MessageOut, status_code=201)
def add_message(sid: str, msg: MessageIn, user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    with db.user_db(user) as con:
        session = dbq.q_get_session(con, sid)
        if not session:
            raise HTTPException(status_code=404, detail="Session nicht gefunden")
        stored = dbq.q_add_message(con, sid, msg.model_dump())
        if msg.role == "user" and msg.type == "message" and msg.text.strip() and session["name"] == DEFAULT_SESSION_NAME:
            dbq.q_rename_session(con, sid, msg.text.strip()[:40])
    return MessageOut(**stored)


@router.patch("/{sid}/messages/{mid}", response_model=MessageOut)
def update_message(sid: str, mid: int, patch: MessagePatch, user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    with db.user_db(user) as con:
        if not dbq.q_get_session(con, sid):
            raise HTTPException(status_code=404, detail="Session nicht gefunden")
        updated = dbq.q_update_message(con, mid, patch.model_dump(exclude_none=True))
        if not updated:
            raise HTTPException(status_code=404, detail="Nachricht nicht gefunden")
    return MessageOut(**updated)


@router.delete("/{sid}/messages/{mid}", status_code=204)
def delete_message(sid: str, mid: int, user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    with db.user_db(user) as con:
        if not dbq.q_get_session(con, sid):
            raise HTTPException(status_code=404, detail="Session nicht gefunden")
        if not dbq.q_get_message(con, mid):
            raise HTTPException(status_code=404, detail="Nachricht nicht gefunden")
        dbq.q_delete_message(con, mid)


@router.delete("/{sid}/messages/after/{mid}", status_code=204)
def delete_messages_after(sid: str, mid: int, user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    """Loescht alle Nachrichten der Session, die nach der Nachricht ``mid`` liegen
    (z. B. Antworten des Assistenten beim Bearbeiten einer Nutzernachricht)."""
    with db.user_db(user) as con:
        if not dbq.q_get_session(con, sid):
            raise HTTPException(status_code=404, detail="Session nicht gefunden")
        msg = dbq.q_get_message(con, mid)
        if not msg or msg["session_id"] != sid:
            raise HTTPException(status_code=404, detail="Nachricht nicht gefunden")
        dbq.q_delete_messages_after(con, sid, mid)


@router.post("/{sid}/attachments", response_model=AttachmentOut, status_code=201)
async def add_attachment(
    sid: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Laedt eine Datei per Multipart-Upload (Rohdaten, kein Base64-in-JSON) hoch;
    das Lesen/Dekodieren passiert serverseitig."""
    raw = await file.read()
    try:
        processed = process_upload(file.filename or "datei", file.content_type or "", raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    def _store() -> dict:
        with db.user_db(user) as con:
            if not dbq.q_get_session(con, sid):
                raise HTTPException(status_code=404, detail="Session nicht gefunden")
            return dbq.q_add_attachment(con, sid, processed)

    # DB-Zugriff ist blockierend -> nicht auf dem Event-Loop ausfuehren
    stored = await asyncio.to_thread(_store)
    return AttachmentOut(id=stored["id"], name=stored["name"], mime=stored["mime"], kind=stored["kind"], size=stored["size"])
