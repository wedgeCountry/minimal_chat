import { state } from "./state.js";

// Composer-Entwuerfe pro Session im localStorage (ueberlebt auch Reload); ein
// geleerter Entwurf wird als Key entfernt, damit die Map nicht waechst.
const KEY = "leanchat.drafts";

// spaet aufloesen: in manchen Umgebungen (Node-Tests, Privacy-Modi) ist das
// global erst spaeter bzw. gar nicht verfuegbar bzw. wirft der Zugriff
function storage() {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null;
  }
}

function readAll() {
  const ls = storage();
  if (!ls) return {};
  try {
    return JSON.parse(ls.getItem(KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function writeAll(map) {
  const ls = storage();
  if (!ls) return;
  try {
    ls.setItem(KEY, JSON.stringify(map));
  } catch {}
}

export function getDraft(sessionId) {
  if (!sessionId) return "";
  return readAll()[sessionId] || "";
}

export function saveDraft(sessionId, text) {
  if (!sessionId) return;
  const map = readAll();
  const t = String(text ?? "");
  if (t) map[sessionId] = t;
  else delete map[sessionId];
  writeAll(map);
}

export function clearDraft(sessionId) {
  if (!sessionId) return;
  const map = readAll();
  if (delete map[sessionId]) writeAll(map);
}

// Laedt den Entwurf der aktiven Session in den Composer, sobald sich die aktive
// Session aendert (renderAll in main.js ruft das bei jedem Rendern; der Entwurf
// der abgewählten Session ist da bereits per input-Event gespeichert).
let syncedId;
export function syncDraftInput() {
  const id = state.activeId ?? null;
  if (id === syncedId) return;
  syncedId = id;
  if (typeof document === "undefined") return;
  const input = document.getElementById("input");
  if (!input) return;
  input.value = getDraft(id);
  input.dispatchEvent(new Event("input")); // Auto-Grow des Composer + Sichern unter der neuen Session
}
