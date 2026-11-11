from __future__ import annotations

import json

import httpx

RealAsyncClient = httpx.AsyncClient

SSE_BODY = (
    b'data: {"choices":[{"delta":{"content":"Hallo"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":" Welt"}}]}\n\n'
    b"data: [DONE]\n\n"
)


def _mock_llm(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=SSE_BODY,
        )

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.chat.httpx.AsyncClient", factory)
    return seen


def test_chat_streams_sse(client, auth_headers, monkeypatch):
    seen = _mock_llm(monkeypatch)
    res = client.post(
        "/api/chat",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert b"Hallo" in res.content and b"[DONE]" in res.content
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer test-api-key"
    assert seen["body"]["stream"] is True
    assert seen["body"]["messages"] == [{"role": "user", "content": "Hi"}]


def test_chat_uses_per_user_settings_and_key(client, auth_headers, monkeypatch):
    seen = _mock_llm(monkeypatch)
    client.put(
        "/api/settings",
        json={"base": "http://per-user.test/v1", "api_key": "sk-user"},
        headers=auth_headers,
    )
    res = client.post(
        "/api/chat",
        json={"model": "m", "messages": [{"role": "user", "content": "x"}]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert seen["url"] == "http://per-user.test/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-user"


def test_chat_requires_auth(client):
    res = client.post("/api/chat", json={"model": "m", "messages": []})
    assert res.status_code == 401


def test_chat_upstream_error_forwarded(client, auth_headers, monkeypatch):
    def handler(request):
        return httpx.Response(500, content=b"boom")

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.chat.httpx.AsyncClient", factory)
    res = client.post(
        "/api/chat",
        json={"model": "m", "messages": [{"role": "user", "content": "x"}]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert b"HTTP 500" in res.content
