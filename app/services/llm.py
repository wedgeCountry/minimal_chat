"""HTTP-Client fuer den OpenAI-kompatiblen LLM-Endpunkt (Chat-Completions als SSE-Stream).

``LlmClient`` kapselt base_url/api_key/timeout; ``stream_completion`` und
``check_llm_connection`` sind schlanke module-level Hüllen fuer die Aufrufer
(run_generation, Settings-Test). Abort wird ueber ``race_abort`` gegen das
Oeffnen der Response und jeden Chunk-Read geracet.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

import httpx

from .sse import sse_filter

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

ClientFactory = Callable[..., httpx.AsyncClient]

T = TypeVar("T")


def filter_request_messages(messages: list[dict[str, Any]], show_system_prompt: bool) -> list[dict[str, Any]]:
    """Serverseitiges Filtern des Requests: System-Prompt nur mitsenden, wenn aktiviert."""
    if show_system_prompt:
        return messages
    return [m for m in messages if m.get("role") != "system"]


async def race_abort(awaitable: Awaitable[T], abort: asyncio.Event | None) -> tuple[T | None, bool]:
    """Await ``awaitable``, es sei denn ``abort`` feuert zuerst -> ``(result, aborted)``.

    Beim Abort wird das haengende Awaitable gecancelt.
    """
    if abort is None:
        return await awaitable, False
    task = asyncio.ensure_future(awaitable)
    abort_wait = asyncio.ensure_future(abort.wait())
    try:
        done, _pending = await asyncio.wait({task, abort_wait}, return_when=asyncio.FIRST_COMPLETED)
        if abort_wait in done:
            task.cancel()
            return None, True
        return task.result(), False
    finally:
        for t in (task, abort_wait):
            if not t.done():
                t.cancel()
        await asyncio.gather(task, abort_wait, return_exceptions=True)


async def aiter_until_abort(chunks: AsyncIterator[bytes], abort: asyncio.Event | None) -> AsyncIterator[bytes]:
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
        try:
            chunk, aborted = await race_abort(it.__anext__(), abort)
        except StopAsyncIteration:
            return
        if aborted:
            return
        yield chunk


class LlmClient:
    """Client fuer einen OpenAI-kompatiblen Endpunkt (base_url + api_key)."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client_factory = client_factory or httpx.AsyncClient

    @property
    def chat_completions_url(self) -> str:
        return self._base_url + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def check_connection(self) -> tuple[bool, str]:
        """Prueft die Erreichbarkeit des LLM-Servers (GET {base}/models)."""
        url = self._base_url + "/models"
        try:
            async with self._client_factory(timeout=5.0) as client:
                res = await client.get(url, headers=self._headers())
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
            return False, f"LLM-Server nicht erreichbar ({url})"
        if res.status_code >= 400:
            return False, f"{url} -> HTTP {res.status_code}"
        return True, f"{url} -> HTTP {res.status_code}"

    async def stream_completion(
        self,
        payload: dict[str, Any],
        settings: dict[str, bool] | None = None,
        abort: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        """Leitet einen Chat-Completions-Request als SSE-Stream weiter.

        ``settings`` steuert das serverseitige Filtern: ``show_system_prompt``
        filtert den Request, ``show_reasoning``/``show_tool_output`` den Response-Stream.
        ``abort`` wird gegen das Oeffnen der Response und jeden Chunk-Read geracet;
        beim Abort wird die Upstream-Verbindung sofort geschlossen.
        """
        flags = settings or {}
        show_reasoning = flags.get("show_reasoning", True)
        show_tool_output = flags.get("show_tool_output", True)
        payload = {
            **payload,
            "messages": filter_request_messages(payload.get("messages", []), flags.get("show_system_prompt", True)),
        }
        async with self._client_factory(timeout=self._timeout) as client:
            # Erreichbarkeit des LLM-Servers ergibt sich aus dem POST selbst:
            # ConnectError/TimeoutError propagieren und werden vom Aufrufer
            # (run_generation) als System-Message persistiert.
            stream_cm = client.stream("POST", self.chat_completions_url, headers=self._headers(), json=payload)
            res, aborted = await race_abort(stream_cm.__aenter__(), abort)
            if aborted:
                return
            try:
                if res.status_code >= 400:
                    # Upstream-Body nicht an den Client reichen (Info-Leak bei internen Zielen)
                    detail = f"HTTP {res.status_code}"
                    if res.status_code == 422:
                        detail += " (Anfrage vom LLM-Server abgelehnt – evtl. zu großer Kontext; alte Nachrichten per Kontext-Checkbox abwählen)"
                    yield f"data: {json.dumps({'error': detail})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                raw = aiter_until_abort(res.aiter_bytes(), abort)
                if show_reasoning and show_tool_output:
                    async for chunk in raw:
                        yield chunk.decode("utf-8", errors="replace")
                else:
                    async for line in sse_filter(raw, show_reasoning=show_reasoning, show_tool_output=show_tool_output):
                        yield line
            finally:
                await stream_cm.__aexit__(None, None, None)


async def stream_completion(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    settings: dict[str, bool] | None = None,
    client_factory: ClientFactory | None = None,
    abort: asyncio.Event | None = None,
) -> AsyncIterator[str]:
    """Module-level Huelle um ``LlmClient.stream_completion`` (Einstieg fuer run_generation)."""
    client = LlmClient(base_url, api_key, client_factory=client_factory)
    async for chunk in client.stream_completion(payload, settings=settings, abort=abort):
        yield chunk


async def check_llm_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    return await LlmClient(base_url, api_key).check_connection()
