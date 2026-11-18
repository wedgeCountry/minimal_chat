"""SSE-Parsing und -Serialisierung (einzige Stelle mit ``data:``-Logik, siehe AGENTS.md Regel 4).

``parse_sse_data``/``parse_sse_buffer`` sind die Parse-Primitive, ``SseParser``
hält den Pufferzustand beim Streamen, ``sse_event`` serialisiert ausgehende Events.
Der LLM-Stream wird bewusst nicht gefiltert (Anzeige-Settings wirken clientseitig),
damit alle Blöcke persistiert werden.
"""

from __future__ import annotations

import json
from typing import Any


def sse_event(payload: dict[str, Any]) -> str:
    """Ein SSE-Event serialisieren (einzige Stelle, die das ausgehende ``data:``-Wire-Format baut)."""
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def parse_sse_data(data: str) -> dict[str, Any] | None:
    """Parst einen einzelnen SSE-data-Payload; ``[DONE]`` und ungueltiges JSON -> None."""
    if data == "[DONE]":
        return None
    try:
        event: dict[str, Any] = json.loads(data)
        return event
    except json.JSONDecodeError:
        return None


def parse_sse_buffer(buf: str) -> tuple[list[dict[str, Any]], str]:
    """Zerlegt einen SSE-Puffer in vollstaendige Events und den unvollstaendigen Rest."""
    events: list[dict[str, Any]] = []
    lines = buf.split("\n")
    rest = lines.pop()
    for line in lines:
        t = line.strip()
        if not t.startswith("data:"):
            continue
        event = parse_sse_data(t[len("data:"):].strip())
        if event is not None:
            events.append(event)
    return events, rest


class SseParser:
    """Statefuler SSE-Parser: ``feed`` nimmt Text-Chunks und liefert fertige Events."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> list[dict[str, Any]]:
        self._buf += chunk
        events, self._buf = parse_sse_buffer(self._buf)
        return events



