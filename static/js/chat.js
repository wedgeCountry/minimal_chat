import { api, openStream } from "./api.js";
import { activeSession, normalizeMessage, normalizeMessages, state } from "./state.js";
import { $, isNearBottom, captureScrollAnchor, restoreScrollAnchor, isFinePointer } from "./util.js";
import { ICONS } from "./icons.js";
import { bubbleEl, setBubbleMode, setBubbleText, enterBubbleEdit, exitBubbleEdit, syncBubbleTts, syncBubbleDelete, copyBubbleText } from "./bubbles.js";
import { nextBubbleMode } from "./bubbleMode.js";
import { loadSessions, newSession, changed } from "./sessions.js";
import { uploadPendingAttachments } from "./attachments.js";
import { confirmModal } from "./confirm.js";
import { resolveSystemPrompt } from "./sessionSettings.js";
import { isBubbleVisible, isDuplicateSystemPrompt, isToolbarMinimal } from "./visibility.js";
import { stopRecording, isSpeaking, stopSpeech } from "./ttsDetectionService.js";

export function setStreamingUI(on) {
  state.streaming = on;
  $("progress").classList.toggle("show", on);
  $("abortBtnSide").classList.toggle("show", on);
  const btn = $("sendBtn");
  btn.classList.toggle("abort", on);
  btn.title = on ? "Abbrechen" : "Senden";
  btn.innerHTML = on ? ICONS.stop : ICONS.send;
}

export function abortStream() {
  const s = activeSession();
  if (s) api.post("/chat/abort", { session_id: s.id }).catch(() => {});
  // Stream nicht sofort schliessen: das done-Event liefert das finale state (offener
  // Block verworfen) und der Poll den persistierten Stand — sonst fallen bereits
  // persistierte Bloecke kurz aus der Ansicht, bis der naechste Poll nachliefert.
  pollOnce();
}

// Live-Daten kommen ausschliesslich ueber die Service-Layer: SSE aus dem In-Memory-State
// des MessageService (GET /api/chat/stream/{sid}, versionierte state-Events mit seq).
// Der Poll (GET /api/sessions/{id}) bleibt Quelle der Wahrheit fuer den persistierten
// Stand und ueberschreibt den SSE-Stand, sobald die Generierung endet und ein Poll den
// persistierten Stand frisch gelesen hat (generating=0 + erfolgreicher Detail-Fetch).
let sseState = null; // { seq, messages, sid } — letzter Stand aus der Service-Layer
let liveStream = null;

// Reines Merge (testbar): state-Event uebernehmen, wenn seq neuer; veraltete Events verwerfen.
export function applySseState(ev, cur) {
  if (!ev || ev.type !== "state" || typeof ev.seq !== "number") return cur;
  if (cur && ev.seq <= cur.seq) return cur;
  const messages = normalizeMessages(ev.messages || []).map((m) =>
    m.id == null && !m.ts ? { ...m, ts: Date.now() } : m // Live-Messages (ts=0) ans Ende sortieren
  );
  return { seq: ev.seq, messages };
}

// Die Ansicht folgt dem SSE-Stand, solange einer zur aktiven Session vorliegt — auch kurz
// nach Stream-Ende, wo der zuletzt gepollte Stand noch der aeltere ist; sonst wuerde die
// fertig gestreamte Bubble verschwinden, bis der naechste Poll nachliefert (Flicker +
// Scroll-Sprung). Ein SSE-Stand einer anderen Session wird ignoriert.
export function pickViewMessages(sse, messages, activeId) {
  return sse && sse.sid === activeId ? sse.messages : messages;
}

function viewMessages() {
  return pickViewMessages(sseState, state.messages, activeSession()?.id ?? null);
}

// Wendet eine Listen-Mutation zusaetzlich auf den Live-SSE-Stand an (nur wenn er zur
// aktiven Session gehoert). Ohne das Spiegeln wuerde die naechste Ansicht den alten Stand
// zeigen und eine lokal geloeschte/geaenderte Bubble kurz wieder auftauchen, bis das
// naechste SSE-Event (seq+1) vom Server ankommt.
export function applyToLiveState(sse, activeId, mutate) {
  if (!sse || sse.sid !== activeId) return sse;
  return { ...sse, messages: mutate(sse.messages) };
}

function liveId() {
  return activeSession()?.id ?? null;
}

function closeStreamSocket() {
  if (liveStream) {
    liveStream.close();
    liveStream = null;
  }
}

export function closeLiveStream() {
  closeStreamSocket();
  if (sseState) {
    sseState = null;
    renderChat(viewMessages());
  }
}

function openLiveStream(s) {
  closeStreamSocket(); // sseState bleibt: nahtloser Uebergang beim (Re-)Connect per seq-Merge
  liveStream = openStream(`/chat/stream/${s.id}`);
  liveStream.onmessage = (e) => {
    let ev;
    try {
      ev = JSON.parse(e.data);
    } catch {
      return;
    }
    if (ev.type === "state") {
      const merged = applySseState(ev, sseState);
      if (merged !== sseState) {
        sseState = { ...merged, sid: s.id };
        renderChat(viewMessages());
      }
    } else if (ev.type === "done" || ev.type === "idle" || ev.type === "error") {
      // Nur den Socket schliessen, sseState bleibt Ansicht: der naechste Poll
      // (generating=0 + frischer Fetch) ersetzt ihn durch den persistierten Stand.
      closeStreamSocket();
      pollOnce();
    }
  };
  liveStream.onerror = () => closeLiveStream();
}

// Primär chronologisch nach ts (ms; jeder Stream-Block traegt als ts seinen Abschluss-
// Zeitstempel beim Typwechsel im LLM-Stream). Bei gleichem ts zaehlt die Turn-Reihenfolge
// (jede User-Message eroeffnet einen neuen Turn); innerhalb eines Turns landet
// die finale Assistant-Message hinter ihren Sondertypen, Toolcall vor Toolresult.
const _TYPE_TIE_RANK = { reasoning: 0, toolcall: 1, toolresult: 2 };

export function sortMessagesForRender(messages) {
  const byTsId = [...messages].sort((a, b) => {
    const d = (a.ts ?? 0) - (b.ts ?? 0);
    return d !== 0 ? d : (a.id ?? 0) - (b.id ?? 0);
  });
  const turnOf = new Map();
  let turn = 0;
  for (const m of byTsId) {
    if (m.role === "user" && m.type === "message") turn += 1;
    turnOf.set(m, turn);
  }
  return byTsId.sort((a, b) => {
    const d = (a.ts ?? 0) - (b.ts ?? 0);
    if (d !== 0) return d;
    const t = turnOf.get(a) - turnOf.get(b);
    if (t !== 0) return t;
    const fa = a.type === "message" && a.role === "assistant" ? 1 : 0;
    const fb = b.type === "message" && b.role === "assistant" ? 1 : 0;
    if (fa !== fb) return fa - fb;
    const ra = _TYPE_TIE_RANK[a.type] ?? 0;
    const rb = _TYPE_TIE_RANK[b.type] ?? 0;
    if (ra !== rb) return ra - rb;
    return (a.id ?? 0) - (b.id ?? 0);
  });
}

export function findLastUserMessage(messages) {
  const sorted = sortMessagesForRender(messages || []);
  for (let i = sorted.length - 1; i >= 0; i--) {
    if (sorted[i].role === "user" && sorted[i].type === "message") return sorted[i];
  }
  return null;
}

export function hasMessagesAfter(messages, id) {
  const sorted = sortMessagesForRender(messages || []);
  const idx = sorted.findIndex((x) => x.id === id);
  return idx >= 0 && sorted.slice(idx + 1).length > 0;
}

let lastMessages = [];

// Lokales Uebernehmen einer erfolgreichen Mutation (keyed by id; ids sind AUTOINCREMENT-
// monoton pro Session). Der naechste Poll/Fetch bzw. das naechste SSE-Event ueberschreibt
// mit dem serverseitigen Stand. Die Mutation wird auch auf den Live-SSE-Stand gespiegelt,
// damit die Ansicht waehrend der Generierung nicht kurz den alten Stand zeigt.
export function applyLocalMessage(m) {
  const n = normalizeMessage(m);
  const upsert = (list) => {
    const i = list.findIndex((x) => x.id === n.id);
    if (i < 0) return [...list, n];
    const copy = list.slice();
    copy[i] = n;
    return copy;
  };
  state.messages = upsert(state.messages);
  sseState = applyToLiveState(sseState, liveId(), upsert);
}

export function removeLocalMessage(mid) {
  state.messages = state.messages.filter((x) => x.id !== mid);
  sseState = applyToLiveState(sseState, liveId(), (msgs) => msgs.filter((x) => x.id !== mid));
}

export function removeLocalMessagesAfter(mid) {
  // id > mid ist genau die serverseitig geloeschte Menge (q_delete_messages_after);
  // Live-Messages (id=null) bleiben erhalten (null <= mid)
  const keep = (msgs) => msgs.filter((x) => x.id <= mid);
  state.messages = keep(state.messages);
  sseState = applyToLiveState(sseState, liveId(), keep);
}

// Keyed reconciliation: Bubbles werden pro Nachricht wiederverwendet und nur
// bei Aenderung aktualisiert, statt das gesamte Chat-DOM bei jedem Poll neu zu bauen.
const bubbleNodes = new Map();

function bubbleKey(m, idx) {
  if (m.id != null) return `msg-${m.id}`;
  return m.role === "system" ? "sys-prompt" : `live-${idx}`;
}

function updateBubble(b, m, showResend, showEdit) {
  b._msg = m;
  const text = m.text || "";
  // im Inline-Edit-Modus das Textarea nicht ueberschreiben
  if (b.dataset.editing !== "true" && b._fullText !== text) setBubbleText(b, text);
  const inCtx = m.inContext !== false;
  const chk = b.querySelector(".chk");
  if (chk) chk.checked = inCtx;
  if (m.type !== "reasoning") {
    b.classList.toggle("selected", inCtx);
    b.classList.toggle("deselected", !inCtx);
  }
  const resend = b.querySelector(".resendBtn");
  if (resend) resend.classList.toggle("u-hidden", !showResend);
  const edit = b.querySelector(".editBtn");
  if (edit) edit.classList.toggle("u-hidden", !showEdit);
  syncBubbleDelete(b);
  syncBubbleTts(b);
}

// Alle gerenderten Bubbles auf die aktuelle Speech-Verfuegbarkeit nachziehen
export function syncAllBubbleTts() {
  for (const b of bubbleNodes.values()) syncBubbleTts(b);
}

export function scrollChatToBottom() {
  const chat = $("chat");
  chat.scrollTop = chat.scrollHeight;
}

export function renderChat(messages) {
  const chat = $("chat");
  const s = activeSession();
  if (!s || !messages?.length) {
    lastMessages = [];
    cancelEdit();
    // Nur Bubbles entfernen; der Session-Settings-Button bleibt als erstes Kind von #chat stehen
    for (const el of [...chat.children]) if (el.id !== "sessionSettingsBtn") el.remove();
    bubbleNodes.clear();
    const empty = document.createElement("div");
    empty.dataset.testid = "chat-empty";
    empty.className = "chatEmpty";
    empty.textContent = s ? "Neue Session – schreibe die erste Nachricht." : "Erstelle eine neue Session, um zu starten.";
    chat.appendChild(empty);
    return;
  }
  chat.querySelector('[data-testid="chat-empty"]')?.remove();
  // nur ans Ende scrollen, wenn der Nutzer bereits unten ist (Refresh/Poll
  // darf nicht hochgescrolltes Lesen unterbrechen); sonst die sichtbare
  // Position ueber einen Anker exakt halten, auch wenn Bubbles oberhalb des
  // Views durch den Stream wachsen oder neu hinzukommen
  const pinToBottom = isNearBottom(chat);
  const anchor = pinToBottom ? null : captureScrollAnchor(chat);
  const sortedMessages = sortMessagesForRender(messages);
  lastMessages = sortedMessages;
  if (editingMessageId != null && !sortedMessages.some((m) => m.id === editingMessageId)) cancelEdit();
  const lastUser = findLastUserMessage(sortedMessages);
  const items = [];
  const sysPrompt = resolveSystemPrompt(state.settings, state.sessionSettings);
  const sysShown = !!(sysPrompt && sysPrompt.trim() && state.settings.show_system_prompt !== false);
  if (sysShown) {
    items.push({ m: { role: "system", type: "message", text: sysPrompt, in_context: true }, showResend: false, showEdit: false });
  }
  for (const m of sortedMessages.filter((m) => isBubbleVisible(m, state.settings))) {
    // Session-System-Message identisch zum Settings-Prompt nicht doppelt rendern
    if (sysShown && isDuplicateSystemPrompt(m, sysPrompt)) continue;
    items.push({ m, showResend: m === lastUser, showEdit: m === lastUser });
  }
  const seen = new Set();
  for (const [idx, item] of items.entries()) {
    const key = bubbleKey(item.m, idx);
    seen.add(key);
    let b = bubbleNodes.get(key);
    if (!b) {
      b = bubbleEl(item.m, handlers, { showResend: item.showResend, showEdit: item.showEdit });
      bubbleNodes.set(key, b);
    } else {
      updateBubble(b, item.m, item.showResend, item.showEdit);
    }
    chat.appendChild(b); // appendChild verschiebt bestehende Knoten an die richtige Stelle
  }
  for (const [key, el] of bubbleNodes) {
    if (!seen.has(key)) {
      el.remove();
      bubbleNodes.delete(key);
    }
  }
  if (pinToBottom) chat.scrollTop = chat.scrollHeight;
  else restoreScrollAnchor(chat, anchor);
}

// Rendert die aktuelle Ansicht (SSE-Live-Stand der aktiven Session, sonst Poll-Stand) —
// refreshChat in main.js nutzt das, damit ein changed() waehrend der Generierung nicht
// den offenen Live-Block aus der Ansicht wirft.
export function renderChatView() {
  renderChat(viewMessages());
}

// Minimalismus: Kontextmenue je nach Geraet — Desktop (feiner Pointer): RECHTSKLICK
// (contextmenu) ueberschreibt das Systemmenue und oeffnet das App-Menue; Klick/Doppelklick
// oeffnen dort nichts. Touch (kein Hover): DOPPEL-Tap oeffnet das App-Menue, Langdruck bleibt
// nativ (Systemmenue + Textauswahl — Webseiten koennen dem Systemmenue keine Eintraege anhaengen).
// Einfacher Tap auf Touch schaltet zusaetzlich den Expand-Modus der Bubble zyklisch weiter
// (normal -> full -> collapsed -> normal), wie der Chevron im Normalmodus (siehe onBubbleTap).
// Laeuft eine Wiedergabe (TTS), stoppt im Minimalismus ein Doppel-Tap/Doppelklick auf eine
// Bubble bzw. die Esc-Taste die Wiedergabe (siehe onBubbleTap / initBubbleMenu).
let ctxMenu = null;
let ctxMenuDocHandler = null;

export function closeBubbleCtxMenu() {
  if (ctxMenuDocHandler) {
    document.removeEventListener("pointerdown", ctxMenuDocHandler);
    ctxMenuDocHandler = null;
  }
  if (ctxMenu) {
    ctxMenu.remove();
    ctxMenu = null;
  }
}

function openBubbleCtxMenu(b, x, y) {
  closeBubbleCtxMenu();
  const menu = document.createElement("div");
  menu.className = "ctxMenu";
  menu.dataset.testid = "bubble-context-menu";
  // Menue nur mit Text (keine Icons)
  const addItem = (testid, label, fn) => {
    const item = document.createElement("button");
    item.dataset.testid = testid;
    item.textContent = label;
    item.onclick = () => {
      closeBubbleCtxMenu();
      fn();
    };
    menu.appendChild(item);
  };
  // immer oben: Textaktionen der Bubble
  addItem("ctx-copy", "Kopieren", () => copyBubbleText(b));
  // danach die Aktionen der (versteckten) Toolbar — Kopieren ist als ctx-copy schon oben
  for (const ctl of b.querySelectorAll(".bubbleHead .iconBtn, .bubbleHead .chk")) {
    if (ctl.classList.contains("copyBtn")) continue;
    if (ctl.classList.contains("chk")) {
      // Kontext-Checkbox als Toggle mit zustandsabhaengigem Label
      const inCtx = b._msg?.inContext !== false;
      addItem("ctx-toggle-context", inCtx ? "Aus dem Kontext ausschließen" : "In den Kontext einschließen", () => ctl.click());
      continue;
    }
    addItem(`ctx-${ctl.dataset.testid || "action"}`, ctl.title || "Aktion", () => ctl.click());
  }
  if (!menu.children.length) return;
  menu.style.left = "0px";
  menu.style.top = "0px";
  document.body.appendChild(menu);
  const r = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(x || 8, window.innerWidth - r.width - 8))}px`;
  menu.style.top = `${Math.max(8, Math.min(y || 8, window.innerHeight - r.height - 8))}px`;
  ctxMenu = menu;
  ctxMenuDocHandler = (ev) => {
    // Tap ausserhalb des Menues und ausserhalb von Bubbles schliesst es sofort;
    // Taps auf Bubbles werden im click-Handler (onBubbleTap) als Toggle behandelt
    if (ctxMenu && !ctxMenu.contains(ev.target) && !ev.target.closest?.(".bubble")) closeBubbleCtxMenu();
  };
  document.addEventListener("pointerdown", ctxMenuDocHandler);
  document.addEventListener("keydown", (ev) => ev.key === "Escape" && closeBubbleCtxMenu(), { once: true });
}

// Nur ein kurzer Tap ohne Bewegung zaehlt — Scrollen/Pan mit dem Finger nicht. Das Menue
// oeffnet erst beim DOPPEL-Tap; der einfache Tap schaltet dafuer den Expand-Modus der Bubble
// zyklisch weiter (wie der Chevron, siehe bubbles.js). Laeuft eine Wiedergabe, stoppt der
// DOPPEL-Tap stattdessen die Wiedergabe (dann kein Menue, kein Expand-Wechsel).
// War beim pointerdown eine
// Textauswahl aktiv (System-Auswahlmenue offen), oeffnet der Tap kein Menue: er bricht die
// Auswahl ab (hadSelection wird am pointerdown gemessen, weil der Browser die Auswahl schon
// beim pointerdown kollabieren kann).
let tapStart = null; // { x, y, t, hadSelection } des pointerdown auf einer Bubble
let lastTap = null; // { t, x, y, bubble } des letzten kurzen Taps (Doppel-Tap-Erkennung)
let pendingModeTap = null; // { timer, bubble } — Einfach-Tap-Expand, wartet das Doppel-Tap-Fenster ab
const TAP_MAX_MOVE_PX = 10;
const TAP_MAX_MS = 500;
const DBL_TAP_MAX_MS = 350;
const DBL_TAP_MAX_PX = 30;

function cancelPendingModeTap() {
  if (pendingModeTap) {
    clearTimeout(pendingModeTap.timer);
    pendingModeTap = null;
  }
}

export function onBubbleTap(e) {
  if (!isToolbarMinimal(state.settings)) return; // ohne Minimalismus normales Klick-Verhalten
  if (e.target.closest("button, input, textarea, a, .editRow")) return; // interaktive Elemente unveraendert
  const b = e.target.closest?.(".bubble");
  if (!b || b.dataset.editing === "true") return;
  if (isFinePointer()) {
    // Desktop: Klick/Doppelklick oeffnen nie das Menue (das kommt vom Rechtsklick/contextmenu);
    // ein Klick bei offenem Menue schliesst es wieder. lastTap wird trotzdem gefuehrt, damit das
    // zweite pointerdown des Doppelklicks die Wortauswahl (Firefox) unterdruecken kann.
    if (ctxMenu) {
      closeBubbleCtxMenu();
      lastTap = null;
      return;
    }
    const dbl =
      lastTap &&
      e.timeStamp - lastTap.t <= DBL_TAP_MAX_MS &&
      Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) <= DBL_TAP_MAX_PX &&
      lastTap.bubble === b;
    lastTap = { t: e.timeStamp, x: e.clientX, y: e.clientY, bubble: b };
    if (dbl && isSpeaking()) stopSpeech(); // Doppelklick stoppt die Wiedergabe; einzelner Klick nicht
    return;
  }
  const start = tapStart;
  tapStart = null;
  if (!start || Math.hypot(e.clientX - start.x, e.clientY - start.y) > TAP_MAX_MOVE_PX || e.timeStamp - start.t > TAP_MAX_MS) return; // kein kurzer Tap (z. B. Scroll-Geste)
  if (start.hadSelection) {
    lastTap = null; // System-Auswahlmenue war offen -> Tap bricht Auswahl ab, zaehlt nicht als Tap
    return;
  }
  if (ctxMenu) {
    cancelPendingModeTap();
    closeBubbleCtxMenu(); // Tap bei offenem Menue schliesst alle Kontextmenues
    lastTap = null;
    return;
  }
  const dbl =
    lastTap &&
    e.timeStamp - lastTap.t <= DBL_TAP_MAX_MS &&
    Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) <= DBL_TAP_MAX_PX &&
    lastTap.bubble === b;
  lastTap = { t: e.timeStamp, x: e.clientX, y: e.clientY, bubble: b };
  if (dbl) {
    lastTap = null;
    cancelPendingModeTap(); // Doppel-Tap ist eine eigene Aktion: aendert nicht den Expand-Modus
    if (isSpeaking()) stopSpeech(); // Doppel-Tap waehrend Wiedergabe: stoppen statt Menue oeffnen
    else openBubbleCtxMenu(b, e.clientX, e.clientY);
    return;
  }
  // Einfacher Tap: Expand-Modus zyklisch weiterschalten (normal -> full -> collapsed -> normal).
  // Verzoegert um das Doppel-Tap-Fenster, damit ein Doppel-Tap nicht zusaetzlich den Modus aendert;
  // Scroll-Gesten kommen hier nie an (Bewegung/Zeit siehe oben) und bleiben unberuehrt.
  cancelPendingModeTap();
  pendingModeTap = {
    bubble: b,
    timer: setTimeout(() => {
      pendingModeTap = null;
      setBubbleMode(b, nextBubbleMode(b.dataset.mode || "normal", b._normalTruncated));
    }, DBL_TAP_MAX_MS),
  };
}

// Desktop: Rechtsklick auf eine Bubble ueberschreibt das System-Kontextmenue durch das App-Menue
export function onBubbleContextMenu(e) {
  if (!isToolbarMinimal(state.settings)) return;
  if (!isFinePointer()) return; // Touch: Langdruck bleibt nativ (Systemmenue + Textauswahl)
  const b = e.target.closest?.(".bubble");
  if (!b) return;
  e.preventDefault();
  openBubbleCtxMenu(b, e.clientX, e.clientY);
}

export function initBubbleMenu() {
  const chat = $("chat");
  chat.addEventListener("click", onBubbleTap); // Touch: Einfach-Tap = Expand-Zyklus, Doppel-Tap-Menue (Desktop: nur Schliessen)
  chat.addEventListener("contextmenu", onBubbleContextMenu); // Desktop: Rechtsklick-Menue (Touch: nativ)
  chat.addEventListener("pointerdown", (e) => {
    const b = e.target.closest?.(".bubble");
    if (!b) {
      tapStart = null;
      return;
    }
    // Doppel-Tap auf derselben Bubble: zweites pointerdown canceln — das ist das Systemdefault,
    // das in Firefox das Wort unter dem Tap selektiert. click/dblclick feuern trotzdem (Pointer-Events-Spec)
    if (
      isToolbarMinimal(state.settings) &&
      lastTap &&
      e.timeStamp - lastTap.t <= DBL_TAP_MAX_MS &&
      Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) <= DBL_TAP_MAX_PX &&
      lastTap.bubble === b
    ) {
      e.preventDefault();
    }
    const sel = window.getSelection();
    tapStart = { x: e.clientX, y: e.clientY, t: e.timeStamp, hadSelection: !!(sel && !sel.isCollapsed) };
  });
  chat.addEventListener("dblclick", (e) => {
    // Desktop: Doppelklick-Wortauswahl im Minimalismus zusaetzlich unterdruecken
    if (isToolbarMinimal(state.settings) && e.target.closest?.(".bubble")) e.preventDefault();
  });
  chat.addEventListener("scroll", () => closeBubbleCtxMenu(), { passive: true });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isSpeaking()) stopSpeech(); // Esc stoppt die laufende Wiedergabe
  });
}

// Edit-Modus: id der Nutzernachricht, die gerade inline in ihrer Bubble bearbeitet wird
let editingMessageId = null;

export function cancelEdit() {
  if (editingMessageId == null) return;
  const mid = editingMessageId;
  editingMessageId = null;
  const b = document.querySelector(`.bubble[data-msg-id="${mid}"]`);
  if (b) exitBubbleEdit(b);
}

// Bearbeiten und Erneut-senden teilen sich diesen Pfad: patchen, alles danach loeschen
async function resubmitMessage(s, mid, text, attachments) {
  const updated = await api.patch(`/sessions/${s.id}/messages/${mid}`, { text, attachments });
  applyLocalMessage(updated);
  try {
    await api.del(`/sessions/${s.id}/messages/after/${mid}`);
    removeLocalMessagesAfter(mid);
  } catch {}
}

async function resendMessage(m) {
  const s = activeSession();
  if (!s || state.streaming || s.generating || m.id == null) return;
  await resubmitMessage(s, m.id, m.text || "", m.attachments || []);
  await loadSessions();
  changed();
  await triggerGeneration(s);
}

// Generierung nach dem Senden/Bearbeiten anstossen (serverseitige Hintergrund-Task).
async function triggerGeneration(s) {
  renderChat(viewMessages()); // lokal gepflegte History (send/resubmit) direkt rendern
  scrollChatToBottom(); // nach dem Absenden direkt zur neuen Nachricht/Antwort springen
  try {
    // Chat-History baut der Server aus der Session-DB (gueltiges LLM-Format inkl. Tool-Calls)
    await api.post("/chat", { session_id: s.id, model: state.settings.model });
  } catch (err) {
    if (err.status === 409) {
      // Es laeuft bereits eine Generierung (z. B. Doppel-POST): kein Fehler persistieren,
      // sondern an den laufenden Stream anhaengen
      setStreamingUI(true);
      openLiveStream(s);
      await pollOnce();
      ensurePolling();
      return;
    }
    const em = { role: "system", type: "message", text: "Fehler: " + err.message, in_context: false };
    const stored = await api.post(`/sessions/${s.id}/messages`, em).catch(() => null);
    if (stored) applyLocalMessage(stored);
    await loadSessions();
    changed();
    return;
  }
  setStreamingUI(true);
  openLiveStream(s); // Live-Chunks direkt aus der Service-Layer (In-Memory)
  await pollOnce();
  ensurePolling();
}

// Speichern aus dem Inline-Edit der Bubble (Save-Button oder Enter)
async function submitEdit(mid, rawText) {
  const s = activeSession();
  if (!s || state.streaming || s.generating || editingMessageId !== mid) return;
  const text = (rawText || "").trim();
  if (!text) {
    cancelEdit();
    return;
  }
  const detail = await api.get(`/sessions/${s.id}`);
  const old = normalizeMessages(detail.messages).find((x) => x.id === mid);
  await resubmitMessage(s, mid, text, old?.attachments || []);
  cancelEdit();
  await loadSessions();
  changed();
  await triggerGeneration(s);
}

const handlers = {
  onEdit: (m, b) => {
    if (state.streaming || !m || m.id == null || editingMessageId === m.id) return;
    cancelEdit();
    editingMessageId = m.id;
    const ui = enterBubbleEdit(b, m.text || "");
    if (!ui) {
      editingMessageId = null;
      return;
    }
    ui.cancelBtn.onclick = () => cancelEdit();
    ui.textarea.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Escape") {
        e.preventDefault();
        cancelEdit();
      } else if (e.key === "Enter" && !e.shiftKey) {
        // Enter sendet immer (Shift+Enter = Zeilenumbruch)
        e.preventDefault();
        submitEdit(m.id, ui.textarea.value);
      }
    });
    ui.textarea.focus();
    ui.textarea.setSelectionRange(ui.textarea.value.length, ui.textarea.value.length);
  },
  onToggleContext: (m) => {
    const s = activeSession();
    if (m.id != null && s)
      api
        .patch(`/sessions/${s.id}/messages/${m.id}`, { in_context: m.inContext })
        .then((updated) => applyLocalMessage(updated))
        .catch(() => {});
  },
  onDelete: async (m) => {
    const ok = await confirmModal({ title: "Nachricht löschen", text: "Diese Nachricht löschen?" });
    if (!ok) return;
    const s = activeSession();
    if (m.id != null && s) {
      try {
        await api.del(`/sessions/${s.id}/messages/${m.id}`);
        removeLocalMessage(m.id);
      } catch {}
    }
    changed();
  },
  onResend: (m) => {
    void resendMessage(m);
  },
};

// Polling des Server-seitigen Generierungsstands: die LLM-Generierung laeuft
// serverseitig in einer Hintergrund-Task und wird in die Session persistiert.
// Dadurch geht nichts verloren, wenn die App in den Hintergrund wechselt.
const POLL_MS = 1200;
let pollTimer = null;
let pollInFlight = false;

export async function pollOnce() {
  if (pollInFlight) return;
  pollInFlight = true;
  try {
    await loadSessions().catch(() => {});
    const s = activeSession();
    let refreshed = false;
    if (s) {
      try {
        const detail = await api.get(`/sessions/${s.id}`);
        const msgs = normalizeMessages(detail.messages);
        state.messages = msgs;
        state.messagesSid = s.id;
        refreshed = true;
      } catch {}
    }
    const generating = !!s?.generating;
    setStreamingUI(generating);
    // z. B. nach Reload waehrend laufender Generierung: Live-Stream der Service-Layer abonnieren
    if (generating && s && !liveStream) openLiveStream(s);
    if (!generating) {
      closeStreamSocket();
      // SSE-Stand erst verwerfen, wenn der Poll den persistierten Stand frisch gelesen
      // hat — sonst faellt die Ansicht nach Stream-Ende auf den aelteren Poll-Stand zurueck
      if (refreshed) sseState = null;
    }
    const view = viewMessages();
    if (JSON.stringify(view) !== JSON.stringify(lastMessages)) renderChat(view);
    if (state.sessions.some((x) => x.generating)) ensurePolling();
    else stopPolling();
  } finally {
    pollInFlight = false;
  }
}

export function ensurePolling() {
  if (!pollTimer) pollTimer = setInterval(pollOnce, POLL_MS);
}

export function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// In-Flight-Guard fuer send(): streaming/generating werden erst am Ende von send()
// gesetzt und die Chat-Zeile wird erst nach den ersten awaits geleert - ein zweiter
// Aufruf im selben Fenster (Doppel-Tap auf Senden, Enter direkt nach der Browser-
// Diktation plus Tap) darf dieselbe Nachricht nicht erneut POSTen.
let sending = false;

export async function send() {
  // auch serverseitig laufendes generating (z. B. nach Reload) zeigt Abbrechen statt Senden
  if (state.streaming || activeSession()?.generating) {
    abortStream();
    return;
  }
  if (sending) return;
  sending = true;
  try {
    stopRecording({ discard: true });
    const input = $("input");
    const text = input.value.trim();
    if (!text && !state.pendingAttachments.length) return;
    let s = activeSession();
    if (!s) {
      await newSession(true);
      s = activeSession();
    }
    const attachments = await uploadPendingAttachments(s.id);
    const created = await api.post(`/sessions/${s.id}/messages`, {
      role: "user",
      type: "message",
      text,
      in_context: true,
      attachments,
    });
    applyLocalMessage(created);
    await loadSessions();
    input.value = "";
    input.style.height = "auto";
    input.style.overflowY = "hidden";
    changed();
    await triggerGeneration(s);
  } finally {
    sending = false;
  }
}

export function renderHeader() {
  const s = activeSession();
  $("headerTitle").textContent = s ? `${state.appName} · ${s.name}` : state.appName;
}
