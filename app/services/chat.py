from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

ClientFactory = Callable[..., httpx.AsyncClient]


async def stream_completion(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    client_factory: ClientFactory | None = None,
) -> AsyncIterator[bytes]:
    """Leitet einen Chat-Completions-Request als SSE-Stream an den LLM-Endpunkt weiter."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    factory = client_factory or httpx.AsyncClient
    async with factory(timeout=DEFAULT_TIMEOUT) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as res:
            if res.status_code >= 400:
                body = (await res.aread()).decode("utf-8", errors="replace")[:300]
                error = json.dumps({"error": f"HTTP {res.status_code}: {body}"})
                yield f"data: {error}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"
                return
            async for chunk in res.aiter_bytes():
                yield chunk
