from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .domain import AttachmentRef, Message, Session

__all__ = ["AttachmentRef"]


class MessageIn(BaseModel):
    role: Literal["user", "assistant", "system"]
    type: Literal["message", "toolcall", "reasoning", "toolresult"] = "message"
    text: str = ""
    in_context: bool = True
    attachments: list[AttachmentRef] = Field(default_factory=list)


class MessageOut(Message):
    # persistierte Messages haben immer eine id
    id: int


class MessagePatch(BaseModel):
    in_context: bool | None = None
    text: str | None = None
    attachments: list[AttachmentRef] | None = None


class SessionIn(BaseModel):
    name: str = Field(default="Neue Session", max_length=120)


class SessionRename(BaseModel):
    # Leer/Whitespace-only ist erlaubt: der Router behaelt dann den alten Namen.
    name: str = Field(max_length=120)


class SessionOut(Session):
    pass


class SessionSettingsIn(BaseModel):
    system_prompt: str | None = Field(default=None, max_length=20000)
    # model_id als String (key/value-Speicher); leer = Standard-Tile des Users
    model_id: str | None = Field(default=None, max_length=20)


class SessionSettingsOut(BaseModel):
    session_id: str = ""
    system_prompt: str = ""
    # model_id als String (key/value-Speicher); leer = Standard-Tile des Users
    model_id: str = ""


class SessionDetail(SessionOut):
    messages: list[MessageOut]
    settings: SessionSettingsOut = Field(default_factory=SessionSettingsOut)


class VisitIn(BaseModel):
    """Serverseitig gemerkter Seitenaufruf (z. B. In-App-View "/#s/<id>" der SPA)."""

    path: str = Field(min_length=1, max_length=2048)


class SettingsIn(BaseModel):
    # default_model_id zeigt auf ein llm_models-Tile (String wie im key/value-Speicher)
    default_model_id: str | None = Field(default=None, max_length=20)
    system_prompt: str | None = None
    theme: Literal["light", "dark"] | None = None
    bubbles_deletable: bool | None = None
    bubbles_checkable: bool | None = None
    bubbles_speaker: bool | None = None
    bubbles_minimal: bool | None = None
    show_system_prompt: bool | None = None
    show_tool_output: bool | None = None
    show_reasoning: bool | None = None
    show_file_button: bool | None = None
    show_image_button: bool | None = None
    speech_mode: Literal["system", "server", "none"] | None = None


class SettingsOut(BaseModel):
    default_model_id: str = ""
    system_prompt: str = ""
    theme: str
    bubbles_deletable: bool = False
    bubbles_checkable: bool = False
    bubbles_speaker: bool = False
    bubbles_minimal: bool = True
    show_system_prompt: bool = True
    show_tool_output: bool = True
    show_reasoning: bool = True
    show_file_button: bool = False
    show_image_button: bool = False
    speech_mode: str = "server"


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
    session_id: str = Field(max_length=64)
    # Modell/Verbindung kommen serverseitig aus dem gewaehlten llm_models-Tile
    # (Session-model_id, sonst default_model_id, sonst Server-Defaults)
    stream: bool = True
    # veraltet: die Chat-History wird serverseitig aus der Session-DB gebaut (build_llm_context)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=500)


class ChatAbortRequest(BaseModel):
    session_id: str = Field(max_length=64)


class ClientLogIn(BaseModel):
    level: Literal["error", "warning", "info"] = "error"
    message: str = Field(max_length=4000)


class LlmModelIn(BaseModel):
    provider: str | None = Field(default=None, max_length=120)
    host: str | None = Field(default=None, max_length=255)
    port: str | None = Field(default=None, max_length=5)
    base: str | None = Field(default=None, max_length=500)
    # write-only wie frueher api_key in SettingsIn: nie in LlmModelOut; leerer String aendert nichts
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)


class LlmModelOut(BaseModel):
    id: int
    provider: str = ""
    host: str = ""
    port: str = ""
    base: str = ""
    model: str = ""


class LlmModelTestIn(BaseModel):
    # optionale Tile-Referenz: base/api_key/model aus dem Body gewinnen sonst gegen das Tile
    model_id: int | None = None
    base: str | None = None
    api_key: str | None = None
    model: str | None = Field(default=None, max_length=200)


class VoiceTTSRequest(BaseModel):
    text: str = Field(max_length=5000)
    voice: str | None = None
    language: Literal["en", "de"] | None = None
