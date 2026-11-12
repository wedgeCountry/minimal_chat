from __future__ import annotations

import logging

from app.routers import log as log_router


def test_post_client_log_requires_auth(client):
    res = client.post("/api/log", json={"level": "error", "message": "TypeError: boom"})
    assert res.status_code == 401


def test_post_client_log_ok(client, auth_headers):
    res = client.post("/api/log", json={"level": "error", "message": "TypeError: boom"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_post_client_log_is_written_to_server_log(client, auth_headers, caplog):
    with caplog.at_level(logging.ERROR, logger="leanchat.client"):
        res = client.post("/api/log", json={"message": "Unhandled promise rejection: kaputt"}, headers=auth_headers)
    assert res.status_code == 200
    assert any("kaputt" in r.message for r in caplog.records)


def test_post_client_log_defaults_to_error_level(client, auth_headers):
    res = client.post("/api/log", json={"message": "x"}, headers=auth_headers)
    assert res.status_code == 200


def test_post_client_log_rejects_too_long_message(client, auth_headers):
    res = client.post("/api/log", json={"message": "x" * 5000}, headers=auth_headers)
    assert res.status_code == 422


def test_post_client_log_is_rate_limited(client, auth_headers):
    log_router._hits.clear()
    for i in range(log_router.RATE_LIMIT):
        res = client.post("/api/log", json={"message": f"m{i}"}, headers=auth_headers)
        assert res.status_code == 200
    res = client.post("/api/log", json={"message": "zu viel"}, headers=auth_headers)
    assert res.status_code == 429
    log_router._hits.clear()
