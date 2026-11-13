"""Security-Tests: SSRF-Schutz fuer LLM-URLs, Security-Header, Request-Size-Limit, TLS-Cookie."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from app.services.chat import validate_llm_base_url
from tests.conftest import TEST_PASSWORD, login_client, register_user


# --- validate_llm_base_url (Unit; IP-Literale brauchen kein DNS) ---


def test_validate_allows_public_ip_literals():
    assert validate_llm_base_url("http://8.8.8.8:1234/v1", allow_private=False) == "http://8.8.8.8:1234/v1"
    assert validate_llm_base_url("https://1.1.1.1/v1", allow_private=False) == "https://1.1.1.1/v1"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:1234/v1",
        "http://localhost:1234/v1",
        "http://169.254.169.254/v1",  # Cloud-Metadata
        "http://10.0.0.5/v1",
        "http://192.168.1.10:8000/v1",
        "http://100.64.0.1/v1",  # CGNAT shared range
        "http://[::1]/v1",
        "http://0.0.0.0/v1",
    ],
)
def test_validate_blocks_private_and_reserved_targets(url):
    with pytest.raises(ValueError):
        validate_llm_base_url(url, allow_private=False)


@pytest.mark.parametrize("url", ["http://127.0.0.1:1234/v1", "http://169.254.169.254/v1", "http://10.0.0.5/v1"])
def test_validate_allows_private_targets_only_with_flag(url):
    assert validate_llm_base_url(url, allow_private=True) == url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://8.8.8.8/v1",
        "file:///etc/passwd",
        "http:///v1",
        "not-a-url",
        "http://user:pass@8.8.8.8/v1",  # Credentials in URL
        "http://8.8.8.8:abc/v1",  # kaputter Port
    ],
)
def test_validate_rejects_malformed_urls(url):
    with pytest.raises(ValueError):
        validate_llm_base_url(url, allow_private=False)


def test_validate_blocks_unresolvable_host():
    with pytest.raises(ValueError):
        validate_llm_base_url("http://does-not-exist.invalid/v1", allow_private=False)


# --- Router-Ebene: oeffentlicher Bind blockiert private LLM-Ziele (SSRF) ---


def _public_client(tmp_path, email="eve@example.com"):
    """App mit oeffentlichem Bind (0.0.0.0) -> allow_private_llm aus."""
    data = tmp_path / "data"
    cfg = AppConfig(
        data_dir=data,
        secret="sec",
        registry_path=data / "user_registry.db",
        users_dir=data / "users",
        host="0.0.0.0",
    )
    assert cfg.allow_private_llm is False
    return login_client(create_app(config=cfg), email)


def test_loopback_bind_auto_allows_private_llm(client, app):
    """Test-App bindet 127.0.0.1 -> private LLM-Ziele bleiben erlaubt (Dev-Default)."""
    assert app.state.config.host == "127.0.0.1"
    assert app.state.config.allow_private_llm is True


def test_chat_rejects_private_llm_target_on_public_bind(tmp_path):
    c = _public_client(tmp_path)
    sid = c.post("/api/sessions", json={"name": "S"}).json()["id"]
    c.put("/api/settings", json={"host": "169.254.169.254", "port": "80"})
    res = c.post("/api/chat", json={"session_id": sid, "model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 400
    assert "blockiert" in res.json()["detail"]


def test_settings_test_rejects_private_base_on_public_bind(tmp_path):
    c = _public_client(tmp_path)
    res = c.post("/api/settings/test", json={"base": "http://127.0.0.1:1234/v1"})
    assert res.status_code == 400


def test_chat_rejects_malformed_base_url(client, auth_headers):
    sid_res = client.post("/api/sessions", json={"name": "S"}, headers=auth_headers)
    sid = sid_res.json()["id"]
    client.put("/api/settings", json={"base": "file:///etc/passwd"}, headers=auth_headers)
    res = client.post("/api/chat", json={"session_id": sid, "model": "m", "messages": [{"role": "user", "content": "x"}]}, headers=auth_headers)
    assert res.status_code == 400


# --- Security-Header ---


def test_security_headers_on_app_pages(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    csp = res.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp  # App braucht keine Inline-Skripte
    assert "Strict-Transport-Security" not in res.headers  # ohne TLS kein HSTS


def test_auth_pages_get_relaxed_csp_for_inline_csrf_script(client):
    res = client.get("/auth/login")
    assert res.status_code == 200
    csp = res.headers["Content-Security-Policy"]
    assert "script-src 'self' 'unsafe-inline'" in csp


def test_hsts_and_secure_session_cookie_with_tls(tmp_path):
    data = tmp_path / "data"
    cfg = AppConfig(
        data_dir=data,
        secret="s",
        registry_path=data / "r.db",
        users_dir=data / "u",
        ssl_certfile=Path("cert.pem"),  # muss nicht existieren (nur Flag)
        ssl_keyfile=Path("key.pem"),
    )
    app = create_app(config=cfg)
    # https-Basis-URL: Secure-Cookies werden nur ueber HTTPS vom Client zurueckgesendet
    with TestClient(app, base_url="https://testserver") as c:
        res = c.get("/")
        assert res.headers["Strict-Transport-Security"].startswith("max-age=")
        register_user(app, "tls@example.com")
        page = c.get("/auth/login")
        token = re.search(r'window\.CSRF_TOKEN = "([^"]+)"', page.text).group(1)
        res = c.post(
            "/auth/api/login",
            json={"email": "tls@example.com", "password": TEST_PASSWORD},
            headers={"X-CSRF-Token": token},
        )
        assert res.status_code == 200
        assert "Secure" in res.headers.get("set-cookie", "")


def test_session_cookie_has_no_secure_flag_without_tls(client):
    page = client.get("/auth/login")
    token = re.search(r'window\.CSRF_TOKEN = "([^"]+)"', page.text).group(1)
    register_user(client.app, "nosec@example.com")
    res = client.post(
        "/auth/api/login",
        json={"email": "nosec@example.com", "password": TEST_PASSWORD},
        headers={"X-CSRF-Token": token},
    )
    assert res.status_code == 200
    set_cookie = res.headers.get("set-cookie", "")
    assert "auth_session" in set_cookie
    assert "Secure" not in set_cookie


# --- Globales Request-Size-Limit (Middleware) ---


def test_request_size_limit_returns_413(client, auth_headers, app):
    app.state.config.max_request_bytes = 16
    res = client.post("/api/log", json={"level": "error", "message": "x" * 100}, headers=auth_headers)
    assert res.status_code == 413
    app.state.config.max_request_bytes = 1024 * 1024
    res = client.post("/api/log", json={"level": "error", "message": "ok"}, headers=auth_headers)
    assert res.status_code == 200


def test_request_size_limit_ignores_non_api_paths(client):
    # /auth-Login-Bodies werden nicht vom /api-Limit erfasst (klein gehalten in der Registry)
    res = client.get("/auth/login")
    assert res.status_code == 200
