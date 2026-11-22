import test from "node:test";
import assert from "node:assert/strict";
import { buildBaseUrl, ensureModelSelect } from "../../static/js/models.js";

test("ensureModelSelect: Input wird durch Select mit den gemeldeten Modellen ersetzt (gleiche id)", () => {
  const input = { tagName: "INPUT", value: "", id: "modelModel", dataset: {}, replaceWith(el) { this.replaced = el; } };
  const created = [];
  globalThis.document = {
    getElementById: (id) => (id === "modelModel" ? input : null),
    createElement: (tag) => {
      const el = { tag, children: [], dataset: {}, appendChild(c) { this.children.push(c); } };
      created.push(el);
      return el;
    },
  };
  try {
    ensureModelSelect(["gpt-x", "gpt-y"]);
    const sel = input.replaced;
    assert.equal(sel.tag, "select");
    assert.equal(sel.id, "modelModel");
    assert.equal(sel.dataset.testid, "model-model-select");
    assert.deepEqual(sel.children.map((o) => o.value), ["gpt-x", "gpt-y"]);
  } finally {
    delete globalThis.document;
  }
});

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
