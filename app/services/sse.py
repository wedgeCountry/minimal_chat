"""SSE-Parsing und -Filtern (einzige Stelle mit ``data:``-Logik, siehe AGENTS.md Regel 4).

``parse_sse_data``/``parse_sse_buffer`` sind die Parse-Primitive, ``SseParser``
hält den Pufferzustand beim Streamen, ``sse_filter`` filtert den LLM-Stream
anhand der User-Settings.
"""

from __future__ import annotations

import json
from typing import AsyncIterator


def parse_sse_data(data: str) -> dict | None:
    """Parst einen einzelnen SSE-data-Payload; ``[DONE]`` und ungueltiges JSON -> None."""
    if data == "[DONE]":
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def parse_sse_buffer(buf: str) -> tuple[list[dict], str]:
    """Zerlegt einen SSE-Puffer in vollstaendige Events und den unvollstaendigen Rest."""
    events: list[dict] = []
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

    def feed(self, chunk: str) -> list[dict]:
        self._buf += chunk
        events, self._buf = parse_sse_buffer(self._buf)
        return events


def _filter_delta(delta: dict, show_reasoning: bool, show_tool_output: bool) -> None:
    if not show_reasoning:
        delta.pop("reasoning_content", None)
        delta.pop("reasoning", None)
        delta.pop("thinking", None)
    if not show_tool_output:
        delta.pop("tool_calls", None)
        delta.pop("tool_results", None)
        delta.pop("tool_result", None)


def _filter_sse_data(data: str, show_reasoning: bool, show_tool_output: bool) -> str:
    if data == "[DONE]":
        return data
    event = parse_sse_data(data)
    if event is None:
        return data
    choices = event.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        delta = choices[0].get("delta")
        if isinstance(delta, dict):
            _filter_delta(delta, show_reasoning, show_tool_output)
    return json.dumps(event, separators=(",", ":"))


def _filter_sse_line(line: str, show_reasoning: bool, show_tool_output: bool) -> str:
    t = line.strip()
    if t.startswith("data:"):
        data = t[len("data:"):].strip()
        return "data: " + _filter_sse_data(data, show_reasoning, show_tool_output) + "\n"
    return line + "\n"


async def sse_filter(
    chunks: AsyncIterator[bytes],
    *,
    show_reasoning: bool = True,
    show_tool_output: bool = True,
) -> AsyncIterator[str]:
    """Serverseitiges Filtern des LLM-SSE-Streams anhand der User-Settings."""
    buf = ""
    async for chunk in chunks:
        buf += chunk.decode("utf-8", errors="replace")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            yield _filter_sse_line(line, show_reasoning, show_tool_output)
    if buf:
        yield _filter_sse_line(buf, show_reasoning, show_tool_output)
