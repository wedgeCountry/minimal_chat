import test from "node:test";
import assert from "node:assert/strict";
import { ICONS } from "../../static/js/icons.js";

test("ICONS provides all icons used by the UI", () => {
  for (const key of ["plus", "edit", "trash", "x", "stop", "send", "chev", "tts", "copy", "attach", "refresh"]) {
    assert.ok(ICONS[key], `missing icon: ${key}`);
    assert.ok(ICONS[key].startsWith("<svg"), `icon ${key} is not svg`);
  }
});
