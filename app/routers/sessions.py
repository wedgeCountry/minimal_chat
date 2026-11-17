from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..config import AppConfig
from ..deps import get_config, get_current_user, get_message_service, get_store
from ..models import AttachmentOut, MessageIn, MessageOut, MessagePatch, SessionDetail, SessionIn, SessionOut, SessionRename
from ..services.files import UploadTooLarge, process_upload, read_upload_capped
from ..services.chat import MessageService
from ..services.store import DEFAULT_SESSION_NAME, AttachmentQuotaExceeded, MessageNotFound, SessionNotFound, UserStoreProtocol
from ..types import UserIdentity

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionOut])
async def list_sessions(user: UserIdentity = Depends(get_current_user), store: UserStoreProtocol = Depends(get_store)) -> list[SessionOut]:
    return [SessionOut.model_validate(s.model_dump()) for s in await store.list_sessions(user)]


@router.post("", response_model=SessionDetail, status_code=201)
async def create_session(
    body: SessionIn,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> SessionDetail:
    session = await store.create_session(user, body.name.strip() or DEFAULT_SESSION_NAME)
    return SessionDetail(**session.model_dump(), messages=[])


@router.get("/{sid}", response_model=SessionDetail)
async def get_session(sid: str, user: UserIdentity = Depends(get_current_user), store: UserStoreProtocol = Depends(get_store)) -> SessionDetail:
    detail = await store.get_session_detail(user, sid)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    session, messages = detail
    return SessionDetail(**session.model_dump(), messages=[MessageOut.model_validate(m.model_dump()) for m in messages])


@router.patch("/{sid}", response_model=SessionOut)
async def rename_session(
    sid: str,
    body: SessionRename,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> SessionOut:
    try:
        session = await store.rename_session(user, sid, body.name)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    return SessionOut.model_validate(session.model_dump())


@router.delete("/{sid}", status_code=204)
async def delete_session(sid: str, user: UserIdentity = Depends(get_current_user), store: UserStoreProtocol = Depends(get_store)) -> None:
    try:
        await store.delete_session(user, sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")


@router.post("/{sid}/messages", response_model=MessageOut, status_code=201)
async def add_message(
    sid: str,
    msg: MessageIn,
    user: UserIdentity = Depends(get_current_user),
    service: MessageService = Depends(get_message_service),
) -> MessageOut:
    # Schreib-Funnel: In-Memory-Messages des Service zuerst, dann persistiert (write-through)
    try:
        stored = await service.add_message(user, sid, msg)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    return MessageOut.model_validate(stored.model_dump())


@router.patch("/{sid}/messages/{mid}", response_model=MessageOut)
async def update_message(
    sid: str,
    mid: int,
    patch: MessagePatch,
    user: UserIdentity = Depends(get_current_user),
    service: MessageService = Depends(get_message_service),
) -> MessageOut:
    try:
        updated = await service.update_message(user, sid, mid, patch)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    except MessageNotFound:
        raise HTTPException(status_code=404, detail="Nachricht nicht gefunden")
    return MessageOut.model_validate(updated.model_dump())


@router.delete("/{sid}/messages/{mid}", status_code=204)
async def delete_message(sid: str, mid: int, user: UserIdentity = Depends(get_current_user), service: MessageService = Depends(get_message_service)) -> None:
    try:
        await service.delete_message(user, sid, mid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    except MessageNotFound:
        raise HTTPException(status_code=404, detail="Nachricht nicht gefunden")


@router.delete("/{sid}/messages/after/{mid}", status_code=204)
async def delete_messages_after(
    sid: str,
    mid: int,
    user: UserIdentity = Depends(get_current_user),
    service: MessageService = Depends(get_message_service),
) -> None:
    """Loescht alle Nachrichten der Session, die nach der Nachricht ``mid`` liegen
    (z. B. Antworten des Assistenten beim Bearbeiten einer Nutzernachricht)."""
    try:
        await service.delete_messages_after(user, sid, mid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    except MessageNotFound:
        raise HTTPException(status_code=404, detail="Nachricht nicht gefunden")


@router.post("/{sid}/attachments", response_model=AttachmentOut, status_code=201)
async def add_attachment(
    sid: str,
    file: UploadFile = File(...),
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
    config: AppConfig = Depends(get_config),
) -> AttachmentOut:
    """Laedt eine Datei per Multipart-Upload (Rohdaten, kein Base64-in-JSON) hoch;
    das Lesen/Dekodieren passiert serverseitig."""
    try:
        raw = await read_upload_capped(file, config.max_upload_bytes)
        processed = process_upload(file.filename or "datei", file.content_type or "", raw, max_bytes=config.max_upload_bytes)
    except UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        stored = await store.add_attachment(user, sid, processed, raw_size=len(raw), max_total_bytes=config.max_user_storage_bytes)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    except AttachmentQuotaExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    return AttachmentOut.model_validate(stored.model_dump())
