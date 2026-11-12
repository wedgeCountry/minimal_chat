"""Minimaler Mock eines OpenAI-kompatiblen Endpunkts fuer die GUI-Tests.

Start: ``uvicorn mock_llm:app --port <port>`` (aus diesem Verzeichnis).
Antwortet auf ``POST /v1/chat/completions`` mit einem SSE-Stream, der
reasoning_content, content und einen tool_call enthaelt.
"""

from __future__ import annotations

import asyncio
import json


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    
    # Handle HEAD requests for connectivity check
    if scope["method"] == "HEAD":
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b"", "more_body": False})
        return
    
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break

    if scope["path"].endswith("/chat/completions"):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/event-stream"),
                    (b"cache-control", b"no-cache"),
                ],
            }
        )
        try:
            req = json.loads(body)
            last = req.get("messages", [])[-1] if req.get("messages") else {}
            content = last.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(p.get("text", "")) for p in content)
            file_read = "Krokodil-Ledertasche" in str(content)
            lorem_read = "Lorem ipsum dolor sit amet" in str(content)
        except Exception:
            file_read = False
            lorem_read = False
        if file_read:
            # Der Datei-Anhang der letzten Nachricht wurde als Text mitgeschickt:
            # das LLM "liest" ihn und antwortet mit dem geheimen Wort.
            chunks = [
                {"choices": [{"delta": {"content": "Die Datei enthält das geheime Wort: Krokodil-Ledertasche"}}]},
            ]
        elif lorem_read:
            chunks = [
                {"choices": [{"delta": {"content": "Die Datei enthält Lorem ipsum (20 Zeilen)."}}]},
            ]
        elif "langsam" in str(content):
            # Langsamer Stream mit Pause: zum Testen des Abbruchs (Teilausgabe bleibt erhalten)
            chunks = [
                {"choices": [{"delta": {"content": "Teil A "}}]},
                {"choices": [{"delta": {"content": "Teil B"}}]},
            ]
        elif "lang" in str(content):
            # Lange mehrzeilige Antwort: zum Testen des Bubble-Clamp-Zyklus
            chunks = [
                {"choices": [{"delta": {"content": "\n".join(f"Zeile {i}" for i in range(1, 16))}}]},
            ]
        else:
            chunks = [
                {"choices": [{"delta": {"reasoning_content": "Ich denke nach... "}}]},
                {"choices": [{"delta": {"content": "Hallo"}}]},
                {"choices": [{"delta": {"content": " Welt"}}]},
                {"choices": [{"delta": {"tool_calls": [{"function": {"name": "get_weather", "arguments": '{"city":"Berlin"}'}}]}}]},
            ]
        slow = "langsam" in str(content)
        for chunk in chunks:
            await send(
                {
                    "type": "http.response.body",
                    "body": ("data: " + json.dumps(chunk) + "\n\n").encode(),
                    "more_body": True,
                }
            )
            await asyncio.sleep(10.0 if slow else 0.02)
        await send({"type": "http.response.body", "body": b"data: [DONE]\n\n", "more_body": False})
    else:
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"error":"not found"}', "more_body": False})
