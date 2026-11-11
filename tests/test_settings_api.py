from __future__ import annotations


DEFAULTS = {
    "base": "http://llm.test/v1",
    "model": "gpt-4o-mini",
    "theme": "light",
    "bubbles_deletable": True,
    "bubbles_user_checkable": True,
    "bubbles_user_deletable": True,
    "show_system_prompt": True,
    "show_tool_output": True,
    "show_reasoning": True,
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
            "bubbles_user_checkable": False,
            "bubbles_user_deletable": False,
            "show_system_prompt": False,
            "show_tool_output": False,
            "show_reasoning": False,
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["bubbles_deletable"] is False
    assert body["bubbles_user_checkable"] is False
    assert body["show_reasoning"] is False
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["bubbles_deletable"] is False
    assert got["bubbles_user_checkable"] is False
    assert got["bubbles_user_deletable"] is False
    assert got["show_system_prompt"] is False
    assert got["show_tool_output"] is False
    assert got["show_reasoning"] is False
    assert got["base"] == DEFAULTS["base"]


def test_settings_require_auth(client):
    assert client.get("/api/settings").status_code == 401
    assert client.put("/api/settings", json={}).status_code == 401
