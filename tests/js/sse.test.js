import test from "node:test";
import assert from "node:assert/strict";
import { parseSSE } from "../../static/js/sse.js";

function fakeReader(chunks) {
  const enc = new TextEncoder();
  let i = 0;
  return {
    read: async () =>
      i < chunks.length
        ? { done: false, value: enc.encode(chunks[i++]) }
        : { done: true, value: undefined },
  };
}

async function collect(chunks) {
  const out = [];
  for await (const ev of parseSSE(fakeReader(chunks))) out.push(ev);
  return out;
}

test("parst mehrere SSE-Events inkl. [DONE]", async () => {
  const events = await collect([
    'data: {"choices":[{"delta":{"content":"Ha"}}]}\n\ndata: {"choices":[{"delta":{"content":"llo"}}]}\n\n',
    "data: [DONE]\n\n",
  ]);
  assert.equal(events.length, 2);
  assert.equal(events[0].choices[0].delta.content, "Ha");
  assert.equal(events[1].choices[0].delta.content, "llo");
});

test("verarbeitet ueber Chunk-Grenzen geteilte Zeilen", async () => {
  const events = await collect([
    'data: {"choices":[{"del',
    'ta":{"content":"X"}}]}\n',
    "\n",
  ]);
  assert.equal(events.length, 1);
  assert.equal(events[0].choices[0].delta.content, "X");
});

test("ignoriert unparsebare und nicht-data Zeilen", async () => {
  const events = await collect([": comment\n\ndata: keine-json\n\ndata: {\"ok\":true}\n\n"]);
  assert.deepEqual(events, [{ ok: true }]);
});
