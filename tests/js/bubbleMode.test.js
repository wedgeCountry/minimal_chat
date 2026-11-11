import test from "node:test";
import assert from "node:assert/strict";
import { BUBBLE_MODES, NORMAL_MAX_LINES, clampText, nextBubbleMode, bubbleModeTitle } from "../../static/js/bubbleMode.js";

const long = Array.from({ length: 15 }, (_, i) => `Zeile ${i + 1}`).join("\n");

test("normal: bis 10 Zeilen bleibt der Text unveraendert", () => {
  const ten = Array.from({ length: NORMAL_MAX_LINES }, (_, i) => `Z${i + 1}`).join("\n");
  assert.equal(clampText(ten, "normal"), ten);
  assert.equal(clampText("kurz", "normal"), "kurz");
});

test("normal: ab 11 Zeilen werden nur 10 Zeilen + [...] gezeigt", () => {
  const out = clampText(long, "normal");
  const lines = out.split("\n");
  assert.equal(lines.length, NORMAL_MAX_LINES + 1);
  assert.equal(lines[NORMAL_MAX_LINES], "[...]");
  assert.equal(lines[0], "Zeile 1");
  assert.equal(lines[NORMAL_MAX_LINES - 1], `Zeile ${NORMAL_MAX_LINES}`);
});

test("full: kompletter Text, auch bei vielen Zeilen", () => {
  assert.equal(clampText(long, "full"), long);
});

test("collapsed: nur 1 Zeile + [...]", () => {
  assert.equal(clampText(long, "collapsed"), "Zeile 1 [...]");
  assert.equal(clampText("nur eine Zeile", "collapsed"), "nur eine Zeile");
});

test("clampText behandelt null/undefined als leeren String", () => {
  assert.equal(clampText(null, "normal"), "");
  assert.equal(clampText(undefined, "collapsed"), "");
});

test("nextBubbleMode zyklisch: normal -> collapsed -> full -> normal", () => {
  assert.equal(nextBubbleMode("normal"), "collapsed");
  assert.equal(nextBubbleMode("collapsed"), "full");
  assert.equal(nextBubbleMode("full"), "normal");
  assert.deepEqual(BUBBLE_MODES, ["normal", "collapsed", "full"]);
});

test("bubbleModeTitle liefert deutsche Tooltips pro Zustand", () => {
  assert.equal(bubbleModeTitle("normal"), "Einklappen");
  assert.equal(bubbleModeTitle("collapsed"), "Voll anzeigen");
  assert.equal(bubbleModeTitle("full"), "Ausklappen");
});
