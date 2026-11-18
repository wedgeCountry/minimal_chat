import test from "node:test";
import assert from "node:assert/strict";
import { sortMessagesForRender, findLastUserMessage, hasMessagesAfter, applyLocalMessage, removeLocalMessage, removeLocalMessagesAfter, cancelSelectionIfTouchOutsideBubble } from "../../static/js/chat.js";
import { state } from "../../static/js/state.js";

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

test("sortMessagesForRender: gleicher ts -> finale Assistant-Message zuletzt, Toolcall vor Toolresult", () => {
  // Persistiert wird ai vor den Tool-Bubbles (id 3 < 4 < 5) - gerendert darf die Antwort trotzdem zuletzt landen
  const messages = [
    { role: "user", type: "message", text: "Frage", ts: 1000, id: 1 },
    { role: "assistant", type: "reasoning", text: "Thinking", ts: 1000, id: 2 },
    { role: "assistant", type: "message", text: "Antwort", ts: 1000, id: 3 },
    { role: "assistant", type: "toolcall", text: "f({})", ts: 1000, id: 4 },
    { role: "assistant", type: "toolresult", text: "f: 42", ts: 1000, id: 5 },
  ];
  const sorted = sortMessagesForRender(messages);
  assert.deepEqual(
    sorted.map((m) => m.text),
    ["Frage", "Thinking", "f({})", "f: 42", "Antwort"]
  );
});

test("sortMessagesForRender: gleicher ts -> User-Message bleibt vor Assistant-Bubbles", () => {
  const messages = [
    { role: "assistant", type: "reasoning", text: "Thinking", ts: 1000, id: 2 },
    { role: "user", type: "message", text: "Frage", ts: 1000, id: 1 },
    { role: "assistant", type: "message", text: "Antwort", ts: 1000, id: 3 },
  ];
  const sorted = sortMessagesForRender(messages);
  assert.deepEqual(sorted.map((m) => m.text), ["Frage", "Thinking", "Antwort"]);
});

test("sortMessagesForRender: zwei Turns in derselben Sekunde bleiben in Gespraechsreihenfolge", () => {
  // Regression: die letzte User-Message darf nicht ueber die erste Antwort rutschen
  const messages = [
    { role: "user", type: "message", text: "Frage 1", ts: 1000, id: 1 },
    { role: "assistant", type: "message", text: "Antwort 1", ts: 1000, id: 2 },
    { role: "user", type: "message", text: "Frage 2", ts: 1000, id: 3 },
    { role: "assistant", type: "message", text: "Antwort 2", ts: 1000, id: 4 },
  ];
  const sorted = sortMessagesForRender(messages);
  assert.deepEqual(sorted.map((m) => m.text), ["Frage 1", "Antwort 1", "Frage 2", "Antwort 2"]);
});

test("sortMessagesForRender: gleicher ts, ein Turn mit Tools -> Frage, Thinking, Toolcall, Toolresult, Antwort; naechster Turn danach", () => {
  const messages = [
    { role: "user", type: "message", text: "Frage 1", ts: 1000, id: 1 },
    { role: "assistant", type: "message", text: "Antwort 1", ts: 1000, id: 2 },
    { role: "assistant", type: "toolcall", text: "f({})", ts: 1000, id: 3 },
    { role: "assistant", type: "toolresult", text: "f: 42", ts: 1000, id: 4 },
    { role: "user", type: "message", text: "Frage 2", ts: 1000, id: 5 },
    { role: "assistant", type: "message", text: "Antwort 2", ts: 1000, id: 6 },
  ];
  const sorted = sortMessagesForRender(messages);
  assert.deepEqual(
    sorted.map((m) => m.text),
    ["Frage 1", "f({})", "f: 42", "Antwort 1", "Frage 2", "Antwort 2"]
  );
});

test("sortMessagesForRender: eigene ms-Ts pro Stream-Block -> Stream-Reihenfolge innerhalb eines Turns", () => {
  // Zwei Zyklen (reasoning, toolcall, toolresult, message) mit Abschluss-Ts je Block:
  // die Sortierung bleibt rein chronologisch, es wird nicht nach Typ umsortiert.
  const messages = [
    { role: "user", type: "message", text: "Frage", ts: 1000, id: 1 },
    { role: "assistant", type: "reasoning", text: "Denken 1", ts: 1001, id: 2 },
    { role: "assistant", type: "toolcall", text: "f({})", ts: 1002, id: 3 },
    { role: "assistant", type: "toolresult", text: "f: 42", ts: 1003, id: 4 },
    { role: "assistant", type: "message", text: "Antwort 1", ts: 1004, id: 5 },
    { role: "assistant", type: "reasoning", text: "Denken 2", ts: 1005, id: 6 },
    { role: "assistant", type: "toolcall", text: "g({})", ts: 1006, id: 7 },
    { role: "assistant", type: "toolresult", text: "g: 43", ts: 1007, id: 8 },
    { role: "assistant", type: "message", text: "Antwort 2", ts: 1008, id: 9 },
  ];
  const sorted = sortMessagesForRender(messages);
  assert.deepEqual(
    sorted.map((m) => m.text),
    ["Frage", "Denken 1", "f({})", "f: 42", "Antwort 1", "Denken 2", "g({})", "g: 43", "Antwort 2"]
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

test("findLastUserMessage: returns the chronologically last user message", () => {
  const messages = [
    { role: "user", type: "message", text: "Frage 1", ts: 1000, id: 1 },
    { role: "assistant", type: "message", text: "Antwort 1", ts: 2000, id: 2 },
    { role: "user", type: "message", text: "Frage 2", ts: 3000, id: 3 },
  ];
  assert.equal(findLastUserMessage(messages).id, 3);
});

test("findLastUserMessage: ignores reasoning/toolcall/system, null when none", () => {
  const messages = [
    { role: "user", type: "message", text: "Frage", ts: 1000, id: 1 },
    { role: "assistant", type: "reasoning", text: "Denke", ts: 2000, id: 2 },
  ];
  assert.equal(findLastUserMessage(messages).id, 1);
  assert.equal(findLastUserMessage([{ role: "assistant", type: "message", text: "A", ts: 1, id: 1 }]), null);
  assert.equal(findLastUserMessage([]), null);
});

test("applyLocalMessage: upsert by id, in_context wird zu inContext normalisiert", () => {
  state.messages = [];
  applyLocalMessage({ id: 5, role: "user", type: "message", text: "hi", in_context: true, ts: 1 });
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].inContext, true);
  applyLocalMessage({ id: 5, role: "user", type: "message", text: "hi edited", in_context: false, ts: 1 });
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].text, "hi edited");
  assert.equal(state.messages[0].inContext, false);
  applyLocalMessage({ id: 6, role: "assistant", type: "message", text: "yo", ts: 2 });
  assert.deepEqual(state.messages.map((m) => m.id), [5, 6]);
});

test("removeLocalMessage: entfernt genau die angegebene id", () => {
  state.messages = [{ id: 1 }, { id: 2 }, { id: 3 }];
  removeLocalMessage(2);
  assert.deepEqual(state.messages.map((m) => m.id), [1, 3]);
});

test("removeLocalMessagesAfter: behaelt id <= mid (AUTOINCREMENT-monoton = serverseitige Loeschmenge)", () => {
  state.messages = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }];
  removeLocalMessagesAfter(2);
  assert.deepEqual(state.messages.map((m) => m.id), [1, 2]);
});

test("hasMessagesAfter: true only when messages follow the given id (edit-truncate check)", () => {
  const messages = [
    { role: "user", type: "message", text: "Frage 1", ts: 1000, id: 1 },
    { role: "assistant", type: "message", text: "Antwort 1", ts: 2000, id: 2 },
    { role: "user", type: "message", text: "Frage 2", ts: 3000, id: 3 },
    { role: "assistant", type: "message", text: "Antwort 2", ts: 4000, id: 4 },
  ];
  assert.equal(hasMessagesAfter(messages, 3), true, "Antwort 2 folgt auf Frage 2");
  assert.equal(hasMessagesAfter(messages, 1), true);
  assert.equal(hasMessagesAfter(messages, 4), false, "letzte Nachricht: nichts folgt");
  assert.equal(hasMessagesAfter(messages, 999), false, "unbekannte id");
  assert.equal(hasMessagesAfter([], 1), false);
});

function fakeSelection(anchorNode) {
  const sel = { isCollapsed: false, rangeCount: 1, anchorNode, cleared: 0 };
  sel.removeAllRanges = () => sel.cleared++;
  return sel;
}

test("cancelSelectionIfTouchOutsideBubble: Touch ausserhalb der Bubble hebt die Auswahl sofort auf", () => {
  const inside = {};
  const outside = {};
  const bubble = { contains: (t) => t === inside };
  const anchorEl = { closest: (s) => (s === ".bubble" ? bubble : null) };
  const sel = fakeSelection({ nodeType: 3, parentElement: anchorEl });
  assert.equal(cancelSelectionIfTouchOutsideBubble(sel, outside), true);
  assert.equal(sel.cleared, 1);
});

test("cancelSelectionIfTouchOutsideBubble: Touch innerhalb derselben Bubble behaelt die Auswahl", () => {
  const inside = {};
  const bubble = { contains: (t) => t === inside };
  const anchorEl = { closest: (s) => (s === ".bubble" ? bubble : null) };
  const sel = fakeSelection({ nodeType: 3, parentElement: anchorEl });
  assert.equal(cancelSelectionIfTouchOutsideBubble(sel, inside), false);
  assert.equal(sel.cleared, 0);
});

test("cancelSelectionIfTouchOutsideBubble: anchorNode als Element (nodeType 1) wird direkt verwendet", () => {
  const outside = {};
  const bubble = { contains: () => false };
  const anchorEl = { nodeType: 1, closest: (s) => (s === ".bubble" ? bubble : null) };
  const sel = fakeSelection(anchorEl);
  assert.equal(cancelSelectionIfTouchOutsideBubble(sel, outside), true);
  assert.equal(sel.cleared, 1);
});

test("cancelSelectionIfTouchOutsideBubble: kollabierte Auswahl, fehlender anchorNode oder Auswahl ausserhalb einer Bubble -> nichts tun", () => {
  const collapsed = { isCollapsed: true, rangeCount: 1, anchorNode: null, cleared: 0, removeAllRanges() { this.cleared++; } };
  assert.equal(cancelSelectionIfTouchOutsideBubble(collapsed, {}), false);
  assert.equal(collapsed.cleared, 0);

  const noAnchor = fakeSelection(null);
  assert.equal(cancelSelectionIfTouchOutsideBubble(noAnchor, {}), false);
  assert.equal(noAnchor.cleared, 0);

  const outsideBubble = fakeSelection({ nodeType: 3, parentElement: { closest: () => null } });
  assert.equal(cancelSelectionIfTouchOutsideBubble(outsideBubble, {}), false);
  assert.equal(outsideBubble.cleared, 0);

  assert.equal(cancelSelectionIfTouchOutsideBubble(null, {}), false);
});
