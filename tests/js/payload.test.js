import test from "node:test";
import assert from "node:assert/strict";
import { buildChatPayload } from "../../static/js/payload.js";

test("filtert deaktivierte und leere Assistant-Nachrichten", () => {
  const payload = buildChatPayload({
    model: "gpt-4o-mini",
    messages: [
      { role: "user", type: "message", text: "Hallo", inContext: true },
      { role: "assistant", type: "message", text: "", inContext: true },
      { role: "assistant", type: "message", text: "Hi!", inContext: false },
      { role: "assistant", type: "reasoning", text: "denke", inContext: true },
      { role: "user", type: "message", text: "Tschuess", inContext: false },
    ],
  });
  assert.equal(payload.stream, true);
  assert.equal(payload.model, "gpt-4o-mini");
  assert.deepEqual(payload.messages, [{ role: "user", content: "Hallo" }]);
});

test("baut Anhang-Referenz-Part mit attachment_id (serverseitige Aufbereitung)", () => {
  const payload = buildChatPayload({
    model: "m",
    messages: [
      {
        role: "user",
        type: "message",
        text: "schau",
        inContext: true,
        attachments: [{ id: 7, name: "notiz.txt", type: "text/plain" }],
      },
    ],
  });
  assert.deepEqual(payload.messages, [
    {
      role: "user",
      content: [
        { type: "text", text: "[Datei: notiz.txt]", attachment_id: 7 },
        { type: "text", text: "schau" },
      ],
    },
  ]);
});

test("baut Mehrfach-Content mit Anhaengen", () => {
  const payload = buildChatPayload({
    model: "m",
    messages: [
      {
        role: "user",
        type: "message",
        text: "schau",
        inContext: true,
        attachments: [
          { name: "bild.png", data: "data:image/png;base64,AAA" },
          { name: "notiz.txt", text: "inhalt" },
        ],
      },
    ],
  });
  assert.deepEqual(payload.messages, [
    {
      role: "user",
      content: [
        { type: "image_url", image_url: { url: "data:image/png;base64,AAA" } },
        { type: "text", text: "[Datei: notiz.txt]\ninhalt" },
        { type: "text", text: "schau" },
      ],
    },
  ]);
});
