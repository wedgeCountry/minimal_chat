import { api } from "./api.js";
import { activeSession, normalizeMessages, state } from "./state.js";
import { $ } from "./util.js";
import { ICONS } from "./icons.js";
import { bubbleEl, setBubbleText } from "./bubbles.js";
import { buildChatPayload } from "./payload.js";
import { loadSessions, newSession, changed } from "./sessions.js";
import { uploadPendingAttachments } from "./attachments.js";
import { confirmModal } from "./confirm.js";
import { isBubbleVisible } from "./visibility.js";

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
}

export function sortMessagesForRender(messages) {
  // Chronologisch nach Zeitstempel, bei Gleichstand (Sekundenaufloesung)
  // nach id (Einfuegereihenfolge) - so landet der Reasoning-Bubble direkt
  // vor seiner Antwort, weil er vor ihr persistiert wird.
  return [...messages].sort((a, b) => {
    const d = (a.ts ?? 0) - (b.ts ?? 0);
    if (d !== 0) return d;
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

// Keyed reconciliation: Bubbles werden pro Nachricht wiederverwendet und nur
// bei Aenderung aktualisiert, statt das gesamte Chat-DOM bei jedem Poll neu zu bauen.
const bubbleNodes = new Map();

function bubbleKey(m) {
  return m.id != null ? `msg-${m.id}` : "sys-prompt";
}

function updateBubble(b, m, showResend, showEdit) {
  b._msg = m;
  const text = m.text || "";
  if (b._fullText !== text) setBubbleText(b, text);
  const inCtx = m.inContext !== false;
  const chk = b.querySelector(".chk");
  if (chk) chk.checked = inCtx;
  if (m.type === "message") {
    b.classList.toggle("selected", inCtx);
    b.classList.toggle("deselected", !inCtx);
  }
  const resend = b.querySelector(".resendBtn");
  if (resend) resend.style.display = showResend ? "" : "none";
  const edit = b.querySelector(".editBtn");
  if (edit) edit.style.display = showEdit ? "" : "none";
}

export function renderChat(messages) {
  const chat = $("chat");
  const s = activeSession();
  if (!s || !messages?.length) {
    lastMessages = [];
    cancelEdit();
    chat.innerHTML = "";
    bubbleNodes.clear();
    const empty = document.createElement("div");
    empty.dataset.testid = "chat-empty";
    empty.style.cssText = "margin:auto;color:var(--muted);font-size:14px;text-align:center";
    empty.textContent = s ? "Neue Session – schreibe die erste Nachricht." : "Erstelle eine neue Session, um zu starten.";
    chat.appendChild(empty);
    return;
  }
  chat.querySelector('[data-testid="chat-empty"]')?.remove();
  const sortedMessages = sortMessagesForRender(messages);
  lastMessages = sortedMessages;
  if (editingMessageId != null && !sortedMessages.some((m) => m.id === editingMessageId)) cancelEdit();
  const lastUser = findLastUserMessage(sortedMessages);
  const items = [];
  const sysPrompt = state.settings.system_prompt;
  if (sysPrompt && state.settings.show_system_prompt !== false) {
    items.push({ m: { role: "system", type: "message", text: sysPrompt, in_context: true }, showResend: false, showEdit: false });
  }
  for (const m of sortedMessages.filter((m) => isBubbleVisible(m, state.settings))) {
    items.push({ m, showResend: m === lastUser, showEdit: m === lastUser });
  }
  const seen = new Set();
  for (const item of items) {
    const key = bubbleKey(item.m);
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
  chat.scrollTop = chat.scrollHeight;
}

// Edit-Modus: id der Nutzernachricht, die gerade im Composer bearbeitet wird
let editingMessageId = null;

function setEditUI(on) {
  $("composerWrap").classList.toggle("editing", on);
  const input = $("input");
  input.placeholder = on ? "Nachricht bearbeiten…" : "Nachricht schreiben…";
  $("sendBtn").title = on ? "Bearbeiten & erneut senden" : "Senden";
}

export function startEdit(m) {
  if (state.streaming || !m || m.id == null) return;
  editingMessageId = m.id;
  setEditUI(true);
  const input = $("input");
  input.value = m.text || "";
  input.dispatchEvent(new Event("input"));
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

export function cancelEdit() {
  if (editingMessageId == null) return;
  editingMessageId = null;
  setEditUI(false);
  const input = $("input");
  input.value = "";
  input.style.height = "auto";
  input.style.overflowY = "hidden";
}

const handlers = {
  onEdit: (m) => startEdit(m),
  onToggleContext: (m) => {
    const s = activeSession();
    if (m.id != null && s)
      api.patch(`/sessions/${s.id}/messages/${m.id}`, { in_context: m.inContext }).catch(() => {});
  },
  onDelete: async (m) => {
    const ok = await confirmModal({ title: "Nachricht löschen", text: "Diese Nachricht löschen?" });
    if (!ok) return;
    const s = activeSession();
    if (m.id != null && s) await api.del(`/sessions/${s.id}/messages/${m.id}`).catch(() => {});
    changed();
  },
  onResend: async (m) => {
    // Erneut senden = Bearbeiten ohne Text-Aenderung: gleicher Code-Pfad wie der
    // Edit-Button (Nachricht patchen, alles danach loeschen, neu generieren).
    if (state.streaming || m.id == null) return;
    const prev = editingMessageId;
    editingMessageId = m.id;
    await send(m.text, m.attachments || []);
    if (editingMessageId === m.id) editingMessageId = prev; // abgebrochen -> vorheriger Zustand
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
    if (s) {
      try {
        const detail = await api.get(`/sessions/${s.id}`);
        const msgs = normalizeMessages(detail.messages);
        if (JSON.stringify(msgs) !== JSON.stringify(lastMessages)) renderChat(msgs);
      } catch {}
    }
    setStreamingUI(!!s?.generating);
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

export async function send(textOverride, attachmentsOverride) {
  if (state.streaming) {
    abortStream();
    return;
  }
  const input = $("input");
  const composerSubmit = typeof textOverride !== "string";
  const text = (composerSubmit ? input.value : textOverride).trim();
  const pending = Array.isArray(attachmentsOverride) ? attachmentsOverride : state.pendingAttachments;
  if (!text && !pending.length) return;
  let s = activeSession();
  if (!s) {
    await newSession(true);
    s = activeSession();
  }
  if (editingMessageId != null) {
    // Bearbeiten/Erneut-senden der letzten Nutzernachricht: Text uebernehmen,
    // alles danach loeschen (Assistenten-Antworten) und anschliessend neu generieren.
    const mid = editingMessageId;
    if (hasMessagesAfter(lastMessages, mid)) {
      const ok = await confirmModal({
        title: composerSubmit ? "Nachricht bearbeiten" : "Erneut senden",
        text:
          "Alle Nachrichten nach dieser Nachricht (inkl. Antworten des Assistenten) werden gelöscht. " +
          (composerSubmit ? "Bearbeiten und erneut senden?" : "Erneut senden?"),
        okLabel: composerSubmit ? "Bearbeiten & senden" : "Erneut senden",
      });
      if (!ok) return; // Edit-Modus bleibt aktiv
    }
    const detail = await api.get(`/sessions/${s.id}`);
    const old = normalizeMessages(detail.messages).find((x) => x.id === mid);
    let attachments = Array.isArray(attachmentsOverride) ? attachmentsOverride : old?.attachments || [];
    if (composerSubmit && !Array.isArray(attachmentsOverride))
      attachments = [...attachments, ...(await uploadPendingAttachments(s.id))];
    await api.patch(`/sessions/${s.id}/messages/${mid}`, { text, attachments });
    await api.del(`/sessions/${s.id}/messages/after/${mid}`).catch(() => {});
    editingMessageId = null;
    setEditUI(false);
  } else {
    const attachments = Array.isArray(attachmentsOverride) ? attachmentsOverride : await uploadPendingAttachments(s.id);
    await api.post(`/sessions/${s.id}/messages`, {
      role: "user",
      type: "message",
      text,
      in_context: true,
      attachments,
    });
  }
  await loadSessions();
  if (composerSubmit) {
    input.value = "";
    input.style.height = "auto";
    input.style.overflowY = "hidden";
  }
  changed();

  const detail = await api.get(`/sessions/${s.id}`);
  const payload = buildChatPayload({ model: state.settings.model, messages: normalizeMessages(detail.messages) });
  try {
    await api.post("/chat", { session_id: s.id, ...payload });
  } catch (err) {
    const em = { role: "system", type: "message", text: "Fehler: " + err.message, in_context: false };
    await api.post(`/sessions/${s.id}/messages`, em).catch(() => {});
    await loadSessions();
    changed();
    return;
  }
  setStreamingUI(true);
  await pollOnce();
  ensurePolling();
}

export function renderHeader() {
  const s = activeSession();
  $("headerTitle").textContent = s ? `${state.appName} · ${s.name}` : state.appName;
}
