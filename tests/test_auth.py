from __future__ import annotations

from tests.conftest import TEST_PASSWORD


def test_register_sets_session_cookie(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "bob@example.com", "password": TEST_PASSWORD},
    )
    assert res.status_code == 201
    assert res.json()["email"] == "bob@example.com"
    assert "auth_session" in res.cookies
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "bob@example.com"


def test_register_duplicate_email_conflict(client, auth_headers):
    res = client.post("/api/auth/register", json={"email": "alice@example.com", "password": TEST_PASSWORD})
    assert res.status_code == 409


def test_register_rejects_weak_password(client):
    res = client.post("/api/auth/register", json={"email": "carol@example.com", "password": "kurz"})
    assert res.status_code == 422


def test_register_rejects_invalid_email(client):
    res = client.post("/api/auth/register", json={"email": "keine-mail", "password": TEST_PASSWORD})
    assert res.status_code == 422


def test_login_success_and_failure(client, auth_headers):
    ok = client.post("/api/auth/login", json={"email": "alice@example.com", "password": TEST_PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["email"] == "alice@example.com"
    bad = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "Falsch-123"})
    assert bad.status_code == 401
    unknown = client.post("/api/auth/login", json={"email": "niemand@example.com", "password": TEST_PASSWORD})
    assert unknown.status_code == 401


def test_me_requires_session(client):
    assert client.get("/api/auth/me").status_code == 401
    client.post("/api/auth/register", json={"email": "alice@example.com", "password": TEST_PASSWORD})
    assert client.get("/api/auth/me").status_code == 200


def test_logout_clears_session(client, auth_headers):
    assert client.get("/api/auth/me").status_code == 200
    res = client.post("/api/auth/logout")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert client.get("/api/auth/me").status_code == 401


def test_auth_pages_mounted(client):
    for path in ("/auth/login", "/auth/register", "/auth/terms", "/auth/impressum"):
        assert client.get(path).status_code == 200, path
