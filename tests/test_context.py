"""Unit-Tests fuer app/services/context.py (LLM-History via trixie_ai.LlmContext)."""

from __future__ import annotations

import json
import time

import httpx

from app.services.context import build_llm_context

RealAsyncClient = httpx.AsyncClient


def _db_row(mid, role, mtype, text, in_context=True, attachments=None):
    """Zeilenform wie q_get_messages / GET /api/sessions/{id} (inkl. ts, session_id)."""
    return {
        "id": mid,
        "session_id": "s1",
        "role": role,
        "type": mtype,
        "text": text,
        "in_context": in_context,
        "attachments": attachments or [],
        "ts": mid * 1000,
    }


def _msg(mid, role, mtype, text, in_context=True, attachments=None):
    return {"id": mid, "role": role, "type": mtype, "text": text, "in_context": in_context, "attachments": attachments or []}


def test_compile_puts_system_prompt_first_then_messages_in_order():
    ctx = build_llm_context(
        [_msg(1, "user", "message", "Hallo"), _msg(2, "assistant", "message", "Hi!")],
        system_prompt="Sei freundlich.",
    )
    assert ctx.compile() == [
        {"role": "system", "content": "Sei freundlich."},
        {"role": "user", "content": "Hallo"},
        {"role": "assistant", "content": "Hi!"},
    ]


def test_toolcall_becomes_assistant_tool_calls_and_toolresult_pairs_as_tool_message():
    msgs = [
        _msg(1, "user", "message", "Wetter in Berlin?"),
        _msg(2, "assistant", "toolcall", 'get_weather({"city":"Berlin"})'),
        _msg(3, "assistant", "toolresult", 'get_weather: {"temp":"21C"}'),
        _msg(4, "assistant", "message", "Es sind 21C in Berlin."),
    ]
    wire = build_llm_context(msgs).compile()
    assert wire[0] == {"role": "user", "content": "Wetter in Berlin?"}
    assert wire[1]["role"] == "assistant"
    assert wire[1]["tool_calls"] == [
        {"id": "call_2", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Berlin"}'}}
    ]
    assert wire[2] == {"role": "tool", "tool_call_id": "call_2", "content": 'get_weather: {"temp":"21C"}'}
    assert wire[3] == {"role": "assistant", "content": "Es sind 21C in Berlin."}


def test_toolcall_json_format_is_parsed():
    import json

    text = json.dumps({"name": "f", "arguments": {"a": 1}})
    wire = build_llm_context([_msg(7, "assistant", "toolcall", text)]).compile()
    assert wire[0]["tool_calls"][0]["function"] == {"name": "f", "arguments": '{"a": 1}'}


def test_reasoning_and_in_context_false_are_excluded():
    msgs = [
        _msg(1, "user", "message", "Hallo"),
        _msg(2, "assistant", "reasoning", "denke...", in_context=False),
        _msg(3, "user", "message", "alt", in_context=False),
    ]
    wire = build_llm_context(msgs).compile()
    assert wire == [{"role": "user", "content": "Hallo"}]


def test_attachments_become_content_parts_and_expand():
    att = {"id": 5, "name": "geheim.txt", "mime": "text/plain", "kind": "text", "size": 3, "content": "abc"}
    msgs = [_msg(1, "user", "message", "lies die Datei", attachments=[{"id": 5, "name": "geheim.txt"}])]
    wire = build_llm_context(msgs, attachments_by_id={5: att}).compile()
    content = wire[0]["content"]
    # reine Text-Parts werden zu einem String verschmolzen (expand_attachment_parts)
    assert isinstance(content, str)
    assert "geheim.txt" in content and "abc" in content and "lies die Datei" in content


# --- DB-Zeilen (q_get_messages-Format) parsen sicher in den Kontext ---


def test_db_rows_with_toolcall_and_toolresult_compile_to_valid_wire_format():
    rows = [
        _db_row(1, "user", "message", "Wetter in Berlin?"),
        _db_row(2, "assistant", "reasoning", "denke...", in_context=False),
        _db_row(3, "assistant", "message", "Es sind 21C."),
        _db_row(4, "assistant", "toolcall", 'get_weather({"city":"Berlin"})'),
        _db_row(5, "assistant", "toolresult", 'get_weather: {"temp":"21C"}'),
        _db_row(6, "system", "message", "Fehler: HTTP 500", in_context=False),
    ]
    wire = build_llm_context(rows, system_prompt="Du bist nett.").compile()
    assert wire[0] == {"role": "system", "content": "Du bist nett."}
    assert wire[1] == {"role": "user", "content": "Wetter in Berlin?"}
    tool_msgs = [m for m in wire if m.get("tool_calls")]
    assert len(tool_msgs) == 1
    tc = tool_msgs[0]["tool_calls"][0]
    assert tc["id"] == "call_4"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "get_weather"
    assert json.loads(tc["function"]["arguments"]) == {"city": "Berlin"}
    tool_res = [m for m in wire if m["role"] == "tool"]
    assert len(tool_res) == 1
    assert tool_res[0]["tool_call_id"] == "call_4"  # gepaart mit dem Toolcall
    assert "21C" in tool_res[0]["content"]
    # reasoning und System-Fehler (in_context=False) fehlen
    assert not any(m["role"] == "system" and m.get("content") == "Fehler: HTTP 500" for m in wire)
    assert not any(m.get("content") == "denke..." for m in wire)


def test_db_rows_malformed_tool_text_do_not_crash():
    rows = [
        _db_row(1, "assistant", "toolcall", ""),
        _db_row(2, "assistant", "toolcall", "name("),
        _db_row(3, "assistant", "toolcall", "weird"),
        _db_row(4, "assistant", "toolresult", ""),
        _db_row(5, "assistant", "toolresult", "only result"),
        _db_row(6, "user", "message", None),
    ]
    wire = build_llm_context(rows).compile()
    tool_calls = [m for m in wire if m.get("tool_calls")]
    assert len(tool_calls) == 3
    assert tool_calls[0]["tool_calls"][0]["function"]["arguments"] == "{}"
    tool_res = [m for m in wire if m["role"] == "tool"]
    assert len(tool_res) == 2  # beide Results gepaart (FIFO)
    assert wire[-1] == {"role": "user", "content": ""}


def test_empty_system_message_is_never_sent_to_llm():
    rows = [
        _db_row(1, "system", "message", ""),
        _db_row(2, "system", "message", "   "),
        _db_row(3, "user", "message", "Hallo"),
    ]
    wire = build_llm_context(rows).compile()
    assert wire == [{"role": "user", "content": "Hallo"}]


def test_db_session_messages_roundtrip_through_api(client, auth_headers, monkeypatch):
    """End-to-end: Toolcall/Toolresult landen in der DB und werden beim naechsten
    Request als gueltige tool_calls-/tool-Messages an das LLM geschickt."""
    sse = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"get_weather","arguments":"{\\"city\\":\\"Berlin\\"}"}}]}}]}\n\n'
        b'data: {"choices":[{"delta":{"tool_results":[{"index":0,"name":"get_weather","result":"{\\"temp\\":\\"21C\\"}"}]}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"Es sind 21C in Berlin."}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", factory)

    sid = client.post("/api/sessions", json={"name": "ctx"}, headers=auth_headers).json()["id"]
    client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "type": "message", "text": "Wetter in Berlin?", "in_context": True},
        headers=auth_headers,
    )
    res = client.post("/api/chat", json={"session_id": sid, "model": "m"}, headers=auth_headers)
    assert res.status_code == 202

    deadline = time.time() + 10
    while time.time() < deadline:
        detail = client.get(f"/api/sessions/{sid}", headers=auth_headers).json()
        if not detail["generating"]:
            break
        time.sleep(0.05)

    # naechster Request baut den Kontext aus den DB-Nachrichten
    seen.clear()
    client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "type": "message", "text": "Und morgen?", "in_context": True},
        headers=auth_headers,
    )
    res = client.post("/api/chat", json={"session_id": sid, "model": "m"}, headers=auth_headers)
    assert res.status_code == 202
    deadline = time.time() + 10
    while time.time() < deadline:
        if not client.get(f"/api/sessions/{sid}", headers=auth_headers).json()["generating"]:
            break
        time.sleep(0.05)

    msgs = seen["body"]["messages"]
    assert msgs[0] == {"role": "user", "content": "Wetter in Berlin?"}
    tc_msgs = [m for m in msgs if m.get("tool_calls")]
    assert len(tc_msgs) == 1 and tc_msgs[0]["role"] == "assistant"
    assert tc_msgs[0]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert json.loads(tc_msgs[0]["tool_calls"][0]["function"]["arguments"]) == {"city": "Berlin"}
    tool_res = [m for m in msgs if m["role"] == "tool"]
    assert len(tool_res) == 1
    assert tool_res[0]["tool_call_id"] == tc_msgs[0]["tool_calls"][0]["id"]
    assert "21C" in tool_res[0]["content"]
    assert {"role": "assistant", "content": "Es sind 21C in Berlin."} in msgs
    assert msgs[-1] == {"role": "user", "content": "Und morgen?"}
