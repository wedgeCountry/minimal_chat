import test from "node:test";
import assert from "node:assert/strict";
import { buildBaseUrl, updateSpeechStatus } from "../../static/js/settings.js";
import { state } from "../../static/js/state.js";
import { controlsVisible, refreshSpeechAvailability } from "../../static/js/ttsDetectionService.js";

test("buildBaseUrl: host + port -> http://host:port/v1", () => {
  assert.equal(buildBaseUrl("192.168.1.10", "8000"), "http://192.168.1.10:8000/v1");
});

test("buildBaseUrl: host without port", () => {
  assert.equal(buildBaseUrl("llm.local", ""), "http://llm.local/v1");
});

test("buildBaseUrl: empty host -> empty string", () => {
  assert.equal(buildBaseUrl("", "8000"), "");
  assert.equal(buildBaseUrl("  ", ""), "");
});

test("buildBaseUrl: trims whitespace", () => {
  assert.equal(buildBaseUrl(" 10.0.0.5 ", " 443 "), "http://10.0.0.5:443/v1");
});

test("updateSpeechStatus: Radio-Auswahl wirkt sofort auf micBtn/Speaker (Firefox: Mic weg, Speaker bleibt)", async () => {
  const saved = {
    mode: state.settings.speech_mode,
    speech: state.speech,
    win: globalThis.window,
    doc: globalThis.document,
    fetch: globalThis.fetch,
  };
  const statusEl = { textContent: "", className: "" };
  const radios = [
    { value: "system", checked: false },
    { value: "server", checked: true },
    { value: "none", checked: false },
  ];
  const fired = [];
  globalThis.window = { speechSynthesis: {} }; // Firefox: TTS ja, STT nein
  globalThis.document = {
    getElementById: (id) => (id === "speechStatus" ? statusEl : null),
    querySelector: (sel) => (sel === 'input[name="speechMode"]:checked' ? radios.find((r) => r.checked) || null : null),
    querySelectorAll: () => radios,
    dispatchEvent: (e) => {
      fired.push(e.type);
      return true;
    },
  };
  // Voice-Companion laeuft (server stt+tts ok)
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ available: true, stt: true, tts: true }) });
  try {
    state.settings.speech_mode = "server";
    await refreshSpeechAvailability();
    assert.equal(controlsVisible("stt"), true);
    assert.equal(controlsVisible("tts"), true);

    // Nutzer waehlt im Settings-Overlay "System-API" (Radio-Wechsel, noch nicht gespeichert)
    radios.find((r) => r.value === "server").checked = false;
    radios.find((r) => r.value === "system").checked = true;
    await updateSpeechStatus();

    assert.equal(state.settings.speech_mode, "system", "Auswahl sofort im State, nicht erst beim Speichern");
    assert.ok(fired.includes("leanchat:speech-availability"), "Event feuert -> main.js blendet Buttons um");
    assert.equal(controlsVisible("stt"), false, "Firefox ohne SpeechRecognition: Mic sofort ausgeblendet");
    assert.equal(controlsVisible("tts"), true, "Firefox mit speechSynthesis: Speaker bleibt sichtbar");
    assert.equal(statusEl.textContent, "Nur TTS verfügbar");
  } finally {
    state.settings.speech_mode = saved.mode;
    state.speech = saved.speech;
    if (saved.win === undefined) delete globalThis.window;
    else globalThis.window = saved.win;
    if (saved.doc === undefined) delete globalThis.document;
    else globalThis.document = saved.doc;
    if (saved.fetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = saved.fetch;
  }
});
