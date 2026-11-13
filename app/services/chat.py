from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from typing import Any, AsyncIterator, Callable
from urllib.parse import urlparse

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

ClientFactory = Callable[..., httpx.AsyncClient]


def validate_llm_base_url(base_url: str, allow_private: bool = False) -> str:
    """SSRF-Vertrag fuer user-gesteuerte LLM-URLs: http/https ohne Credentials;
    ohne allow_private werden per DNS private/reservierte Ziel-IPs abgelehnt."""
    url = (base_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Ungueltige LLM-Base-URL (nur http/https mit Host erlaubt)")
    if parsed.username or parsed.password:
        raise ValueError("Credentials in der LLM-URL sind nicht erlaubt")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Ungueltiger Port in der LLM-Base-URL") from exc
    if not allow_private:
        try:
            infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise ValueError(f"LLM-Host nicht aufloesbar: {parsed.hostname}") from exc
        shared_range = ipaddress.ip_network("100.64.0.0/10")  # CGNAT: is_private ist hier False
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
                or ip in shared_range
            ):
                raise ValueError(
                    f"LLM-Ziel {ip} liegt in einem privaten/reservierten Netz und ist blockiert "
                    "(LEANCHAT_ALLOW_PRIVATE_LLM=1 erlaubt private Ziele)"
                )
    return url


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


def filter_request_messages(messages: list[dict[str, Any]], show_system_prompt: bool) -> list[dict[str, Any]]:
    """Serverseitiges Filtern des Requests: System-Prompt nur mitsenden, wenn aktiviert."""
    if show_system_prompt:
        return messages
    return [m for m in messages if m.get("role") != "system"]


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
            if not show_reasoning:
                delta.pop("reasoning_content", None)
                delta.pop("reasoning", None)
            if not show_tool_output:
                delta.pop("tool_calls", None)
                delta.pop("tool_results", None)
                delta.pop("tool_result", None)
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


async def _aiter_until_abort(chunks: AsyncIterator[bytes], abort: asyncio.Event | None) -> AsyncIterator[bytes]:
    """Liefert Chunks wie ``chunks``, endet aber sofort, sobald ``abort`` gesetzt ist.

    Der haengende Read wird gecancelt: ein Abort wirkt damit auch dann, wenn das
    LLM (noch) keine weiteren Chunks liefert.
    """
    if abort is None:
        async for chunk in chunks:
            yield chunk
        return
    it = chunks.__aiter__()
    while not abort.is_set():
        nxt = asyncio.ensure_future(it.__anext__())
        abort_wait = asyncio.ensure_future(abort.wait())
        done, _pending = await asyncio.wait({nxt, abort_wait}, return_when=asyncio.FIRST_COMPLETED)
        if abort_wait in done:
            nxt.cancel()
            await asyncio.gather(nxt, abort_wait, return_exceptions=True)
            return
        abort_wait.cancel()
        await asyncio.gather(abort_wait, return_exceptions=True)
        try:
            chunk = nxt.result()
        except StopAsyncIteration:
            return
        yield chunk


async def stream_completion(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    settings: dict[str, bool] | None = None,
    client_factory: ClientFactory | None = None,
    abort: asyncio.Event | None = None,
) -> AsyncIterator[str]:
    """Leitet einen Chat-Completions-Request als SSE-Stream weiter.

    ``settings`` steuert das serverseitige Filtern: ``show_system_prompt``
    filtert den Request, ``show_reasoning``/``show_tool_output`` den Response-Stream.
    ``abort`` wird gegen das Oeffnen der Response und jeden Chunk-Read geracet;
    beim Abort wird die Upstream-Verbindung sofort geschlossen.
    """
    flags = settings or {}
    show_system_prompt = flags.get("show_system_prompt", True)
    show_reasoning = flags.get("show_reasoning", True)
    show_tool_output = flags.get("show_tool_output", True)

    payload = {**payload, "messages": filter_request_messages(payload.get("messages", []), show_system_prompt)}
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    factory = client_factory or httpx.AsyncClient
    async with factory(timeout=DEFAULT_TIMEOUT) as client:
        # Erreichbarkeit des LLM-Servers ergibt sich aus dem POST selbst:
        # ConnectError/TimeoutError propagieren und werden vom Aufrufer
        # (run_generation) als System-Message persistiert.
        stream_cm = client.stream("POST", url, headers=headers, json=payload)
        if abort is not None and abort.is_set():
            return
        if abort is None:
            res = await stream_cm.__aenter__()
        else:
            enter = asyncio.ensure_future(stream_cm.__aenter__())
            abort_wait = asyncio.ensure_future(abort.wait())
            done, _pending = await asyncio.wait({enter, abort_wait}, return_when=asyncio.FIRST_COMPLETED)
            if abort_wait in done and abort.is_set():
                enter.cancel()
                await asyncio.gather(enter, abort_wait, return_exceptions=True)
                return
            abort_wait.cancel()
            await asyncio.gather(abort_wait, return_exceptions=True)
            res = enter.result()
        try:
            if res.status_code >= 400:
                # Upstream-Body nicht an den Client reichen (Info-Leak bei internen Zielen)
                error = json.dumps({"error": f"HTTP {res.status_code}"})
                yield f"data: {error}\n\n"
                yield "data: [DONE]\n\n"
                return
            raw = _aiter_until_abort(res.aiter_bytes(), abort)
            if show_reasoning and show_tool_output:
                async for chunk in raw:
                    yield chunk.decode("utf-8", errors="replace")
            else:
                async for line in sse_filter(raw, show_reasoning=show_reasoning, show_tool_output=show_tool_output):
                    yield line
        finally:
            await stream_cm.__aexit__(None, None, None)
