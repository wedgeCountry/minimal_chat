import test from "node:test";
import assert from "node:assert/strict";
import { encodeWav, voiceStatus, voiceAvailable, transcribeAudio, synthesizeSpeech, VOICE_UNAVAILABLE_MSG } from "../../static/js/voice.js";

test("encodeWav erzeugt gueltigen RIFF/WAVE-Header", async () => {
  const samples = new Float32Array([0, 0.5, -0.5, 1, -1]);
  const blob = encodeWav(samples, 16000);
  assert.equal(blob.type, "audio/wav");
  const buf = new DataView(await blob.arrayBuffer());
  const str = (o, n) => String.fromCharCode(...new Uint8Array(buf.buffer, o, n));
  assert.equal(str(0, 4), "RIFF");
  assert.equal(str(8, 4), "WAVE");
  assert.equal(str(12, 4), "fmt ");
  assert.equal(str(36, 4), "data");
  assert.equal(buf.getUint32(4, true), 36 + samples.length * 2);
  assert.equal(buf.getUint32(24, true), 16000);
  assert.equal(buf.getUint16(22, true), 1);
  assert.equal(buf.getUint16(34, true), 16);
  assert.equal(buf.getUint32(40, true), samples.length * 2);
  assert.equal(buf.getInt16(44, true), 0);
  assert.equal(buf.getInt16(46, true), 16383);
  assert.equal(buf.getInt16(48, true), Math.round(-0.5 * 0x8000));
});

function mockFetch(impl) {
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, opts });
    return impl(url, opts);
  };
  return calls;
}

test("voiceAvailable true bei available status", async () => {
  mockFetch(async () => ({ ok: true, json: async () => ({ available: true, stt: true, tts: true }) }));
  assert.equal(await voiceAvailable(), true);
});

test("voiceAvailable false bei Netzwerkfehler", async () => {
  mockFetch(async () => {
    throw new Error("network down");
  });
  const s = await voiceStatus();
  assert.deepEqual(s, { available: false, stt: false, tts: false });
  assert.equal(await voiceAvailable(), false);
});

test("transcribeAudio postet Multipart und liefert Text", async () => {
  const calls = mockFetch(async () => ({ ok: true, json: async () => ({ text: "Hallo", language: "de" }) }));
  const blob = new Blob([new Uint8Array([1, 2, 3])], { type: "audio/wav" });
  const text = await transcribeAudio(blob);
  assert.equal(text, "Hallo");
  assert.equal(calls[0].url, "/api/voice/stt");
  assert.equal(calls[0].opts.method, "POST");
  assert.ok(calls[0].opts.body instanceof FormData);
});

test("transcribeAudio wirft Service-nicht-verfuegbar bei 503", async () => {
  mockFetch(async () => ({ ok: false, status: 503, text: async () => JSON.stringify({ detail: "Sprachdienst nicht verfügbar" }) }));
  await assert.rejects(() => transcribeAudio(new Blob([])), (err) => err.message === VOICE_UNAVAILABLE_MSG);
});

test("synthesizeSpeech postet JSON und liefert Blob", async () => {
  const calls = mockFetch(async () => ({ ok: true, blob: async () => new Blob([new Uint8Array([9])]) }));
  const blob = await synthesizeSpeech("Hallo Welt", "de");
  assert.equal(blob.size, 1);
  assert.equal(calls[0].url, "/api/voice/tts");
  assert.deepEqual(JSON.parse(calls[0].opts.body), { text: "Hallo Welt", language: "de" });
});

test("synthesizeSpeech wirft Service-nicht-verfuegbar bei 503", async () => {
  mockFetch(async () => ({ ok: false, status: 503, text: async () => "" }));
  await assert.rejects(() => synthesizeSpeech("x"), (err) => err.message === VOICE_UNAVAILABLE_MSG);
});
