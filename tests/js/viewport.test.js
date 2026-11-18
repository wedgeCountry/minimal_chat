import test from "node:test";
import assert from "node:assert/strict";
import { applyVisualViewport, initViewportSync } from "../../app/static/js/viewport.js";

test("applyVisualViewport koppelt die Root-Hoehe an den Visual Viewport und resettet den Pan", () => {
  const root = { style: {} };
  const calls = [];
  const win = { visualViewport: { height: 412.5, scale: 1 }, scrollTo: (x, y) => calls.push([x, y]) };
  assert.equal(applyVisualViewport(root, win), true);
  assert.equal(root.style.height, "412.5px");
  assert.deepEqual(calls, [[0, 0]]);
});

test("applyVisualViewport ignoriert Pinch-Zoom (scale != 1)", () => {
  const root = { style: {} };
  const win = {
    visualViewport: { height: 300, scale: 2 },
    scrollTo: () => assert.fail("bei Pinch-Zoom darf nicht gescrollt werden"),
  };
  assert.equal(applyVisualViewport(root, win), false);
  assert.equal(root.style.height, undefined);
});

test("applyVisualViewport ohne visualViewport (alte Browser) aendert nichts", () => {
  const root = { style: {} };
  const win = { scrollTo: () => assert.fail("ohne visualViewport darf nicht gescrollt werden") };
  assert.equal(applyVisualViewport(root, win), false);
  assert.equal(root.style.height, undefined);
});

test("initViewportSync wendet sofort an und reagiert auf resize/scroll", () => {
  const root = { style: {} };
  const handlers = {};
  const vv = { height: 500, scale: 1, addEventListener: (t, fn) => (handlers[t] = fn) };
  const win = { visualViewport: vv, scrollTo: () => {} };
  const doc = { documentElement: root, getElementById: () => null };
  initViewportSync(win, doc);
  assert.equal(root.style.height, "500px");
  vv.height = 300;
  handlers["resize"]();
  assert.equal(root.style.height, "300px");
  vv.height = 844;
  handlers["scroll"]();
  assert.equal(root.style.height, "844px");
});

test("initViewportSync scrollt das Eingabefeld bei Fokus in den sichtbaren Bereich", () => {
  const root = { style: {} };
  const handlers = {};
  const input = { calls: [], addEventListener: (t, fn) => (handlers[t] = fn), scrollIntoView: (opts) => input.calls.push(opts) };
  const win = { scrollTo: () => {} };
  const doc = { documentElement: root, getElementById: (id) => (id === "input" ? input : null) };
  initViewportSync(win, doc);
  assert.equal(root.style.height, undefined); // kein visualViewport -> Layout unangetastet
  handlers["focus"]();
  assert.deepEqual(input.calls, [{ block: "nearest" }]);
});
