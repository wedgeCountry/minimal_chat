// Baut den Request-Payload fuer /api/chat aus den Session-Nachrichten.
export function buildChatPayload({ model, messages }) {
  return {
    model,
    stream: true,
    messages: messages
      .filter(
        (m) =>
          m.inContext !== false &&
          m.type === "message" &&
          (m.role !== "assistant" || m.text)
      )
      .map((m) => {
        const content = m.attachments?.length
          ? [
              ...m.attachments.map((a) =>
                a.id != null
                  ? { type: "text", text: `[Datei: ${a.name}]`, attachment_id: a.id }
                  : { type: "text", text: `[Datei: ${a.name}]\n${a.text || ""}` }
              ),
              { type: "text", text: m.text || "" },
            ]
          : m.text || "";
        return { role: m.role, content };
      }),
  };
}
