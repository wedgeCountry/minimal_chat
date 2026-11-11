import test from "node:test";
import assert from "node:assert/strict";
import { buildBaseUrl } from "../../static/js/settings.js";

test("buildBaseUrl: host + port -> http://host:port/v1", () => {
  assert.equal(buildBaseUrl("192.168.1.10", "8000"), "http://192.168.1.10:8000/v1");
});

test("buildBaseUrl: host without port", () => {
  assert.equal(buildBaseUrl("llm.local", ""), "http://llm.local/v1");
});

test("buildBaseUrl: empty host -> empty string", () => {
  assert.equal(buildBaseUrl("", "8000"), "");
  assert.equal(buildBaseUrl("  ", ""), "");
});

test("buildBaseUrl: trims whitespace", () => {
  assert.equal(buildBaseUrl(" 10.0.0.5 ", " 443 "), "http://10.0.0.5:443/v1");
});
