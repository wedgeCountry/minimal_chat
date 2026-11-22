import test from "node:test";
import assert from "node:assert/strict";

function stubSide() {
  const side = {
    classes: new Set(["hidden"]),
    classList: null,
  };
  side.classList = {
    contains: (c) => side.classes.has(c),
    toggle: (c, force) => {
      const on = force === undefined ? !side.classes.has(c) : force;
      if (on) side.classes.add(c);
      else side.classes.delete(c);
    },
    add: (c) => side.classes.add(c),
  };
  globalThis.document = { getElementById: (id) => (id === "side" ? side : null) };
  return side;
}

function stubHistoryAndWindow() {
  const calls = { push: [], back: 0 };
  const listeners = {};
  let state = null;
  globalThis.history = {
    get state() {
      return state;
    },
    pushState: (s) => {
      calls.push.push(s);
      state = s;
    },
    back: () => {
      calls.back += 1;
      state = null;
    },
  };
  globalThis.window = {
    addEventListener: (ev, fn) => {
      (listeners[ev] ||= []).push(fn);
    },
  };
  globalThis.location = { pathname: "/", search: "", hash: "" };
  return {
    calls,
    fire: (ev) => (listeners[ev] || []).forEach((fn) => fn({})),
  };
}

const { setSideHidden, initSidePanelHistory } = await import("../../static/js/sidePanel.js");

test("oeffnen des Panels pusht einen History-Eintrag", () => {
  const side = stubSide();
  const { calls } = stubHistoryAndWindow();
  setSideHidden(false);
  assert.equal(side.classList.contains("hidden"), false);
  assert.deepEqual(calls.push, [{ sidePanelOpen: true }]);
  assert.equal(calls.back, 0);
});

test("schliessen per UI nach dem Oeffnen entfernt den Eintrag wieder", () => {
  const side = stubSide();
  const { calls } = stubHistoryAndWindow();
  setSideHidden(false);
  setSideHidden(true);
  assert.equal(side.classList.contains("hidden"), true);
  assert.equal(calls.back, 1);
});

test("popstate bei offenem Panel schliesst es ohne weiteres history.back", () => {
  const side = stubSide();
  const env = stubHistoryAndWindow();
  initSidePanelHistory();
  setSideHidden(false);
  env.fire("popstate");
  assert.equal(side.classList.contains("hidden"), true);
  assert.equal(env.calls.back, 0);
  assert.equal(env.calls.push.length, 1);
});

test("popstate bei geschlossenem Panel aendert nichts", () => {
  const side = stubSide();
  const env = stubHistoryAndWindow();
  initSidePanelHistory();
  env.fire("popstate");
  assert.equal(side.classList.contains("hidden"), true);
  assert.equal(env.calls.back, 0);
  assert.equal(env.calls.push.length, 0);
});

test("initiales Ausblenden pusht keinen Eintrag", () => {
  const side = stubSide();
  const { calls } = stubHistoryAndWindow();
  setSideHidden(true);
  assert.equal(side.classList.contains("hidden"), true);
  assert.equal(calls.push.length, 0);
  assert.equal(calls.back, 0);
});

test("setSideHidden(true, false) schliesst ohne history.back (kein Race mit anschliessendem pushState)", () => {
  const side = stubSide();
  const { calls } = stubHistoryAndWindow();
  setSideHidden(false);
  setSideHidden(true, false);
  assert.equal(side.classList.contains("hidden"), true);
  assert.equal(calls.back, 0);
});
