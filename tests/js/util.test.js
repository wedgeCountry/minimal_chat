import test from "node:test";
import assert from "node:assert/strict";
import { $, esc, isNearBottom, spliceAtCursor, captureScrollAnchor, restoreScrollAnchor } from "../../static/js/util.js";

test("esc maskiert HTML-Sonderzeichen", () => {
  assert.equal(esc('<b class="x">&</b>'), "&lt;b class=&quot;x&quot;&gt;&amp;&lt;/b&gt;");
});

test("esc behandelt null/undefined als leeren String", () => {
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
});

test("$ looks up elements by id via document.getElementById", () => {
  const el = { id: "chat" };
  globalThis.document = { getElementById: (id) => (id === "chat" ? el : null) };
  assert.equal($("chat"), el);
  assert.equal($("missing"), null);
});

test("spliceAtCursor fuegt an Cursor-Position ein", () => {
  assert.deepEqual(spliceAtCursor("Hallo Welt", 6, 6, "du"), { value: "Hallo duWelt", cursor: 8 });
  assert.deepEqual(spliceAtCursor("Hallo", 0, 0, ">> "), { value: ">> Hallo", cursor: 3 });
  assert.deepEqual(spliceAtCursor("Hallo", 5, 5, "!"), { value: "Hallo!", cursor: 6 });
});

test("spliceAtCursor ersetzt Markierung und clamped Positionen", () => {
  assert.deepEqual(spliceAtCursor("Hallo Welt", 6, 10, "du"), { value: "Hallo du", cursor: 8 });
  assert.deepEqual(spliceAtCursor("abc", 99, 99, "x"), { value: "abcx", cursor: 4 });
  assert.deepEqual(spliceAtCursor("abc", -5, 2, "x"), { value: "xc", cursor: 1 });
  assert.deepEqual(spliceAtCursor(null, null, null, "x"), { value: "x", cursor: 1 });
});

test("isNearBottom: true nur nahe am unteren Rand", () => {
  const el = { scrollHeight: 1000, clientHeight: 200, scrollTop: 800 };
  assert.equal(isNearBottom(el), true); // exakt unten
  assert.equal(isNearBottom({ ...el, scrollTop: 750 }), true); // 50px Rest < 80
  assert.equal(isNearBottom({ ...el, scrollTop: 719 }), false); // 81px Rest > 80
  assert.equal(isNearBottom({ ...el, scrollTop: 0 }), false); // ganz oben
  assert.equal(isNearBottom({ ...el, scrollTop: 750 }, 10), false); // 50px Rest > kleinerer Threshold
  assert.equal(isNearBottom({ ...el, scrollTop: 795 }, 10), true); // 5px Rest <= 10
});

const rect = (top, bottom) => ({ top, bottom });
const child = (top, bottom, connected = true) => ({
  getBoundingClientRect: () => rect(top, bottom),
  isConnected: connected,
});

test("captureScrollAnchor: erstes Kind, das den oberen Rand schneidet, samt Offset", () => {
  const kids = [child(-300, 50), child(80, 200), child(200, 300)];
  const el = { getBoundingClientRect: () => rect(100, 500), children: kids };
  const a = captureScrollAnchor(el);
  assert.equal(a.el, kids[1]);
  assert.equal(a.offset, -20); // 80 - 100
});

test("captureScrollAnchor: null wenn kein Kind den oberen Rand schneidet", () => {
  const el = { getBoundingClientRect: () => rect(100, 500), children: [child(-300, 50), child(50, 99)] };
  assert.equal(captureScrollAnchor(el), null);
  assert.equal(captureScrollAnchor({ getBoundingClientRect: () => rect(0, 100), children: [] }), null);
});

test("restoreScrollAnchor: scrollTop wird um die Bewegung des Ankers korrigiert", () => {
  const anchorEl = child(30, 130);
  const el = { scrollTop: 400, getBoundingClientRect: () => rect(100, 500) };
  const anchor = { el: anchorEl, offset: 30 - 100 };
  anchorEl.getBoundingClientRect = () => rect(150, 250); // Anker 120px weiter unten im View
  restoreScrollAnchor(el, anchor);
  assert.equal(el.scrollTop, 520);
  anchorEl.getBoundingClientRect = () => rect(-20, 80); // Anker 50px hochgewandert
  restoreScrollAnchor(el, anchor);
  assert.equal(el.scrollTop, 470);
});

test("restoreScrollAnchor: null oder getrennter Anker -> kein Eingriff", () => {
  const el = { scrollTop: 400, getBoundingClientRect: () => rect(100, 500) };
  restoreScrollAnchor(el, null);
  assert.equal(el.scrollTop, 400);
  restoreScrollAnchor(el, { el: child(0, 10, false), offset: 0 });
  assert.equal(el.scrollTop, 400);
});
