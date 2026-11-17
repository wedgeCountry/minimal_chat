"""e2e-Tests: Composer bleibt bei geoeffneter Soft-Tastatur sichtbar und am unteren Rand.

Mobil-Format (iPhone-aehnlicher Viewport mit Touch). Desktop-Chromium zeigt keine
echte Tastatur - der Tastatur-Zustand wird deshalb ueber den exportierten
``applyVisualViewport``-Handler mit einem gestubbten Visual Viewport simuliert.
Alle Selektoren laufen ueber ``data-testid``.
"""

from __future__ import annotations

import pytest

from tests.e2e.test_user_journey import T, _login, _register_client

pytestmark = pytest.mark.e2e

MOBILE_VIEWPORT = {"width": 390, "height": 844}


@pytest.fixture()
def mobile_page(server_port):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport=MOBILE_VIEWPORT,
            is_mobile=True,
            has_touch=True,
            device_scale_factor=3,
        )
        pg = context.new_page()
        yield pg
        context.close()
        browser.close()


def _register(base_url, email):
    _register_client(base_url, email, "Geheim-123")


def test_viewport_meta_declares_resizes_content(mobile_page, base_url):
    email = "kb-meta-user@example.com"
    _register(base_url, email)
    _login(mobile_page, base_url, email, "Geheim-123")
    content = mobile_page.evaluate("() => document.querySelector('meta[name=\"viewport\"]').content")
    assert "interactive-widget=resizes-content" in content
    assert "viewport-fit=cover" in content


def test_composer_stays_at_bottom_of_visual_viewport_when_keyboard_open(mobile_page, base_url):
    email = "kb-viewport-user@example.com"
    _register(base_url, email)
    _login(mobile_page, base_url, email, "Geheim-123")
    mobile_page.wait_for_selector(T["chat_input"])
    mobile_page.locator(T["chat_input"]).click()

    # Tastatur offen simulieren: Visual Viewport schrumpft auf 400px, Fenster-Pan aktiv
    result = mobile_page.evaluate(
        """async () => {
          const mod = await import('/js/viewport.js');
          window.scrollTo(0, 200); // Pan, wie ihn der Browser beim Fokussieren setzt
          const fakeWin = {
            visualViewport: { height: 400, scale: 1 },
            scrollTo: (x, y) => window.scrollTo(x, y),
          };
          mod.applyVisualViewport(document.documentElement, fakeWin);
          const wrap = document.querySelector('[data-testid="composer-wrap"]').getBoundingClientRect();
          const input = document.querySelector('[data-testid="chat-input"]').getBoundingClientRect();
          return {
            rootHeight: document.documentElement.style.height,
            scrollY: window.scrollY,
            wrapBottom: wrap.bottom,
            inputBottom: input.bottom,
          };
        }"""
    )
    assert result["rootHeight"] == "400px", f"Root-Hoehe muss an den Visual Viewport gekoppelt sein, got {result['rootHeight']!r}"
    assert result["scrollY"] == 0, "bestehender Fenster-Pan muss zurueckgesetzt werden"
    assert abs(result["wrapBottom"] - 400) < 1, f"Composer muss am unteren Rand des sichtbaren Bereichs kleben, bottom={result['wrapBottom']}"
    assert result["inputBottom"] <= 400 + 0.5, f"Eingabefeld muss vollstaendig sichtbar sein, bottom={result['inputBottom']}"
