import test from "node:test";
import assert from "node:assert/strict";

const events = [];
globalThis.document = { dispatchEvent: (e) => events.push(e.type) };
const fetchCalls = [];
globalThis.fetch = async (url, opts) => {
  fetchCalls.push({ url, opts });
  return { ok: true, status: 200, json: async () => ({ ok: true }), text: async () => "{}" };
};

let histState = null;
const histCalls = { push: [], replace: [] };
globalThis.history = {
  get state() {
    return histState;
  },
  pushState: (s, _t, url) => {
    histCalls.push.push({ s, url });
    histState = s;
  },
  replaceState: (s, _t, url) => {
    histCalls.replace.push({ s, url });
    histState = s;
  },
};
globalThis.location = { hash: "" };
const listeners = {};
globalThis.window = { addEventListener: (ev, fn) => (listeners[ev] ||= []).push(fn) };

const { state, setActiveId } = await import("../../static/js/state.js");
const { viewPath, sessionIdFromHash, pushView, replaceView, initViewHistory } = await import("../../static/js/visits.js");

test("viewPath kodiert die aktive Session als Hash", () => {
  state.sessions = [{ id: "s1", name: "A", ts: 1 }];
  setActiveId("s1");
  assert.equal(viewPath(), "/#s/s1");
  setActiveId(null);
  assert.equal(viewPath(), "/");
});

test("sessionIdFromHash parst nur Session-Hashes", () => {
  assert.equal(sessionIdFromHash("#/s/abc"), "abc");
  assert.equal(sessionIdFromHash("#/s/a%20b"), "a b");
  assert.equal(sessionIdFromHash("#/s/a/b"), null);
  assert.equal(sessionIdFromHash("#/other"), null);
  assert.equal(sessionIdFromHash(""), null);
});

test("pushView pusht History-Eintrag und meldet den Pfad an den Server", () => {
  state.sessions = [{ id: "s1", name: "A", ts: 1 }];
  setActiveId("s1");
  fetchCalls.length = 0;
  histCalls.push.length = 0;
  pushView();
  assert.equal(histCalls.push.length, 1);
  assert.equal(histCalls.push[0].url, "/#s/s1");
  assert.deepEqual(histCalls.push[0].s, { lcView: "/#s/s1" });
  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0].url, "/api/visits");
  assert.deepEqual(JSON.parse(fetchCalls[0].opts.body), { path: "/#s/s1" });
});

test("replaceView ersetzt den aktuellen Eintrag und meldet den Pfad", () => {
  state.sessions = [{ id: "s1", name: "A", ts: 1 }];
  setActiveId("s1");
  fetchCalls.length = 0;
  histCalls.replace.length = 0;
  replaceView();
  assert.equal(histCalls.replace.length, 1);
  assert.equal(histCalls.replace[0].url, "/#s/s1");
  assert.equal(fetchCalls.length, 1);
});

test("popstate wechselt auf die Session aus dem Hash ohne neuen Eintrag", () => {
  state.sessions = [
    { id: "a", name: "A", ts: 1 },
    { id: "b", name: "B", ts: 2 },
  ];
  setActiveId("a");
  initViewHistory();
  location.hash = "#/s/b";
  histCalls.push.length = 0;
  (listeners["popstate"] || []).forEach((fn) => fn({}));
  assert.equal(state.activeId, "b");
  assert.equal(histCalls.push.length, 0);
});

test("popstate ohne Session-Hash aendert die aktive Session nicht", () => {
  state.sessions = [{ id: "a", name: "A", ts: 1 }];
  setActiveId("a");
  location.hash = "";
  (listeners["popstate"] || []).forEach((fn) => fn({}));
  assert.equal(state.activeId, "a");
});
