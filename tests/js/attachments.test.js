import test from "node:test";
import assert from "node:assert/strict";
import { isTextFile } from "../../static/js/attachments.js";

test("isTextFile: text/* MIME-Typen sind Textdateien", () => {
  assert.equal(isTextFile("a.txt", "text/plain"), true);
  assert.equal(isTextFile("a.csv", "text/csv"), true);
  assert.equal(isTextFile("a.md", "text/markdown"), true);
});

test("isTextFile: strukturierte Text-Typen und +json/+xml-Suffixe", () => {
  assert.equal(isTextFile("a.json", "application/json"), true);
  assert.equal(isTextFile("a.xml", "application/xml"), true);
  assert.equal(isTextFile("a.json", "application/vnd.api+json"), true);
  assert.equal(isTextFile("a.yaml", "application/x-yaml"), true);
});

test("isTextFile: Extension-Fallback bei leerem MIME-Typ", () => {
  assert.equal(isTextFile("notes.md", ""), true);
  assert.equal(isTextFile("script.py", ""), true);
  assert.equal(isTextFile("data.bin", ""), false);
  assert.equal(isTextFile("ohneEndung", ""), false);
});

test("isTextFile: Binaerdateien und Bilder sind keine Textdateien", () => {
  assert.equal(isTextFile("doc.pdf", "application/pdf"), false);
  assert.equal(isTextFile("x.png", "image/png"), false);
  assert.equal(isTextFile("x.svg", "image/svg+xml"), false);
  assert.equal(isTextFile("a.zip", "application/zip"), false);
});
