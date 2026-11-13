"""Unit-Tests fuer app/services/llm.py (Abort-Race) und app/services/sse.py (SseParser)."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.llm import aiter_until_abort, race_abort
from app.services.sse import SseParser
from app.services.ssrf import LlmUrlValidator


# --- race_abort ---


def test_race_abort_returns_result_without_abort_event():
    async def main():
        return await race_abort(asyncio.sleep(0, result=42), None)

    assert asyncio.run(main()) == (42, False)


def test_race_abort_cancels_pending_awaitable_when_event_fires():
    async def main():
        ev = asyncio.Event()

        async def setter():
            await asyncio.sleep(0.05)
            ev.set()

        asyncio.ensure_future(setter())
        t0 = time.monotonic()
        result, aborted = await race_abort(asyncio.sleep(30), ev)
        return result, aborted, time.monotonic() - t0

    result, aborted, elapsed = asyncio.run(main())
    assert aborted is True
    assert result is None
    assert elapsed < 5  # nicht die vollen 30s warten


def test_race_abort_returns_result_when_event_not_set():
    async def main():
        return await race_abort(asyncio.sleep(0, result="ok"), asyncio.Event())

    assert asyncio.run(main()) == ("ok", False)


def test_race_abort_propagates_exception_of_awaitable():
    async def main():
        async def boom():
            raise ValueError("kaputt")

        with pytest.raises(ValueError, match="kaputt"):
            await race_abort(boom(), asyncio.Event())

    asyncio.run(main())


# --- aiter_until_abort ---


def test_aiter_until_abort_passes_chunks_through_without_event():
    async def gen():
        yield b"a"
        yield b"b"

    async def main():
        return [c async for c in aiter_until_abort(gen(), None)]

    assert asyncio.run(main()) == [b"a", b"b"]


def test_aiter_until_abort_stops_on_abort_even_without_further_chunks():
    async def gen():
        yield b"a"
        await asyncio.sleep(30)  # LLM stalled: keine weiteren Chunks
        yield b"b"

    async def main():
        ev = asyncio.Event()

        async def setter():
            await asyncio.sleep(0.05)
            ev.set()

        asyncio.ensure_future(setter())
        t0 = time.monotonic()
        out = [c async for c in aiter_until_abort(gen(), ev)]
        return out, time.monotonic() - t0

    out, elapsed = asyncio.run(main())
    assert out == [b"a"]
    assert elapsed < 5


# --- SseParser ---


def test_sse_parser_feeds_split_events_across_chunks():
    parser = SseParser()
    assert parser.feed('data: {"choices":[{"delta":{"content":"Ha') == []
    events = parser.feed('llo"}}]}\n\ndata: {"choices":[{"delta":{"content":" Welt"}}]}\n\ndata: [DONE]\n\n')
    assert events == [
        {"choices": [{"delta": {"content": "Hallo"}}]},
        {"choices": [{"delta": {"content": " Welt"}}]},
    ]
    assert parser.feed("") == []


# --- LlmUrlValidator (Klasse direkt) ---


def test_llm_url_validator_blocks_private_ip_literal():
    with pytest.raises(ValueError, match="blockiert"):
        LlmUrlValidator(allow_private=False).validate("http://127.0.0.1:1234/v1")


def test_llm_url_validator_allows_private_with_flag():
    v = LlmUrlValidator(allow_private=True)
    assert v.validate("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1"


def test_llm_url_validator_rejects_credentials_in_url():
    with pytest.raises(ValueError, match="Credentials"):
        LlmUrlValidator(allow_private=True).validate("http://user:pass@8.8.8.8/v1")
