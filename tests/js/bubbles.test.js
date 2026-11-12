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
  return {
    classList: makeClassList(),
    dataset: {},
    querySelector: (sel) => (sel === ".chev" ? chev : sel === ".bubbleBody" ? body : null),
    _body: body,
    _chev: chev,
  };
}

const { setBubbleMode, setBubbleText } = await import("../../static/js/bubbles.js");

const LONG = Array.from({ length: 12 }, (_, i) => `Zeile ${i + 1}`).join("\n");

test("setBubbleText clamps to 10 lines in normal mode and marks clamped", () => {
  const b = fakeBubble();
  b.dataset.mode = "normal";
  setBubbleText(b, LONG);
  assert.ok(b._body.textContent.endsWith("\n[...]"));
  assert.equal(b._body.textContent.split("\n").length, 11);
  assert.ok(b._body.classList.contains("clamped"));
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

test("setBubbleText with short text is not clamped", () => {
  const b = fakeBubble();
  b.dataset.mode = "normal";
  setBubbleText(b, "kurz");
  assert.equal(b._body.textContent, "kurz");
  assert.equal(b._body.classList.contains("clamped"), false);
});
