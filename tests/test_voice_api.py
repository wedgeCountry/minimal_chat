from __future__ import annotations

import json

import httpx

RealAsyncClient = httpx.AsyncClient

WAV_BYTES = b"RIFF" + b"\x00" * 40


def _mock_voice(monkeypatch, handler):
    seen = {}

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return handler(request)

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(wrapped))

    monkeypatch.setattr("app.services.voice.httpx.AsyncClient", factory)
    return seen


def test_voice_status_available(client, auth_headers, monkeypatch):
    seen = _mock_voice(monkeypatch, lambda req: httpx.Response(200, json={"status": "ok"}))
    res = client.get("/api/voice/status", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"available": True, "stt": True, "tts": True}
    assert seen["url"] == "http://127.0.0.1:8001/health"


def test_voice_status_unavailable_on_connect_error(client, auth_headers, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("Connection refused")

    _mock_voice(monkeypatch, handler)
    res = client.get("/api/voice/status", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"available": False, "stt": False, "tts": False}


def test_voice_status_unavailable_on_timeout(client, auth_headers, monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("timeout")

    _mock_voice(monkeypatch, handler)
    res = client.get("/api/voice/status", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["available"] is False


def test_voice_stt_forwards_audio_and_returns_text(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/stt"
        assert request.url.params.get("language") == "auto"
        assert b"file" in request.content
        assert WAV_BYTES[:4] in request.content
        return httpx.Response(200, json={"text": "Hallo Welt", "language": "de"})

    seen = _mock_voice(monkeypatch, handler)
    res = client.post(
        "/api/voice/stt?language=auto",
        files={"file": ("rec.wav", WAV_BYTES, "audio/wav")},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json() == {"text": "Hallo Welt", "language": "de"}
    assert seen["method"] == "POST"


def test_voice_stt_unavailable_returns_503(client, auth_headers, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("Connection refused")

    _mock_voice(monkeypatch, handler)
    res = client.post(
        "/api/voice/stt",
        files={"file": ("rec.wav", WAV_BYTES, "audio/wav")},
        headers=auth_headers,
    )
    assert res.status_code == 503
    assert "nicht verfügbar" in res.json()["detail"]


def test_voice_stt_upstream_error_forwarded(client, auth_headers, monkeypatch):
    def handler(request):
        return httpx.Response(400, json={"detail": "bad wav"})

    _mock_voice(monkeypatch, handler)
    res = client.post(
        "/api/voice/stt",
        files={"file": ("rec.wav", WAV_BYTES, "audio/wav")},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_voice_tts_returns_wav(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/tts"
        body = json.loads(request.content)
        assert body == {"text": "Hallo Welt", "language": "de"}
        return httpx.Response(200, content=WAV_BYTES, headers={"content-type": "audio/wav"})

    _mock_voice(monkeypatch, handler)
    res = client.post("/api/voice/tts", json={"text": "Hallo Welt", "language": "de"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"
    assert res.content == WAV_BYTES


def test_voice_tts_unavailable_returns_503(client, auth_headers, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("Connection refused")

    _mock_voice(monkeypatch, handler)
    res = client.post("/api/voice/tts", json={"text": "Hallo"}, headers=auth_headers)
    assert res.status_code == 503
    assert "nicht verfügbar" in res.json()["detail"]


def test_voice_tts_upstream_error_forwarded(client, auth_headers, monkeypatch):
    def handler(request):
        return httpx.Response(400, json={"detail": "unbekannte Stimme"})

    _mock_voice(monkeypatch, handler)
    res = client.post("/api/voice/tts", json={"text": "Hallo"}, headers=auth_headers)
    assert res.status_code == 400


def test_voice_endpoints_require_auth(client):
    assert client.get("/api/voice/status").status_code == 401
    res = client.post("/api/voice/tts", json={"text": "x"})
    assert res.status_code == 401
    res = client.post("/api/voice/stt", files={"file": ("a.wav", WAV_BYTES, "audio/wav")})
    assert res.status_code == 401
