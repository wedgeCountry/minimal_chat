"""e2e-Tests: Zusammenspiel von TTS (Speaker-Button der Bubbles) und STT (Mikrofon-Button).

Abgedecktes Verhalten:
- laeuft die Wiedergabe (Speaker-Button), wird eine Aufnahme unterdrueckt
- Senden im Composer stoppt die Aufnahme; Chat-Zeile und Aufnahme-Puffer werden geleert
- erneuter Klick auf den Speaker-Button stoppt die Wiedergabe
- Aufnahme laeuft + Klick auf Speaker-Button -> Aufnahme stoppt (Puffer wird verworfen)

Der Voice-Companion wird per ``page.route`` gestubbt (Status ok, TTS liefert ein WAV,
STT zaehlt die Aufrufe); das Mikrofon laeuft ueber Chromiums Fake-Media-Device.
Alle Selektoren laufen ueber ``data-testid``.
"""

from __future__ import annotations

import io
import math
import wave

import pytest

from tests.e2e.test_user_journey import T, _chat_once, _login, _register_client

pytestmark = pytest.mark.e2e

MIC = '[data-testid="mic-btn"]'
TTS_BTN = '[data-testid="bubble-tts-btn"]'
ERROR_OVERLAY = '[data-testid="error-overlay"]'
ERROR_OK = '[data-testid="error-ok"]'

MIC_ON = '() => document.querySelector(\'[data-testid="mic-btn"]\').classList.contains("on")'
MIC_OFF = '() => !document.querySelector(\'[data-testid="mic-btn"]\').classList.contains("on")'
TTS_ON = '() => !!document.querySelector(\'[data-testid="bubble-tts-btn"].on\')'
TTS_OFF = '() => !document.querySelector(\'[data-testid="bubble-tts-btn"].on\')'


def _wav_bytes(seconds: float = 6.0, rate: int = 8000) -> bytes:
    """Kleiner 440-Hz-Ton als WAV (damit die Wiedergabe im Test eine Weile laeuft)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += v.to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))
    return buf.getvalue()


WAV = _wav_bytes()


@pytest.fixture()
def voice_page(server_port):
    """Seite mit gestubbtem Voice-Companion und Fake-Mikrofon; liefert (page, {"stt_calls": n})."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    voice_state = {"stt_calls": 0}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ]
        )
        context = browser.new_context(permissions=["microphone"])
        pg = context.new_page()

        def _status(route):
            route.fulfill(json={"available": True, "stt": True, "tts": True}, content_type="application/json")

        def _tts(route):
            route.fulfill(body=WAV, content_type="audio/wav")

        def _stt(route):
            voice_state["stt_calls"] += 1
            route.fulfill(json={"text": "transkribierter Text"}, content_type="application/json")

        pg.route("**/api/voice/status", _status)
        pg.route("**/api/voice/tts", _tts)
        pg.route("**/api/voice/stt", _stt)
        yield pg, voice_state
        context.close()
        browser.close()


def _dismiss_error_if_open(page):
    if page.locator(f"{ERROR_OVERLAY}.open").count():
        page.click(ERROR_OK)
        page.wait_for_selector(f"{ERROR_OVERLAY}:not(.open)", state="attached")


def _setup_with_answer(page, base_url, llm_expect, email):
    """Registriert/Loggt ein und schickt eine Nachricht, damit eine Assistant-Bubble mit Speaker-Button existiert."""
    _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    _chat_once(page, "Bitte vorlesen", 1, llm_expect["default"], llm_expect["timeout_ms"])
    page.locator(TTS_BTN).first.wait_for(state="visible")
    page.locator(MIC).wait_for(state="visible")


def test_speaker_pressed_again_stops_playback(voice_page, base_url, llm_expect):
    """Wiedergabe laeuft -> erneuter Klick auf den Speaker-Button stoppt sie."""
    page, _ = voice_page
    _setup_with_answer(page, base_url, llm_expect, "voice-toggle@example.com")

    page.locator(TTS_BTN).first.click()
    page.wait_for_function(TTS_ON, timeout=10000)

    # erneuter Klick auf denselben Speaker-Button -> Wiedergabe stoppt (ohne Fehler-Overlay)
    page.locator(TTS_BTN).first.click()
    page.wait_for_function(TTS_OFF, timeout=10000)
    assert page.locator(f"{ERROR_OVERLAY}.open").count() == 0, "Stopp der Wiedergabe darf kein Fehler-Overlay oeffnen"

    # danach ist das Mikrofon wieder normal nutzbar (Aufnahme startet)
    page.locator(MIC).click()
    page.wait_for_function(MIC_ON, timeout=10000)
    page.locator(MIC).click()
    page.wait_for_function(MIC_OFF, timeout=10000)


def test_playback_suppresses_recording(voice_page, base_url, llm_expect):
    """Wiedergabe laeuft -> Mikrofon-Klick startet KEINE Aufnahme (unterdrueckt)."""
    page, voice_state = voice_page
    _setup_with_answer(page, base_url, llm_expect, "voice-suppress@example.com")

    page.locator(TTS_BTN).first.click()
    page.wait_for_function(TTS_ON, timeout=10000)

    # Mikrofon waehrend der Wiedergabe druecken: Aufnahme darf nicht starten
    page.locator(MIC).click()
    page.wait_for_timeout(800)
    assert page.evaluate(MIC_ON) is False, "Aufnahme wurde trotz Wiedergabe gestartet"
    assert voice_state["stt_calls"] == 0
    _dismiss_error_if_open(page)

    # Wiedergabe stoppen -> danach funktioniert das Mikrofon wieder
    page.locator(TTS_BTN).first.click()
    page.wait_for_function(TTS_OFF, timeout=10000)
    page.locator(MIC).click()
    page.wait_for_function(MIC_ON, timeout=10000)
    page.locator(MIC).click()
    page.wait_for_function(MIC_OFF, timeout=10000)


def test_speaker_press_stops_recording(voice_page, base_url, llm_expect):
    """Aufnahme laeuft -> Klick auf den Speaker-Button stoppt die Aufnahme (Puffer wird verworfen)."""
    page, voice_state = voice_page
    _setup_with_answer(page, base_url, llm_expect, "voice-tts-stops-rec@example.com")

    page.locator(MIC).click()
    page.wait_for_function(MIC_ON, timeout=10000)

    # Speaker-Button druecken: Wiedergabe startet, Aufnahme stoppt
    page.locator(TTS_BTN).first.click()
    page.wait_for_function(TTS_ON, timeout=10000)
    page.wait_for_function(MIC_OFF, timeout=10000)

    # Aufnahme-Puffer wurde verworfen: kein STT-Aufruf, kein Text im Composer
    page.wait_for_timeout(1000)
    assert voice_state["stt_calls"] == 0, "Puffer der abgebrochenen Aufnahme wurde doch transkribiert"
    assert page.locator(T["chat_input"]).input_value() == ""


def test_submit_stops_recording_and_clears_input_and_buffer(voice_page, base_url, llm_expect):
    """Senden stoppt die Aufnahme; Chat-Zeile und Aufnahme-Puffer werden geleert."""
    page, voice_state = voice_page
    email = "voice-submit@example.com"
    _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")
    page.locator(MIC).wait_for(state="visible")

    # Aufnahme starten, dann Text tippen und abschicken
    page.locator(MIC).click()
    page.wait_for_function(MIC_ON, timeout=10000)
    page.fill(T["chat_input"], "Nachricht trotz laufender Aufnahme")
    page.click(T["send_btn"])

    # Aufnahme wurde durch das Senden gestoppt
    page.wait_for_function(MIC_OFF, timeout=10000)
    # Chat-Zeile wurde geleert
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"chat-input\"]').value === ''",
        timeout=10000,
    )

    # LLM-Antwort abwarten (Mock: "Hallo Welt")
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )

    # Aufnahme-Puffer wurde verworfen: kein STT-Aufruf, und spaeter wird auch
    # kein transkribierter Text in die geleerte Chat-Zeile eingefuegt
    page.wait_for_timeout(1000)
    assert voice_state["stt_calls"] == 0, "Puffer wurde nach dem Senden doch transkribiert"
    assert page.locator(T["chat_input"]).input_value() == ""
    assert page.evaluate(MIC_ON) is False
