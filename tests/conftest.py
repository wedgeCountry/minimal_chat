from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
        default_llm_base="http://llm.test/v1",
        default_api_key="test-api-key",
    )


@pytest.fixture()
def app(config):
    return create_app(config=config)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client):
    """Registriert alice@example.com; der TestClient haelt anschliessend den
    Session-Cookie, daher genuegen leere Headers."""
    res = client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": TEST_PASSWORD},
    )
    assert res.status_code == 201, res.text
    return {}
