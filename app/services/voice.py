"""Client fuer den Voice-Companion-Server (vendored Wheel voice_companion).

Der Voice-Companion stellt /health, POST /v1/stt (WAV-Datei -> Text) und
POST /v1/tts (Text -> WAV) bereit. Dieses Modul kapselt den HTTP-Zugriff;
bei nicht erreichbarem Server wird VoiceServiceUnavailable geworfen.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

HEALTH_TIMEOUT = httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=2.0)
VOICE_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0)

ClientFactory = Callable[..., httpx.AsyncClient]

NETWORK_ERRORS = (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)


class VoiceServiceUnavailable(Exception):
    """Voice-Companion-Server ist nicht erreichbar."""


class VoiceUpstreamError(Exception):
    """Voice-Companion hat mit einem HTTP-Fehler geantwortet."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def check_voice_service(base_url: str, client_factory: ClientFactory | None = None) -> bool:
    """Funktionspruefung: GET /health am Voice-Companion."""
    factory = client_factory or httpx.AsyncClient
    url = base_url.rstrip("/") + "/health"
    try:
        async with factory(timeout=HEALTH_TIMEOUT) as client:
            res = await client.get(url)
    except NETWORK_ERRORS:
        return False
    return res.status_code == 200


async def transcribe_speech(
    base_url: str,
    audio: bytes,
    filename: str,
    content_type: str,
    language: str | None = None,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    """POST /v1/stt: WAV-Audio -> {"text": ..., "language": ...}."""
    factory = client_factory or httpx.AsyncClient
    url = base_url.rstrip("/") + "/v1/stt"
    files = {"file": (filename, audio, content_type or "application/octet-stream")}
    params = {"language": language} if language else None
    try:
        async with factory(timeout=VOICE_TIMEOUT) as client:
            res = await client.post(url, files=files, params=params)
    except NETWORK_ERRORS as e:
        raise VoiceServiceUnavailable(str(e)) from e
    if res.status_code >= 400:
        raise VoiceUpstreamError(res.status_code, res.text[:300])
    return res.json()


async def synthesize_speech(
    base_url: str,
    text: str,
    language: str | None = None,
    voice: str | None = None,
    client_factory: ClientFactory | None = None,
) -> tuple[bytes, str]:
    """POST /v1/tts: Text -> (WAV-Bytes, Content-Type)."""
    factory = client_factory or httpx.AsyncClient
    url = base_url.rstrip("/") + "/v1/tts"
    payload: dict[str, Any] = {"text": text}
    if language:
        payload["language"] = language
    if voice:
        payload["voice"] = voice
    try:
        async with factory(timeout=VOICE_TIMEOUT) as client:
            res = await client.post(url, json=payload)
    except NETWORK_ERRORS as e:
        raise VoiceServiceUnavailable(str(e)) from e
    if res.status_code >= 400:
        raise VoiceUpstreamError(res.status_code, res.text[:300])
    return res.content, res.headers.get("content-type", "audio/wav")
