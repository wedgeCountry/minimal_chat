"""Smoke-Tests fuer die App-Factory und das Static-Mounting (app/main.py)."""

from __future__ import annotations


def test_root_serves_index_html(client):
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
