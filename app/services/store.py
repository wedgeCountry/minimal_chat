"""Persistenz-Gateway (Repository): einzige Schicht zwischen App-Code (Router,
Generierungs-Task) und der Datenbank.

``UserStore`` kapselt ``Database.user_db`` + die ``q_*``-Helper + ``asyncio.to_thread``:
Aufrufer arbeiten asynchron mit fachlichen Methoden und bekommen Zeilen-Typen
(``SessionRow``/``MessageRow``/...) statt einer ``sqlite3.Connection``. Verschluesselung,
Datei-Layout, Schema-Migrationen und Locks bleiben in ``app/db/database.py``; direkter
Zugriff auf ``Database``/``q_*`` ist nur noch dieser Schicht und den DB-Unit-Tests vorbehalten
(AGENTS.md Regel 1). Jede Methode oeffnet die per-user DB genau einmal (ein Schreibzugriff
= ein Entschluesseln/Verschluesseln) und fuehrt blockierenden Code nie auf dem Event-Loop aus.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from ..db import database as dbq
from ..db.database import Database
from ..types import AttachmentContent, AttachmentRow, MessageInput, MessageRow, SessionRow, UserIdentity

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


class UserStore:
    """Asynchroner, fachlicher Zugriff auf die Daten eines Users."""

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

    async def list_sessions(self, user: UserIdentity) -> list[SessionRow]:
        return await self._run(user, dbq.q_list_sessions)

    async def create_session(self, user: UserIdentity, name: str) -> SessionRow:
        return await self._run(user, lambda con: dbq.q_create_session(con, name))

    async def get_session(self, user: UserIdentity, sid: str) -> SessionRow | None:
        return await self._run(user, lambda con: dbq.q_get_session(con, sid))

    async def session_exists(self, user: UserIdentity, sid: str) -> bool:
        return await self._run(user, lambda con: dbq.q_get_session(con, sid) is not None)

    async def get_session_detail(self, user: UserIdentity, sid: str) -> tuple[SessionRow, list[MessageRow]] | None:
        def _do(con: sqlite3.Connection) -> tuple[SessionRow, list[MessageRow]] | None:
            session = dbq.q_get_session(con, sid)
            if not session:
                return None
            return session, dbq.q_get_messages(con, sid)

        return await self._run(user, _do)

    async def rename_session(self, user: UserIdentity, sid: str, name: str) -> SessionRow:
        """Umbenennen; leer/Whitespace-only behaelt den alten Namen."""

        def _do(con: sqlite3.Connection) -> SessionRow:
            session = dbq.q_get_session(con, sid)
            if not session:
                raise SessionNotFound(sid)
            stripped = name.strip()
            if stripped:
                dbq.q_rename_session(con, sid, stripped)
                session = dbq.q_get_session(con, sid)
                if not session:
                    raise SessionNotFound(sid)
            return session

        return await self._run(user, _do)

    async def delete_session(self, user: UserIdentity, sid: str) -> None:
        def _do(con: sqlite3.Connection) -> None:
            if not dbq.q_get_session(con, sid):
                raise SessionNotFound(sid)
            dbq.q_delete_session(con, sid)

        await self._run(user, _do)

    # --- Messages ---

    async def add_message(self, user: UserIdentity, sid: str, msg: Mapping[str, Any]) -> MessageRow:
        """Message anlegen; Session wird beim ersten User-Text auf den Text umbenannt."""

        def _do(con: sqlite3.Connection) -> MessageRow:
            session = dbq.q_get_session(con, sid)
            if not session:
                raise SessionNotFound(sid)
            stored = dbq.q_add_message(con, sid, msg)
            text = str(msg.get("text") or "").strip()
            if msg.get("role") == "user" and msg.get("type", "message") == "message" and text and session["name"] == DEFAULT_SESSION_NAME:
                dbq.q_rename_session(con, sid, text[:40])
            return stored

        return await self._run(user, _do)

    def _check_session_and_message(self, con: sqlite3.Connection, sid: str, mid: int) -> None:
        if not dbq.q_get_session(con, sid):
            raise SessionNotFound(sid)
        msg = dbq.q_get_message(con, mid)
        if not msg or msg["session_id"] != sid:
            raise MessageNotFound(mid)

    async def update_message(self, user: UserIdentity, sid: str, mid: int, patch: Mapping[str, Any]) -> MessageRow:
        def _do(con: sqlite3.Connection) -> MessageRow:
            self._check_session_and_message(con, sid, mid)
            updated = dbq.q_update_message(con, mid, patch)
            if updated is None:
                raise MessageNotFound(mid)
            return updated

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

    async def add_messages(self, user: UserIdentity, sid: str, messages: list[MessageInput]) -> list[MessageRow]:
        """Mehrere Messages in einem DB-Oeffnen anlegen (Generierungs-Bloecke), Reihenfolge bleibt erhalten."""

        def _do(con: sqlite3.Connection) -> list[MessageRow]:
            return [dbq.q_add_message(con, sid, m) for m in messages]

        return await self._run(user, _do)

    # --- Attachments ---

    async def get_session_attachments(self, user: UserIdentity, sid: str) -> list[AttachmentRow]:
        return await self._run(user, lambda con: dbq.q_get_session_attachments(con, sid))

    async def add_attachment(
        self,
        user: UserIdentity,
        sid: str,
        att: AttachmentContent,
        raw_size: int,
        max_total_bytes: int,
    ) -> AttachmentRow:
        def _do(con: sqlite3.Connection) -> AttachmentRow:
            if not dbq.q_get_session(con, sid):
                raise SessionNotFound(sid)
            if dbq.q_total_attachment_bytes(con) + raw_size > max_total_bytes:
                raise AttachmentQuotaExceeded(max_total_bytes)
            return dbq.q_add_attachment(con, sid, att)

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

    async def load_chat_context(
        self, user: UserIdentity, sid: str
    ) -> tuple[SessionRow, dict[str, str], dict[int, AttachmentRow], list[MessageRow]] | None:
        """Session + Settings + Attachments + Messages in einem DB-Oeffnen laden."""

        def _do(con: sqlite3.Connection) -> tuple[SessionRow, dict[str, str], dict[int, AttachmentRow], list[MessageRow]] | None:
            session = dbq.q_get_session(con, sid)
            if not session:
                return None
            stored = dbq.q_get_user_settings(con)
            attachments = {a["id"]: a for a in dbq.q_get_session_attachments(con, sid)}
            messages = dbq.q_get_messages(con, sid)
            return session, stored, attachments, messages

        return await self._run(user, _do)

    async def finalize_generation(self, user: UserIdentity, sid: str, messages: list[MessageInput], error: str | None) -> None:
        """Finaler Flush am Stream-Ende: Messages persistieren, Fehler als System-Message, generating=0."""

        def _do(con: sqlite3.Connection) -> None:
            for m in messages:
                dbq.q_add_message(con, sid, m)
            if error:
                dbq.q_add_message(con, sid, {"role": "system", "type": "message", "text": "Fehler: " + error, "in_context": False})
            dbq.q_set_generating(con, sid, False)

        await self._run(user, _do)
