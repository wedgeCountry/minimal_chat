from __future__ import annotations

import re

from tests.conftest import TEST_PASSWORD


def _csrf_token(client, page="/auth/login"):
    """Holt den CSRF-Token aus einer Auth-Seite (Cookie + Header muessen uebereinstimmen)."""
    res = client.get(page)
    assert res.status_code == 200, page
    return re.search(r'window\.CSRF_TOKEN = "([^"]+)"', res.text).group(1)


def _register(client, email, password=TEST_PASSWORD):
    token = _csrf_token(client, "/auth/register")
    return client.post(
        "/auth/api/register",
        json={
            "email": email,
            "password": password,
            "confirm_password": password,
            "display_name": email.split("@", 1)[0],
            "accepted_terms": True,
        },
        headers={"X-CSRF-Token": token},
    )


def _login(client, email, password=TEST_PASSWORD):
    token = _csrf_token(client, "/auth/login")
    return client.post(
        "/auth/api/login",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": token},
    )


def test_register_sets_session_cookie(client):
    res = _register(client, "bob@example.com")
    assert res.status_code == 200, res.text
    assert res.json()["email"] == "bob@example.com"
    assert "auth_session" in res.cookies
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"email": "bob@example.com", "username": "bob"}


def test_register_duplicate_email_conflict(client, auth_headers):
    res = _register(client, "alice@example.com")
    assert res.status_code == 409


def test_register_rejects_weak_password(client):
    res = _register(client, "carol@example.com", "kurz")
    assert res.status_code == 422


def test_register_rejects_invalid_email(client):
    res = _register(client, "keine-mail")
    assert res.status_code == 422


def test_login_success_and_failure(client, auth_headers):
    ok = _login(client, "alice@example.com")
    assert ok.status_code == 200
    assert ok.json()["email"] == "alice@example.com"
    bad = _login(client, "alice@example.com", "Falsch-123")
    assert bad.status_code == 401
    unknown = _login(client, "niemand@example.com")
    assert unknown.status_code == 401


def test_me_requires_session(client):
    assert client.get("/api/auth/me").status_code == 401
    _register(client, "alice@example.com")
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
