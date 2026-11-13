import test from "node:test";
import assert from "node:assert/strict";

const store = new Map();
globalThis.sessionStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};

const { state, activeSession, setActiveId, normalizeMessage, normalizeMessages } = await import("../../static/js/state.js");

test("setActiveId sets state and persists to sessionStorage", () => {
  setActiveId("s1");
  assert.equal(state.activeId, "s1");
  assert.equal(store.get("leanchat.active"), "s1");
});

test("setActiveId(null) clears state and storage", () => {
  setActiveId("s2");
  setActiveId(null);
  assert.equal(state.activeId, null);
  assert.equal(store.has("leanchat.active"), false);
});

test("activeSession returns the session with the active id or null", () => {
  state.sessions = [
    { id: "a", name: "A", ts: 1 },
    { id: "b", name: "B", ts: 2 },
  ];
  setActiveId("b");
  assert.equal(activeSession().name, "B");
  setActiveId("missing");
  assert.equal(activeSession(), null);
});

test("normalizeMessage maps server in_context to inContext", () => {
  // Regression: API liefert in_context (snake_case), UI liest inContext
  assert.equal(normalizeMessage({ id: 1, in_context: false }).inContext, false);
  assert.equal(normalizeMessage({ id: 2, in_context: true }).inContext, true);
  // ohne Server-Feld bleibt der lokale inContext-Wert erhalten
  assert.equal(normalizeMessage({ id: 3, inContext: false }).inContext, false);
  assert.equal(normalizeMessage({ id: 4 }).inContext, true);
});

test("normalizeMessages handles lists and null", () => {
  assert.deepEqual(normalizeMessages(null), []);
  const out = normalizeMessages([{ id: 1, in_context: false }]);
  assert.equal(out[0].inContext, false);
  assert.equal(out[0].id, 1);
});

test("state.settings enthaelt alle BOOL_SETTING_KEYS mit ihren Defaults (Single Source of Truth)", async () => {
  const { BOOL_SETTING_KEYS, BOOL_SETTING_DEFAULTS, defaultBoolSettings } = await import("../../static/js/settingsKeys.js");
  assert.deepEqual(defaultBoolSettings(), BOOL_SETTING_DEFAULTS);
  for (const k of BOOL_SETTING_KEYS) {
    assert.ok(k in BOOL_SETTING_DEFAULTS, `Default fehlt fuer ${k}`);
    assert.equal(state.settings[k], BOOL_SETTING_DEFAULTS[k]);
  }
});
