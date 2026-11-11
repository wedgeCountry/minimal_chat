// Reiner SSE-Parser: zerlegt einen Byte-Stream in JSON-Events.
// `data: [DONE]` und unparsebare Zeilen werden uebersprungen.
export async function* parseSSE(reader) {
  const dec = new TextDecoder();
  let buf = "";
  const handleLine = function* (line) {
    const t = line.trim();
    if (!t.startsWith("data:")) return;
    const data = t.slice(5).trim();
    if (data === "[DONE]") return;
    try {
      yield JSON.parse(data);
    } catch {
      return;
    }
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      buf += dec.decode();
      for (const event of handleLine(buf)) yield event;
      break;
    }
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const line of lines) {
      for (const event of handleLine(line)) yield event;
    }
  }
}
