import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = { location: { href: "" } };

const { goToLogin } = await import("../../static/js/auth.js");

test("goToLogin redirects to the auth login page", () => {
  goToLogin();
  assert.equal(globalThis.window.location.href, "/auth/login");
});
