"""Minimaler Mock eines OpenAI-kompatiblen Endpunkts fuer die GUI-Tests.

Start: ``uvicorn mock_llm:app --port <port>`` (aus diesem Verzeichnis).
Antwortet auf ``POST /v1/chat/completions`` mit einem SSE-Stream. Standard-Antwort
(in agentenueblicher Reihenfolge): reasoning_content, tool_call, tool_result, content.
Trigger im Text der letzten User-Message: "doppelzyklus" (zwei volle
Reasoning/Toolcall/Toolresult/Message-Zyklen in einem Stream), "langsam" (Abbruch-Test),
"slowtool" (langsamer Stream mit Tool-Call/Tool-Result, Live-Streaming-Test),
"lang" (lange Antwort), "oneline" (eine lange Zeile), Dateiinhalt -> Datei-Antwort.

Ausserdem zeichnet der Mock jeden Request-Body auf: ``GET /received`` liefert die Liste aller
aufgezeichneten ``POST /chat/completions``-Bodies (JSON), ``POST /received/clear`` leert sie -
fuer e2e-Assertions auf den an das LLM gesendeten Kontext.
"""

from __future__ import annotations

import asyncio
import json

# Aufgezeichnete Request-Bodies (nur /chat/completions), siehe GET /received
_received: list[dict] = []


async def _json_response(send, payload: bytes, status: int = 200) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": payload, "more_body": False})


async def app(scope, receive, send):
    if scope["type"] != "http":
        return

    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break

    if scope["method"] == "GET" and scope["path"] == "/received":
        await _json_response(send, json.dumps(_received).encode())
        return
    if scope["method"] == "POST" and scope["path"] == "/received/clear":
        _received.clear()
        await _json_response(send, b'{"ok":true}')
        return

    if scope["path"].endswith("/chat/completions"):
        try:
            req = json.loads(body)
        except Exception:
            req = {}
        _received.append(req)
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
        last = req.get("messages", [])[-1] if req.get("messages") else {}
        content = last.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(p.get("text", "")) for p in content)
        file_read = "Krokodil-Ledertasche" in str(content)
        lorem_read = "Lorem ipsum dolor sit amet" in str(content)
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
        elif "chunky" in str(content):
            # Mehrere Content-Chunks mit Pause dazwischen: zum Testen, dass der Client
            # den Stream stufenweise (bit by bit) sieht
            chunks = [
                {"choices": [{"delta": {"content": "Alpha "}}]},
                {"choices": [{"delta": {"content": "Beta "}}]},
                {"choices": [{"delta": {"content": "Gamma "}}]},
                {"choices": [{"delta": {"content": "Delta"}}]},
            ]
        elif "langsam" in str(content):
            # Langsamer Stream mit Pause: zum Testen des Abbruchs (Teilausgabe bleibt erhalten)
            chunks = [
                {"choices": [{"delta": {"content": "Teil A "}}]},
                {"choices": [{"delta": {"content": "Teil B"}}]},
            ]
        elif "slowtool" in str(content):
            # Langsamer Stream MIT Tool-Call/Tool-Result (je ~0.8 s Pause): zum Testen, dass
            # Tool-Call- und Tool-Result-Bubbles live (waehrend des Streams) im UI erscheinen
            chunks = [
                {"choices": [{"delta": {"reasoning_content": "Ich suche... "}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "web_search", "arguments": '{"q":"Wetter Berlin"}'}}]}}]},
                {"choices": [{"delta": {"tool_results": [{"index": 0, "name": "web_search", "result": "Ergebnis A\\nErgebnis B"}]}}]},
                {"choices": [{"delta": {"content": "Antwort mit Tool-Ergebnis"}}]},
            ]
        elif "lang" in str(content):
            # Lange mehrzeilige Antwort: zum Testen des Bubble-Clamp-Zyklus
            chunks = [
                {"choices": [{"delta": {"content": "\n".join(f"Zeile {i}" for i in range(1, 16))}}]},
            ]
        elif "oneline" in str(content):
            # Eine einzige sehr lange Zeile: collapsed darf nur eine GUI-Zeile zeigen
            chunks = [
                {"choices": [{"delta": {"content": "Lorem ipsum dolor sit amet " * 40}}]},
            ]
        elif "doppelzyklus" in str(content):
            # Zwei volle Zyklen in einem Stream: Reasoning, Toolcall, Toolresult, Message,
            # dann nochmals Reasoning, Toolcall, Toolresult, Message
            chunks = [
                {"choices": [{"delta": {"reasoning_content": "Denken eins... "}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "get_weather", "arguments": '{"city":"Berlin"}'}}]}}]},
                {"choices": [{"delta": {"tool_results": [{"index": 0, "name": "get_weather", "result": "21 Grad, sonnig"}]}}]},
                {"choices": [{"delta": {"content": "Antwort eins"}}]},
                {"choices": [{"delta": {"reasoning_content": "Denken zwei... "}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 1, "function": {"name": "get_time", "arguments": '{"tz":"Europe/Berlin"}'}}]}}]},
                {"choices": [{"delta": {"tool_results": [{"index": 1, "name": "get_time", "result": "12:00 Uhr"}]}}]},
                {"choices": [{"delta": {"content": "Antwort zwei"}}]},
            ]
        else:
            chunks = [
                {"choices": [{"delta": {"reasoning_content": "Ich denke nach... "}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "get_weather", "arguments": '{"city":"Berlin"}'}}]}}]},
                {"choices": [{"delta": {"tool_results": [{"index": 0, "name": "get_weather", "result": "Z1\\nZ2\\nZ3"}]}}]},
                {"choices": [{"delta": {"content": "Hallo"}}]},
                {"choices": [{"delta": {"content": " Welt"}}]},
            ]
        text = str(content)
        slow = "langsam" in text
        chunky = "chunky" in text
        slowtool = "slowtool" in text
        delay = 10.0 if slow else (0.8 if slowtool else (0.4 if chunky else 0.02))
        for chunk in chunks:
            await send(
                {
                    "type": "http.response.body",
                    "body": ("data: " + json.dumps(chunk) + "\n\n").encode(),
                    "more_body": True,
                }
            )
            await asyncio.sleep(delay)
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
