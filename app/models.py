from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

class MessageIn(BaseModel):
    role: Literal["user", "assistant", "system"]
    type: Literal["message", "toolcall", "reasoning"] = "message"
    text: str = ""
    in_context: bool = True
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class MessageOut(MessageIn):
    id: int


class MessagePatch(BaseModel):
    in_context: bool | None = None
    text: str | None = None
    attachments: list[dict[str, Any]] | None = None


class SessionIn(BaseModel):
    name: str = "Neue Session"


class SessionRename(BaseModel):
    # Leer/Whitespace-only ist erlaubt: der Router behaelt dann den alten Namen.
    name: str = Field(max_length=120)


class SessionOut(BaseModel):
    id: str
    name: str
    ts: int
    generating: bool = False


class SessionDetail(SessionOut):
    messages: list[MessageOut]


class SettingsIn(BaseModel):
    base: str | None = None
    host: str | None = None
    port: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    theme: Literal["light", "dark"] | None = None
    api_key: str | None = None
    bubbles_deletable: bool | None = None
    bubbles_checkable: bool | None = None
    bubbles_speaker: bool | None = None
    show_system_prompt: bool | None = None
    show_tool_output: bool | None = None
    show_reasoning: bool | None = None
    show_file_button: bool | None = None
    show_image_button: bool | None = None


class SettingsOut(BaseModel):
    base: str
    host: str = ""
    port: str = ""
    model: str
    system_prompt: str = ""
    theme: str
    bubbles_deletable: bool = False
    bubbles_checkable: bool = False
    bubbles_speaker: bool = False
    show_system_prompt: bool = True
    show_tool_output: bool = True
    show_reasoning: bool = True
    show_file_button: bool = False
    show_image_button: bool = False


class AttachmentOut(BaseModel):
    id: int
    name: str
    mime: str
    kind: str
    size: int


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatRequest(BaseModel):
    session_id: str
    model: str
    stream: bool = True
    messages: list[ChatMessage]


class ChatAbortRequest(BaseModel):
    session_id: str


class ClientLogIn(BaseModel):
    level: Literal["error", "warning", "info"] = "error"
    message: str = Field(max_length=4000)


class SettingsTestIn(BaseModel):
    base: str | None = None
    api_key: str | None = None


class VoiceTTSRequest(BaseModel):
    text: str
    voice: str | None = None
    language: Literal["en", "de"] | None = None
