// Reine Logik der dreistufigen Bubble-Ansicht (unit-testbar):
// normal = max. 10 Zeilen, Rest hinter [...]; full = kompletter Text;
// collapsed = 1 Zeile, Rest hinter [...].
// Klick-Reihenfolge: normal -> full -> collapsed -> normal.
export const BUBBLE_MODES = ["normal", "full", "collapsed"];
export const NORMAL_MAX_LINES = 10;

export function clampText(text, mode) {
  const t = text || "";
  if (mode === "full") return t;
  const maxLines = mode === "collapsed" ? 1 : NORMAL_MAX_LINES;
  const lines = t.split("\n");
  if (lines.length <= maxLines) return t;
  if (mode === "collapsed") return `${lines[0]} [...]`;
  return `${lines.slice(0, maxLines).join("\n")}\n[...]`;
}

export function isClamped(text, mode) {
  return clampText(text, mode) !== (text || "");
}

export function nextBubbleMode(mode) {
  return BUBBLE_MODES[(BUBBLE_MODES.indexOf(mode) + 1) % BUBBLE_MODES.length];
}

export function bubbleModeTitle(mode) {
  return mode === "normal" ? "Alles anzeigen" : mode === "full" ? "Einklappen" : "Ausklappen";
}
