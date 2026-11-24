import test from "node:test";
import assert from "node:assert/strict";
import { sortMessagesForRender, findLastUserMessage, hasMessagesAfter, applyLocalMessage, removeLocalMessage, removeLocalMessagesAfter, inheritedBubbleMode, onBubbleTap, initBubbleMenu, closeBubbleCtxMenu, send, stopPolling } from "../../static/js/chat.js";
import { state } from "../../static/js/state.js";
import { speak, isSpeaking, stopSpeech } from "../../static/js/ttsDetectionService.js";
import { setBubbleText } from "../../static/js/bubbles.js";

const LONG_TEXT = Array.from({ length: 15 }, (_, i) => `Zeile ${i + 1}`).join("\n");

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

test("inheritedBubbleMode: persistierte Nachricht uebernimmt den Modus der ersetzten Live-Bubble (gleich Rolle+Typ)", () => {
  // Stream-Ende: der offene Block (id=null, Key live-<idx>) bekommt seine DB-id (msg-<id>)
  const nodes = new Map([
    ["msg-1", { _msg: { id: 1, role: "user", type: "message" }, dataset: { mode: "normal" } }],
    ["live-1", { _msg: { id: null, role: "assistant", type: "message" }, dataset: { mode: "full" } }],
  ]);
  assert.equal(inheritedBubbleMode(nodes, { id: 2, role: "assistant", type: "message" }), "full");
  assert.equal(inheritedBubbleMode(nodes, { id: 2, role: "assistant", type: "reasoning" }), undefined, "anderer Typ -> keine Uebernahme");
  assert.equal(inheritedBubbleMode(nodes, { id: 2, role: "user", type: "message" }), undefined, "andere Rolle -> keine Uebernahme");
});

test("inheritedBubbleMode: Live-Bubble selbst (id=null) und Nicht-live-Keys liefern nichts bzw. den eigenen Modus beim Re-Keying", () => {
  const nodes = new Map([
    ["sys-prompt", { _msg: { id: null, role: "system", type: "message" }, dataset: { mode: "full" } }],
    ["live-2", { _msg: { id: null, role: "assistant", type: "message" }, dataset: { mode: "collapsed" } }],
  ]);
  // sys-prompt traegt zwar id=null, aber keinen live-Key -> wird ignoriert
  assert.equal(inheritedBubbleMode(nodes, { id: 9, role: "system", type: "message" }), undefined);
  // derselbe Live-Block mit verschobenem Index (live-2 -> live-3) uebernimmt seinen Modus
  assert.equal(inheritedBubbleMode(nodes, { id: null, role: "assistant", type: "message" }), "collapsed");
  assert.equal(inheritedBubbleMode(new Map(), { id: 3, role: "assistant", type: "message" }), undefined);
  assert.equal(inheritedBubbleMode(nodes, null), undefined);
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

// --- onBubbleTap im Minimalismus: Touch Einfach-Tap = Expand-Zyklus, Doppel-Tap = nur Menue ---

let tapClock = 1_000_000; // monoton steigende synthetische timeStamps ueber alle Tests hinweg

function makeClassList() {
  const set = new Set();
  return {
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    toggle: (c, on) => (on ? set.add(c) : set.delete(c)),
    contains: (c) => set.has(c),
  };
}

function fakeTapBubble(chat) {
  const classes = makeClassList();
  classes.add("bubble");
  classes.add("normal");
  const body = { textContent: "", classList: makeClassList(), scrollHeight: 0, clientHeight: 0 };
  const chev = { title: "" };
  const collapseBtn = { style: {} };
  const b = {
    dataset: { mode: "normal", type: "message", testid: "bubble-msg-1" },
    classList: classes,
    _fullText: "Hallo Welt",
    querySelector: (sel) => (sel === ".bubbleBody" ? body : sel === ".chev" ? chev : sel === ".collapseBtn" ? collapseBtn : null),
    querySelectorAll: () => [],
    closest: (sel) => (sel === ".bubble" ? b : sel === "#chat" ? chat : null),
    getBoundingClientRect: () => ({ top: 10, bottom: 60, height: 50 }),
    _body: body,
  };
  return b;
}

function installTapDom({ finePointer }) {
  const listeners = {};
  const appended = [];
  const chat = {
    scrollTop: 0,
    addEventListener: (type, fn) => {
      (listeners[type] ??= []).push(fn);
    },
    getBoundingClientRect: () => ({ top: 0, bottom: 600 }),
  };
  const savedDoc = globalThis.document;
  const savedWin = globalThis.window;
  const savedSettings = state.settings;
  globalThis.document = {
    getElementById: (id) => (id === "chat" ? chat : null),
    createElement: () => ({
      children: [],
      style: {},
      dataset: {},
      className: "",
      textContent: "",
      onclick: null,
      removed: false,
      appendChild(c) {
        this.children.push(c);
      },
      remove() {
        this.removed = true;
      },
      contains: () => false,
      getBoundingClientRect: () => ({ top: 0, left: 0, width: 120, height: 40 }),
    }),
    body: { appendChild: (el) => appended.push(el) },
    addEventListener: (type, fn) => {
      (listeners[type] ??= []).push(fn);
    },
    removeEventListener: () => {},
    querySelectorAll: () => [],
  };
  globalThis.window = {
    matchMedia: () => ({ matches: finePointer }),
    getSelection: () => ({ isCollapsed: true }),
    innerWidth: 390,
    innerHeight: 844,
  };
  state.settings = { ...state.settings, bubbles_minimal: true };
  initBubbleMenu();
  return {
    listeners,
    appended,
    chat,
    cleanup() {
      closeBubbleCtxMenu();
      if (savedDoc === undefined) delete globalThis.document;
      else globalThis.document = savedDoc;
      if (savedWin === undefined) delete globalThis.window;
      else globalThis.window = savedWin;
      state.settings = savedSettings;
    },
  };
}

function tapAt(dom, b, t0, { dt = 50, dx = 0, dy = 0 } = {}) {
  const target = { closest: (sel) => (sel === ".bubble" ? b : null) };
  const pd = { target, timeStamp: t0, clientX: 5, clientY: 5, preventDefault() {} };
  const clk = { target, timeStamp: t0 + dt, clientX: 5 + dx, clientY: 5 + dy, preventDefault() {} };
  for (const fn of dom.listeners.pointerdown ?? []) fn(pd);
  for (const fn of dom.listeners.click ?? []) fn(clk);
}

function singleTap(dom, b) {
  const t0 = tapClock;
  tapClock += 1000; // Abstand > DBL_TAP_MAX_MS: kein Doppel-Tap
  tapAt(dom, b, t0);
}

function dblTap(dom, b) {
  const t0 = tapClock;
  tapClock += 1000;
  tapAt(dom, b, t0);
  tapAt(dom, b, t0 + 200); // 200ms <= DBL_TAP_MAX_MS
}

function scrollTap(dom, b) {
  const t0 = tapClock;
  tapClock += 1000;
  tapAt(dom, b, t0, { dy: 80 }); // click 80px versetzt -> > TAP_MAX_MOVE_PX
}

test("onBubbleTap Touch+Minimalismus: Einfach-Tap schaltet den Expand-Modus zyklisch weiter (normal -> full -> collapsed -> normal)", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: false });
  try {
    const b = fakeTapBubble(dom.chat);
    setBubbleText(b, LONG_TEXT); // in normal gekuerzt -> voller Dreier-Zyklus
    assert.equal(b._normalTruncated, true);
    singleTap(dom, b);
    assert.equal(b.dataset.mode, "normal", "sofort nach dem Tap noch kein Modus-Wechsel (Doppel-Tap-Fenster abwarten)");
    t.mock.timers.tick(400);
    assert.equal(b.dataset.mode, "full");
    assert.ok(b.classList.contains("full"));
    singleTap(dom, b);
    t.mock.timers.tick(400);
    assert.equal(b.dataset.mode, "collapsed");
    singleTap(dom, b);
    t.mock.timers.tick(400);
    assert.equal(b.dataset.mode, "normal", "voller Zyklus endet wieder bei normal");
    assert.equal(dom.appended.length, 0, "Einfach-Taps oeffnen kein Kontextmenue");
  } finally {
    dom.cleanup();
  }
});

test("onBubbleTap Touch+Minimalismus: ungekuerzte Bubble springt direkt normal -> collapsed -> normal (full == normal)", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: false });
  try {
    const b = fakeTapBubble(dom.chat); // "Hallo Welt": in normal weder geclippt noch geclamped
    setBubbleText(b, "Hallo Welt");
    assert.equal(b._normalTruncated, false);
    singleTap(dom, b);
    t.mock.timers.tick(400);
    assert.equal(b.dataset.mode, "collapsed", "full wird uebersprungen, weil full == normal");
    assert.ok(b.classList.contains("collapsed"));
    singleTap(dom, b);
    t.mock.timers.tick(400);
    assert.equal(b.dataset.mode, "normal", "von collapsed immer zurueck zu normal");
  } finally {
    dom.cleanup();
  }
});

test("onBubbleTap Touch+Minimalismus: Doppel-Tap oeffnet nur das Kontextmenue, aendert den Expand-Modus nicht", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: false });
  try {
    const b = fakeTapBubble(dom.chat);
    dblTap(dom, b); // erste Tap-Haelfte plant einen Modus-Wechsel, die zweite cancelt ihn und oeffnet das Menue
    assert.equal(dom.appended.length, 1, "Kontextmenue wurde geoeffnet");
    assert.equal(dom.appended[0].dataset.testid, "bubble-context-menu");
    t.mock.timers.tick(500);
    assert.equal(b.dataset.mode, "normal", "Doppel-Tap darf den Expand-Modus nicht aendern");
  } finally {
    dom.cleanup();
  }
});

test("onBubbleTap Touch+Minimalismus: Tap bei offenem Menue schliesst es ohne Modus-Wechsel", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: false });
  try {
    const b = fakeTapBubble(dom.chat);
    dblTap(dom, b);
    assert.equal(dom.appended.length, 1);
    singleTap(dom, b); // Menue offen -> schliessen statt Expand
    t.mock.timers.tick(500);
    assert.equal(b.dataset.mode, "normal");
    assert.ok(dom.appended[0].removed, "Menue wurde geschlossen");
  } finally {
    dom.cleanup();
  }
});

test("onBubbleTap Touch+Minimalismus: Scroll-Geste (Pointer bewegt sich) weder Modus-Wechsel noch Menue", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: false });
  try {
    const b = fakeTapBubble(dom.chat);
    scrollTap(dom, b);
    t.mock.timers.tick(500);
    assert.equal(b.dataset.mode, "normal", "Scroll-Geste darf keinen Expand ausloesen");
    assert.equal(dom.appended.length, 0, "Scroll-Geste darf kein Menue oeffnen");
  } finally {
    dom.cleanup();
  }
});

test("onBubbleTap: ohne Minimalismus kein Tap-Verhalten; auf Desktop (feiner Pointer) weder Menue noch Modus-Wechsel", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: false });
  try {
    state.settings = { ...state.settings, bubbles_minimal: false };
    const b = fakeTapBubble(dom.chat);
    singleTap(dom, b);
    dblTap(dom, b);
    t.mock.timers.tick(500);
    assert.equal(b.dataset.mode, "normal", "ohne Minimalismus bleibt der Modus unangetastet");
    assert.equal(dom.appended.length, 0);
  } finally {
    dom.cleanup();
  }
  const domDesk = installTapDom({ finePointer: true });
  try {
    const b = fakeTapBubble(domDesk.chat);
    singleTap(domDesk, b);
    dblTap(domDesk, b);
    t.mock.timers.tick(500);
    assert.equal(b.dataset.mode, "normal", "Desktop: Klick/Doppelklick aendern nicht den Modus (Expand laeuft ueber Body-Klick)");
    assert.equal(domDesk.appended.length, 0, "Desktop: Klick/Doppelklick oeffnen kein Menue");
  } finally {
    domDesk.cleanup();
  }
});

// System-TTS stubben und eine Wiedergabe starten (isSpeaking() true); liefert Restore-Funktion.
async function startSystemSpeech() {
  const calls = { speak: 0, cancel: 0 };
  const synth = {
    speak() {
      calls.speak += 1;
    },
    cancel() {
      calls.cancel += 1;
    },
  };
  const saved = {
    win: globalThis.window,
    synth: globalThis.speechSynthesis,
    utterance: globalThis.SpeechSynthesisUtterance,
    speech: state.speech,
    mode: state.settings.speech_mode,
  };
  globalThis.speechSynthesis = synth;
  globalThis.SpeechSynthesisUtterance = class {
    constructor(text) {
      this.text = text;
    }
  };
  globalThis.window.speechSynthesis = synth; // systemTtsAvailable(): "speechSynthesis" in window
  state.settings = { ...state.settings, speech_mode: "system" };
  state.speech = { systemStt: false, systemTts: true, serverStt: false, serverTts: false };
  await speak("Hallo Welt", null, {});
  assert.ok(isSpeaking(), "Vorbedingung: Wiedergabe laeuft");
  return {
    calls,
    restore() {
      stopSpeech();
      state.speech = saved.speech;
      state.settings = { ...state.settings, speech_mode: saved.mode };
      if (saved.synth === undefined) delete globalThis.speechSynthesis;
      else globalThis.speechSynthesis = saved.synth;
      if (saved.utterance === undefined) delete globalThis.SpeechSynthesisUtterance;
      else globalThis.SpeechSynthesisUtterance = saved.utterance;
      if (saved.win && "speechSynthesis" in saved.win) delete saved.win.speechSynthesis;
    },
  };
}

test("onBubbleTap Touch+Minimalismus: Einfach-Tap waehrend Wiedergabe stoppt nicht, sondern Expand-Zyklus; Doppel-Tap stoppt", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: false });
  const speech = await startSystemSpeech();
  try {
    const b = fakeTapBubble(dom.chat);
    setBubbleText(b, LONG_TEXT); // gekuerzt in normal -> Zyklus erreicht full
    singleTap(dom, b);
    t.mock.timers.tick(400);
    assert.equal(isSpeaking(), true, "Einfach-Tap stoppt die Wiedergabe nicht mehr");
    assert.equal(speech.calls.cancel, 0);
    assert.equal(b.dataset.mode, "full", "Einfach-Tap feuert den normalen Expand-Zyklus");
    assert.equal(dom.appended.length, 0, "kein Kontextmenue");
    dblTap(dom, b); // Doppel-Tap waehrend Wiedergabe: stoppen statt Menue
    t.mock.timers.tick(500);
    assert.equal(isSpeaking(), false, "Doppel-Tap stoppt die Wiedergabe");
    assert.ok(speech.calls.cancel >= 1, "speechSynthesis.cancel() wurde gerufen");
    assert.equal(b.dataset.mode, "full", "Doppel-Tap aendert nicht den Modus");
    assert.equal(dom.appended.length, 0, "Doppel-Tap oeffnet bei laufender Wiedergabe kein Menue");
  } finally {
    speech.restore();
    dom.cleanup();
  }
});

test("onBubbleTap Touch+Minimalismus: Doppel-Tap waehrend Wiedergabe stoppt sie statt Menue zu oeffnen", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: false });
  const speech = await startSystemSpeech();
  try {
    const b = fakeTapBubble(dom.chat);
    dblTap(dom, b);
    t.mock.timers.tick(500);
    assert.equal(isSpeaking(), false, "Doppel-Tap stoppt die Wiedergabe");
    assert.ok(speech.calls.cancel >= 1, "speechSynthesis.cancel() wurde gerufen");
    assert.equal(dom.appended.length, 0, "waehrend der Wiedergabe oeffnet der Doppel-Tap kein Menue");
    assert.equal(b.dataset.mode, "normal", "Doppel-Tap aendert nicht den Modus");
  } finally {
    speech.restore();
    dom.cleanup();
  }
});

test("onBubbleTap Desktop+Minimalismus: einzelner Klick waehrend Wiedergabe stoppt nicht; Doppelklick stoppt", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: true });
  const speech = await startSystemSpeech();
  try {
    const b = fakeTapBubble(dom.chat);
    singleTap(dom, b);
    t.mock.timers.tick(500);
    assert.equal(isSpeaking(), true, "einzelner Klick stoppt die Wiedergabe nicht");
    assert.equal(speech.calls.cancel, 0);
    assert.equal(b.dataset.mode, "normal", "kein Expand-Wechsel auf Desktop");
    assert.equal(dom.appended.length, 0, "kein Kontextmenue");
    dblTap(dom, b); // Doppelklick
    assert.equal(isSpeaking(), false, "Doppelklick stoppt die Wiedergabe");
    assert.ok(speech.calls.cancel >= 1, "speechSynthesis.cancel() wurde gerufen");
    assert.equal(b.dataset.mode, "normal", "Doppelklick aendert nicht den Modus");
    assert.equal(dom.appended.length, 0, "Desktop oeffnet per Klick/Doppelklick kein Menue");
  } finally {
    speech.restore();
    dom.cleanup();
  }
});

test("Escape (keydown auf document) stoppt die laufende Wiedergabe; andere Tasten nicht", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const dom = installTapDom({ finePointer: false });
  const speech = await startSystemSpeech();
  try {
    assert.ok(isSpeaking(), "Vorbedingung: Wiedergabe laeuft");
    for (const fn of dom.listeners.keydown ?? []) fn({ key: "Enter" });
    assert.ok(isSpeaking(), "andere Tasten stoppen die Wiedergabe nicht");
    for (const fn of dom.listeners.keydown ?? []) fn({ key: "Escape" });
    assert.equal(isSpeaking(), false, "Escape stoppt die Wiedergabe");
    assert.ok(speech.calls.cancel >= 1, "speechSynthesis.cancel() wurde gerufen");
  } finally {
    speech.restore();
    dom.cleanup();
  }
});

// --- send(): Doppel-Submit-Guard ---

function fakeNode() {
  const node = {
    className: "",
    dataset: {},
    style: {},
    innerHTML: "",
    textContent: "",
    title: "",
    value: "",
    checked: false,
    onclick: null,
    onchange: null,
    children: [],
    scrollTop: 0,
    scrollHeight: 0,
    clientHeight: 0,
    classList: makeClassList(),
    appendChild(c) {
      this.children.push(c);
    },
    insertBefore() {},
    remove() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {},
    focus() {},
    click() {},
    setSelectionRange() {},
    getBoundingClientRect: () => ({ top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 }),
    querySelector: () => fakeNode(),
    querySelectorAll: () => [],
    closest: () => null,
  };
  return node;
}

test("send(): zweiter Aufruf waehrend des ersten (Doppel-Tap / Enter nach Browser-Diktation) POSTet die Nachricht nicht doppelt", async () => {
  const savedDoc = globalThis.document;
  const savedFetch = globalThis.fetch;
  const savedEventSource = globalThis.EventSource;
  const savedSettings = state.settings;
  const savedSessions = state.sessions;
  const savedActiveId = state.activeId;
  const savedStreaming = state.streaming;
  const savedMessages = state.messages;
  const savedPending = state.pendingAttachments;

  const input = fakeNode();
  input.value = "Hallo Welt";
  const elements = {
    input,
    attachments: fakeNode(),
    chat: fakeNode(),
    sendBtn: fakeNode(),
    progress: fakeNode(),
    abortBtnSide: fakeNode(),
  };
  globalThis.document = {
    getElementById: (id) => elements[id] ?? null,
    createElement: () => fakeNode(),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    dispatchEvent: () => {},
  };
  globalThis.EventSource = class {
    close() {}
  };

  const session = { id: "s1", name: "S", generating: false, ts: 1 };
  const created = { id: 1, role: "user", type: "message", text: "Hallo Welt", in_context: true, ts: 1000 };
  const messagePosts = [];
  let release;
  const gate = new Promise((r) => (release = r));
  globalThis.fetch = async (url, opts = {}) => {
    if (opts.method === "POST" && url === "/api/sessions/s1/messages") {
      messagePosts.push(JSON.parse(opts.body));
      await gate; // erster Versand bleibt im Flug (langsames Netz)
      return { ok: true, status: 201, json: async () => created, text: async () => "" };
    }
    if (url === "/api/sessions") return { ok: true, status: 200, json: async () => [session], text: async () => "" };
    if (url === "/api/sessions/s1")
      return { ok: true, status: 200, json: async () => ({ id: "s1", messages: [created] }), text: async () => "" };
    if (opts.method === "POST" && url === "/api/chat")
      return { ok: true, status: 202, json: async () => ({ status: "started" }), text: async () => "" };
    throw new Error("unerwarteter fetch: " + url);
  };

  state.settings = { ...savedSettings, system_prompt: "" };
  state.sessions = [session];
  state.activeId = "s1";
  state.streaming = false;
  state.messages = [];
  state.pendingAttachments = [];

  try {
    const p1 = send();
    await new Promise((r) => setTimeout(r, 0)); // p1 bis zum messages-POST durchlaufen lassen
    const p2 = send(); // Doppel-Tap auf Senden / Enter direkt nach der Diktation
    await p2;
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(messagePosts.length, 1, "zweiter send()-Aufruf darf nicht erneut POSTen");
    release();
    await p1;
    assert.equal(messagePosts.length, 1, "nach Abschluss des ersten send() weiterhin nur ein POST");
    assert.equal(messagePosts[0].text, "Hallo Welt");
    assert.equal(input.value, "", "Chat-Zeile wurde nach dem Senden geleert");
  } finally {
    stopPolling();
    if (savedDoc === undefined) delete globalThis.document;
    else globalThis.document = savedDoc;
    if (savedFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = savedFetch;
    if (savedEventSource === undefined) delete globalThis.EventSource;
    else globalThis.EventSource = savedEventSource;
    state.settings = savedSettings;
    state.sessions = savedSessions;
    state.activeId = savedActiveId;
    state.streaming = savedStreaming;
    state.messages = savedMessages;
    state.pendingAttachments = savedPending;
  }
});

// --- send(): optimistisches UI ---

function installSendHarness(fetchImpl) {
  const savedDoc = globalThis.document;
  const savedFetch = globalThis.fetch;
  const savedEventSource = globalThis.EventSource;
  const savedSettings = state.settings;
  const savedSessions = state.sessions;
  const savedActiveId = state.activeId;
  const savedStreaming = state.streaming;
  const savedMessages = state.messages;
  const savedPending = state.pendingAttachments;

  const input = fakeNode();
  const elements = {
    input,
    attachments: fakeNode(),
    chat: fakeNode(),
    sendBtn: fakeNode(),
    progress: fakeNode(),
    abortBtnSide: fakeNode(),
  };
  globalThis.document = {
    getElementById: (id) => elements[id] ?? null,
    createElement: () => fakeNode(),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    dispatchEvent: () => {},
  };
  globalThis.EventSource = class {
    close() {}
  };
  globalThis.fetch = fetchImpl;

  const session = { id: "s1", name: "S", generating: false, ts: 1 };
  state.settings = { ...savedSettings, system_prompt: "" };
  state.sessions = [session];
  state.activeId = "s1";
  state.streaming = false;
  state.messages = [];
  state.pendingAttachments = [];

  return {
    input,
    elements,
    session,
    restore() {
      stopPolling();
      if (savedDoc === undefined) delete globalThis.document;
      else globalThis.document = savedDoc;
      if (savedFetch === undefined) delete globalThis.fetch;
      else globalThis.fetch = savedFetch;
      if (savedEventSource === undefined) delete globalThis.EventSource;
      else globalThis.EventSource = savedEventSource;
      state.settings = savedSettings;
      state.sessions = savedSessions;
      state.activeId = savedActiveId;
      state.streaming = savedStreaming;
      state.messages = savedMessages;
      state.pendingAttachments = savedPending;
    },
  };
}

test("send(): optimistisch - Composer wird sofort geleert und die Nachricht erscheint lokal, bevor der Server antwortet", async () => {
  const created = { id: 1, role: "user", type: "message", text: "Hallo Welt", in_context: true, ts: 1000 };
  const messagePosts = [];
  const calls = [];
  let release;
  const gate = new Promise((r) => (release = r));
  const h = installSendHarness(async (url, opts = {}) => {
    calls.push((opts.method ? opts.method + " " : "") + url);
    if (opts.method === "POST" && url === "/api/sessions/s1/messages") {
      messagePosts.push(JSON.parse(opts.body));
      await gate; // Versand bleibt im Flug (langsames Netz)
      return { ok: true, status: 201, json: async () => created, text: async () => "" };
    }
    if (url === "/api/sessions") return { ok: true, status: 200, json: async () => [h.session], text: async () => "" };
    if (url === "/api/sessions/s1")
      return { ok: true, status: 200, json: async () => ({ id: "s1", messages: [created] }), text: async () => "" };
    if (opts.method === "POST" && url === "/api/chat")
      return { ok: true, status: 202, json: async () => ({ status: "started" }), text: async () => "" };
    throw new Error("unerwarteter fetch: " + (opts.method ? opts.method + " " : "") + url);
  });
  h.input.value = "Hallo Welt";
  try {
    const p = send();
    await new Promise((r) => setTimeout(r, 0)); // bis zum messages-POST durchlaufen lassen
    assert.equal(h.input.value, "", "Composer ist sofort geleert, noch waehrend der POST haengt");
    assert.equal(messagePosts.length, 1);
    const local = state.messages.find((m) => m.text === "Hallo Welt");
    assert.ok(local, "optimistische Nachricht ist lokal sichtbar, bevor der Server antwortet");
    assert.equal(local.id, null);
    assert.equal(local.role, "user");
    release();
    await p;
    const matches = state.messages.filter((m) => m.text === "Hallo Welt");
    assert.equal(matches.length, 1, "keine Doppel-Bubble nach der Server-Antwort");
    assert.equal(matches[0].id, 1, "optimistische Live-Message wurde durch die persistierte ersetzt");
    assert.ok(calls.includes("POST /api/chat"), "Generierung wurde angestossen");
    assert.ok(calls.some((c) => c.endsWith("/api/sessions")), "Session-Liste wurde neu geladen");
  } finally {
    h.restore();
  }
});

test("send(): Rollback bei Server-Fehler - Text und Anhaenge landen zurueck im Composer, lokale Bubble verschwindet", async () => {
  const h = installSendHarness(async (url, opts = {}) => {
    if (opts.method === "POST" && url === "/api/sessions/s1/attachments")
      return { ok: true, status: 201, json: async () => ({ id: 7, name: "a.txt", mime: "text/plain", kind: "text", size: 2 }), text: async () => "" };
    if (opts.method === "POST" && url === "/api/sessions/s1/messages")
      return { ok: false, status: 500, text: async () => "boom" };
    if (url === "/api/sessions") return { ok: true, status: 200, json: async () => [h.session], text: async () => "" };
    throw new Error("unerwarteter fetch: " + (opts.method ? opts.method + " " : "") + url);
  });
  h.input.value = "Hallo Welt";
  state.pendingAttachments = [{ name: "a.txt", type: "text/plain", file: new File(["hi"], "a.txt", { type: "text/plain" }) }];
  try {
    await assert.rejects(send(), /boom/);
    assert.equal(h.input.value, "Hallo Welt", "Text landet zurueck in der Chat-Zeile");
    assert.equal(state.messages.length, 0, "optimistische Bubble wurde entfernt");
    assert.equal(state.pendingAttachments.length, 1, "Anhang landet zurueck in der Pending-Liste");
    assert.equal(state.pendingAttachments[0].name, "a.txt");
    assert.equal(h.elements.attachments.children.length, 1, "Anhang-Chip wird wieder gerendert");
  } finally {
    h.restore();
  }
});
