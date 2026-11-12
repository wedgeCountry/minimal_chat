from __future__ import annotations

import base64
import time

from app.auth import user_identity
from app.db import database as dbq


def _create_session(client, headers, name="Neue Session"):
    res = client.post("/api/sessions", json={"name": name}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_session_crud(client, auth_headers):
    s = _create_session(client, auth_headers)
    assert s["name"] == "Neue Session"
    assert s["messages"] == []

    listing = client.get("/api/sessions", headers=auth_headers).json()
    assert [x["id"] for x in listing] == [s["id"]]

    renamed = client.patch(f"/api/sessions/{s['id']}", json={"name": "Projekt"}, headers=auth_headers)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Projekt"

    detail = client.get(f"/api/sessions/{s['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["name"] == "Projekt"

    res = client.delete(f"/api/sessions/{s['id']}", headers=auth_headers)
    assert res.status_code == 204
    assert client.get("/api/sessions", headers=auth_headers).json() == []


def test_sessions_require_auth(client):
    assert client.get("/api/sessions").status_code == 401
    assert client.post("/api/sessions", json={}).status_code == 401


def test_sessions_are_isolated_per_user(client, auth_headers, app):
    from tests.conftest import login_client

    s = _create_session(client, auth_headers, "Nur Alice")
    other_client = login_client(app, "bob@example.com")
    assert other_client.get("/api/sessions").json() == []
    assert other_client.get(f"/api/sessions/{s['id']}").status_code == 404


def test_add_message_auto_renames_session(client, auth_headers):
    s = _create_session(client, auth_headers)
    res = client.post(
        f"/api/sessions/{s['id']}/messages",
        json={"role": "user", "text": "Was ist die Hauptstadt von Frankreich?"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    msg = res.json()
    assert msg["id"] >= 1 and msg["role"] == "user" and msg["in_context"] is True
    detail = client.get(f"/api/sessions/{s['id']}", headers=auth_headers).json()
    assert detail["name"] == "Was ist die Hauptstadt von Frankreich?"[:40]
    assert len(detail["messages"]) == 1


def test_message_update_and_delete(client, auth_headers):
    s = _create_session(client, auth_headers)
    m = client.post(
        f"/api/sessions/{s['id']}/messages",
        json={"role": "user", "text": "Hallo"},
        headers=auth_headers,
    ).json()
    patched = client.patch(
        f"/api/sessions/{s['id']}/messages/{m['id']}", json={"in_context": False}, headers=auth_headers
    )
    assert patched.status_code == 200
    assert patched.json()["in_context"] is False
    res = client.delete(f"/api/sessions/{s['id']}/messages/{m['id']}", headers=auth_headers)
    assert res.status_code == 204
    assert client.get(f"/api/sessions/{s['id']}", headers=auth_headers).json()["messages"] == []


def test_message_on_missing_session_404(client, auth_headers):
    res = client.post("/api/sessions/unknown/messages", json={"role": "user", "text": "x"}, headers=auth_headers)
    assert res.status_code == 404


def test_sessions_listed_newest_first(client, auth_headers):
    first = _create_session(client, auth_headers, "Erste")
    time.sleep(0.02)  # ts hat ms-Aufloesung
    second = _create_session(client, auth_headers, "Zweite")
    listing = client.get("/api/sessions", headers=auth_headers).json()
    assert [x["id"] for x in listing] == [second["id"], first["id"]]


def test_rename_validation_and_404(client, auth_headers):
    s = _create_session(client, auth_headers, "Projekt")
    # Leerer oder reiner Whitespace-Name behaelt den alten Namen (kein 422, kein Leerstring)
    for empty in ("", "   "):
        res = client.patch(f"/api/sessions/{s['id']}", json={"name": empty}, headers=auth_headers)
        assert res.status_code == 200, res.text
        assert res.json()["name"] == "Projekt"
    # Zu langer Name wird abgelehnt
    res = client.patch(f"/api/sessions/{s['id']}", json={"name": "x" * 121}, headers=auth_headers)
    assert res.status_code == 422
    assert client.get(f"/api/sessions/{s['id']}", headers=auth_headers).json()["name"] == "Projekt"
    # Unbekannte Session -> 404
    assert client.patch("/api/sessions/unknown", json={"name": "x"}, headers=auth_headers).status_code == 404
    assert client.delete("/api/sessions/unknown", headers=auth_headers).status_code == 404


def test_message_patch_and_delete_unknown_id_404(client, auth_headers):
    s = _create_session(client, auth_headers)
    res = client.patch(f"/api/sessions/{s['id']}/messages/9999", json={"in_context": False}, headers=auth_headers)
    assert res.status_code == 404
    res = client.delete(f"/api/sessions/{s['id']}/messages/9999", headers=auth_headers)
    assert res.status_code == 404


def test_delete_session_cascades_messages_and_attachments(client, auth_headers, app, config):
    s = _create_session(client, auth_headers)
    client.post(
        f"/api/sessions/{s['id']}/messages",
        json={"role": "user", "text": "Hallo"},
        headers=auth_headers,
    )
    res = client.post(
        f"/api/sessions/{s['id']}/attachments",
        json={"name": "a.txt", "type": "text/plain", "data": base64.b64encode(b"hi").decode()},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text

    assert client.delete(f"/api/sessions/{s['id']}", headers=auth_headers).status_code == 204

    user = user_identity(config.secret, "alice@example.com")
    with app.state.db.user_db(user) as con:
        assert dbq.q_get_session(con, s["id"]) is None
        assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0


def test_messages_are_isolated_per_user(client, auth_headers, app):
    from tests.conftest import login_client

    s = _create_session(client, auth_headers, "Nur Alice")
    m = client.post(
        f"/api/sessions/{s['id']}/messages",
        json={"role": "user", "text": "Geheim"},
        headers=auth_headers,
    ).json()

    bob = login_client(app, "bob@example.com")
    assert bob.patch(
        f"/api/sessions/{s['id']}/messages/{m['id']}", json={"text": "gehackt"}
    ).status_code == 404
    assert bob.delete(f"/api/sessions/{s['id']}/messages/{m['id']}").status_code == 404
    assert bob.post(
        f"/api/sessions/{s['id']}/messages", json={"role": "user", "text": "x"}
    ).status_code == 404

    # Alice sieht ihre Nachricht unveraendert
    detail = client.get(f"/api/sessions/{s['id']}", headers=auth_headers).json()
    assert [msg["text"] for msg in detail["messages"]] == ["Geheim"]
