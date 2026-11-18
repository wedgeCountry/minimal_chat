import test from "node:test";
import assert from "node:assert/strict";

function makeClassList() {
  const set = new Set();
  return {
    set,
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    toggle: (c, on) => (on ? set.add(c) : set.delete(c)),
    contains: (c) => set.has(c),
  };
}

function fakeBubble() {
  const chev = { title: "" };
  const body = { textContent: "", classList: makeClassList() };
  const collapseBtn = { style: {} };
  return {
    classList: makeClassList(),
    dataset: {},
    querySelector: (sel) => (sel === ".chev" ? chev : sel === ".bubbleBody" ? body : sel === ".collapseBtn" ? collapseBtn : null),
    _body: body,
    _chev: chev,
    _collapseBtn: collapseBtn,
  };
}

const { setBubbleMode, setBubbleText, syncBubbleTts, syncBubbleDelete } = await import("../../static/js/bubbles.js");
const { state } = await import("../../static/js/state.js");

const LONG = Array.from({ length: 12 }, (_, i) => `Zeile ${i + 1}`).join("\n");

test("setBubbleText clamps to 10 lines in normal mode and marks clamped", () => {
  const b = fakeBubble();
  b.dataset.mode = "normal";
  setBubbleText(b, LONG);
  assert.ok(b._body.textContent.endsWith("\n[...]"));
  assert.equal(b._body.textContent.split("\n").length, 11);
  assert.ok(b._body.classList.contains("clamped"));
});

test("setBubbleText setzt _normalTruncated: true bei >10 Zeilen, false bei kurzem Text", () => {
  const b = fakeBubble();
  b.dataset.mode = "normal";
  setBubbleText(b, LONG);
  assert.equal(b._normalTruncated, true);
  setBubbleText(b, "kurz");
  assert.equal(b._normalTruncated, false);
});

test("setBubbleMode full shows the complete text, collapsed only the first line", () => {
  const b = fakeBubble();
  b.dataset.mode = "normal";
  setBubbleText(b, LONG);
  setBubbleMode(b, "full");
  assert.equal(b.dataset.mode, "full");
  assert.equal(b._body.textContent, LONG);
  assert.equal(b._body.classList.contains("clamped"), false);
  assert.ok(b.classList.contains("full"));
  setBubbleMode(b, "collapsed");
  assert.equal(b._body.textContent, "Zeile 1 [...]");
  assert.ok(b._body.classList.contains("clamped"));
});

test("setBubbleMode: collapseBtn-Sichtbarkeit ist CSS-gesteuert (.bubble.full .collapseBtn), kein Inline-Style", () => {
  const b = fakeBubble();
  b.dataset.mode = "normal";
  setBubbleMode(b, "full");
  assert.ok(b.classList.contains("full"));
  assert.equal(b._collapseBtn.style.display, undefined, "kein Inline-Style am collapseBtn");
  setBubbleMode(b, "collapsed");
  assert.ok(!b.classList.contains("full"));
  assert.equal(b._collapseBtn.style.display, undefined);
  setBubbleMode(b, "normal");
  assert.ok(!b.classList.contains("full"));
  assert.equal(b._collapseBtn.style.display, undefined);
});

test("setBubbleMode cycles classes and sets the chevron title", () => {
  const b = fakeBubble();
  setBubbleMode(b, "normal");
  assert.ok(b.classList.contains("normal"));
  assert.equal(b._chev.title, "Alles anzeigen");
  setBubbleMode(b, "collapsed");
  assert.equal(b.classList.contains("normal"), false);
  assert.ok(b.classList.contains("collapsed"));
  assert.equal(b._chev.title, "Ausklappen");
});

function fakeChat(scrollTop, top = 100) {
  return { scrollTop, getBoundingClientRect: () => ({ top, bottom: top + 600 }) };
}

function fakeScrollBubble(chat, top, heights) {
  // getBoundingClientRect spiegelt die Hoehe des jeweiligen Modus (CSS line-clamp etc.)
  const b = fakeBubble();
  b.getBoundingClientRect = () => {
    const h = heights[b.dataset.mode] ?? 0;
    return { top, bottom: top + h, height: h };
  };
  b.closest = (sel) => (sel === "#chat" ? chat : null);
  return b;
}

test("setBubbleMode kollabiert oberhalb des Viewports ohne Scroll-Sprung", () => {
  // Bubble komplett oberhalb des Viewports: Inhalt an der Viewport-Kante rueckt um
  // die volle Schrumpfung hoch -> scrollTop korrigiert mit (Browser-Clamp wird ueberschrieben)
  const chat = fakeChat(1000);
  const b = fakeScrollBubble(chat, -400, { full: 500, collapsed: 40 });
  b.dataset.mode = "full";
  setBubbleMode(b, "collapsed");
  assert.equal(chat.scrollTop, 540); // 1000 - (500-40)
});

test("setBubbleMode: Bubble schneidet die obere Viewport-Kante -> Anker an der kollabierten Kante", () => {
  const chat = fakeChat(300);
  const b = fakeScrollBubble(chat, -100, { full: 500, collapsed: 40 });
  b.dataset.mode = "full";
  setBubbleMode(b, "collapsed");
  // untere Kante nach Kollaps: 300 + (-100 + 500 - 100) - 460 = 140 -> scrollTop landet darauf
  assert.equal(chat.scrollTop, 140);
});

test("setBubbleMode: Bubble vollstaendig im Viewport -> scrollTop bleibt stehen", () => {
  const chat = fakeChat(300);
  const b = fakeScrollBubble(chat, 150, { full: 500, collapsed: 40 });
  b.dataset.mode = "full";
  setBubbleMode(b, "collapsed");
  assert.equal(chat.scrollTop, 300);
});

test("setBubbleMode: Aufklappen oberhalb des Viewports -> scrollTop folgt nach unten", () => {
  const chat = fakeChat(1000);
  const b = fakeScrollBubble(chat, -400, { full: 500, collapsed: 40 });
  b.dataset.mode = "collapsed";
  setBubbleMode(b, "full");
  assert.equal(chat.scrollTop, 1460); // 1000 + (500-40)
});

test("setBubbleText with short text is not clamped", () => {
  const b = fakeBubble();
  b.dataset.mode = "normal";
  setBubbleText(b, "kurz");
  assert.equal(b._body.textContent, "kurz");
  assert.equal(b._body.classList.contains("clamped"), false);
});

test("toolcall/toolresult: literale \\n zaehlen als Zeilenumbruch (collapsed zeigt nur Zeile 1 + [...])", () => {
  for (const type of ["toolcall", "toolresult"]) {
    const b = fakeBubble();
    b.dataset.type = type;
    b.dataset.mode = "collapsed";
    setBubbleText(b, "Z1\\nZ2\\nZ3");
    assert.equal(b._body.textContent, "Z1 [...]", `${type} mit escaped Newlines muss gekuerzt werden`);
    assert.ok(b._body.classList.contains("clamped"));
    setBubbleMode(b, "full");
    assert.equal(b._body.textContent, "Z1\nZ2\nZ3", `${type} full zeigt echte Umbrueche`);
  }
});

test("message: literales \\n bleibt unangetastet", () => {
  const b = fakeBubble();
  b.dataset.type = "message";
  b.dataset.mode = "collapsed";
  setBubbleText(b, "Z1\\nZ2\\nZ3");
  assert.equal(b._body.textContent, "Z1\\nZ2\\nZ3");
  assert.equal(b._body.classList.contains("clamped"), false);
});

function fakeTtsBubble() {
  let tts = null;
  return {
    _msg: { text: "Hallo" },
    _tts: () => tts,
    _clear: () => { tts = null; },
    querySelector(sel) {
      if (sel === ".ttsBtn") return tts;
      if (sel === ".bubbleHead") return { insertBefore: (el) => { tts = el; } };
      return null;
    },
  };
}

test("syncBubbleTts: Speaker-Button folgt Settings/Availability auch bei wiederverwendeten Bubbles", () => {
  const savedDoc = globalThis.document;
  const savedSettings = state.settings;
  const savedSpeech = state.speech;
  const b = fakeTtsBubble();
  globalThis.document = {
    createElement: () => ({
      className: "", dataset: {}, title: "", innerHTML: "", onclick: null, removed: false,
      remove() { this.removed = true; b._clear(); },
    }),
  };
  try {
    state.settings = { ...state.settings, bubbles_speaker: true, speech_mode: "server" };
    state.speech = { systemStt: false, systemTts: false, serverStt: true, serverTts: true };
    const added = syncBubbleTts(b);
    assert.ok(added, "wird eingefuegt wenn der gewaehlte Modus verfuegbar ist");
    assert.equal(b._tts(), added);
    assert.equal(typeof added.onclick, "function", "Handler ist verdrahtet");

    state.speech = { systemStt: true, systemTts: true, serverStt: false, serverTts: false };
    assert.equal(syncBubbleTts(b), null, "wird entfernt wenn der gewaehlte Modus nicht verfuegbar ist");
    assert.ok(added.removed);
    assert.equal(b._tts(), null);

    state.speech = { systemStt: true, systemTts: true, serverStt: true, serverTts: true };
    assert.ok(syncBubbleTts(b), "wird wieder eingefuegt");
    state.settings = { ...state.settings, speech_mode: "none" };
    assert.equal(syncBubbleTts(b), null, "Modus none -> entfernt");

    state.settings = { ...state.settings, speech_mode: "server", bubbles_speaker: false };
    state.speech = { systemStt: false, systemTts: false, serverStt: true, serverTts: true };
    assert.equal(syncBubbleTts(b), null, "bubbles_speaker=false -> entfernt");
  } finally {
    state.settings = savedSettings;
    state.speech = savedSpeech;
    if (savedDoc === undefined) delete globalThis.document;
    else globalThis.document = savedDoc;
  }
});

function fakeDelBubble() {
  let del = null;
  return {
    _msg: { id: 1, text: "Hallo" },
    _handlers: { onDelete: null },
    _del: () => del,
    _clear: () => { del = null; },
    querySelector(sel) {
      if (sel === ".delBtn") return del;
      if (sel === ".bubbleHead") return { firstChild: null, insertBefore: (el) => { del = el; } };
      return null;
    },
  };
}

test("syncBubbleDelete: Muelleimer-Button folgt dem Setting auch bei wiederverwendeten Bubbles", () => {
  const savedDoc = globalThis.document;
  const savedSettings = state.settings;
  const b = fakeDelBubble();
  let deletedWith = null;
  b._handlers = { onDelete: (m) => { deletedWith = m; } };
  globalThis.document = {
    createElement: () => ({
      className: "", dataset: {}, title: "", innerHTML: "", onclick: null, removed: false,
      remove() { this.removed = true; b._clear(); },
    }),
  };
  try {
    state.settings = { ...state.settings, bubbles_deletable: true };
    const added = syncBubbleDelete(b);
    assert.ok(added, "wird eingefuegt wenn bubbles_deletable aktiv ist");
    assert.equal(b._del(), added);
    assert.equal(added.dataset.testid, "bubble-delete-btn");
    added.onclick();
    assert.equal(deletedWith, b._msg, "onDelete-Handler ist verdrahtet");

    state.settings = { ...state.settings, bubbles_deletable: false };
    assert.equal(syncBubbleDelete(b), null, "wird entfernt wenn bubbles_deletable=false");
    assert.ok(added.removed);
    assert.equal(b._del(), null);

    state.settings = { ...state.settings, bubbles_deletable: true };
    assert.ok(syncBubbleDelete(b), "wird wieder eingefuegt");
  } finally {
    state.settings = savedSettings;
    if (savedDoc === undefined) delete globalThis.document;
    else globalThis.document = savedDoc;
  }
});
