from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=1024)


class LoginRequest(BaseModel):
    email: str
    password: str


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


class SessionIn(BaseModel):
    name: str = "Neue Session"


class SessionRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SessionOut(BaseModel):
    id: str
    name: str
    ts: int


class SessionDetail(SessionOut):
    messages: list[MessageOut]


class SettingsIn(BaseModel):
    base: str | None = None
    model: str | None = None
    theme: Literal["light", "dark"] | None = None
    api_key: str | None = None
    bubbles_deletable: bool | None = None
    bubbles_user_checkable: bool | None = None
    bubbles_user_deletable: bool | None = None
    show_system_prompt: bool | None = None
    show_tool_output: bool | None = None
    show_reasoning: bool | None = None


class SettingsOut(BaseModel):
    base: str
    model: str
    theme: str
    bubbles_deletable: bool = True
    bubbles_user_checkable: bool = True
    bubbles_user_deletable: bool = True
    show_system_prompt: bool = True
    show_tool_output: bool = True
    show_reasoning: bool = True


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatRequest(BaseModel):
    model: str
    stream: bool = True
    messages: list[ChatMessage]
