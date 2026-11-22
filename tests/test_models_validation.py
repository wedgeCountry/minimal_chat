"""Unit-Tests fuer die Pydantic-Validierung der API-Models (app/models.py).

Ungueltige Eingaben muessen mit 422 abgelehnt werden, bevor Router-Code laeuft.
"""

from __future__ import annotations


def _new_session(client, auth_headers) -> str:
    res = client.post("/api/sessions", json={"name": "Val"}, headers=auth_headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_message_rejects_invalid_role(client, auth_headers):
    sid = _new_session(client, auth_headers)
    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "admin", "text": "x"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_message_rejects_invalid_type(client, auth_headers):
    sid = _new_session(client, auth_headers)
    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "type": "banner", "text": "x"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_settings_reject_invalid_theme(client, auth_headers):
    res = client.put("/api/settings", json={"theme": "blue"}, headers=auth_headers)
    assert res.status_code == 422


def test_chat_rejects_missing_fields(client, auth_headers):
    # nur session_id ist Pflicht; Modell/Verbindung kommen serverseitig aus dem Tile
    assert client.post("/api/chat", json={}, headers=auth_headers).status_code == 422
    assert client.post("/api/chat", json={"session_id": "x" * 65}, headers=auth_headers).status_code == 422


def test_chat_message_requires_role_and_content(client, auth_headers):
    sid = _new_session(client, auth_headers)
    res = client.post(
        "/api/chat",
        json={"session_id": sid, "messages": [{"role": "user"}]},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_client_log_rejects_message_over_4000_chars(client, auth_headers):
    res = client.post("/api/log", json={"level": "error", "message": "x" * 4001}, headers=auth_headers)
    assert res.status_code == 422
    res = client.post("/api/log", json={"level": "fatal", "message": "x"}, headers=auth_headers)
    assert res.status_code == 422


def test_message_attachment_requires_id(client, auth_headers):
    sid = _new_session(client, auth_headers)
    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "text": "x", "attachments": [{"name": "a.txt"}]},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_session_name_over_120_chars_rejected(client, auth_headers):
    res = client.post("/api/sessions", json={"name": "x" * 121}, headers=auth_headers)
    assert res.status_code == 422


def test_chat_abort_session_id_over_64_chars_rejected(client, auth_headers):
    res = client.post("/api/chat/abort", json={"session_id": "x" * 65}, headers=auth_headers)
    assert res.status_code == 422
