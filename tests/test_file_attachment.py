"""Beispiel-Unit-Test fuer Datei-Anhaenge (Textdateien) im Chat-Request.

Nutzt eine echte Datei (tests/fixtures/lorem_ipsum.txt, 20 Zeilen Lorem ipsum)
und prueft, dass der komplette Dateiinhalt unverkuerzt im Request an das LLM
und in der persistierten Session landet.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

RealAsyncClient = httpx.AsyncClient

FIXTURE = Path(__file__).with_name("fixtures") / "lorem_ipsum.txt"

SSE_BODY = b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'


def _mock_llm(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=SSE_BODY)

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.chat.httpx.AsyncClient", factory)
    return seen


def test_text_file_reaches_llm_request_untruncated(client, auth_headers, monkeypatch):
    """Die komplette Textdatei landet als Text-Content-Part im LLM-Request (alle 20 Zeilen)."""
    seen = _mock_llm(monkeypatch)
    content = FIXTURE.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert len(lines) == 20
    # Content-Part exakt so gebaut wie static/js/payload.js aus einem Text-Anhang
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": f"[Datei: lorem_ipsum.txt]\n{content}"},
            {"type": "text", "text": "Was steht in der Datei?"},
        ],
    }
    res = client.post("/api/chat", json={"model": "m", "messages": [message]}, headers=auth_headers)
    assert res.status_code == 200
    sent_parts = seen["body"]["messages"][0]["content"]
    assert sent_parts[1] == {"type": "text", "text": "Was steht in der Datei?"}
    sent_file = sent_parts[0]["text"]
    assert sent_file == f"[Datei: lorem_ipsum.txt]\n{content}"
    for line in lines:
        assert line in sent_file


def test_text_file_attachment_persisted_untruncated(client, auth_headers):
    """Der Anhang wird vollstaendig in der Session gespeichert (kein serverseitiges Abschneiden)."""
    content = FIXTURE.read_text(encoding="utf-8")
    sid = client.post("/api/sessions", json={"name": "Dateitest"}, headers=auth_headers).json()["id"]
    attachment = {"name": "lorem_ipsum.txt", "type": "text/plain", "text": content}
    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={
            "role": "user",
            "type": "message",
            "text": "lies die Datei",
            "in_context": True,
            "attachments": [attachment],
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    detail = client.get(f"/api/sessions/{sid}", headers=auth_headers).json()
    stored = detail["messages"][0]["attachments"][0]["text"]
    assert stored == content
    assert len(stored.splitlines()) == 20
