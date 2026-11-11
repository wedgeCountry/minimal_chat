import test from "node:test";
import assert from "node:assert/strict";

function stubDom({ mobile }) {
  const side = { classes: new Set(), classList: { add(c) { this.classes.add(c); }, contains(c) { return this.classes.has(c); } } };
  side.classList.classes = side.classes;
  globalThis.window = { matchMedia: () => ({ matches: mobile }) };
  globalThis.document = {
    getElementById: (id) => (id === "side" ? side : null),
    dispatchEvent: () => true,
  };
  return side;
}

const { openSession, newSession, hideSidePanelOnMobile } = await import("../../static/js/sessions.js");
const { state } = await import("../../static/js/state.js");

test("openSession hides side panel on mobile", () => {
  const side = stubDom({ mobile: true });
  state.sessions = [{ id: "s1", name: "A", ts: 1 }];
  openSession("s1");
  assert.ok(side.classList.contains("hidden"));
  assert.equal(state.activeId, "s1");
});

test("openSession keeps side panel visible on desktop", () => {
  const side = stubDom({ mobile: false });
  state.sessions = [{ id: "s1", name: "A", ts: 1 }];
  openSession("s1");
  assert.equal(side.classList.contains("hidden"), false);
});

test("newSession(open=true) hides side panel on mobile", async () => {
  const side = stubDom({ mobile: true });
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ id: "s2", name: "Neue Session", ts: 2 }) });
  await newSession(true);
  assert.ok(side.classList.contains("hidden"));
  assert.equal(state.activeId, "s2");
});

test("newSession(open=false) does not hide side panel", async () => {
  const side = stubDom({ mobile: true });
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ id: "s3", name: "Neue Session", ts: 3 }) });
  await newSession(false);
  assert.equal(side.classList.contains("hidden"), false);
});

test("hideSidePanelOnMobile is a no-op on desktop", () => {
  const side = stubDom({ mobile: false });
  hideSidePanelOnMobile();
  assert.equal(side.classList.contains("hidden"), false);
});
