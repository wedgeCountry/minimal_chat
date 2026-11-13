import test from "node:test";
import assert from "node:assert/strict";
import { isBubbleDeletable, isBubbleCheckable, isBubbleSpeaker, isBubbleVisible } from "../../static/js/visibility.js";

const allOn = {
  bubbles_deletable: true,
  bubbles_checkable: true,
  bubbles_speaker: true,
  show_system_prompt: true,
  show_tool_output: true,
  show_reasoning: true,
};

test("alle Bubbles sichtbar bei Defaults", () => {
  assert.ok(isBubbleVisible({ role: "user", type: "message" }, allOn));
  assert.ok(isBubbleVisible({ role: "assistant", type: "reasoning" }, allOn));
  assert.ok(isBubbleVisible({ role: "assistant", type: "toolcall" }, allOn));
  assert.ok(isBubbleVisible({ role: "assistant", type: "toolresult" }, allOn));
  assert.ok(isBubbleVisible({ role: "system", type: "message" }, allOn));
});

test("show_reasoning=false blendet Reasoning-Bubbles aus", () => {
  const s = { ...allOn, show_reasoning: false };
  assert.equal(isBubbleVisible({ role: "assistant", type: "reasoning" }, s), false);
  assert.ok(isBubbleVisible({ role: "assistant", type: "message" }, s));
});

test("show_tool_output=false blendet Tool-Calls und Tool-Results aus", () => {
  const s = { ...allOn, show_tool_output: false };
  assert.equal(isBubbleVisible({ role: "assistant", type: "toolcall" }, s), false);
  assert.equal(isBubbleVisible({ role: "assistant", type: "toolresult" }, s), false);
});

test("show_system_prompt=false blendet System-Bubbles aus", () => {
  const s = { ...allOn, show_system_prompt: false };
  assert.equal(isBubbleVisible({ role: "system", type: "message" }, s), false);
});

test("Checkable/Speaker Schalter", () => {
  assert.ok(isBubbleCheckable(allOn));
  assert.equal(isBubbleCheckable({ ...allOn, bubbles_checkable: false }), false);
  assert.ok(isBubbleSpeaker(allOn));
  assert.equal(isBubbleSpeaker({ ...allOn, bubbles_speaker: false }), false);
});

test("bubbles_deletable=false sperrt den Loeschen-Button fuer alle Bubbles", () => {
  assert.ok(isBubbleDeletable(allOn));
  assert.equal(isBubbleDeletable({ ...allOn, bubbles_deletable: false }), false);
  assert.equal(isBubbleDeletable({}), true);
});
