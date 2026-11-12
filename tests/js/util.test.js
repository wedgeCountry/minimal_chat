import test from "node:test";
import assert from "node:assert/strict";
import { $ , esc } from "../../static/js/util.js";

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
