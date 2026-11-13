"""Unit-Tests fuer serverseitige Datei-Verarbeitung (Anhaenge).

Der Client laedt die Rohdatei per Multipart-Upload hoch (POST /api/sessions/{sid}/attachments),
der Server liest/dekodiert sie und expandiert die Referenz beim LLM-Request.
Nutzt eine echte Datei (tests/fixtures/lorem_ipsum.txt, 20 Zeilen Lorem ipsum).
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

import httpx
import pytest

from app.services.files import UploadTooLarge, expand_attachment_parts, is_text_file, process_upload, read_upload_capped

RealAsyncClient = httpx.AsyncClient

FIXTURE = Path(__file__).with_name("fixtures") / "lorem_ipsum.txt"

SSE_BODY = b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'


def _mock_llm(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=SSE_BODY)

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", factory)
    return seen


def _wait_generation(client, auth_headers, sid: str, timeout: float = 10.0) -> dict:
    """Pollt die Session, bis die serverseitige Generierung fertig ist."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        res = client.get(f"/api/sessions/{sid}", headers=auth_headers)
        assert res.status_code == 200, res.text
        last = res.json()
        if not last["generating"]:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Generierung wurde nicht fertig (letzter Stand: {last})")


def _new_session(client, auth_headers, name="Dateitest") -> str:
    res = client.post("/api/sessions", json={"name": name}, headers=auth_headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _upload(client, auth_headers, sid: str, name: str, mime: str, raw: bytes) -> dict:
    res = client.post(
        f"/api/sessions/{sid}/attachments",
        files={"file": (name, raw, mime)},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_is_text_file_detection():
    assert is_text_file("a.txt", "text/plain") is True
    assert is_text_file("a.json", "application/json") is True
    assert is_text_file("a.json", "application/vnd.api+json") is True
    assert is_text_file("notes.md", "") is True
    assert is_text_file("script.py", "") is True
    assert is_text_file("doc.pdf", "application/pdf") is False
    assert is_text_file("x.png", "image/png") is False
    assert is_text_file("data.bin", "") is False


def test_process_upload_reads_text_file_utf8_untruncated():
    content = FIXTURE.read_text(encoding="utf-8")
    att = process_upload("lorem_ipsum.txt", "text/plain", content.encode("utf-8"))
    assert att["kind"] == "text"
    assert att["content"] == content
    assert len(att["content"].splitlines()) == 20


def test_process_upload_marks_oversized_text_explicitly():
    att = process_upload("gross.txt", "text/plain", ("x" * 100_001).encode("utf-8"))
    assert att["kind"] == "text"
    assert len(att["content"]) == 100_000 + len("\n[… gekürzt: Datei zu lang für Inline-Übertragung]")
    assert att["content"].endswith("[… gekürzt: Datei zu lang für Inline-Übertragung]")


def test_process_upload_binary_gets_explicit_note():
    att = process_upload("doc.pdf", "application/pdf", b"%PDF-1.4 fake")
    assert att["kind"] == "binary"
    assert "Binärdatei" in att["content"] and "13 Bytes" in att["content"]
    assert "%PDF" not in att["content"]


def test_process_upload_too_large_raises_upload_too_large():
    with pytest.raises(UploadTooLarge):
        process_upload("a.bin", "application/octet-stream", b"x" * 11, max_bytes=10)


def test_read_upload_capped_streams_and_enforces_limit():
    class FakeUpload:
        def __init__(self, data: bytes):
            self._d = data
            self._i = 0

        async def read(self, n: int) -> bytes:
            if self._i >= len(self._d):
                return b""
            chunk = self._d[self._i : self._i + n]
            self._i += n
            return chunk

    assert asyncio.run(read_upload_capped(FakeUpload(b"12345"), 10)) == b"12345"
    with pytest.raises(UploadTooLarge):
        asyncio.run(read_upload_capped(FakeUpload(b"12345"), 4))


def test_expand_attachment_parts_tolerates_malformed_attachment_id():
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi", "attachment_id": "abc"}]}]
    out = expand_attachment_parts(messages, {})
    assert out[0]["content"] == "hi"  # rein textuelle Parts werden zu einem String verschmolzen


def test_expand_attachment_parts_expands_known_attachment_id():
    atts = {1: {"kind": "text", "name": "a.txt", "content": "INHALT"}}
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi", "attachment_id": 1}]}]
    out = expand_attachment_parts(messages, atts)
    assert out[0]["content"] == "[Datei: a.txt]\nINHALT"


def test_upload_endpoint_stores_attachment(client, auth_headers):
    sid = _new_session(client, auth_headers)
    raw = FIXTURE.read_bytes()
    att = _upload(client, auth_headers, sid, "lorem_ipsum.txt", "text/plain", raw)
    assert att["name"] == "lorem_ipsum.txt"
    assert att["mime"] == "text/plain"
    assert att["kind"] == "text"
    assert att["size"] == len(raw)


def test_upload_endpoint_rejects_oversize_and_unknown_session(client, auth_headers):
    from app.services.files import MAX_UPLOAD_BYTES

    sid = _new_session(client, auth_headers)
    res = client.post(
        f"/api/sessions/{sid}/attachments",
        files={"file": ("gross.bin", b"x" * (MAX_UPLOAD_BYTES + 1), "application/octet-stream")},
        headers=auth_headers,
    )
    assert res.status_code == 413  # Upload-Limit -> 413 (nicht 400)
    res = client.post(
        "/api/sessions/unknown/attachments",
        files={"file": ("x.txt", b"hi", "text/plain")},
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_text_file_reaches_llm_request_untruncated_via_server_processing(client, auth_headers, monkeypatch):
    """Komplette Textdatei (20 Zeilen) landet unverkuerzt im LLM-Request.

    Ablauf wie im Client: Datei hochladen -> Referenz an die Nachricht ->
    /api/chat -> Server expandiert die Referenz serverseitig.
    """
    seen = _mock_llm(monkeypatch)
    content = FIXTURE.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert len(lines) == 20

    sid = _new_session(client, auth_headers)
    att = _upload(client, auth_headers, sid, "lorem_ipsum.txt", "text/plain", content.encode("utf-8"))
    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={
            "role": "user",
            "type": "message",
            "text": "Was steht in der Datei?",
            "in_context": True,
            "attachments": [{"id": att["id"], "name": att["name"], "type": att["mime"]}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 201

    # Payload wie vom Client gebaut (buildChatPayload): Anhang als Referenz-Part
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "[Datei: lorem_ipsum.txt]", "attachment_id": att["id"]},
            {"type": "text", "text": "Was steht in der Datei?"},
        ],
    }
    res = client.post(
        "/api/chat",
        json={"session_id": sid, "model": "m", "messages": [message]},
        headers=auth_headers,
    )
    assert res.status_code == 202

    _wait_generation(client, auth_headers, sid)
    # Rein textuelle Parts werden zu einem String verschmolzen (422-Regression:
    # manche LLM-Server verlangen content als String)
    sent = seen["body"]["messages"][0]["content"]
    assert isinstance(sent, str)
    assert sent == f"[Datei: lorem_ipsum.txt]\n{content}\n\nWas steht in der Datei?"
    for line in lines:
        assert line in sent


def test_binary_attachment_sends_note_not_raw_bytes(client, auth_headers, monkeypatch):
    seen = _mock_llm(monkeypatch)
    sid = _new_session(client, auth_headers)
    raw = b"%PDF-1.4 fake binary \x00\x01\x02"
    att = _upload(client, auth_headers, sid, "doc.pdf", "application/pdf", raw)
    assert att["kind"] == "binary"
    # Chat-History kommt aus der Session-DB: Nachricht mit Anhang zuerst speichern
    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={
            "role": "user",
            "type": "message",
            "text": "was steht da?",
            "in_context": True,
            "attachments": [{"id": att["id"], "name": att["name"], "type": att["mime"]}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    res = client.post(
        "/api/chat",
        json={"session_id": sid, "model": "m"},
        headers=auth_headers,
    )
    assert res.status_code == 202
    _wait_generation(client, auth_headers, sid)
    sent = seen["body"]["messages"][0]["content"]
    assert isinstance(sent, str)
    assert sent.startswith("[Datei: doc.pdf]\n(Binärdatei,")
    assert "%PDF" not in sent


def test_image_attachment_keeps_list_content_with_image_url(client, auth_headers, monkeypatch):
    """Bild-Anhaenge bleiben Listen-Content (image_url-Part), Text-Parts daneben."""
    seen = _mock_llm(monkeypatch)
    sid = _new_session(client, auth_headers)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    att = _upload(client, auth_headers, sid, "bild.png", "image/png", png)
    assert att["kind"] == "image"
    # Chat-History kommt aus der Session-DB: Nachricht mit Anhang zuerst speichern
    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={
            "role": "user",
            "type": "message",
            "text": "was ist auf dem Bild?",
            "in_context": True,
            "attachments": [{"id": att["id"], "name": att["name"], "type": att["mime"]}],
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    res = client.post(
        "/api/chat",
        json={"session_id": sid, "model": "m"},
        headers=auth_headers,
    )
    assert res.status_code == 202
    _wait_generation(client, auth_headers, sid)
    sent = seen["body"]["messages"][0]["content"]
    assert isinstance(sent, list)
    assert sent[0] == {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}"}}
    assert sent[1] == {"type": "text", "text": "was ist auf dem Bild?"}
