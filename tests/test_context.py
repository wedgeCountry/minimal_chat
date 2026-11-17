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
    wire = build_llm_context([
        _msg(7, "assistant", "toolcall", text),
        _msg(8, "assistant", "toolresult", "f: ok"),
    ]).compile()
    assert wire[0]["tool_calls"][0]["function"] == {"name": "f", "arguments": '{"a": 1}'}
    assert wire[1] == {"role": "tool", "tool_call_id": "call_7", "content": "f: ok"}


def test_reasoning_and_in_context_false_are_excluded():
    msgs = [
        _msg(1, "user", "message", "Hallo"),
        _msg(2, "assistant", "reasoning", "denke...", in_context=False),
        _msg(3, "user", "message", "alt", in_context=False),
    ]
    wire = build_llm_context(msgs).compile()
    assert wire == [{"role": "user", "content": "Hallo"}]


def test_attachments_become_content_parts_and_expand():
    from app.domain import Attachment
    att = Attachment(id=5, name="geheim.txt", mime="text/plain", kind="text", size=3, content="abc")
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
    # alle gepaarten Calls landen in EINEM assistant-Message; der dritte Call hat kein
    # Result und wird verworfen (kein ungueltiges dangling tool_calls im Request)
    assert len(tool_calls) == 1
    assert len(tool_calls[0]["tool_calls"]) == 2
    assert tool_calls[0]["tool_calls"][0]["function"]["arguments"] == "{}"
    tool_res = [m for m in wire if m["role"] == "tool"]
    assert len(tool_res) == 2  # beide Results gepaart (FIFO)
    assert {r["tool_call_id"] for r in tool_res} == {c["id"] for c in tool_calls[0]["tool_calls"]}
    assert wire[-1] == {"role": "user", "content": ""}


def test_parallel_toolcalls_compile_to_one_assistant_message_with_all_tool_calls():
    """Deep-Research-Stream mit parallelen Toolcalls: tool_calls [0,1] in einem Delta,
    danach tool_results [0,1] -> DB-Reihenfolge toolcall, toolcall, toolresult, toolresult.
    Daraus muss EIN assistant-Message mit beiden tool_calls direkt gefolgt von beiden
    tool-Messages werden (sonst 422 bzw. das Modell sieht die Ergebnisse nicht)."""
    rows = [
        _db_row(1, "user", "message", "Recherchiere X"),
        _db_row(2, "assistant", "toolcall", 'search({"q":"a"})'),
        _db_row(3, "assistant", "toolcall", 'search({"q":"b"})'),
        _db_row(4, "assistant", "toolresult", "search: ERGEBNIS A"),
        _db_row(5, "assistant", "toolresult", "search: ERGEBNIS B"),
        _db_row(6, "assistant", "message", "Zusammenfassung"),
        _db_row(7, "user", "message", "Was kam bei A raus?"),
    ]
    wire = build_llm_context(rows).compile()
    tool_call_msgs = [m for m in wire if m.get("tool_calls")]
    assert len(tool_call_msgs) == 1
    assert [c["id"] for c in tool_call_msgs[0]["tool_calls"]] == ["call_2", "call_3"]
    tool_res = [m for m in wire if m["role"] == "tool"]
    assert [r["tool_call_id"] for r in tool_res] == ["call_2", "call_3"]
    assert [r["content"] for r in tool_res] == ["search: ERGEBNIS A", "search: ERGEBNIS B"]
    # assistant-Message mit tool_calls steht direkt vor seinen tool-Messages
    idx = wire.index(tool_call_msgs[0])
    assert wire[idx + 1]["role"] == "tool" and wire[idx + 2]["role"] == "tool"
    assert wire[0] == {"role": "user", "content": "Recherchiere X"}
    assert wire[-1] == {"role": "user", "content": "Was kam bei A raus?"}


def test_deselected_toolresult_drops_whole_tool_group_instead_of_dangling_tool_calls():
    """Nur die Toolresult-Bubbles abwaehlen: der zugehoerige Toolcall darf nicht als
    assistant-Message mit unbeantworteten tool_calls im Request landen (422)."""
    rows = [
        _db_row(1, "user", "message", "Recherchiere X"),
        _db_row(2, "assistant", "toolcall", 'search({"q":"a"})'),
        _db_row(3, "assistant", "toolcall", 'search({"q":"b"})'),
        _db_row(4, "assistant", "toolresult", "search: ERGEBNIS A", in_context=False),
        _db_row(5, "assistant", "toolresult", "search: ERGEBNIS B", in_context=False),
        _db_row(6, "user", "message", "Was kam bei A raus?"),
    ]
    wire = build_llm_context(rows).compile()
    assert not any(m.get("tool_calls") for m in wire)
    assert not any(m["role"] == "tool" for m in wire)
    assert [m["role"] for m in wire] == ["user", "user"]


def test_partially_deselected_results_keep_only_complete_pairs():
    """Von zwei parallelen Toolcalls nur ein Result im Kontext: nur das vollstaendige
    Paar (erster Call + erstes Result) wird gesendet, das Request bleibt gueltig."""
    rows = [
        _db_row(1, "user", "message", "Recherchiere X"),
        _db_row(2, "assistant", "toolcall", 'search({"q":"a"})'),
        _db_row(3, "assistant", "toolcall", 'search({"q":"b"})'),
        _db_row(4, "assistant", "toolresult", "search: ERGEBNIS A"),
        _db_row(5, "assistant", "toolresult", "search: ERGEBNIS B", in_context=False),
    ]
    wire = build_llm_context(rows).compile()
    tool_call_msgs = [m for m in wire if m.get("tool_calls")]
    assert len(tool_call_msgs) == 1
    assert [c["id"] for c in tool_call_msgs[0]["tool_calls"]] == ["call_2"]
    tool_res = [m for m in wire if m["role"] == "tool"]
    assert len(tool_res) == 1 and tool_res[0]["tool_call_id"] == "call_2"
    assert tool_res[0]["content"] == "search: ERGEBNIS A"


def test_toolresult_without_preceding_toolcall_is_skipped():
    """Eine tool-Message ohne passenden tool_call ist ungueltig (422 bei strikten Servern)."""
    rows = [
        _db_row(1, "assistant", "toolresult", "f: ok"),
        _db_row(2, "user", "message", "Hallo"),
    ]
    wire = build_llm_context(rows).compile()
    assert [m["role"] for m in wire] == ["user"]


def test_excluded_toolcall_drops_its_toolresult_from_wire():
    """Kontext-Checkbox am Tool-Call abwaehlen -> Tool-Result landet nicht als orphan im Request."""
    rows = [
        _db_row(1, "user", "message", "Wetter in Berlin?"),
        _db_row(2, "assistant", "toolcall", 'get_weather({"city":"Berlin"})', in_context=False),
        _db_row(3, "assistant", "toolresult", "get_weather: 21C", in_context=True),
        _db_row(4, "assistant", "message", "Es sind 21C."),
    ]
    wire = build_llm_context(rows).compile()
    assert not any(m.get("tool_calls") for m in wire)
    assert not any(m["role"] == "tool" for m in wire)
    assert [m["role"] for m in wire] == ["user", "assistant"]


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


def _run_generation(client, auth_headers, sid):
    res = client.post("/api/chat", json={"session_id": sid, "model": "m"}, headers=auth_headers)
    assert res.status_code == 202
    deadline = time.time() + 10
    while time.time() < deadline:
        if not client.get(f"/api/sessions/{sid}", headers=auth_headers).json()["generating"]:
            return
        time.sleep(0.05)
    raise AssertionError("Generierung wurde nicht fertig")


def test_parallel_toolcalls_roundtrip_through_api_stay_valid_for_next_request(client, auth_headers, monkeypatch):
    """Deep-Research-Stream mit parallelen Toolcalls (tool_calls [0,1] in einem Delta,
    dann tool_results [0,1]): Beim naechsten Request muss das Paar als EIN assistant-
    Message mit beiden tool_calls direkt gefolgt von beiden tool-Messages an das LLM
    gehen - sonst lehnt ein strikter Server das Request ab (422) bzw. sieht das Modell
    die langen Tool-Ergebnisse nicht ('nicht genug Kontext')."""
    sse = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"search","arguments":"{\\"q\\":\\"a\\"}"}},{"index":1,"function":{"name":"search","arguments":"{\\"q\\":\\"b\\"}"}}]}}]}\n\n'
        b'data: {"choices":[{"delta":{"tool_results":[{"index":0,"name":"search","result":"ERGEBNIS A"},{"index":1,"name":"search","result":"ERGEBNIS B"}]}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"Zusammenfassung."}}]}\n\n'
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

    sid = client.post("/api/sessions", json={"name": "ctx-parallel"}, headers=auth_headers).json()["id"]
    client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "type": "message", "text": "Recherchiere X", "in_context": True},
        headers=auth_headers,
    )
    _run_generation(client, auth_headers, sid)

    # naechster Request baut den Kontext aus den DB-Nachrichten (Reihenfolge:
    # toolcall, toolcall, toolresult, toolresult)
    seen.clear()
    client.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "type": "message", "text": "Was kam bei A raus?", "in_context": True},
        headers=auth_headers,
    )
    _run_generation(client, auth_headers, sid)

    msgs = seen["body"]["messages"]
    tc_msgs = [m for m in msgs if m.get("tool_calls")]
    assert len(tc_msgs) == 1 and tc_msgs[0]["role"] == "assistant"
    assert [c["id"] for c in tc_msgs[0]["tool_calls"]] == ["call_2", "call_3"]
    assert [c["function"]["name"] for c in tc_msgs[0]["tool_calls"]] == ["search", "search"]
    idx = msgs.index(tc_msgs[0])
    tool_res = [m for m in msgs if m["role"] == "tool"]
    assert len(tool_res) == 2
    assert [r["tool_call_id"] for r in tool_res] == ["call_2", "call_3"]
    assert [r["content"] for r in tool_res] == ["search: ERGEBNIS A", "search: ERGEBNIS B"]
    # tool-Messages folgen direkt auf das assistant-Message mit den tool_calls
    assert msgs[idx + 1]["role"] == "tool" and msgs[idx + 2]["role"] == "tool"
    assert msgs[0] == {"role": "user", "content": "Recherchiere X"}
    assert msgs[-1] == {"role": "user", "content": "Was kam bei A raus?"}
