import test from "node:test";
import assert from "node:assert/strict";

function stubDom() {
  const events = [];
  globalThis.document = { dispatchEvent: (e) => events.push(e.type) };
  return events;
}

const { openSession, newSession } = await import("../../static/js/sessions.js");
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
