from __future__ import annotations

import logging


def test_post_client_log_ok(client):
    res = client.post("/api/log", json={"level": "error", "message": "TypeError: boom"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_post_client_log_is_written_to_server_log(client, caplog):
    with caplog.at_level(logging.ERROR, logger="leanchat.client"):
        res = client.post("/api/log", json={"message": "Unhandled promise rejection: kaputt"})
    assert res.status_code == 200
    assert any("kaputt" in r.message for r in caplog.records)


def test_post_client_log_defaults_to_error_level(client):
    res = client.post("/api/log", json={"message": "x"})
    assert res.status_code == 200


def test_post_client_log_rejects_too_long_message(client):
    res = client.post("/api/log", json={"message": "x" * 5000})
    assert res.status_code == 422
