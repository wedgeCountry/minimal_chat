import test from "node:test";
import assert from "node:assert/strict";
import { normalizeErrorMessage, ERROR_AUTO_CLOSE_MS } from "../../static/js/errors.js";

test("normalizeErrorMessage: Error uses stack or message", () => {
  const err = new Error("boom");
  const out = normalizeErrorMessage(err);
  assert.ok(out.includes("boom"));
});

test("normalizeErrorMessage: string passes through", () => {
  assert.equal(normalizeErrorMessage("kaputt"), "kaputt");
});

test("normalizeErrorMessage: object is serialized", () => {
  assert.equal(normalizeErrorMessage({ code: 42 }), '{"code":42}');
});

test("normalizeErrorMessage: null falls back to string form", () => {
  assert.equal(normalizeErrorMessage(null), "null");
});

test("error overlay auto-closes after 10 seconds", () => {
  assert.equal(ERROR_AUTO_CLOSE_MS, 10000);
});
