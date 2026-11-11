import test from "node:test";
import assert from "node:assert/strict";
import { sortMessagesForRender } from "../../static/js/chat.js";

test("sortMessagesForRender: reasoning bubbles appear before message bubbles with the same timestamp", () => {
  const messages = [
    { role: "assistant", type: "message", text: "Answer 1", ts: 1000, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking 1", ts: 1000, inContext: false },
    { role: "user", type: "message", text: "User message", ts: 500, inContext: true },
    { role: "assistant", type: "message", text: "Answer 2", ts: 2000, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking 2", ts: 2000, inContext: false },
  ];

  const sorted = sortMessagesForRender(messages);

  // Verify the order
  assert.equal(sorted.length, 5, "All messages should be present");

  // Check that reasoning bubbles appear before their corresponding message bubbles
  const reasoning1Index = sorted.findIndex((m) => m.type === "reasoning" && m.text === "Thinking 1");
  const message1Index = sorted.findIndex((m) => m.type === "message" && m.text === "Answer 1");
  assert.ok(reasoning1Index < message1Index, "Reasoning 1 should appear before Answer 1");

  const reasoning2Index = sorted.findIndex((m) => m.type === "reasoning" && m.text === "Thinking 2");
  const message2Index = sorted.findIndex((m) => m.type === "message" && m.text === "Answer 2");
  assert.ok(reasoning2Index < message2Index, "Reasoning 2 should appear before Answer 2");

  // Check overall order: user message, reasoning 1, answer 1, reasoning 2, answer 2
  assert.equal(sorted[0].text, "User message");
  assert.equal(sorted[1].text, "Thinking 1");
  assert.equal(sorted[2].text, "Answer 1");
  assert.equal(sorted[3].text, "Thinking 2");
  assert.equal(sorted[4].text, "Answer 2");
});

test("sortMessagesForRender: messages with different timestamps remain in chronological order", () => {
  const messages = [
    { role: "user", type: "message", text: "User message 1", ts: 1000, inContext: true },
    { role: "assistant", type: "message", text: "Answer 1", ts: 2000, inContext: true },
    { role: "user", type: "message", text: "User message 2", ts: 3000, inContext: true },
    { role: "assistant", type: "message", text: "Answer 2", ts: 4000, inContext: true },
  ];

  const sorted = sortMessagesForRender(messages);

  // Verify the order remains chronological
  assert.equal(sorted.length, 4);
  assert.equal(sorted[0].text, "User message 1");
  assert.equal(sorted[1].text, "Answer 1");
  assert.equal(sorted[2].text, "User message 2");
  assert.equal(sorted[3].text, "Answer 2");
});

test("sortMessagesForRender: handles empty array", () => {
  const sorted = sortMessagesForRender([]);
  assert.equal(sorted.length, 0);
});

test("sortMessagesForRender: handles single message", () => {
  const messages = [{ role: "user", type: "message", text: "Hello", ts: 1000, inContext: true }];
  const sorted = sortMessagesForRender(messages);
  assert.equal(sorted.length, 1);
  assert.equal(sorted[0].text, "Hello");
});

test("sortMessagesForRender: reasoning and message with same timestamp, reasoning first", () => {
  const messages = [
    { role: "assistant", type: "message", text: "Answer", ts: 1000, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking", ts: 1000, inContext: false },
  ];

  const sorted = sortMessagesForRender(messages);
  assert.equal(sorted.length, 2);
  assert.equal(sorted[0].type, "reasoning");
  assert.equal(sorted[1].type, "message");
});

test("sortMessagesForRender: multiple reasoning and message bubbles with same timestamp", () => {
  const messages = [
    { role: "assistant", type: "message", text: "Answer 1", ts: 1000, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking 1", ts: 1000, inContext: false },
    { role: "assistant", type: "message", text: "Answer 2", ts: 1000, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking 2", ts: 1000, inContext: false },
  ];

  const sorted = sortMessagesForRender(messages);
  assert.equal(sorted.length, 4);
  // All reasoning bubbles should appear before all message bubbles
  assert.equal(sorted[0].type, "reasoning");
  assert.equal(sorted[0].text, "Thinking 1");
  assert.equal(sorted[1].type, "reasoning");
  assert.equal(sorted[1].text, "Thinking 2");
  assert.equal(sorted[2].type, "message");
  assert.equal(sorted[2].text, "Answer 1");
  assert.equal(sorted[3].type, "message");
  assert.equal(sorted[3].text, "Answer 2");
});

test("sortMessagesForRender: other message types (e.g., toolcall) appear after reasoning and message", () => {
  const messages = [
    { role: "assistant", type: "message", text: "Answer", ts: 1000, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking", ts: 1000, inContext: false },
    { role: "assistant", type: "toolcall", text: "Tool Call", ts: 1000, inContext: false },
  ];

  const sorted = sortMessagesForRender(messages);
  assert.equal(sorted.length, 3);
  // Order: reasoning, message, toolcall
  assert.equal(sorted[0].type, "reasoning");
  assert.equal(sorted[1].type, "message");
  assert.equal(sorted[2].type, "toolcall");
});

test("sortMessagesForRender: system bubbles appear before all other bubbles", () => {
  const messages = [
    { role: "system", type: "message", text: "System Prompt", ts: 1000, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking", ts: 1000, inContext: false },
    { role: "assistant", type: "message", text: "Answer", ts: 1000, inContext: true },
    { role: "assistant", type: "toolcall", text: "Tool Call", ts: 1000, inContext: false },
  ];

  const sorted = sortMessagesForRender(messages);
  assert.equal(sorted.length, 4);
  // Order: system, reasoning, message, toolcall
  assert.equal(sorted[0].role, "system");
  assert.equal(sorted[0].text, "System Prompt");
  assert.equal(sorted[1].type, "reasoning");
  assert.equal(sorted[1].text, "Thinking");
  assert.equal(sorted[2].type, "message");
  assert.equal(sorted[2].text, "Answer");
  assert.equal(sorted[3].type, "toolcall");
  assert.equal(sorted[3].text, "Tool Call");
});
