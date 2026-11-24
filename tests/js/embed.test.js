import test from "node:test";
import assert from "node:assert/strict";
import { isEmbedMode, applyEmbedMode } from "../../static/js/embed.js";

test("isEmbedMode erkennt ?embed und ?embed=1, aber nicht aehnliche Namen/Werte", () => {
  assert.equal(isEmbedMode("?embed=1"), true);
  assert.equal(isEmbedMode("?embed"), true);
  assert.equal(isEmbedMode("?s=abc&embed=1"), true);
  assert.equal(isEmbedMode("?foo=embed"), false);
  assert.equal(isEmbedMode("?embedx=1"), false);
  assert.equal(isEmbedMode(""), false);
  assert.equal(isEmbedMode("?foo=1"), false);
});

test("applyEmbedMode setzt die Klasse embed auf <html>", () => {
  const added = [];
  const doc = { documentElement: { classList: { add: (c) => added.push(c) } } };
  applyEmbedMode("?embed=1", doc);
  assert.deepEqual(added, ["embed"]);
});

test("applyEmbedMode ohne embed-Parameter setzt keine Klasse", () => {
  const added = [];
  const doc = { documentElement: { classList: { add: (c) => added.push(c) } } };
  applyEmbedMode("?foo=1", doc);
  assert.deepEqual(added, []);
});
