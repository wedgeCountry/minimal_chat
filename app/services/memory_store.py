"""In-Memory-Implementierung von ``UserStoreProtocol`` fuer Unit-Tests des Service-Layers
(ohne SQLite/Verschluesselung). Gleiche fachliche Semantik wie ``SqliteUserStore``:
gleiche Exceptions, gleiches try_start_generating-Protokoll ('ok' | 'busy' | 'missing').
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from ..domain import Attachment, Message, Session
from ..types import MessageInput, UserIdentity
from .store import (
    DEFAULT_SESSION_NAME,
    AttachmentQuotaExceeded,
    MessageNotFound,
    SessionNotFound,
    UserStoreProtocol,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


class InMemoryUserStore(UserStoreProtocol):
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Session]] = {}  # uid -> sid -> Session
        self._messages: dict[str, dict[str, list[Message]]] = {}  # uid -> sid -> [Message]
        self._attachments: dict[str, dict[str, list[Attachment]]] = {}
        self._settings: dict[str, dict[str, str]] = {}
        self._next_mid: dict[str, int] = {}
        self._next_aid: dict[str, int] = {}

    @staticmethod
    def now_ms() -> int:
        return _now_ms()

    def _uid(self, user: UserIdentity) -> str:
        return user["uid"]

    def _sess(self, user: UserIdentity, sid: str) -> Session:
        row = self._sessions.setdefault(self._uid(user), {}).get(sid)
        if row is None:
            raise SessionNotFound(sid)
        return row

    def _msgs(self, user: UserIdentity, sid: str) -> list[Message]:
        self._sess(user, sid)
        return self._messages.setdefault(self._uid(user), {}).setdefault(sid, [])

    # --- Sessions ---

    async def list_sessions(self, user: UserIdentity) -> list[Session]:
        rows = sorted(self._sessions.get(self._uid(user), {}).values(), key=lambda s: s.ts, reverse=True)
        return [r.model_copy() for r in rows]

    async def create_session(self, user: UserIdentity, name: str) -> Session:
        sid = f"mem-{len(self._sessions.setdefault(self._uid(user), {})) + 1}-{ _now_ms()}"
        row = Session(id=sid, name=name, ts=_now_ms())
        uid = self._uid(user)
        self._sessions.setdefault(uid, {})[sid] = row
        self._messages.setdefault(uid, {})[sid] = []
        self._attachments.setdefault(uid, {})[sid] = []
        return row.model_copy()

    async def get_session(self, user: UserIdentity, sid: str) -> Session | None:
        row = self._sessions.get(self._uid(user), {}).get(sid)
        return row.model_copy() if row else None

    async def session_exists(self, user: UserIdentity, sid: str) -> bool:
        return sid in self._sessions.get(self._uid(user), {})

    async def get_session_detail(self, user: UserIdentity, sid: str) -> tuple[Session, list[Message]] | None:
        row = await self.get_session(user, sid)
        if row is None:
            return None
        return row, [m.model_copy() for m in self._msgs(user, sid)]

    async def rename_session(self, user: UserIdentity, sid: str, name: str) -> Session:
        row = self._sess(user, sid)
        stripped = name.strip()
        if stripped:
            row.name = stripped
        return row.model_copy()

    async def delete_session(self, user: UserIdentity, sid: str) -> None:
        self._sess(user, sid)
        del self._sessions[self._uid(user)][sid]
        self._messages.get(self._uid(user), {}).pop(sid, None)
        self._attachments.get(self._uid(user), {}).pop(sid, None)

    # --- Messages ---

    async def add_message(self, user: UserIdentity, sid: str, msg: Mapping[str, Any]) -> Message:
        row = self._sess(user, sid)
        uid = self._uid(user)
        mid = self._next_mid.get(uid, 0) + 1
        self._next_mid[uid] = mid
        from ..domain import AttachmentRef

        m = Message(
            id=mid,
            role=msg["role"],
            type=msg.get("type", "message"),
            text=str(msg.get("text", "")),
            in_context=bool(msg.get("in_context", True)),
            attachments=[AttachmentRef.model_validate(a) for a in msg.get("attachments", [])],
            ts=int(msg.get("created_at") or _now_ms()),
        )
        self._msgs(user, sid).append(m)
        text = m.text.strip()
        if m.role == "user" and m.type == "message" and text and row.name == DEFAULT_SESSION_NAME:
            row.name = text[:40]
        row.ts = _now_ms()
        return m.model_copy()

    async def update_message(self, user: UserIdentity, sid: str, mid: int, patch: Mapping[str, Any]) -> Message:
        msgs = self._msgs(user, sid)
        m = next((x for x in msgs if x.id == mid), None)
        if m is None:
            raise MessageNotFound(mid)
        if patch.get("in_context") is not None:
            m.in_context = bool(patch["in_context"])
        if patch.get("text") is not None:
            m.text = str(patch["text"])
        if patch.get("attachments") is not None:
            from ..domain import AttachmentRef

            m.attachments = [AttachmentRef.model_validate(a) for a in patch["attachments"]]
        if patch.get("created_at") is not None:
            m.ts = int(patch["created_at"])
        return m.model_copy()

    async def delete_message(self, user: UserIdentity, sid: str, mid: int) -> None:
        msgs = self._msgs(user, sid)
        if not any(x.id == mid for x in msgs):
            raise MessageNotFound(mid)
        msgs[:] = [x for x in msgs if x.id != mid]

    async def delete_messages_after(self, user: UserIdentity, sid: str, mid: int) -> None:
        msgs = self._msgs(user, sid)
        if not any(x.id == mid for x in msgs):
            raise MessageNotFound(mid)
        msgs[:] = [x for x in msgs if x.id is not None and x.id <= mid]

    async def add_messages(self, user: UserIdentity, sid: str, messages: list[MessageInput]) -> list[Message]:
        out = []
        for msg in messages:
            out.append(await self.add_message(user, sid, msg))
        return out

    # --- Attachments ---

    async def get_session_attachments(self, user: UserIdentity, sid: str) -> list[Attachment]:
        self._sess(user, sid)
        return [a.model_copy() for a in self._attachments.setdefault(self._uid(user), {}).setdefault(sid, [])]

    async def add_attachment(
        self, user: UserIdentity, sid: str, att: Attachment, raw_size: int, max_total_bytes: int
    ) -> Attachment:
        self._sess(user, sid)
        uid = self._uid(user)
        atts = self._attachments[uid].setdefault(sid, [])
        if sum(a.size for a in atts) + raw_size > max_total_bytes:
            raise AttachmentQuotaExceeded(max_total_bytes)
        aid = self._next_aid.get(uid, 0) + 1
        self._next_aid[uid] = aid
        stored = att.model_copy(update={"id": aid, "session_id": sid})
        atts.append(stored)
        return stored.model_copy()

    # --- Settings ---

    async def get_user_settings(self, user: UserIdentity) -> dict[str, str]:
        return dict(self._settings.setdefault(self._uid(user), {}))

    async def update_user_settings(self, user: UserIdentity, values: Mapping[str, str]) -> dict[str, str]:
        stored = self._settings.setdefault(self._uid(user), {})
        stored.update(values)
        return dict(stored)

    # --- Generierungs-Status ---

    async def try_start_generating(self, user: UserIdentity, sid: str) -> str:
        row = self._sessions.get(self._uid(user), {}).get(sid)
        if row is None:
            return "missing"
        if row.generating:
            return "busy"
        row.generating = True
        return "ok"

    async def set_generating(self, user: UserIdentity, sid: str, on: bool) -> None:
        self._sess(user, sid).generating = on

    async def clear_generating_if_idle(self, user: UserIdentity, sid: str, running: bool) -> None:
        if sid in self._sessions.get(self._uid(user), {}) and not running:
            self._sessions[self._uid(user)][sid].generating = False

    async def load_chat_context(
        self, user: UserIdentity, sid: str
    ) -> tuple[Session, dict[str, str], dict[int, Attachment], list[Message]] | None:
        detail = await self.get_session_detail(user, sid)
        if detail is None:
            return None
        session, messages = detail
        atts = await self.get_session_attachments(user, sid)
        settings = await self.get_user_settings(user)
        return session, settings, {a.id: a for a in atts if a.id is not None}, messages

    async def finalize_generation(
        self, user: UserIdentity, sid: str, messages: list[MessageInput], error: str | None
    ) -> list[Message]:
        added = await self.add_messages(user, sid, messages)
        if error:
            added.append(
                await self.add_message(user, sid, {"role": "system", "type": "message", "text": "Fehler: " + error, "in_context": False})
            )
        await self.set_generating(user, sid, False)
        return added
