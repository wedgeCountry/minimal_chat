from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import crypto
from app.main import create_app

TEST_PASSWORD = "geheim123"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("LEANCHAT_API_KEY", "test-api-key")
    monkeypatch.setenv("LEANCHAT_LLM_BASE", "http://llm.test/v1")
    return create_app(data_dir=tmp_path / "data", secret="test-secret")


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client):
    res = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": TEST_PASSWORD, "key": crypto.new_key()},
    )
    assert res.status_code == 201, res.text
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}
