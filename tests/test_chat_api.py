from __future__ import annotations

import json

import httpx

RealAsyncClient = httpx.AsyncClient

SSE_BODY = (
    b'data: {"choices":[{"delta":{"reasoning_content":"denke"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"Hallo"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":" Welt"}}]}\n\n'
    b'data: {"choices":[{"delta":{"tool_calls":[{"function":{"name":"f","arguments":"{}"}}]}}]}\n\n'
    b"data: [DONE]\n\n"
)


def _mock_llm(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        # Handle HEAD request for connectivity check
        if request.method == "HEAD":
            return httpx.Response(200)
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
    assert b"reasoning_content" in res.content and b"tool_calls" in res.content
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer test-api-key"
    assert seen["body"]["stream"] is True
    assert seen["body"]["messages"] == [{"role": "user", "content": "Hi"}]


def test_chat_filters_reasoning_and_tool_output_server_side(client, auth_headers, monkeypatch):
    _mock_llm(monkeypatch)
    client.put(
        "/api/settings",
        json={"show_reasoning": False, "show_tool_output": False},
        headers=auth_headers,
    )
    res = client.post(
        "/api/chat",
        json={"model": "m", "messages": [{"role": "user", "content": "Hi"}]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert b"Hallo" in res.content
    assert b"reasoning_content" not in res.content
    assert b"tool_calls" not in res.content
    assert b"[DONE]" in res.content


def test_chat_filters_system_prompt_from_request_server_side(client, auth_headers, monkeypatch):
    seen = _mock_llm(monkeypatch)
    client.put("/api/settings", json={"show_system_prompt": False}, headers=auth_headers)
    res = client.post(
        "/api/chat",
        json={
            "model": "m",
            "messages": [
                {"role": "system", "content": "Du bist ein Assistent."},
                {"role": "user", "content": "Hi"},
            ],
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
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


def test_chat_server_unreachable(client, auth_headers, monkeypatch):
    def handler(request):
        if request.method == "HEAD":
            raise httpx.ConnectError("Connection refused")
        return httpx.Response(200, content=SSE_BODY)

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
    assert b"LLM-Server nicht erreichbar" in res.content
    assert b"[DONE]" in res.content


def test_chat_server_timeout(client, auth_headers, monkeypatch):
    """Test that a timeout error during connectivity check is handled properly."""
    def handler(request):
        if request.method == "HEAD":
            raise httpx.TimeoutException("Connection timed out")
        return httpx.Response(200, content=SSE_BODY)

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
    assert b"LLM-Server nicht erreichbar" in res.content
    assert b"[DONE]" in res.content


def test_chat_server_network_error(client, auth_headers, monkeypatch):
    """Test that a network error during connectivity check is handled properly."""
    def handler(request):
        if request.method == "HEAD":
            raise httpx.NetworkError("Network unreachable")
        return httpx.Response(200, content=SSE_BODY)

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
    assert b"LLM-Server nicht erreichbar" in res.content
    assert b"[DONE]" in res.content


def test_chat_server_reachable_but_completions_fail(client, auth_headers, monkeypatch):
    """Test that connectivity check passes but POST to completions fails."""
    def handler(request):
        if request.method == "HEAD":
            return httpx.Response(200)
        # POST to /chat/completions fails
        return httpx.Response(500, content=b"Internal Server Error")

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
    # Should get the HTTP 500 error, not the connectivity error
    assert b"HTTP 500" in res.content
    assert b"LLM-Server nicht erreichbar" not in res.content
    assert b"[DONE]" in res.content
