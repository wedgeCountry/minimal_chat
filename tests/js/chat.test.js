import test from "node:test";
import assert from "node:assert/strict";
import { sortMessagesForRender } from "../../static/js/chat.js";

test("sortMessagesForRender: chronological by ts", () => {
  const messages = [
    { role: "assistant", type: "message", text: "Answer 2", ts: 2000, id: 4, inContext: true },
    { role: "user", type: "message", text: "User message", ts: 500, id: 1, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking 1", ts: 1000, id: 2, inContext: false },
    { role: "assistant", type: "message", text: "Answer 1", ts: 1000, id: 3, inContext: true },
  ];

  const sorted = sortMessagesForRender(messages);

  assert.equal(sorted.length, 4, "All messages should be present");
  assert.equal(sorted[0].text, "User message");
  assert.equal(sorted[1].text, "Thinking 1");
  assert.equal(sorted[2].text, "Answer 1");
  assert.equal(sorted[3].text, "Answer 2");
});

test("sortMessagesForRender: same ts falls back to id (reasoning persisted before its answer)", () => {
  const messages = [
    { role: "assistant", type: "message", text: "Answer", ts: 1000, id: 3, inContext: true },
    { role: "user", type: "message", text: "User", ts: 1000, id: 1, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking", ts: 1000, id: 2, inContext: false },
  ];

  const sorted = sortMessagesForRender(messages);

  assert.deepEqual(sorted.map((m) => m.text), ["User", "Thinking", "Answer"]);
});

test("sortMessagesForRender: reasoning does not jump above earlier user messages", () => {
  // Regression: with only priority-on-equal-ts, a reasoning bubble of a later
  // turn was sorted above the user message of the same second.
  const messages = [
    { role: "user", type: "message", text: "Frage 1", ts: 1000, id: 1, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking 1", ts: 1000, id: 2, inContext: false },
    { role: "assistant", type: "message", text: "Antwort 1", ts: 1000, id: 3, inContext: true },
    { role: "user", type: "message", text: "Frage 2", ts: 2000, id: 4, inContext: true },
    { role: "assistant", type: "reasoning", text: "Thinking 2", ts: 2000, id: 5, inContext: false },
    { role: "assistant", type: "message", text: "Antwort 2", ts: 2000, id: 6, inContext: true },
  ];

  const sorted = sortMessagesForRender(messages);

  assert.deepEqual(
    sorted.map((m) => m.text),
    ["Frage 1", "Thinking 1", "Antwort 1", "Frage 2", "Thinking 2", "Antwort 2"]
  );
});

test("sortMessagesForRender: handles empty array", () => {
  assert.equal(sortMessagesForRender([]).length, 0);
});

test("sortMessagesForRender: handles single message", () => {
  const sorted = sortMessagesForRender([{ role: "user", type: "message", text: "Hello", ts: 1000, id: 1 }]);
  assert.equal(sorted.length, 1);
  assert.equal(sorted[0].text, "Hello");
});

test("sortMessagesForRender: messages without ts keep id order", () => {
  const messages = [
    { role: "assistant", type: "message", text: "Antwort", id: 2 },
    { role: "user", type: "message", text: "Frage", id: 1 },
  ];
  const sorted = sortMessagesForRender(messages);
  assert.deepEqual(sorted.map((m) => m.text), ["Frage", "Antwort"]);
});
