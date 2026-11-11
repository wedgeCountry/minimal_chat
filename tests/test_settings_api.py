from __future__ import annotations


def test_default_settings(client, auth_headers):
    res = client.get("/api/settings", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"base": "http://llm.test/v1", "model": "gpt-4o-mini", "theme": "light"}


def test_update_settings_and_api_key_write_only(client, auth_headers):
    res = client.put(
        "/api/settings",
        json={"base": "http://other.test/v1", "model": "gpt-x", "theme": "dark", "api_key": "sk-geheim"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json() == {"base": "http://other.test/v1", "model": "gpt-x", "theme": "dark"}
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["theme"] == "dark"
    assert "api_key" not in got
    assert "sk-geheim" not in str(got)


def test_settings_require_auth(client):
    assert client.get("/api/settings").status_code == 401
    assert client.put("/api/settings", json={}).status_code == 401
