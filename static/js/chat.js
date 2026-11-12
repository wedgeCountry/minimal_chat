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

let lastMessages = [];

// Keyed reconciliation: Bubbles werden pro Nachricht wiederverwendet und nur
// bei Aenderung aktualisiert, statt das gesamte Chat-DOM bei jedem Poll neu zu bauen.
const bubbleNodes = new Map();

function bubbleKey(m) {
  return m.id != null ? `msg-${m.id}` : "sys-prompt";
}

function updateBubble(b, m, showResend) {
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
}

export function renderChat(messages) {
  const chat = $("chat");
  const s = activeSession();
  if (!s || !messages?.length) {
    lastMessages = [];
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
  const lastUser = findLastUserMessage(sortedMessages);
  const items = [];
  const sysPrompt = state.settings.system_prompt;
  if (sysPrompt && state.settings.show_system_prompt !== false) {
    items.push({ m: { role: "system", type: "message", text: sysPrompt, in_context: true }, showResend: false });
  }
  for (const m of sortedMessages.filter((m) => isBubbleVisible(m, state.settings))) {
    items.push({ m, showResend: m === lastUser });
  }
  const seen = new Set();
  for (const item of items) {
    const key = bubbleKey(item.m);
    seen.add(key);
    let b = bubbleNodes.get(key);
    if (!b) {
      b = bubbleEl(item.m, handlers, { showResend: item.showResend });
      bubbleNodes.set(key, b);
    } else {
      updateBubble(b, item.m, item.showResend);
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

const handlers = {
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
    if (state.streaming) return;
    const idx = lastMessages.findIndex((x) => x.id === m.id);
    const answered = idx >= 0 && lastMessages.slice(idx + 1).some((x) => x.role === "assistant");
    if (answered) {
      const ok = await confirmModal({
        title: "Erneut senden",
        text: "Auf diese Nachricht hat der Assistent bereits geantwortet. Erneut senden?",
        okLabel: "Erneut senden",
      });
      if (!ok) return;
    }
    await send(m.text, m.attachments || []);
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
  const text = (typeof textOverride === "string" ? textOverride : input.value).trim();
  const pending = Array.isArray(attachmentsOverride) ? attachmentsOverride : state.pendingAttachments;
  if (!text && !pending.length) return;
  let s = activeSession();
  if (!s) {
    await newSession(true);
    s = activeSession();
  }
  const attachments = Array.isArray(attachmentsOverride) ? attachmentsOverride : await uploadPendingAttachments(s.id);
  await api.post(`/sessions/${s.id}/messages`, {
    role: "user",
    type: "message",
    text,
    in_context: true,
    attachments,
  });
  await loadSessions();
  if (typeof textOverride !== "string") {
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
