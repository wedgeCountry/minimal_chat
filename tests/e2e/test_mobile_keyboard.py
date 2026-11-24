"""e2e-Tests: Composer bleibt bei geoeffneter Soft-Tastatur sichtbar und am unteren Rand.

Mobil-Format (iPhone-aehnlicher Viewport mit Touch). Desktop-Chromium zeigt keine
echte Tastatur - der Tastatur-Zustand wird deshalb ueber den exportierten
``applyVisualViewport``-Handler mit einem gestubbten Visual Viewport simuliert.
Alle Selektoren laufen ueber ``data-testid``.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import SPEECH_STUB
from tests.e2e.test_user_journey import T, _confirm_delete, _login, _register_client

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


@pytest.fixture()
def mobile_speech_page(server_port):
    """Touch-Seite mit gestubbtem speechSynthesis (System-TTS ohne echtes Audio)."""
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
        pg.add_init_script(SPEECH_STUB)
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

    # Touch + Minimalismus: Textauswahl bleibt aktiv (Langdruck = natives Systemmenue),
    # Doppel-Tap oeffnet das App-Menue, Tap bei offenem Menue schliesst, Scroll-Geste oeffnet nichts
    body_sel = f"{bubble} .bubbleBody"
    assert mobile_page.locator(body_sel).evaluate("el => getComputedStyle(el).userSelect") in ("text", "auto"), "Textauswahl darf im Minimalismus nicht per CSS deaktiviert sein"
    # systemeigenes Doppel-Tap-Zoom (Firefox Android) auf den Bubbles abgeschaltet — der
    # Doppel-Tap ist unserer (App-Kontextmenue); Scrollen/Pan bleibt via touch-action:manipulation
    assert mobile_page.locator(bubble).evaluate("el => getComputedStyle(el).touchAction") == "manipulation", "touch-action muss im Minimalismus 'manipulation' sein (kein systemeigenes Doppel-Tap-Zoom)"
    menu = mobile_page.locator('[data-testid="bubble-context-menu"]')

    box = mobile_page.locator(bubble).bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    mobile_page.touchscreen.tap(cx, cy)  # einfacher Tap -> KEIN Menue
    mobile_page.wait_for_timeout(300)
    assert menu.count() == 0, "einfacher Tap darf im Minimalismus kein Kontextmenue oeffnen"
    # Doppel-Tap (zwei pointerdown+click-Paare in einem Tick -> deterministisch schnell genug);
    # das zweite pointerdown muss preventDefault sein, damit Firefox nicht das Wort selektiert
    mobile_page.wait_for_timeout(400)  # evtl. stale lastTap ablaufen lassen
    dbl = mobile_page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const r = el.getBoundingClientRect();
          const x = r.x + r.width / 2, y = r.y + r.height / 2;
          const fired = [];
          for (let i = 0; i < 2; i++) {
            const pd = new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: x, clientY: y });
            el.dispatchEvent(pd);
            fired.push(pd.defaultPrevented);
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
          }
          return { secondPdPrevented: fired[1], collapsed: window.getSelection().isCollapsed };
        }""",
        bubble,
    )
    assert dbl["secondPdPrevented"] is True, "pointerdown des Doppel-Taps muss preventDefault sein (Wortauswahl unterdrueckt)"
    assert dbl["collapsed"] is True, "Doppel-Tap darf kein Wort selektieren"
    menu.wait_for(state="visible")
    assert menu.locator("button").count() >= 2, "Kontextmenue muss Kopieren und die Bubble-Aktionen enthalten"
    assert menu.locator("button svg").count() == 0, "Kontextmenue darf keine Icons enthalten (nur Text)"
    assert menu.locator('[data-testid="ctx-copy"]').count() == 1, "Menue-Eintrag fehlt: ctx-copy"
    # Tap auf die Bubble (ausserhalb des Menues, das am Doppel-Tap-Punkt oeffnet) schliesst es
    mobile_page.touchscreen.tap(box["x"] + 20, box["y"] + 6)
    mobile_page.wait_for_selector('[data-testid="bubble-context-menu"]', state="detached")

    # System-Auswahlmenue offen (aktive Textauswahl): Tap darf kein App-Menue oeffnen
    mobile_page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const r = document.createRange();
          r.selectNodeContents(el);
          const s = window.getSelection();
          s.removeAllRanges();
          s.addRange(r);
        }""",
        body_sel,
    )
    mobile_page.touchscreen.tap(cx, cy)
    mobile_page.wait_for_timeout(300)
    assert menu.count() == 0, "bei aktiver System-Auswahl darf ein Tap kein App-Menue oeffnen"
    mobile_page.evaluate("() => window.getSelection().removeAllRanges()")
    mobile_page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const r = el.getBoundingClientRect();
          const x = r.x + r.width / 2, y = r.y + r.height / 2;
          for (let i = 0; i < 2; i++) {
            el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
          }
        }""",
        bubble,
    )
    menu.wait_for(state="visible")
    mobile_page.keyboard.press("Escape")
    mobile_page.wait_for_selector('[data-testid="bubble-context-menu"]', state="detached")

    # Scroll-Geste (Pointer wird bewegt, click landet versetzt) darf kein Menue oeffnen
    opened = mobile_page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const r = el.getBoundingClientRect();
          const x = r.x + r.width / 2, y = r.y + r.height / 2;
          el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
          el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y + 60 }));
          return !!document.querySelector('[data-testid="bubble-context-menu"]');
        }""",
        bubble,
    )
    assert opened is False, "Scroll/Pan-Geste darf kein Kontextmenue oeffnen"

    # Langdruck (contextmenu) bleibt nativ: kein preventDefault, kein eigenes Menue
    not_prevented = mobile_page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
          el.dispatchEvent(ev);
          return !ev.defaultPrevented;
        }""",
        body_sel,
    )
    assert not_prevented, "contextmenu (Langdruck) darf nicht preventDefault sein — natives Systemmenue bleibt"
    mobile_page.wait_for_timeout(300)
    assert menu.count() == 0, "beim Langdruck darf kein eigenes Kontextmenue erscheinen"


def test_minimalism_single_tap_cycles_expansion_mode(mobile_page, base_url, llm_expect):
    """Minimalismus auf Touch: ein einfacher Tap auf eine Bubble schaltet den Expand-Modus
    zyklisch weiter (normal -> full -> collapsed -> normal), wie der Expand-Button im
    Normalmodus. Der Doppel-Tap oeffnet als eigene Aktion
    nur das Kontextmenue (kein Modus-Wechsel); Scroll-Gesten loesen weder Menue noch
    Modus-Wechsel aus."""
    if llm_expect["default"] is None:
        pytest.skip("Minimalismus-Tap-Test braucht den Mock-LLM")
    email = "minimal-tap-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(mobile_page, base_url, email, "Geheim-123")

    assert mobile_page.evaluate("() => matchMedia('(hover: none) and (pointer: coarse)').matches"), "Test braucht Touch-Emulation ohne Hover"

    mobile_page.fill(T["chat_input"], "lang")
    mobile_page.click(T["send_btn"])
    mobile_page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    bubble = '[data-testid="chat"] .bubble[data-role="assistant"][data-type="message"]'

    res = api_client.put("/api/settings", json={"bubbles_minimal": True})
    assert res.status_code == 200, res.text
    mobile_page.reload()
    mobile_page.wait_for_selector(bubble, timeout=llm_expect["timeout_ms"])
    mobile_page.wait_for_function("() => document.documentElement.classList.contains('bubbles-minimal')")

    menu = mobile_page.locator('[data-testid="bubble-context-menu"]')

    def mode():
        return mobile_page.locator(bubble).evaluate("el => el.dataset.mode")

    def tap():
        # Bubble-Hoehe aendert sich je Modus -> Zielpunkt jedes Mal neu messen
        box = mobile_page.locator(bubble).bounding_box()
        mobile_page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        # > Doppel-Tap-Fenster (350ms): der Einfach-Tap feuert, der naechste Tap zaehlt nicht als Doppel-Tap
        mobile_page.wait_for_timeout(500)

    assert mode() == "normal"
    tap()
    assert mode() == "full", "erster Tap: normal -> full (Text ist in normal gekuerzt)"
    tap()
    assert mode() == "collapsed", "zweiter Tap: full -> collapsed"
    tap()
    assert mode() == "normal", "dritter Tap: collapsed -> normal (voller Zyklus)"
    assert menu.count() == 0, "Einfach-Taps duerfen kein Kontextmenue oeffnen"

    # Doppel-Tap (zwei pointerdown+click-Paare in einem Tick): eigene Aktion — Menue ja, Modus-Wechsel nein
    mobile_page.wait_for_timeout(400)  # evtl. stale lastTap ablaufen lassen
    opened = mobile_page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const r = el.getBoundingClientRect();
          const x = r.x + r.width / 2, y = r.y + r.height / 2;
          for (let i = 0; i < 2; i++) {
            el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
          }
          return !!document.querySelector('[data-testid="bubble-context-menu"]');
        }""",
        bubble,
    )
    assert opened is True, "Doppel-Tap muss das Kontextmenue oeffnen"
    mobile_page.wait_for_timeout(500)  # ein von der ersten Tap-Haelfte geplanter Modus-Wechsel darf nicht feuern
    assert mode() == "normal", "Doppel-Tap darf den Expand-Modus nicht aendern"
    menu.wait_for(state="visible")
    mobile_page.keyboard.press("Escape")
    mobile_page.wait_for_selector('[data-testid="bubble-context-menu"]', state="detached")

    # Scroll-Geste (Pointer wird bewegt, click landet versetzt): weder Menue noch Modus-Wechsel
    mobile_page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const r = el.getBoundingClientRect();
          const x = r.x + r.width / 2, y = r.y + r.height / 2;
          el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
          el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y + 60 }));
        }""",
        bubble,
    )
    mobile_page.wait_for_timeout(500)
    assert mode() == "normal", "Scroll-Geste darf den Expand-Modus nicht aendern"
    assert menu.count() == 0, "Scroll-Geste darf kein Kontextmenue oeffnen"


def test_minimalism_dbltap_or_escape_stops_playback(mobile_speech_page, base_url, llm_expect):
    """Minimalismus auf Touch mit laufender Wiedergabe (TTS): ein einfacher Tap stoppt die
    Wiedergabe NICHT, sondern schaltet den Expand-Modus zyklisch weiter. Doppel-Tap oder Esc
    stoppen die Wiedergabe (dann kein Kontextmenue, kein Expand-Wechsel)."""
    if llm_expect["default"] is None:
        pytest.skip("Minimalismus-TTS-Test braucht den Mock-LLM")
    page = mobile_speech_page
    email = "minimal-tts-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(page, base_url, email, "Geheim-123")

    assert page.evaluate("() => matchMedia('(hover: none) and (pointer: coarse)').matches"), "Test braucht Touch-Emulation ohne Hover"

    page.fill(T["chat_input"], "lang")
    page.click(T["send_btn"])
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    bubble = '[data-testid="chat"] .bubble[data-role="assistant"][data-type="message"]'
    tts_btn = f"{bubble} [data-testid=\"bubble-tts-btn\"]"

    res = api_client.put("/api/settings", json={"bubbles_minimal": True, "speech_mode": "system", "bubbles_speaker": True})
    assert res.status_code == 200, res.text
    page.reload()
    page.wait_for_selector(bubble, timeout=llm_expect["timeout_ms"])
    page.wait_for_function("() => document.documentElement.classList.contains('bubbles-minimal')")
    page.wait_for_selector(tts_btn, state="attached")  # Button existiert auch im ausgeblendeten Head

    speaking = "async () => (await import('/js/ttsDetectionService.js')).isSpeaking()"
    menu = page.locator('[data-testid="bubble-context-menu"]')

    def mode():
        return page.locator(bubble).evaluate("el => el.dataset.mode")

    def tap():
        # Bubble-Hoehe aendert sich je Modus -> Zielpunkt jedes Mal neu messen
        box = page.locator(bubble).bounding_box()
        page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        # > Doppel-Tap-Fenster (350ms): der Einfach-Tap feuert, der naechste Tap zaehlt nicht als Doppel-Tap
        page.wait_for_timeout(500)

    def dbltap():
        return page.evaluate(
            """(sel) => {
              const el = document.querySelector(sel);
              const r = el.getBoundingClientRect();
              const x = r.x + r.width / 2, y = r.y + r.height / 2;
              for (let i = 0; i < 2; i++) {
                el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
              }
              return !!document.querySelector('[data-testid="bubble-context-menu"]');
            }""",
            bubble,
        )

    def start_speech():
        # Speaker-Button liegt im ausgeblendeten Head -> per JS klicken
        page.evaluate(f"() => document.querySelector('{tts_btn}').click()")
        page.wait_for_function(speaking, timeout=10000)

    start_speech()
    assert mode() == "normal"

    # Einfach-Tap waehrend der Wiedergabe: stoppt NICHT, sondern normaler Expand-Zyklus
    tap()
    assert page.evaluate(speaking) is True, "Einfach-Tap darf die Wiedergabe nicht stoppen"
    assert mode() == "full", "Einfach-Tap feuert den normalen Expand-Zyklus"
    assert menu.count() == 0, "der Tap darf kein Kontextmenue oeffnen"

    # Doppel-Tap waehrend der Wiedergabe: stoppt sie, oeffnet kein Menue
    page.wait_for_timeout(400)  # evtl. stale lastTap ablaufen lassen
    opened = dbltap()
    page.wait_for_timeout(500)  # ein von der ersten Tap-Haelfte geplanter Expand darf nicht feuern
    assert opened is False, "Doppel-Tap darf waehrend der Wiedergabe kein Kontextmenue oeffnen"
    assert page.evaluate(speaking) is False, "Doppel-Tap muss die Wiedergabe stoppen"
    assert page.evaluate("() => window.__tts.cancelCalls") >= 1, "speechSynthesis.cancel() wurde gerufen"
    assert mode() == "full", "Doppel-Tap aendert nicht den Expand-Modus"

    # Esc stoppt die Wiedergabe ebenfalls
    start_speech()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.evaluate(speaking) is False, "Escape muss die Wiedergabe stoppen"
    assert menu.count() == 0

def test_send_tap_keeps_input_focus_when_keep_keyboard_open(mobile_page, base_url, llm_expect):
    """Setting keep_keyboard_open (Default an): Tap auf Senden darf auf dem Smartphone die
    Tastatur nicht schliessen - der Focus-Wechsel auf den Button (mousedown-Default) wird
    unterdrueckt, der Input bleibt fokussiert; der click feuert trotzdem (Nachricht geht raus).
    Mit keep_keyboard_open=false wechselt der Focus auf den Button (Tastatur klappt zu)."""
    if llm_expect["default"] is None:
        pytest.skip("braucht den Mock-LLM")
    email = "kb-send-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    _login(mobile_page, base_url, email, "Geheim-123")
    assert mobile_page.evaluate("() => 'ontouchstart' in window || matchMedia('(hover: none) and (pointer: coarse)').matches"), (
        "Test braucht Touch-Emulation"
    )

    active = "() => document.activeElement?.dataset.testid"

    # Default an: Input fokussieren, dann Senden tappen -> Focus bleibt im Input
    mobile_page.locator(T["chat_input"]).click()
    assert mobile_page.evaluate(active) == "chat-input"
    mobile_page.fill(T["chat_input"], "Hallo")
    mobile_page.click(T["send_btn"])
    assert mobile_page.evaluate(active) == "chat-input", "Send-Tap darf den Input nicht blur-en (Tastatur bleibt offen)"
    # click hat trotz preventDefault des mousedown gefeuert: User-Bubble ist unterwegs
    mobile_page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === 1",
        timeout=llm_expect["timeout_ms"],
    )

    # Setting aus: nach Reload wechselt der Focus auf den Send-Button (Tastatur klappt zu)
    res = api_client.put("/api/settings", json={"keep_keyboard_open": False})
    assert res.status_code == 200, res.text
    mobile_page.reload()
    mobile_page.wait_for_selector(T["chat_input"], timeout=llm_expect["timeout_ms"])
    mobile_page.locator(T["chat_input"]).click()
    assert mobile_page.evaluate(active) == "chat-input"
    mobile_page.fill(T["chat_input"], "Zweite Nachricht")
    mobile_page.click(T["send_btn"])
    assert mobile_page.evaluate(active) == "send-btn", "mit keep_keyboard_open=false darf der Send-Tap den Button fokussieren"

def test_minimalism_touch_dbltap_menu_action_delete(mobile_page, base_url, llm_expect):
    """Minimalismus auf Touch: der Doppel-Tap oeffnet das Kontextmenue; ein Menue-Eintrag
    (hier Loeschen, der Menue-Abbildung des versteckten Muellimer-Buttons) fuehrt die Aktion
    aus - die User-Bubble ist danach weg."""
    if llm_expect["default"] is None:
        pytest.skip("braucht den Mock-LLM")
    email = "minimal-touch-del-user@example.com"
    api_client = _register_client(base_url, email, "Geheim-123")
    res = api_client.put("/api/settings", json={"bubbles_minimal": True, "bubbles_deletable": True})
    assert res.status_code == 200, res.text
    _login(mobile_page, base_url, email, "Geheim-123")

    assert mobile_page.evaluate("() => matchMedia('(hover: none) and (pointer: coarse)').matches"), "Test braucht Touch-Emulation ohne Hover"

    mobile_page.fill(T["chat_input"], "Hallo")
    mobile_page.click(T["send_btn"])
    mobile_page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"assistant\"][data-type=\"message\"]').length === 1"
        " && !document.querySelector('[data-testid=\"send-btn\"]').classList.contains('abort')",
        timeout=llm_expect["timeout_ms"],
    )
    user_sel = '[data-testid="chat"] .bubble[data-role="user"]'
    assert mobile_page.locator(user_sel).count() == 1
    mobile_page.wait_for_function("() => document.documentElement.classList.contains('bubbles-minimal')")

    # Doppel-Tap (zwei pointerdown+click-Paare in einem Tick) oeffnet das App-Kontextmenue
    opened = mobile_page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          const r = el.getBoundingClientRect();
          const x = r.x + r.width / 2, y = r.y + r.height / 2;
          for (let i = 0; i < 2; i++) {
            el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
          }
          return !!document.querySelector('[data-testid="bubble-context-menu"]');
        }""",
        user_sel,
    )
    assert opened is True, "Doppel-Tap muss das Kontextmenue oeffnen"
    menu = mobile_page.locator('[data-testid="bubble-context-menu"]')
    menu.wait_for(state="visible")

    # Menue-Eintrag Loeschen fuehrt dieselbe Aktion wie der versteckte Toolbar-Button aus
    del_item = menu.locator('[data-testid="ctx-bubble-delete-btn"]')
    assert del_item.count() == 1, "Menue muss den Loeschen-Eintrag enthalten"
    del_item.click()
    _confirm_delete(mobile_page)
    mobile_page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=\"chat\"] .bubble[data-role=\"user\"]').length === 0",
        timeout=llm_expect["timeout_ms"],
    )
    assert mobile_page.locator(user_sel).count() == 0

