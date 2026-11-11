from __future__ import annotations


def test_meta_returns_default_app_name(client):
    res = client.get("/api/meta")
    assert res.status_code == 200
    assert res.json() == {"app_name": "LeanChat"}


def test_meta_returns_custom_app_name(app):
    app.state.config.app_name = "MeinChat"
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        res = c.get("/api/meta")
    assert res.json() == {"app_name": "MeinChat"}
