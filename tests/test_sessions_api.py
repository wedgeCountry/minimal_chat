from __future__ import annotations


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


def test_sessions_are_isolated_per_user(client, auth_headers):
    from app.db import crypto

    s = _create_session(client, auth_headers, "Nur Alice")
    other = client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "geheim123", "key": crypto.new_key()},
    )
    other_h = {"Authorization": "Bearer " + other.json()["token"]}
    assert client.get("/api/sessions", headers=other_h).json() == []
    assert client.get(f"/api/sessions/{s['id']}", headers=other_h).status_code == 404


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
