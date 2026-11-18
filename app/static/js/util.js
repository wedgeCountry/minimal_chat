export const $ = (id) => document.getElementById(id);

// true, wenn der Scroll-Container (fast) ganz unten steht - dann darf beim
// Re-Render ans Ende gescrollt werden, ohne den Nutzer beim Lesen hochzureissen.
export function isNearBottom(el, threshold = 80) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}

// Scroll-Anker fuer Re-Render: erstes Kind, das den oberen Rand des Containers
// schneidet, samt Abstand zu diesem Rand. Nach dem Re-Render laesst sich die
// sichtbare Position exakt halten, auch wenn sich Hoehen oberhalb des Views
// geaendert haben (z. B. waechst die streamende Bubble oberhalb des Ankers).
export function captureScrollAnchor(el) {
  const top = el.getBoundingClientRect().top;
  for (const child of el.children) {
    const r = child.getBoundingClientRect();
    if (r.bottom > top) return { el: child, offset: r.top - top };
  }
  return null;
}

export function restoreScrollAnchor(el, anchor) {
  if (!anchor || !anchor.el.isConnected) return;
  const top = el.getBoundingClientRect().top;
  const r = anchor.el.getBoundingClientRect();
  el.scrollTop += r.top - top - anchor.offset;
}

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
