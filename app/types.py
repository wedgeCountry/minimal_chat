"""Getypte interne Datenstrukturen (DB-Zeilen, User-Identitaet, Message-Input).

Als TypedDicts, damit der bestehende dict-Zugriff (``user["uid"]``) erhalten bleibt
und mypy Schluessel und Typen prueft. Die Grenz-Models (API-Requests/Responses in
app/models.py, AppConfig in app/config.py) sind Pydantic-Models mit Validierung.
"""

from __future__ import annotations

from typing import Any, TypedDict


class UserIdentity(TypedDict):
    """Aus Server-Secret + E-Mail abgeleitete lokale User-Identitaet (app/auth.py:user_identity)."""

    uid: str
    email: str
    username: str
    key: str
    legacy_key: str


class SessionRow(TypedDict):
    """Eine Zeile aus ``sessions`` (DB-Format)."""

    id: str
    name: str
    ts: int
    generating: bool


class MessageRow(TypedDict):
    """Eine Zeile aus ``messages`` (DB-Format, inkl. session_id; ts = created_at in ms)."""

    id: int
    session_id: str
    role: str
    type: str
    text: str
    in_context: bool
    attachments: list[dict[str, Any]]
    ts: int


class _MessageInputBase(TypedDict):
    role: str


class MessageInput(_MessageInputBase, total=False):
    """Neue Message fuer q_add_message (``role`` ist Pflicht, der Rest optional)."""

    type: str
    text: str
    in_context: bool
    attachments: list[dict[str, Any]]
    created_at: int


class SessionSettingRow(TypedDict):
    """Eine Zeile aus ``session_settings`` (DB-Format)."""

    session_id: str
    key: str
    value: str


class AttachmentRow(TypedDict):
    """Eine Zeile aus ``attachments`` (DB-Format)."""

    id: int
    session_id: str
    name: str
    mime: str
    kind: str
    size: int
    content: str

