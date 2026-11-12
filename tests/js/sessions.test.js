import test from "node:test";
import assert from "node:assert/strict";

function stubDom() {
  const events = [];
  globalThis.document = { dispatchEvent: (e) => events.push(e.type) };
  return events;
}

const { openSession, newSession, sortedSessions, loadSessions, renameSession } = await import("../../static/js/sessions.js");
const { state } = await import("../../static/js/state.js");

test("openSession dispatches leanchat:session-selected", () => {
  const events = stubDom();
  state.sessions = [{ id: "s1", name: "A", ts: 1 }];
  openSession("s1");
  assert.ok(events.includes("leanchat:session-selected"));
  assert.equal(state.activeId, "s1");
});

test("newSession(open=true) dispatches leanchat:session-selected", async () => {
  const events = stubDom();
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ id: "s2", name: "Neue Session", ts: 2 }) });
  await newSession(true);
  assert.ok(events.includes("leanchat:session-selected"));
  assert.equal(state.activeId, "s2");
});

test("newSession(open=false) does not dispatch leanchat:session-selected", async () => {
  const events = stubDom();
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ id: "s3", name: "Neue Session", ts: 3 }) });
  await newSession(false);
  assert.equal(events.includes("leanchat:session-selected"), false);
});

test("sortedSessions returns newest first without mutating state.sessions", () => {
  state.sessions = [
    { id: "old", ts: 1 },
    { id: "new", ts: 3 },
    { id: "mid", ts: 2 },
  ];
  assert.deepEqual(sortedSessions().map((s) => s.id), ["new", "mid", "old"]);
  assert.deepEqual(state.sessions.map((s) => s.id), ["old", "new", "mid"]);
});

test("loadSessions loads sessions and activates the first when none active", async () => {
  stubDom();
  globalThis.fetch = async (url) => {
    assert.equal(url, "/api/sessions");
    return { ok: true, status: 200, json: async () => [{ id: "s9", name: "A", ts: 9 }], text: async () => "" };
  };
  state.activeId = null;
  await loadSessions();
  assert.deepEqual(state.sessions, [{ id: "s9", name: "A", ts: 9 }]);
  assert.equal(state.activeId, "s9");
});

function stubRenameDom(inputValue) {
  const inp = { dataset: {}, value: inputValue, focus() {}, select() {}, onkeydown: null, onblur: null };
  const nameEl = { replaceChildren() {} };
  globalThis.document = {
    dispatchEvent: () => {},
    querySelector: (sel) => (sel === '[data-name="s1"]' ? nameEl : null),
    createElement: () => inp,
  };
  return inp;
}

test("renameSession: empty/whitespace name keeps old name (no PATCH)", async () => {
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, method: opts?.method });
    return { ok: true, status: 200, json: async () => [], text: async () => "" };
  };
  const inp = stubRenameDom("");
  state.sessions = [{ id: "s1", name: "Alt", ts: 1 }];
  const p = renameSession("s1");
  inp.value = "   "; // Leer-Eingabe nach Oeffnen des Editors
  inp.onkeydown({ key: "Enter", stopPropagation() {} });
  await p;
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(calls.filter((c) => c.method === "PATCH").length, 0);
  assert.equal(state.sessions[0].name, "Alt");
});

test("renameSession: new name is sent via PATCH, Escape cancels without PATCH", async () => {
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, method: opts?.method, body: opts?.body });
    return { ok: true, status: 200, json: async () => [{ id: "s1", name: "Neu", ts: 1 }], text: async () => "" };
  };
  state.sessions = [{ id: "s1", name: "Alt", ts: 1 }];

  const inp1 = stubRenameDom("");
  const p1 = renameSession("s1");
  inp1.value = "Neu"; // neuer Name nach Oeffnen des Editors
  inp1.onkeydown({ key: "Enter", stopPropagation() {} });
  await p1;
  await new Promise((r) => setTimeout(r, 10));
  const patch = calls.find((c) => c.method === "PATCH");
  assert.ok(patch);
  assert.equal(patch.url, "/api/sessions/s1");
  assert.deepEqual(JSON.parse(patch.body), { name: "Neu" });

  calls.length = 0;
  const inp2 = stubRenameDom("");
  const p2 = renameSession("s1");
  inp2.value = "Anderer";
  inp2.onkeydown({ key: "Escape", stopPropagation() {} });
  await p2;
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(calls.filter((c) => c.method === "PATCH").length, 0);
});
