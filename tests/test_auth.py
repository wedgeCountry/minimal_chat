from __future__ import annotations

from app.db import crypto

TEST_PASSWORD = "geheim123"


def test_register_returns_token(client):
    res = client.post(
        "/api/auth/register",
        json={"username": "bob", "password": TEST_PASSWORD, "key": crypto.new_key()},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["username"] == "bob"
    assert body["token"]


def test_register_duplicate_username_conflict(client, auth_headers):
    res = client.post("/api/auth/register", json={"username": "alice", "password": TEST_PASSWORD})
    assert res.status_code == 409


def test_register_rejects_short_password(client):
    res = client.post("/api/auth/register", json={"username": "carol", "password": "kurz"})
    assert res.status_code == 422


def test_login_success_and_failure(client, auth_headers):
    ok = client.post("/api/auth/login", json={"username": "alice", "password": TEST_PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["token"]
    bad = client.post("/api/auth/login", json={"username": "alice", "password": "falsch123"})
    assert bad.status_code == 401
    unknown = client.post("/api/auth/login", json={"username": "niemand", "password": TEST_PASSWORD})
    assert unknown.status_code == 401


def test_me_requires_token(client, auth_headers):
    assert client.get("/api/auth/me").status_code == 401
    res = client.get("/api/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"username": "alice"}


def test_invalid_token_rejected(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage.token"})
    assert res.status_code == 401


def test_logout(client, auth_headers):
    res = client.post("/api/auth/logout", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"ok": True}
