"""Persistenz-Gateway (Repository): einzige Schicht zwischen App-Code (Router,
MessageService) und der Datenbank.

Die oeffentliche Schnittstelle ist ``UserStoreProtocol``; ``SqliteUserStore`` kapselt
``Database.user_db`` + die ``q_*``-Helper + ``asyncio.to_thread`` und mappt dabei
DB-Zeilen (TypedDicts aus app/types.py) auf die kanonischen Domain-Models (app/domain.py).
Aufrufer arbeiten asynchron mit fachlichen Methoden und Domain-Objekten
(``Session``/``Message``/...) statt ``sqlite3.Connection``. Verschluesselung,
Datei-Layout, Schema-Migrationen und Locks bleiben in ``app/db/database.py``; direkter
Zugriff auf ``Database``/``q_*`` ist nur noch dieser Schicht und den DB-Unit-Tests vorbehalten
(AGENTS.md Regel 1). Jede Methode oeffnet die per-user DB genau einmal (ein Schreibzugriff
= ein Entschluesseln/Verschluesseln) und fuehrt blockierenden Code nie auf dem Event-Loop aus.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypeVar, runtime_checkable

from ..db import database as dbq
from ..db.database import Database
from ..domain import Attachment, AttachmentRef, ChatContext, Message, Session
from ..types import AttachmentRow, MessageInput, MessageRow, SessionRow, UserIdentity

T = TypeVar("T")

DEFAULT_SESSION_NAME = "Neue Session"


class SessionNotFound(Exception):
    pass


class MessageNotFound(Exception):
    pass


class AttachmentQuotaExceeded(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"Speicherplatz-Kontingent ueberschritten (Limit {limit} Bytes)")
        self.limit = limit


def error_message_input(error: str) -> MessageInput:
    """System-Message, die einen Generierungs-Fehler persistiert (in_context=False,
    landet nie im LLM-Kontext). Geteilt von SqliteUserStore und InMemoryUserStore."""
    return {"role": "system", "type": "message", "text": "Fehler: " + error, "in_context": False}


def default_name_for_first_user_text(role: str, msg_type: str, text: str, current_name: str) -> str | None:
    """Neuer Session-Name beim ersten User-Text (None = Name bleibt unveraendert)."""
    stripped = text.strip()
    if role == "user" and msg_type == "message" and stripped and current_name == DEFAULT_SESSION_NAME:
        return stripped[:40]
    return None


# --- Row -> Domain Mapping ---


def _to_session(row: SessionRow) -> Session:
    return Session(id=row["id"], name=row["name"], ts=row["ts"], generating=row["generating"])


def _to_message(row: MessageRow) -> Message:
    return Message(
        id=row["id"],
        role=row["role"],  # type: ignore[arg-type]  # DB-CHECK erzwingt gueltige Literal-Werte
        type=row["type"],  # type: ignore[arg-type]
        text=row["text"],
        in_context=row["in_context"],
        attachments=[AttachmentRef.model_validate(a) for a in row["attachments"]],
        ts=row["ts"],
    )


def _to_attachment(row: AttachmentRow) -> Attachment:
    return Attachment(
        id=row["id"],
        session_id=row["session_id"],
        name=row["name"],
        mime=row["mime"],
        kind=row["kind"],
        size=row["size"],
        content=row["content"],
    )


@runtime_checkable
class UserStoreProtocol(Protocol):
    """Schnittstelle des Persistenz-Gateways (implementiert z. B. von SqliteUserStore
    und dem InMemoryUserStore fuer Tests)."""

    async def list_sessions(self, user: UserIdentity) -> list[Session]: ...
    async def create_session(self, user: UserIdentity, name: str) -> Session: ...
    async def get_session(self, user: UserIdentity, sid: str) -> Session | None: ...
    async def session_exists(self, user: UserIdentity, sid: str) -> bool: ...
    async def get_session_detail(self, user: UserIdentity, sid: str) -> tuple[Session, list[Message], dict[str, str]] | None: ...
    async def rename_session(self, user: UserIdentity, sid: str, name: str) -> Session: ...
    async def delete_session(self, user: UserIdentity, sid: str) -> None: ...
    async def add_message(self, user: UserIdentity, sid: str, msg: Mapping[str, Any]) -> Message: ...
    async def update_message(self, user: UserIdentity, sid: str, mid: int, patch: Mapping[str, Any]) -> Message: ...
    async def delete_message(self, user: UserIdentity, sid: str, mid: int) -> None: ...
    async def delete_messages_after(self, user: UserIdentity, sid: str, mid: int) -> None: ...
    async def add_messages(self, user: UserIdentity, sid: str, messages: list[MessageInput]) -> list[Message]: ...
    async def get_session_attachments(self, user: UserIdentity, sid: str) -> list[Attachment]: ...
    async def add_attachment(self, user: UserIdentity, sid: str, att: Attachment, raw_size: int, max_total_bytes: int) -> Attachment: ...
    async def get_user_settings(self, user: UserIdentity) -> dict[str, str]: ...
    async def update_user_settings(self, user: UserIdentity, values: Mapping[str, str]) -> dict[str, str]: ...
    async def get_session_settings(self, user: UserIdentity, sid: str) -> dict[str, str]: ...
    async def update_session_settings(self, user: UserIdentity, sid: str, values: Mapping[str, str]) -> dict[str, str]: ...
    async def try_start_generating(self, user: UserIdentity, sid: str) -> str: ...
    async def set_generating(self, user: UserIdentity, sid: str, on: bool) -> None: ...
    async def clear_generating_if_idle(self, user: UserIdentity, sid: str, running: bool) -> None: ...
    async def load_chat_context(self, user: UserIdentity, sid: str) -> ChatContext | None: ...
    async def finalize_generation(self, user: UserIdentity, sid: str, messages: list[MessageInput], error: str | None) -> list[Message]: ...

    @staticmethod
    def now_ms() -> int: ...


class SqliteUserStore(UserStoreProtocol):
    """UserStoreProtocol ueber die verschluesselten per-user SQLite-Dateien."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def now_ms() -> int:
        return dbq.now_ms()

    def _run_sync(self, user: UserIdentity, fn: Callable[[sqlite3.Connection], T]) -> T:
        with self._db.user_db(user) as con:
            return fn(con)

    async def _run(self, user: UserIdentity, fn: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(self._run_sync, user, fn)

    # --- Sessions ---

    async def list_sessions(self, user: UserIdentity) -> list[Session]:
        return await self._run(user, lambda con: [_to_session(r) for r in dbq.q_list_sessions(con)])

    async def create_session(self, user: UserIdentity, name: str) -> Session:
        return await self._run(user, lambda con: _to_session(dbq.q_create_session(con, name)))

    async def get_session(self, user: UserIdentity, sid: str) -> Session | None:
        return await self._run(user, lambda con: (lambda r: _to_session(r) if r else None)(dbq.q_get_session(con, sid)))

    async def session_exists(self, user: UserIdentity, sid: str) -> bool:
        return await self._run(user, lambda con: dbq.q_get_session(con, sid) is not None)

    async def get_session_detail(self, user: UserIdentity, sid: str) -> tuple[Session, list[Message], dict[str, str]] | None:
        def _do(con: sqlite3.Connection) -> tuple[Session, list[Message], dict[str, str]] | None:
            row = dbq.q_get_session(con, sid)
            if not row:
                return None
            return (
                _to_session(row),
                [_to_message(r) for r in dbq.q_get_messages(con, sid)],
                dbq.q_get_session_settings(con, sid),
            )

        return await self._run(user, _do)

    async def rename_session(self, user: UserIdentity, sid: str, name: str) -> Session:
        """Umbenennen; leer/Whitespace-only behaelt den alten Namen."""

        def _do(con: sqlite3.Connection) -> Session:
            row = dbq.q_get_session(con, sid)
            if not row:
                raise SessionNotFound(sid)
            stripped = name.strip()
            if stripped:
                dbq.q_rename_session(con, sid, stripped)
                row = dbq.q_get_session(con, sid)
                if not row:
                    raise SessionNotFound(sid)
            return _to_session(row)

        return await self._run(user, _do)

    async def delete_session(self, user: UserIdentity, sid: str) -> None:
        def _do(con: sqlite3.Connection) -> None:
            if not dbq.q_get_session(con, sid):
                raise SessionNotFound(sid)
            dbq.q_delete_session(con, sid)

        await self._run(user, _do)

    # --- Messages ---

    async def add_message(self, user: UserIdentity, sid: str, msg: Mapping[str, Any]) -> Message:
        """Message anlegen; Session wird beim ersten User-Text auf den Text umbenannt."""

        def _do(con: sqlite3.Connection) -> Message:
            session = dbq.q_get_session(con, sid)
            if not session:
                raise SessionNotFound(sid)
            stored = dbq.q_add_message(con, sid, msg)
            new_name = default_name_for_first_user_text(str(msg.get("role") or ""), str(msg.get("type") or "message"), str(msg.get("text") or ""), session["name"])
            if new_name:
                dbq.q_rename_session(con, sid, new_name)
            return _to_message(stored)

        return await self._run(user, _do)

    def _check_session_and_message(self, con: sqlite3.Connection, sid: str, mid: int) -> None:
        if not dbq.q_get_session(con, sid):
            raise SessionNotFound(sid)
        msg = dbq.q_get_message(con, mid)
        if not msg or msg["session_id"] != sid:
            raise MessageNotFound(mid)

    async def update_message(self, user: UserIdentity, sid: str, mid: int, patch: Mapping[str, Any]) -> Message:
        def _do(con: sqlite3.Connection) -> Message:
            self._check_session_and_message(con, sid, mid)
            updated = dbq.q_update_message(con, mid, patch)
            if updated is None:
                raise MessageNotFound(mid)
            return _to_message(updated)

        return await self._run(user, _do)

    async def delete_message(self, user: UserIdentity, sid: str, mid: int) -> None:
        def _do(con: sqlite3.Connection) -> None:
            self._check_session_and_message(con, sid, mid)
            dbq.q_delete_message(con, mid)

        await self._run(user, _do)

    async def delete_messages_after(self, user: UserIdentity, sid: str, mid: int) -> None:
        def _do(con: sqlite3.Connection) -> None:
            self._check_session_and_message(con, sid, mid)
            dbq.q_delete_messages_after(con, sid, mid)

        await self._run(user, _do)

    async def add_messages(self, user: UserIdentity, sid: str, messages: list[MessageInput]) -> list[Message]:
        """Mehrere Messages in einem DB-Oeffnen anlegen (Generierungs-Bloecke), Reihenfolge bleibt erhalten."""

        def _do(con: sqlite3.Connection) -> list[Message]:
            return [_to_message(dbq.q_add_message(con, sid, m)) for m in messages]

        return await self._run(user, _do)

    # --- Attachments ---

    async def get_session_attachments(self, user: UserIdentity, sid: str) -> list[Attachment]:
        return await self._run(user, lambda con: [_to_attachment(r) for r in dbq.q_get_session_attachments(con, sid)])

    async def add_attachment(
        self,
        user: UserIdentity,
        sid: str,
        att: Attachment,
        raw_size: int,
        max_total_bytes: int,
    ) -> Attachment:
        def _do(con: sqlite3.Connection) -> Attachment:
            if not dbq.q_get_session(con, sid):
                raise SessionNotFound(sid)
            if dbq.q_total_attachment_bytes(con) + raw_size > max_total_bytes:
                raise AttachmentQuotaExceeded(max_total_bytes)
            return _to_attachment(dbq.q_add_attachment(con, sid, att.model_dump()))

        return await self._run(user, _do)

    # --- User Settings ---

    async def get_user_settings(self, user: UserIdentity) -> dict[str, str]:
        return await self._run(user, dbq.q_get_user_settings)

    async def update_user_settings(self, user: UserIdentity, values: Mapping[str, str]) -> dict[str, str]:
        def _do(con: sqlite3.Connection) -> dict[str, str]:
            for key, value in values.items():
                dbq.q_set_user_setting(con, key, value)
            return dbq.q_get_user_settings(con)

        return await self._run(user, _do)

    # --- Session Settings ---

    async def get_session_settings(self, user: UserIdentity, sid: str) -> dict[str, str]:
        def _do(con: sqlite3.Connection) -> dict[str, str]:
            if not dbq.q_get_session(con, sid):
                raise SessionNotFound(sid)
            return dbq.q_get_session_settings(con, sid)

        return await self._run(user, _do)

    async def update_session_settings(self, user: UserIdentity, sid: str, values: Mapping[str, str]) -> dict[str, str]:
        def _do(con: sqlite3.Connection) -> dict[str, str]:
            if not dbq.q_get_session(con, sid):
                raise SessionNotFound(sid)
            for key, value in values.items():
                dbq.q_set_session_setting(con, sid, key, value)
            return dbq.q_get_session_settings(con, sid)

        return await self._run(user, _do)

    # --- Generierungs-Status ---

    async def try_start_generating(self, user: UserIdentity, sid: str) -> str:
        """Atomares Check-and-Set: 'ok' | 'busy' | 'missing'."""
        return await self._run(user, lambda con: dbq.q_try_start_generating(con, sid))

    async def set_generating(self, user: UserIdentity, sid: str, on: bool) -> None:
        await self._run(user, lambda con: dbq.q_set_generating(con, sid, on))

    async def clear_generating_if_idle(self, user: UserIdentity, sid: str, running: bool) -> None:
        """Verwaistes generating-Flag (z. B. nach Server-Neustart) zuruecksetzen, wenn keine Task laeuft."""

        def _do(con: sqlite3.Connection) -> None:
            if dbq.q_get_session(con, sid) and not running:
                dbq.q_set_generating(con, sid, False)

        await self._run(user, _do)

    async def load_chat_context(self, user: UserIdentity, sid: str) -> ChatContext | None:
        """Session + User-Settings + Session-Settings + Attachments + Messages in einem DB-Oeffnen laden."""

        def _do(con: sqlite3.Connection) -> ChatContext | None:
            row = dbq.q_get_session(con, sid)
            if not row:
                return None
            return ChatContext(
                session=_to_session(row),
                user_settings=dbq.q_get_user_settings(con),
                session_settings=dbq.q_get_session_settings(con, sid),
                attachments={a["id"]: _to_attachment(a) for a in dbq.q_get_session_attachments(con, sid)},
                messages=[_to_message(r) for r in dbq.q_get_messages(con, sid)],
            )

        return await self._run(user, _do)

    async def finalize_generation(
        self, user: UserIdentity, sid: str, messages: list[MessageInput], error: str | None
    ) -> list[Message]:
        """Finaler Flush am Stream-Ende: Messages persistieren, Fehler als System-Message, generating=0.
        Rueckgabe: die neu persistierten Messages (inkl. Fehler-Message)."""

        def _do(con: sqlite3.Connection) -> list[Message]:
            added = [_to_message(dbq.q_add_message(con, sid, m)) for m in messages]
            if error:
                added.append(_to_message(dbq.q_add_message(con, sid, error_message_input(error))))
            dbq.q_set_generating(con, sid, False)
            return added

        return await self._run(user, _do)

