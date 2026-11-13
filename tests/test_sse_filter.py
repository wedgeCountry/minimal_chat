"""Unit-Tests fuer das serverseitige SSE-Filtern (app/services/chat.py).

Pin-Verhalten: Reasoning/Tool-Calls landen nur im Stream, wenn die
User-Settings sie aktivieren; [DONE] und Nicht-JSON-Zeilen gehen unveraendert
durch; ein SSE-Event darf ueber mehrere Chunks verteilt sein.
"""

from __future__ import annotations

import asyncio
import json

from app.services.chat import filter_request_messages, sse_filter


async def _aiter(chunks):
    for c in chunks:
        yield c


def _collect(chunks, **kwargs) -> list[str]:
    async def run():
        out = []
        async for line in sse_filter(_aiter(chunks), **kwargs):
            out.append(line)
        return out

    return asyncio.run(run())


def _event(delta: dict) -> bytes:
    return ("data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n").encode()


def _data_lines(out: list[str]) -> list[dict]:
    return [json.loads(line[len("data: ") :].strip()) for line in out if line.startswith("data: ")]


# --- filter_request_messages ---


def test_filter_request_messages_keeps_system_when_enabled():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert filter_request_messages(msgs, True) == msgs


def test_filter_request_messages_strips_system_when_disabled():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert filter_request_messages(msgs, False) == [{"role": "user", "content": "u"}]


def test_filter_request_messages_does_not_mutate_input():
    msgs = [{"role": "system", "content": "s"}]
    filter_request_messages(msgs, False)
    assert msgs == [{"role": "system", "content": "s"}]


# --- sse_filter: Pass-through ---


def test_sse_filter_passes_done_through_untouched():
    out = _collect([b"data: [DONE]\n\n"])
    assert out == ["data: [DONE]\n", "\n"]  # Leerzeile zwischen Events bleibt erhalten


def test_sse_filter_passes_malformed_json_through_untouched():
    out = _collect([b"data: {not-json}\n\n"])
    assert out == ["data: {not-json}\n", "\n"]


def test_sse_filter_passes_non_data_lines_through():
    out = _collect([b": keep-alive\n", b"event: message\n"])
    assert out == [": keep-alive\n", "event: message\n"]


def test_sse_filter_keeps_content_when_all_flags_on():
    chunks = [_event({"content": "Hallo", "reasoning_content": "denke", "tool_calls": [{"index": 0}]})]
    out = _collect(chunks, show_reasoning=True, show_tool_output=True)
    delta = _data_lines(out)[0]["choices"][0]["delta"]
    assert delta["content"] == "Hallo"
    assert delta["reasoning_content"] == "denke"
    assert delta["tool_calls"] == [{"index": 0}]


# --- sse_filter: Filtern ---


def test_sse_filter_strips_reasoning_content_and_reasoning_alias():
    chunks = [
        _event({"reasoning_content": "a"}),
        _event({"reasoning": "b", "content": "c"}),
    ]
    out = _collect(chunks, show_reasoning=False, show_tool_output=True)
    first, second = [e["choices"][0]["delta"] for e in _data_lines(out)]
    assert "reasoning_content" not in first
    assert "reasoning" not in second
    assert second["content"] == "c"


def test_sse_filter_strips_tool_calls_when_disabled():
    chunks = [_event({"content": "ok", "tool_calls": [{"index": 0, "function": {"name": "f"}}]})]
    out = _collect(chunks, show_reasoning=True, show_tool_output=False)
    delta = _data_lines(out)[0]["choices"][0]["delta"]
    assert "tool_calls" not in delta


def test_sse_filter_keeps_and_strips_tool_results_with_tool_output():
    chunks = [_event({"content": "ok", "tool_results": [{"index": 0, "result": "42"}], "tool_result": "x"})]
    out = _collect(chunks, show_reasoning=True, show_tool_output=True)
    delta = _data_lines(out)[0]["choices"][0]["delta"]
    assert delta["tool_results"] == [{"index": 0, "result": "42"}]
    assert delta["tool_result"] == "x"
    out = _collect(chunks, show_reasoning=True, show_tool_output=False)
    delta = _data_lines(out)[0]["choices"][0]["delta"]
    assert "tool_results" not in delta
    assert "tool_result" not in delta
    assert delta["content"] == "ok"


# --- sse_filter: Chunks ---


def test_sse_filter_handles_event_split_across_chunks():
    payload = _event({"reasoning_content": "denke", "content": "Hi"})
    mid = len(payload) // 2
    out = _collect([payload[:mid], payload[mid:]], show_reasoning=False, show_tool_output=False)
    delta = _data_lines(out)[0]["choices"][0]["delta"]
    assert delta == {"content": "Hi"}


def test_sse_filter_flushes_trailing_buffer_without_newline():
    out = _collect([b'data: {"choices":[{"delta":{"content":"x"}}]}'])
    assert len(out) == 1
    assert out[0].startswith("data: ")
    assert out[0].endswith("\n")


def test_sse_filter_handles_empty_stream():
    assert _collect([]) == []
