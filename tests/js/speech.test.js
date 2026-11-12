import test from "node:test";
import assert from "node:assert/strict";
import { speechControlsVisible } from "../../static/js/visibility.js";
import { speechStatusLabel, SPEECH_MODES } from "../../static/js/speech.js";

const avail = { systemStt: true, systemTts: true, serverStt: true, serverTts: true };
const availOff = { systemStt: false, systemTts: false, serverStt: false, serverTts: false };
const serverOnly = { systemStt: false, systemTts: false, serverStt: true, serverTts: true };

test("Modus none blendet beide Controls aus", () => {
  assert.equal(speechControlsVisible("none", "stt", avail), false);
  assert.equal(speechControlsVisible("none", "tts", avail), false);
});

test("Modus system nutzt System-Verfuegbarkeit je Control", () => {
  assert.equal(speechControlsVisible("system", "stt", avail), true);
  assert.equal(speechControlsVisible("system", "tts", avail), true);
  assert.equal(speechControlsVisible("system", "stt", availOff), false);
  assert.equal(speechControlsVisible("system", "tts", { ...avail, systemTts: false }), false);
  assert.equal(speechControlsVisible("system", "stt", { ...avail, systemStt: false }), false);
});

test("Modus server nutzt Server-Verfuegbarkeit je Control", () => {
  assert.equal(speechControlsVisible("server", "stt", serverOnly), true);
  assert.equal(speechControlsVisible("server", "tts", serverOnly), true);
  assert.equal(speechControlsVisible("server", "stt", availOff), false);
  assert.equal(speechControlsVisible("server", "tts", { ...serverOnly, serverTts: false }), false);
});

test("unbekannter Modus blendet aus, fehlende Avail-Daten = nicht verfuegbar", () => {
  assert.equal(speechControlsVisible("???", "stt", avail), false);
  assert.equal(speechControlsVisible("server", "stt", {}), false);
  assert.equal(speechControlsVisible("server", "stt", null), false);
});

test("speechStatusLabel: none = deaktiviert, sonst gruen/rot", () => {
  assert.deepEqual(speechStatusLabel("none", avail), { text: "Deaktiviert", cls: "" });
  assert.deepEqual(speechStatusLabel("server", avail), { text: "Verfügbar", cls: "ok" });
  assert.deepEqual(speechStatusLabel("server", availOff), { text: "Nicht verfügbar", cls: "err" });
  assert.deepEqual(speechStatusLabel("system", avail), { text: "Verfügbar", cls: "ok" });
  assert.deepEqual(speechStatusLabel("system", availOff), { text: "Nicht verfügbar", cls: "err" });
  assert.deepEqual(speechStatusLabel("system", serverOnly), { text: "Nicht verfügbar", cls: "err" });
});

test("SPEECH_MODES enthaelt genau system/server/none", () => {
  assert.deepEqual(SPEECH_MODES, ["system", "server", "none"]);
});
