"""LLM-Kontext (Chat-History) aus den Session-Nachrichten aufbauen.

Nutzt ``trixie_ai.context.LlmContext`` (vendored Wheel): System-Prompt zuerst,
dann die Nachrichten in Reihenfolge. Toolcalls werden als ``assistant``-Message
mit ``tool_calls`` uebersetzt, Tool-Ergebnisse als gepaarte ``tool``-Message -
damit kann das Modell Tool-Calls von normalem Text unterscheiden.
"""

from __future__ import annotations

import json
from typing import Any

from trixie_ai.context import LlmContext

from .files import expand_attachment_parts


def _parse_toolcall(text: str) -> dict[str, str]:
    """Text einer Toolcall-Message -> {"name", "arguments"} (JSON oder ``name(args)``)."""
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("name"):
            args = data.get("arguments")
            if isinstance(args, (dict, list)):
                args = json.dumps(args)
            return {"name": str(data["name"]), "arguments": str(args or "{}")}
    except (json.JSONDecodeError, TypeError):
        pass
    t = (text or "").strip()
    if "(" in t and t.endswith(")"):
        name, args = t.split("(", 1)
        return {"name": name.strip() or "tool", "arguments": args[:-1].strip() or "{}"}
    return {"name": t or "tool", "arguments": "{}"}


def build_llm_context(
    messages: list[dict[str, Any]],
    *,
    system_prompt: str = "",
    attachments_by_id: dict[int, dict] | None = None,
) -> LlmContext:
    """Session-Nachrichten (DB-Format) -> LlmContext; ``compile()`` liefert die Wire-Messages."""
    ctx = LlmContext()
    if system_prompt:
        ctx.add_system_prompt(system_prompt)
    pending_tool_call_ids: list[str] = []
    wire: list[dict[str, Any]] = []
    for m in messages or []:
        if m.get("in_context") is False:
            continue
        role = m.get("role", "user")
        mtype = m.get("type", "message")
        text = m.get("text") or ""
        mid = m.get("id")
        if mtype == "toolcall":
            fn = _parse_toolcall(text)
            tid = f"call_{mid}" if mid is not None else f"call_{len(pending_tool_call_ids)}"
            pending_tool_call_ids.append(tid)
            wire.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": tid, "type": "function", "function": {"name": fn["name"], "arguments": fn["arguments"]}}],
            })
        elif mtype == "toolresult":
            tid = pending_tool_call_ids.pop(0) if pending_tool_call_ids else (f"call_{mid}" if mid is not None else "call_0")
            wire.append({"role": "tool", "tool_call_id": tid, "content": text})
        elif mtype == "reasoning":
            continue  # Thinking wird nicht an das Modell gesendet
        else:
            # leere System-Nachricht nicht an das LLM senden (sonst 422) und nie anzeigen
            if role == "system" and not text.strip():
                continue
            content: Any = text
            atts = m.get("attachments") or []
            if atts:
                content = [{"type": "text", "text": f"[Datei: {a.get('name', 'datei')}]", "attachment_id": a.get("id")} for a in atts]
                if text:
                    content.append({"type": "text", "text": text})
            wire.append({"role": role, "content": content})
    ctx.messages.extend(expand_attachment_parts(wire, attachments_by_id or {}))
    return ctx
