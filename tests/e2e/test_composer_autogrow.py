"""e2e-Tests: Chat-Eingabefeld (Composer) waechst sofort bei Zeilenumbruch und schrumpft sofort beim Loeschen.

Mobil-Format (iPhone-aehnlicher Viewport mit Touch), damit das Verhalten auf einem
Smartphone abgedeckt ist. Alle Selektoren laufen ueber ``data-testid``.
"""

from __future__ import annotations

import pytest

from tests.e2e.test_user_journey import T, _login, _register_client

pytestmark = pytest.mark.e2e

MOBILE_VIEWPORT = {"width": 390, "height": 844}

LONG_TEXT = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua ut enim ad minim veniam quis nostrud"
)


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


def _metrics(page):
    return page.evaluate(
        """() => {
          const t = document.querySelector('[data-testid="chat-input"]');
          const r = t.getBoundingClientRect();
          return {len: t.value.length, h: r.height, sh: t.scrollHeight, ch: t.clientHeight};
        }"""
    )


def test_input_grows_at_line_wrap_and_shrinks_on_delete(mobile_page, base_url):
    email = "autogrow-user@example.com"
    _register_client(base_url, email, "Geheim-123")
    _login(mobile_page, base_url, email, "Geheim-123")
    mobile_page.wait_for_selector(T["chat_input"])
    ta = mobile_page.locator(T["chat_input"])
    ta.click()

    initial = _metrics(mobile_page)
    one_line_h = initial["h"]
    assert initial["len"] == 0

    # Zeichen fuer Zeichen tippen: nach jedem Zeichen muss der gesamte Inhalt
    # sichtbar sein (scrollHeight <= clientHeight + 1), d.h. das Feld waechst
    # spaetestens beim Zeilenumbruch auf die zweite Zeile.
    growth = {0: one_line_h}
    for ch in LONG_TEXT:
        mobile_page.keyboard.type(ch)
        m = _metrics(mobile_page)
        assert m["sh"] <= m["ch"] + 1, (
            f"content hidden after typing len={m['len']}: scrollHeight={m['sh']} clientHeight={m['ch']}"
        )
        growth[m["len"]] = m["h"]

    final = _metrics(mobile_page)
    assert final["h"] > one_line_h + 10, "input should have grown beyond one line"
    assert final["sh"] <= final["ch"] + 1

    # Zeichen fuer Zeichen loeschen: das Feld muss sofort wieder schrumpfen,
    # sobald eine Zeile geleert ist (gleiche Hoehe wie beim Wachsen bei gleicher Laenge).
    for _ in range(len(LONG_TEXT)):
        mobile_page.keyboard.press("Backspace")
        m = _metrics(mobile_page)
        assert m["sh"] <= m["ch"] + 1, (
            f"content hidden after deleting to len={m['len']}: scrollHeight={m['sh']} clientHeight={m['ch']}"
        )
        assert m["h"] <= growth[m["len"]] + 0.5, (
            f"input did not shrink immediately at len={m['len']}: h={m['h']} expected<={growth[m['len']]}"
        )

    end = _metrics(mobile_page)
    assert end["len"] == 0
    assert abs(end["h"] - one_line_h) < 1, f"input should be back to one line, h={end['h']} vs {one_line_h}"


def test_input_caps_at_max_height_and_scrolls(mobile_page, base_url):
    email = "autogrow-cap-user@example.com"
    _register_client(base_url, email, "Geheim-123")
    _login(mobile_page, base_url, email, "Geheim-123")
    mobile_page.wait_for_selector(T["chat_input"])
    ta = mobile_page.locator(T["chat_input"])
    ta.click()
    mobile_page.keyboard.type(LONG_TEXT * 6)
    m = _metrics(mobile_page)
    overflow_y = mobile_page.evaluate(
        "() => document.querySelector('[data-testid=\"chat-input\"]').style.overflowY"
    )
    assert m["h"] <= 180.5, f"input must be capped at max-height 180px, h={m['h']}"
    assert m["sh"] > m["ch"] + 1, "content beyond the cap must be scrollable"
    assert overflow_y == "auto", f"overflowY should be auto beyond the cap, got {overflow_y!r}"
    mobile_page.keyboard.press("Backspace")
    mobile_page.fill(T["chat_input"], "")
    m2 = _metrics(mobile_page)
    overflow_y2 = mobile_page.evaluate(
        "() => document.querySelector('[data-testid=\"chat-input\"]').style.overflowY"
    )
    assert m2["sh"] <= m2["ch"] + 1
    assert overflow_y2 == "hidden", f"overflowY should be hidden again when content fits, got {overflow_y2!r}"
