import test from "node:test";
import assert from "node:assert/strict";

const classes = new Set();
globalThis.document = { documentElement: { classList: {
  add: (c) => classes.add(c),
  remove: (c) => classes.delete(c),
  toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
  contains: (c) => classes.has(c),
} } };

const { state } = await import("../../static/js/state.js");
const { applyTheme } = await import("../../static/js/theme.js");

test("applyTheme adds dark class when theme is dark", () => {
  state.settings.theme = "dark";
  applyTheme();
  assert.ok(classes.has("dark"));
});

test("applyTheme removes dark class when theme is light", () => {
  state.settings.theme = "light";
  applyTheme();
  assert.equal(classes.has("dark"), false);
});
