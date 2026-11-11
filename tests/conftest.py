from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.auth import TERMS_VERSION, display_name_from_email
from app.config import AppConfig
from app.main import create_app

TEST_PASSWORD = "Geheim-123"


@pytest.fixture()
def config(tmp_path):
    """App-Config komplett ueber das Objekt gesteuert - keine Systemvariablen noetig."""
    data = tmp_path / "data"
    return AppConfig(
        data_dir=data,
        secret="test-secret",
        registry_path=data / "user_registry.db",
        users_dir=data / "users",
        default_llm_host="llm.test",
        default_llm_port="",
        default_api_key="test-api-key",
    )


@pytest.fixture()
def app(config):
    return create_app(config=config)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def register_user(app, email: str, password: str = TEST_PASSWORD) -> None:
    """Legt einen User direkt in der Registry an (ohne HTTP-Login)."""
    if not app.state.registry.user_exists(email):
        app.state.registry.create_user(email, password, display_name_from_email(email), TERMS_VERSION)


def login_via_api(client, email: str, password: str = TEST_PASSWORD) -> None:
    """Echter Login ueber die user_registry-API (CSRF-Token aus der Login-Seite);
    der Client haelt danach den Session-Cookie."""
    res = client.get("/auth/login")
    token = re.search(r'window\.CSRF_TOKEN = "([^"]+)"', res.text).group(1)
    res = client.post(
        "/auth/api/login",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": token},
    )
    assert res.status_code == 200, res.text


def login_client(app, email: str = "alice@example.com", password: str = TEST_PASSWORD) -> TestClient:
    """TestClient mit gueltigem Session-Cookie fuer ``email``."""
    register_user(app, email, password)
    client = TestClient(app)
    login_via_api(client, email, password)
    return client


@pytest.fixture()
def auth_headers(app, client):
    """Meldet alice@example.com im TestClient an; danach genuegen leere Headers."""
    register_user(app, "alice@example.com")
    login_via_api(client, "alice@example.com")
    return {}
