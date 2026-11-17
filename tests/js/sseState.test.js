import test from "node:test";
import assert from "node:assert/strict";
import { applySseState } from "../../static/js/chat.js";

test("applySseState: state-Event mit hoeherem seq wird uebernommen", () => {
  const cur = { seq: 2, messages: [{ id: 1, text: "alt", in_context: true }] };
  const next = applySseState({ type: "state", seq: 3, messages: [{ id: 1, text: "neu", in_context: true }, { id: null, text: "live", in_context: true, ts: 0 }] }, cur);
  assert.equal(next.seq, 3);
  assert.equal(next.messages.length, 2);
  assert.equal(next.messages[0].inContext, true, "in_context wird zu inContext normalisiert");
  assert.ok(next.messages[1].ts > 0, "Live-Messages bekommen clientseitig ein ts (sortieren ans Ende)");
});

test("applySseState: veraltetes seq und Nicht-state-Events werden verworfen", () => {
  const cur = { seq: 5, messages: [] };
  assert.equal(applySseState({ type: "state", seq: 4, messages: [{ id: 9 }] }, cur), cur);
  assert.equal(applySseState({ type: "state", seq: 5, messages: [] }, cur), cur);
  assert.equal(applySseState({ type: "done" }, cur), cur);
  assert.equal(applySseState(null, cur), cur);
});
