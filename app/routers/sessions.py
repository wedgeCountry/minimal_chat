from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from ..config import AppConfig
from ..deps import get_config, get_current_user, get_message_service, get_store
from ..models import AttachmentOut, MessageIn, MessageOut, MessagePatch, SessionDetail, SessionIn, SessionOut, SessionRename, SessionSettingsIn, SessionSettingsOut
from ..services.files import process_upload, read_upload_capped
from ..services.settings import SESSION_CLEARABLE_WITH_EMPTY, SESSION_SETTING_KEYS
from ..services.chat import MessageService
from ..services.store import DEFAULT_SESSION_NAME, SessionNotFound, UserStoreProtocol
from ..types import UserIdentity

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionOut])
async def list_sessions(user: UserIdentity = Depends(get_current_user), store: UserStoreProtocol = Depends(get_store)) -> list[SessionOut]:
    return [SessionOut.model_validate(s.model_dump()) for s in await store.list_sessions(user)]


def _session_settings_out(sid: str, stored: dict[str, str]) -> SessionSettingsOut:
    return SessionSettingsOut.model_validate({"session_id": sid, **{key: stored.get(key) or "" for key in SESSION_SETTING_KEYS}})


@router.post("", response_model=SessionDetail, status_code=201)
async def create_session(
    body: SessionIn,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> SessionDetail:
    session = await store.create_session(user, body.name.strip() or DEFAULT_SESSION_NAME)
    return SessionDetail(**session.model_dump(), messages=[], settings=_session_settings_out(session.id, {}))


@router.get("/{sid}", response_model=SessionDetail)
async def get_session(sid: str, user: UserIdentity = Depends(get_current_user), store: UserStoreProtocol = Depends(get_store)) -> SessionDetail:
    detail = await store.get_session_detail(user, sid)
    if detail is None:
        raise SessionNotFound(sid)
    session, messages, session_settings = detail
    return SessionDetail(
        **session.model_dump(),
        messages=[MessageOut.model_validate(m.model_dump()) for m in messages],
        settings=_session_settings_out(sid, session_settings),
    )


@router.get("/{sid}/settings", response_model=SessionSettingsOut)
async def get_session_settings(sid: str, user: UserIdentity = Depends(get_current_user), store: UserStoreProtocol = Depends(get_store)) -> SessionSettingsOut:
    stored = await store.get_session_settings(user, sid)
    return _session_settings_out(sid, stored)


@router.put("/{sid}/settings", response_model=SessionSettingsOut)
async def put_session_settings(
    sid: str,
    body: SessionSettingsIn,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> SessionSettingsOut:
    values: dict[str, str] = {}
    for key in SESSION_SETTING_KEYS:
        value = getattr(body, key)
        if value is not None and (value != "" or key in SESSION_CLEARABLE_WITH_EMPTY):
            values[key] = value
    stored = await store.update_session_settings(user, sid, values)
    return _session_settings_out(sid, stored)


@router.patch("/{sid}", response_model=SessionOut)
async def rename_session(
    sid: str,
    body: SessionRename,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> SessionOut:
    session = await store.rename_session(user, sid, body.name)
    return SessionOut.model_validate(session.model_dump())


@router.delete("/{sid}", status_code=204)
async def delete_session(sid: str, user: UserIdentity = Depends(get_current_user), store: UserStoreProtocol = Depends(get_store)) -> None:
    await store.delete_session(user, sid)


@router.post("/{sid}/messages", response_model=MessageOut, status_code=201)
async def add_message(
    sid: str,
    msg: MessageIn,
    user: UserIdentity = Depends(get_current_user),
    service: MessageService = Depends(get_message_service),
) -> MessageOut:
    # Schreib-Funnel: In-Memory-Messages des Service zuerst, dann persistiert (write-through)
    stored = await service.add_message(user, sid, msg)
    return MessageOut.model_validate(stored.model_dump())


@router.patch("/{sid}/messages/{mid}", response_model=MessageOut)
async def update_message(
    sid: str,
    mid: int,
    patch: MessagePatch,
    user: UserIdentity = Depends(get_current_user),
    service: MessageService = Depends(get_message_service),
) -> MessageOut:
    updated = await service.update_message(user, sid, mid, patch)
    return MessageOut.model_validate(updated.model_dump())


@router.delete("/{sid}/messages/{mid}", status_code=204)
async def delete_message(sid: str, mid: int, user: UserIdentity = Depends(get_current_user), service: MessageService = Depends(get_message_service)) -> None:
    await service.delete_message(user, sid, mid)


@router.delete("/{sid}/messages/after/{mid}", status_code=204)
async def delete_messages_after(
    sid: str,
    mid: int,
    user: UserIdentity = Depends(get_current_user),
    service: MessageService = Depends(get_message_service),
) -> None:
    """Loescht alle Nachrichten der Session, die nach der Nachricht ``mid`` liegen
    (z. B. Antworten des Assistenten beim Bearbeiten einer Nutzernachricht)."""
    await service.delete_messages_after(user, sid, mid)


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
    # UploadTooLarge/SessionNotFound/AttachmentQuotaExceeded werden zentral in app/main.py gemappt
    raw = await read_upload_capped(file, config.max_upload_bytes)
    processed = process_upload(file.filename or "datei", file.content_type or "", raw, max_bytes=config.max_upload_bytes)
    stored = await store.add_attachment(user, sid, processed, raw_size=len(raw), max_total_bytes=config.max_user_storage_bytes)
    return AttachmentOut.model_validate(stored.model_dump())
