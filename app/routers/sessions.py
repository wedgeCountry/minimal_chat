from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException

from ..db import database as dbq
from ..db.database import Database
from ..deps import get_current_user, get_db
from ..models import AttachmentIn, AttachmentOut, MessageIn, MessageOut, MessagePatch, SessionDetail, SessionIn, SessionOut, SessionRename
from ..services.files import process_upload

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

DEFAULT_SESSION_NAME = "Neue Session"


def _get_or_404(db: Database, user: dict, sid: str):
    with db.user_db(user) as con:
        session = dbq.q_get_session(con, sid)
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    return session


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


@router.post("/{sid}/attachments", response_model=AttachmentOut, status_code=201)
def add_attachment(sid: str, body: AttachmentIn, user: dict = Depends(get_current_user), db: Database = Depends(get_db)):
    """Laedt eine Datei-Rohform hoch; das Lesen/Dekodieren passiert serverseitig."""
    try:
        raw = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Ungueltige Base64-Daten")
    try:
        processed = process_upload(body.name, body.type, raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    with db.user_db(user) as con:
        if not dbq.q_get_session(con, sid):
            raise HTTPException(status_code=404, detail="Session nicht gefunden")
        stored = dbq.q_add_attachment(con, sid, processed)
    return AttachmentOut(id=stored["id"], name=stored["name"], mime=stored["mime"], kind=stored["kind"], size=stored["size"])
