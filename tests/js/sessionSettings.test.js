import test from "node:test";
import assert from "node:assert/strict";
import { resolveSystemPrompt, pickSessionSettings } from "../../static/js/sessionSettings.js";
import { SESSION_SETTING_KEYS } from "../../static/js/settingsKeys.js";

test("resolveSystemPrompt: nicht-leerer Session-Prompt gewinnt ueber den globalen Prompt", () => {
  assert.equal(resolveSystemPrompt({ system_prompt: "global" }, { system_prompt: "session" }), "session");
});

test("resolveSystemPrompt: leerer oder Whitespace-Session-Prompt -> globaler Prompt", () => {
  assert.equal(resolveSystemPrompt({ system_prompt: "global" }, { system_prompt: "" }), "global");
  assert.equal(resolveSystemPrompt({ system_prompt: "global" }, { system_prompt: "   " }), "global");
  assert.equal(resolveSystemPrompt({ system_prompt: "global" }, {}), "global");
});

test("resolveSystemPrompt: beide leer -> leerer String", () => {
  assert.equal(resolveSystemPrompt({ system_prompt: "" }, {}), "");
  assert.equal(resolveSystemPrompt({}, undefined), "");
});

test("pickSessionSettings: nur bekannte Keys, fehlende/unbekannte fehlen bzw. werden leer", () => {
  assert.deepEqual(pickSessionSettings({ session_id: "abc", system_prompt: "p", tool_use: "x" }), { system_prompt: "p" });
  assert.deepEqual(pickSessionSettings({}), { system_prompt: "" });
  assert.deepEqual(pickSessionSettings(undefined), Object.fromEntries(SESSION_SETTING_KEYS.map((k) => [k, ""])));
});
