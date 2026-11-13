from __future__ import annotations

import httpx

RealAsyncClient = httpx.AsyncClient

DEFAULTS = {
    "base": "http://llm.test/v1",
    "host": "llm.test",
    "port": "",
    "model": "gpt-4o-mini",
    "system_prompt": "",
    "theme": "light",
    "bubbles_deletable": True,
    "bubbles_checkable": True,
    "bubbles_speaker": True,
    "show_system_prompt": True,
    "show_tool_output": True,
    "show_reasoning": True,
    "show_file_button": False,
    "show_image_button": False,
}


def test_default_settings(client, auth_headers):
    res = client.get("/api/settings", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == DEFAULTS


def test_update_settings_and_api_key_write_only(client, auth_headers):
    res = client.put(
        "/api/settings",
        json={"base": "http://other.test/v1", "model": "gpt-x", "theme": "dark", "api_key": "sk-geheim"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["base"] == "http://other.test/v1"
    assert res.json()["theme"] == "dark"
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["theme"] == "dark"
    assert "api_key" not in got
    assert "sk-geheim" not in str(got)


def test_boolean_display_settings_roundtrip(client, auth_headers):
    res = client.put(
        "/api/settings",
        json={
            "bubbles_deletable": False,
            "bubbles_checkable": False,
            "bubbles_speaker": False,
            "show_system_prompt": False,
            "show_tool_output": False,
            "show_reasoning": False,
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["bubbles_deletable"] is False
    assert body["bubbles_checkable"] is False
    assert body["bubbles_speaker"] is False
    assert body["show_reasoning"] is False
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["bubbles_deletable"] is False
    assert got["bubbles_checkable"] is False
    assert got["bubbles_speaker"] is False
    assert got["show_system_prompt"] is False
    assert got["show_tool_output"] is False
    assert got["show_reasoning"] is False
    assert got["base"] == DEFAULTS["base"]


def test_legacy_user_setting_keys_fall_back_to_default(client, auth_headers, app):
    """Umbenannte alte Schluessel (bubbles_user_*) werden nicht mehr gelesen:
    Default greift (bubbles_checkable/bubbles_deletable default True)."""
    from app.auth import user_identity
    from app.db import database as dbq

    db = app.state.db
    user = user_identity(app.state.config.secret, "alice@example.com")
    with db.user_db(user) as con:
        dbq.q_set_user_setting(con, "bubbles_user_checkable", "0")
        dbq.q_set_user_setting(con, "bubbles_user_deletable", "0")
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["bubbles_checkable"] is True
    assert got["bubbles_deletable"] is True


def test_host_port_compute_base_url(client, auth_headers):
    res = client.put(
        "/api/settings",
        json={"host": "192.168.1.10", "port": "8000"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["base"] == "http://192.168.1.10:8000/v1"
    assert body["host"] == "192.168.1.10"
    assert body["port"] == "8000"
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["base"] == "http://192.168.1.10:8000/v1"


def test_host_without_port_and_legacy_base_fallback(client, auth_headers):
    res = client.put("/api/settings", json={"host": "llm.local"}, headers=auth_headers)
    assert res.json()["base"] == "http://llm.local/v1"
    # host leeren -> wieder gespeicherte base / Default
    client.put("/api/settings", json={"host": "", "base": "http://legacy.test/v1"}, headers=auth_headers)
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["base"] == "http://legacy.test/v1"


def test_system_prompt_roundtrip_and_clear(client, auth_headers):
    res = client.put("/api/settings", json={"system_prompt": "Sei freundlich."}, headers=auth_headers)
    assert res.json()["system_prompt"] == "Sei freundlich."
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["system_prompt"] == "Sei freundlich."
    client.put("/api/settings", json={"system_prompt": ""}, headers=auth_headers)
    assert client.get("/api/settings", headers=auth_headers).json()["system_prompt"] == ""


def test_settings_require_auth(client):
    assert client.get("/api/settings").status_code == 401
    assert client.put("/api/settings", json={}).status_code == 401
    assert client.post("/api/settings/test", json={}).status_code == 401


def _mock_llm_models(monkeypatch, handler):
    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.chat.httpx.AsyncClient", factory)


def test_connection_test_ok(client, auth_headers, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": []})

    _mock_llm_models(monkeypatch, handler)
    res = client.post("/api/settings/test", json={}, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert seen["url"] == "http://llm.test/v1/models"
    assert seen["auth"] == "Bearer test-api-key"


def test_connection_test_uses_body_overrides(client, auth_headers, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": []})

    _mock_llm_models(monkeypatch, handler)
    res = client.post(
        "/api/settings/test",
        json={"base": "http://other.test/v1", "api_key": "sk-other"},
        headers=auth_headers,
    )
    assert res.json()["ok"] is True
    assert seen["url"] == "http://other.test/v1/models"
    assert seen["auth"] == "Bearer sk-other"


def test_connection_test_unreachable(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    _mock_llm_models(monkeypatch, handler)
    res = client.post("/api/settings/test", json={}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["ok"] is False


def test_connection_test_http_error_is_red(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    _mock_llm_models(monkeypatch, handler)
    res = client.post("/api/settings/test", json={}, headers=auth_headers)
    assert res.json() == {"ok": False, "detail": "http://llm.test/v1/models -> HTTP 401"}


def test_settings_out_uses_env_default_host_port(client, auth_headers, app):
    app.state.config.default_llm_host = "10.9.8.7"
    app.state.config.default_llm_port = "9999"
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["host"] == "10.9.8.7"
    assert got["port"] == "9999"
    assert got["base"] == "http://10.9.8.7:9999/v1"
