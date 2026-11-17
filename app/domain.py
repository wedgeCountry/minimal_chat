"""Kanonische Domain-Models: eine einzige Quelle fuer Message/Session/Attachment,
genutzt von Service-Memory (app/services/chat.py), SSE-Events, API-Responses
(app/models.py) und der Row-Mapping-Schicht des UserStore (app/services/store.py).

`id=None` kennzeichnet eine Live-Message, die noch nicht persistiert ist (ts=0 =
offener Stream-Block); persistierte Messages haben immer id und ts (ms).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AttachmentRef(BaseModel):
    """Referenz auf einen serverseitig gespeicherten Anhang (POST /api/sessions/{id}/attachments)."""

    # extra="allow": der Client schickt z. B. noch "type" (MIME) mit; wird 1:1 durchgereicht
    model_config = ConfigDict(extra="allow")

    id: int
    name: str = ""


MessageType = Literal["message", "toolcall", "reasoning", "toolresult"]
MessageRole = Literal["user", "assistant", "system"]


class Message(BaseModel):
    id: int | None = None  # None = Live-Message (noch nicht persistiert)
    role: MessageRole
    type: MessageType = "message"
    text: str = ""
    in_context: bool = True
    attachments: list[AttachmentRef] = Field(default_factory=list)
    ts: int = 0  # ms seit Epoch (created_at); 0 = offener Stream-Block


class Session(BaseModel):
    id: str
    name: str
    ts: int
    generating: bool = False


class Attachment(BaseModel):
    """Serverseitig aufbereiteter Anhang (process_upload / DB-Zeile)."""

    id: int | None = None
    session_id: str = ""
    name: str
    mime: str
    kind: str
    size: int
    content: str = ""
