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


def test_minimalism_hides_toolbar_on_touch_and_longpress_opens_menu(mobile_page, base_url, llm_expect):
    """Minimalismus auf Touch-Geraet (kein Hover): Bubble-Toolbar ist dauerhaft ausgeblendet —
    auch ohne Hover-Event — und oeffnet sich per Langdruck (contextmenu) als Kontextmenue."""
    if llm_expect["default"] is None:
        pytest.skip("Minimalismus-Touch-Test braucht den Mock-LLM")
    email = "minimal-touch-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(mobile_page, base_url, email, "Geheim-123")

    assert mobile_page.evaluate("() => matchMedia('(hover: none) and (pointer: coarse)').matches"), "Test braucht Touch-Emulation ohne Hover"

    mobile_page.fill(T["chat_input"], "Hallo")
    mobile_page.click(T["send_btn"])
    mobile_page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    bubble = '[data-testid="chat"] .bubble[data-role="assistant"][data-type="message"]'
    toolbar_btn = f"{bubble} .bubbleHead .iconBtn"

    res = api_client.put("/api/settings", json={"bubbles_minimal": True})
    assert res.status_code == 200, res.text
    mobile_page.reload()
    mobile_page.wait_for_selector(bubble, timeout=llm_expect["timeout_ms"])
    mobile_page.wait_for_function("() => document.documentElement.classList.contains('bubbles-minimal')")

    # Touch-Geraet: es gibt kein Hover — die Toolbar muss trotzdem ausgeblendet sein
    assert mobile_page.locator(toolbar_btn).first.evaluate("el => getComputedStyle(el).display") == "none", (
        "Toolbar muss im Minimalismus auf Touch-Geraeten ausgeblendet sein"
    )
    assert mobile_page.locator(f"{bubble} .bubbleHead .role").evaluate("el => getComputedStyle(el).display") == "none", (
        "Rollen-Label muss im Minimalismus ausgeblendet sein"
    )

    # Langdruck (contextmenu) oeffnet das Kontextmenue mit den Bubble-Aktionen
    mobile_page.dispatch_event(bubble, "contextmenu")
    menu = mobile_page.locator('[data-testid="bubble-context-menu"]')
    menu.wait_for(state="visible")
    assert menu.locator("button").count() >= 2, "Kontextmenue muss die Bubble-Aktionen enthalten"
    mobile_page.keyboard.press("Escape")
    mobile_page.wait_for_selector('[data-testid="bubble-context-menu"]', state="detached")
