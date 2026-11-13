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

test("baut Mehrfach-Content mit Anhaengen (Server-Referenz + Text-Anhang)", () => {
  const payload = buildChatPayload({
    model: "m",
    messages: [
      {
        role: "user",
        type: "message",
        text: "schau",
        inContext: true,
        attachments: [
          { id: 7, name: "bild.png", type: "image/png" },
          { name: "notiz.txt", text: "inhalt" },
        ],
      },
    ],
  });
  assert.deepEqual(payload.messages, [
    {
      role: "user",
      content: [
        { type: "text", text: "[Datei: bild.png]", attachment_id: 7 },
        { type: "text", text: "[Datei: notiz.txt]\ninhalt" },
        { type: "text", text: "schau" },
      ],
    },
  ]);
});

test("inContext=false schliesst die Nachricht aus dem Payload aus (auch nach normalizeMessages)", async () => {
  const { normalizeMessages } = await import("../../static/js/state.js");
  // Server-Shape mit in_context=false, wie nach einem Reload geladen
  const serverMsgs = [
    { role: "user", type: "message", text: "alt", in_context: false, id: 1 },
    { role: "assistant", type: "message", text: "antwort", in_context: true, id: 2 },
    { role: "user", type: "message", text: "neu", in_context: true, id: 3 },
  ];
  const payload = buildChatPayload({ model: "m", messages: normalizeMessages(serverMsgs) });
  assert.deepEqual(
    payload.messages.map((m) => m.content),
    ["antwort", "neu"]
  );
});
