from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

ClientFactory = Callable[..., httpx.AsyncClient]


def filter_request_messages(messages: list[dict[str, Any]], show_system_prompt: bool) -> list[dict[str, Any]]:
    """Serverseitiges Filtern des Requests: System-Prompt nur mitsenden, wenn aktiviert."""
    if show_system_prompt:
        return messages
    return [m for m in messages if m.get("role") != "system"]


def _filter_sse_data(data: str, show_reasoning: bool, show_tool_output: bool) -> str:
    if data == "[DONE]":
        return data
    try:
        event = json.loads(data)
    except json.JSONDecodeError:
        return data
    choices = event.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        delta = choices[0].get("delta")
        if isinstance(delta, dict):
            if not show_reasoning:
                delta.pop("reasoning_content", None)
                delta.pop("reasoning", None)
            if not show_tool_output:
                delta.pop("tool_calls", None)
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


async def check_llm_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    """Prueft die Erreichbarkeit des LLM-Servers (GET {base}/models)."""
    url = base_url.rstrip("/") + "/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
        return False, f"LLM-Server nicht erreichbar ({url})"
    if res.status_code >= 400:
        return False, f"{url} -> HTTP {res.status_code}"
    return True, f"{url} -> HTTP {res.status_code}"


async def stream_completion(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    settings: dict[str, bool] | None = None,
    client_factory: ClientFactory | None = None,
) -> AsyncIterator[str]:
    """Leitet einen Chat-Completions-Request als SSE-Stream weiter.

    ``settings`` steuert das serverseitige Filtern: ``show_system_prompt``
    filtert den Request, ``show_reasoning``/``show_tool_output`` den Response-Stream.
    """
    flags = settings or {}
    show_system_prompt = flags.get("show_system_prompt", True)
    show_reasoning = flags.get("show_reasoning", True)
    show_tool_output = flags.get("show_tool_output", True)

    payload = {**payload, "messages": filter_request_messages(payload.get("messages", []), show_system_prompt)}
    url = base_url.rstrip("/") + "/chat/completions"
    #print("Chat completion url: ", url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    # Check if LLM server is reachable
    factory = client_factory or httpx.AsyncClient
    async with factory(timeout=DEFAULT_TIMEOUT) as client:
        # Try to connect to the server with a HEAD request
        try:
            await client.head(base_url.rstrip("/"), timeout=5.0)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
            error = json.dumps({"error": f"LLM-Server nicht erreichbar ({base_url.rstrip('/')}). Bitte überprüfe die Server-URL und die Verbindung."})
            yield f"data: {error}\n\n"
            yield "data: [DONE]\n\n"
            return
        
        async with client.stream("POST", url, headers=headers, json=payload) as res:
            if res.status_code >= 400:
                body = (await res.aread()).decode("utf-8", errors="replace")[:300]
                error = json.dumps({"error": f"HTTP {res.status_code}: {body}"})
                yield f"data: {error}\n\n"
                yield "data: [DONE]\n\n"
                return
            raw = res.aiter_bytes()
            if show_reasoning and show_tool_output:
                async for chunk in raw:
                    yield chunk.decode("utf-8", errors="replace")
            else:
                async for line in sse_filter(raw, show_reasoning=show_reasoning, show_tool_output=show_tool_output):
                    yield line
