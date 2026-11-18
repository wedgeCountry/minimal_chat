"""Unit-Tests fuers serverseitige Request-Filtern (app/services/llm.py).

Der LLM-Response-Stream wird bewusst nicht gefiltert: Anzeige-Settings
(``show_reasoning``/``show_tool_output``) wirken clientseitig (visibility.js),
damit Reasoning/Tool-Calls/Tool-Ergebnisse trotz abgewählter Anzeige in der
per-user DB persistiert werden (Regression: siehe tests/test_chat_api.py).
"""

from __future__ import annotations

from app.services.llm import filter_request_messages


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
