"""Smoke-Tests fuer die App-Factory und das Static-Mounting (app/main.py)."""

from __future__ import annotations

import pytest

from tests.conftest import login_client


def test_auto_login_refused_on_non_loopback_host(tmp_path, monkeypatch):
    """Auto-Login (Testmodus) darf nicht auf einem oeffentlich erreichbaren Host starten."""
    from app.config import AppConfig
    from app.main import create_app

    monkeypatch.setenv("LEANCHAT_AUTO_LOGIN", "1")
    cfg = AppConfig(
        data_dir=tmp_path / "data",
        secret="s",
        registry_path=tmp_path / "data" / "user_registry.db",
        users_dir=tmp_path / "data" / "users",
        host="0.0.0.0",
        port=8000,
    )
    with pytest.raises(RuntimeError, match="AUTO_LOGIN"):
        create_app(config=cfg)


def test_root_redirects_unauthenticated_to_login(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/auth/login"


def test_root_redirect_followed_lands_on_login_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert str(res.url).endswith("/auth/login")


def test_root_serves_index_html_when_authenticated(app):
    with login_client(app) as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "<title>LeanChat</title>" in res.text


def test_static_js_module_is_served(client):
    res = client.get("/js/main.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]


def test_static_partial_is_served(client):
    res = client.get("/partials/chat-window.html")
    assert res.status_code == 200


def test_unknown_static_path_404(client):
    assert client.get("/js/gibts-nicht.js").status_code == 404
