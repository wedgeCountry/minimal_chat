from __future__ import annotations

import httpx

from app.auth import user_identity
from app.db import database as dbq

RealAsyncClient = httpx.AsyncClient


def _create_model(client, auth_headers, **fields) -> dict:
    body = {"provider": "Lokal", "host": "192.168.1.10", "port": "8000", "model": "gpt-x", **fields}
    res = client.post("/api/settings/models", json=body, headers=auth_headers)
    assert res.status_code == 201, res.text
    return res.json()


def _mock_llm_models(monkeypatch, handler):
    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", factory)


def test_models_crud_roundtrip(client, auth_headers, app, config):
    assert client.get("/api/settings/models", headers=auth_headers).json() == []

    m = _create_model(client, auth_headers, api_key="sk-geheim")
    assert m["provider"] == "Lokal"
    assert m["host"] == "192.168.1.10"
    assert m["port"] == "8000"
    assert m["model"] == "gpt-x"
    assert "api_key" not in m  # Secret nie in der Antwort

    got = client.get(f"/api/settings/models/{m['id']}", headers=auth_headers).json()
    assert got == m
    assert "sk-geheim" not in str(got)

    lst = client.get("/api/settings/models", headers=auth_headers).json()
    assert [x["id"] for x in lst] == [m["id"]]

    res = client.put(
        f"/api/settings/models/{m['id']}",
        json={"model": "gpt-y", "api_key": "sk-neu", "port": "9000"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["model"] == "gpt-y"
    assert res.json()["port"] == "9000"
    assert res.json()["host"] == "192.168.1.10"  # nicht gesendete Felder bleiben

    # leerer api_key aendert nichts (write-only), neues api_key wird gespeichert aber nie ausgeliefert
    client.put(f"/api/settings/models/{m['id']}", json={"api_key": ""}, headers=auth_headers)
    got = client.get(f"/api/settings/models/{m['id']}", headers=auth_headers).json()
    assert "api_key" not in got
    stored = client.get("/api/settings/models", headers=auth_headers).json()
    assert "sk-neu" not in str(stored)

    # api_key liegt in der per-user DB (nur Test-Code liest direkt, siehe AGENTS.md)
    user = user_identity(config.secret, "alice@example.com")
    with app.state.db.user_db(user) as con:
        row = dbq.q_get_llm_model(con, m["id"])
        assert row is not None and row["api_key"] == "sk-neu"

    assert client.delete(f"/api/settings/models/{m['id']}", headers=auth_headers).status_code == 204
    assert client.get("/api/settings/models", headers=auth_headers).json() == []
    assert client.get(f"/api/settings/models/{m['id']}", headers=auth_headers).status_code == 404
    assert client.delete(f"/api/settings/models/{m['id']}", headers=auth_headers).status_code == 404


def test_first_model_becomes_default_and_delete_reassigns_default(client, auth_headers):
    m1 = _create_model(client, auth_headers, model="eins")
    m2 = _create_model(client, auth_headers, model="zwei")
    got = client.get("/api/settings", headers=auth_headers).json()
    assert got["default_model_id"] == str(m1["id"])

    # explizit umschalten
    res = client.put("/api/settings", json={"default_model_id": str(m2["id"])}, headers=auth_headers)
    assert res.json()["default_model_id"] == str(m2["id"])

    # default loeschen -> default_model_id zeigt auf das verbleibende Tile
    assert client.delete(f"/api/settings/models/{m2['id']}", headers=auth_headers).status_code == 204
    assert client.get("/api/settings", headers=auth_headers).json()["default_model_id"] == str(m1["id"])

    # letztes Tile loeschen -> default_model_id leer
    assert client.delete(f"/api/settings/models/{m1['id']}", headers=auth_headers).status_code == 204
    assert client.get("/api/settings", headers=auth_headers).json()["default_model_id"] == ""


def test_models_require_auth_and_404(client, app):
    from fastapi.testclient import TestClient

    anon = TestClient(app)
    assert anon.get("/api/settings/models").status_code == 401
    assert anon.put("/api/settings/models/1", json={}).status_code == 401
    assert anon.delete("/api/settings/models/1").status_code == 401
    assert anon.post("/api/settings/models/test", json={}).status_code == 401


def test_models_isolated_per_user(client, auth_headers, app):
    from tests.conftest import login_client

    m = _create_model(client, auth_headers)
    bob = login_client(app, "bob@example.com")
    assert bob.get("/api/settings/models", headers={}).json() == []
    assert bob.get(f"/api/settings/models/{m['id']}").status_code == 404
    assert bob.put(f"/api/settings/models/{m['id']}", json={"model": "gehackt"}).status_code == 404
    assert bob.delete(f"/api/settings/models/{m['id']}").status_code == 404
    assert client.get(f"/api/settings/models/{m['id']}", headers=auth_headers).json()["model"] == "gpt-x"


def test_legacy_llm_settings_migrate_into_tile(client, auth_headers, app, config):
    """Migration: flache user_settings-Keys (base/host/port/model/api_key) landen in einem
    Tile, default_model_id zeigt darauf, die Legacy-Keys werden entfernt."""
    user = user_identity(config.secret, "alice@example.com")
    with app.state.db.user_db(user) as con:
        dbq.q_set_user_setting(con, "host", "10.1.2.3")
        dbq.q_set_user_setting(con, "port", "8000")
        dbq.q_set_user_setting(con, "model", "legacy-model")
        dbq.q_set_user_setting(con, "api_key", "sk-legacy")
        dbq.q_set_user_setting(con, "base", "http://legacy.test/v1")
        dbq.q_set_user_setting(con, "theme", "dark")

    models = client.get("/api/settings/models", headers=auth_headers).json()
    assert len(models) == 1
    assert models[0]["host"] == "10.1.2.3"
    assert models[0]["port"] == "8000"
    assert models[0]["base"] == "http://legacy.test/v1"
    assert models[0]["model"] == "legacy-model"
    assert "api_key" not in models[0]

    settings = client.get("/api/settings", headers=auth_headers).json()
    assert settings["default_model_id"] == str(models[0]["id"])
    assert settings["theme"] == "dark"  # Nicht-LLM-Settings bleiben erhalten

    with app.state.db.user_db(user) as con:
        stored = dbq.q_get_user_settings(con)
        for key in ("base", "host", "port", "model", "api_key"):
            assert key not in stored
        assert stored["default_model_id"] == str(models[0]["id"])
        row = dbq.q_get_llm_model(con, models[0]["id"])
        assert row is not None and row["api_key"] == "sk-legacy"


def test_connection_test_ok_uses_server_defaults(client, auth_headers, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": []})

    _mock_llm_models(monkeypatch, handler)
    res = client.post("/api/settings/models/test", json={}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["ok"] is True
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
        "/api/settings/models/test",
        json={"base": "http://other.test/v1", "api_key": "sk-other"},
        headers=auth_headers,
    )
    assert res.json()["ok"] is True
    assert seen["url"] == "http://other.test/v1/models"
    assert seen["auth"] == "Bearer sk-other"


def test_connection_test_uses_tile_values(client, auth_headers, monkeypatch):
    """Ohne explizite base/api_key gewinnt das referenzierte Tile (gespeicherter api_key)."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": []})

    _mock_llm_models(monkeypatch, handler)
    m = _create_model(client, auth_headers, host="tile.test", api_key="sk-tile")
    res = client.post("/api/settings/models/test", json={"model_id": m["id"]}, headers=auth_headers)
    assert res.json()["ok"] is True
    assert seen["url"] == "http://tile.test:8000/v1/models"
    assert seen["auth"] == "Bearer sk-tile"
    # Body-Werte schlagen das Tile
    res = client.post(
        "/api/settings/models/test",
        json={"model_id": m["id"], "base": "http://override.test/v1", "api_key": "sk-body"},
        headers=auth_headers,
    )
    assert res.json()["ok"] is True
    assert seen["url"] == "http://override.test/v1/models"
    assert seen["auth"] == "Bearer sk-body"


def test_connection_test_unknown_model_404(client, auth_headers):
    res = client.post("/api/settings/models/test", json={"model_id": 4242}, headers=auth_headers)
    assert res.status_code == 404


def test_connection_test_unreachable(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    _mock_llm_models(monkeypatch, handler)
    res = client.post("/api/settings/models/test", json={}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["ok"] is False


def test_connection_test_http_401_is_reported_as_invalid_key(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    _mock_llm_models(monkeypatch, handler)
    res = client.post("/api/settings/models/test", json={}, headers=auth_headers)
    body = res.json()
    assert body["ok"] is False
    assert "401" in body["detail"] and "API-Schlüssel" in body["detail"]
    # Upstream-Body darf nicht durchgereicht werden
    assert "bad key" not in body["detail"]


def test_connection_test_http_403_is_reported_as_denied(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    _mock_llm_models(monkeypatch, handler)
    res = client.post("/api/settings/models/test", json={}, headers=auth_headers)
    assert res.json()["ok"] is False
    assert "403" in res.json()["detail"]


def test_connection_test_other_http_error_keeps_status(client, auth_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    _mock_llm_models(monkeypatch, handler)
    res = client.post("/api/settings/models/test", json={}, headers=auth_headers)
    assert res.json() == {"ok": False, "detail": "http://llm.test/v1/models -> HTTP 500"}


def test_connection_test_model_available(client, auth_headers, monkeypatch):
    """GET /models listet das Modell -> ok mit Verfuegbarkeits-Hinweis."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-x"}, {"id": "gpt-y"}]})

    _mock_llm_models(monkeypatch, handler)
    m = _create_model(client, auth_headers, model="gpt-x")
    res = client.post("/api/settings/models/test", json={"model_id": m["id"]}, headers=auth_headers)
    assert res.json()["ok"] is True
    assert "gpt-x" in res.json()["detail"] and "verfügbar" in res.json()["detail"]


def test_connection_test_model_not_offered_is_differentiated(client, auth_headers, monkeypatch):
    """Server erreichbar + Key ok, aber Modell fehlt in /models -> eigene Meldung."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "anderes-modell"}]})

    _mock_llm_models(monkeypatch, handler)
    m = _create_model(client, auth_headers, model="gpt-x")
    res = client.post("/api/settings/models/test", json={"model_id": m["id"]}, headers=auth_headers)
    body = res.json()
    assert body["ok"] is False
    assert "nicht verfügbar" in body["detail"] and "gpt-x" in body["detail"]
    assert "anderes-modell" in body["detail"]  # angebotene Modelle als Hinweis


def test_connection_test_body_model_overrides_tile(client, auth_headers, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["models"] = True
        return httpx.Response(200, json={"data": [{"id": "nur-dieses"}]})

    _mock_llm_models(monkeypatch, handler)
    m = _create_model(client, auth_headers, model="gpt-x")
    # Body-Modell gewinnt gegen das Tile-Modell
    res = client.post(
        "/api/settings/models/test", json={"model_id": m["id"], "model": "nur-dieses"}, headers=auth_headers
    )
    assert res.json()["ok"] is True
    res = client.post("/api/settings/models/test", json={"model_id": m["id"]}, headers=auth_headers)
    assert res.json()["ok"] is False and "gpt-x" in res.json()["detail"]
