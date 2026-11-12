import test from "node:test";
import assert from "node:assert/strict";

function stubEnv({ status = 200, body = "{}", headers = {} } = {}) {
  const events = [];
  globalThis.document = { dispatchEvent: (e) => events.push(e) };
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, opts });
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: `status-${status}`,
      headers,
      json: async () => JSON.parse(body),
      text: async () => body,
    };
  };
  return { events, calls };
}

const { api } = await import("../../static/js/api.js");

test("api.get returns parsed json and calls /api prefix", async () => {
  const { calls } = stubEnv({ body: '{"ok":true}' });
  const res = await api.get("/sessions");
  assert.deepEqual(res, { ok: true });
  assert.equal(calls[0].url, "/api/sessions");
  assert.equal(calls[0].opts.method, "GET");
});

test("api.post sends JSON body with content-type", async () => {
  const { calls } = stubEnv({ status: 201, body: '{"id":"s1"}' });
  const res = await api.post("/sessions", { name: "A" });
  assert.deepEqual(res, { id: "s1" });
  assert.equal(calls[0].opts.method, "POST");
  assert.equal(calls[0].opts.headers["Content-Type"], "application/json");
  assert.equal(calls[0].opts.body, JSON.stringify({ name: "A" }));
});

test("204 returns null without parsing", async () => {
  stubEnv({ status: 204, body: "" });
  assert.equal(await api.del("/sessions/s1"), null);
});

test("401 dispatches leanchat:unauthorized and throws", async () => {
  const { events } = stubEnv({ status: 401, body: '{"detail":"Nicht authentifiziert"}' });
  await assert.rejects(api.get("/sessions"), /Nicht authentifiziert/);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "leanchat:unauthorized");
});

test("non-ok throws the detail message from the JSON body", async () => {
  stubEnv({ status: 409, body: '{"detail":"Es laeuft bereits eine Generierung"}' });
  await assert.rejects(api.post("/chat", {}), /bereits eine Generierung/);
});

test("non-ok falls back to raw text when body is not JSON", async () => {
  stubEnv({ status: 500, body: "Internal Server Error" });
  await assert.rejects(api.get("/sessions"), /Internal Server Error/);
});

test("api.patch and api.put use the right methods", async () => {
  const { calls } = stubEnv({ body: "{}" });
  await api.patch("/sessions/s1", { name: "B" });
  await api.put("/settings", { theme: "dark" });
  assert.equal(calls[0].opts.method, "PATCH");
  assert.equal(calls[1].opts.method, "PUT");
});
