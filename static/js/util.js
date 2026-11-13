export const $ = (id) => document.getElementById(id);

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  }[c]));

// Text an Cursor-Position einfuegen (ersetzt eine evtl. Markierung).
// Liefert neuen Wert + neue Cursor-Position.
export function spliceAtCursor(value, start, end, text) {
  const v = String(value ?? "");
  const s = Math.max(0, Math.min(start ?? v.length, v.length));
  const e = Math.max(s, Math.min(end ?? s, v.length));
  return { value: v.slice(0, s) + text + v.slice(e), cursor: s + text.length };
}
