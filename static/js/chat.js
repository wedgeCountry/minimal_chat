import { api, streamChat } from "./api.js";
import { activeSession, state } from "./state.js";
import { $, esc } from "./util.js";
import { ICONS } from "./icons.js";
import { bubbleEl, setBubbleMode, setBubbleText } from "./bubbles.js";
import { buildChatPayload } from "./payload.js";
import { parseSSE } from "./sse.js";
import { loadSessions, newSession, changed } from "./sessions.js";
import { confirmModal, showError } from "./confirm.js";
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
  state.abortCtrl?.abort();
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

export function renderChat(messages) {
  const chat = $("chat");
  chat.innerHTML = "";
  const s = activeSession();
  if (!s || !messages?.length) {
    lastMessages = [];
    const empty = document.createElement("div");
    empty.dataset.testid = "chat-empty";
    empty.style.cssText = "margin:auto;color:var(--muted);font-size:14px;text-align:center";
    empty.textContent = s ? "Neue Session – schreibe die erste Nachricht." : "Erstelle eine neue Session, um zu starten.";
    chat.appendChild(empty);
    return;
  }
  const sortedMessages = sortMessagesForRender(messages);
  lastMessages = sortedMessages;
  const lastUser = findLastUserMessage(sortedMessages);
  const sysPrompt = state.settings.system_prompt;
  if (sysPrompt && state.settings.show_system_prompt !== false) {
    chat.appendChild(bubbleEl({ role: "system", type: "message", text: sysPrompt, in_context: true }, handlers));
  }
  sortedMessages.filter((m) => isBubbleVisible(m, state.settings)).forEach((m) => chat.appendChild(bubbleEl(m, handlers, { showResend: m === lastUser })));
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

export function applyToolCallDelta(toolCalls, tc) {
  const idx = tc.index ?? toolCalls.size;
  let entry = toolCalls.get(idx);
  if (!entry) {
    entry = { name: "", args: "", msg: { role: "assistant", type: "toolcall", text: "", in_context: false }, el: null };
    toolCalls.set(idx, entry);
  }
  entry.name += tc.function?.name || "";
  entry.args += tc.function?.arguments || "";
  entry.msg.text = `${entry.name || "tool"}(${entry.args})`;
  return entry;
}

export async function send(textOverride, attachmentsOverride) {
  if (state.streaming) {
    abortStream();
    return;
  }
  const input = $("input");
  const text = (typeof textOverride === "string" ? textOverride : input.value).trim();
  const attachments = Array.isArray(attachmentsOverride) ? attachmentsOverride : state.pendingAttachments.splice(0);
  if (!text && !attachments.length) return;
  let s = activeSession();
  if (!s) {
    await newSession(true);
    s = activeSession();
  }
  const userMsg = await api.post(`/sessions/${s.id}/messages`, {
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

  const aiMsg = { role: "assistant", type: "message", text: "", in_context: true };
  const thinkMsg = { role: "assistant", type: "reasoning", text: "", in_context: false };
  let hasThink = false;
  const toolCalls = new Map();
  const chat = $("chat");
  const aiEl = bubbleEl(aiMsg, handlers);
  chat.appendChild(aiEl);
  let thinkEl = null;
  setStreamingUI(true);
  state.abortCtrl = new AbortController();

  const persist = async (m) => {
    try {
      return await api.post(`/sessions/${s.id}/messages`, m);
    } catch {
      return null;
    }
  };

  try {
    const detail = await api.get(`/sessions/${s.id}`);
    const payload = buildChatPayload({ model: state.settings.model, messages: detail.messages });
    const res = await streamChat(payload, state.abortCtrl.signal);
    const reader = res.body.getReader();
    for await (const j of parseSSE(reader)) {
      if (j.error) throw new Error(j.error);
      const delta = j.choices?.[0]?.delta || {};
      const reasoning = delta.reasoning_content ?? delta.reasoning;
      if (reasoning && state.settings.show_reasoning !== false) {
        if (!hasThink) {
          hasThink = true;
          thinkEl = bubbleEl(thinkMsg, handlers);
          setBubbleMode(thinkEl, "full");
          chat.appendChild(thinkEl);
        }
        thinkMsg.text += reasoning;
        setBubbleText(thinkEl, thinkMsg.text);
      }
      if (delta.content) {
        aiMsg.text += delta.content;
        setBubbleText(aiEl, aiMsg.text);
      }
      if (delta.tool_calls && state.settings.show_tool_output !== false) {
        for (const tc of delta.tool_calls) {
          const entry = applyToolCallDelta(toolCalls, tc);
          if (!entry.el) {
            entry.el = bubbleEl(entry.msg, handlers);
            chat.appendChild(entry.el);
          }
          setBubbleText(entry.el, entry.msg.text);
        }
      }
      chat.scrollTop = chat.scrollHeight;
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      if (err.message.includes("LLM-Server nicht erreichbar")) {
        await showError(err.message);
      } else {
        const em = { role: "system", type: "message", text: "Fehler: " + err.message, in_context: false };
        if (isBubbleVisible(em, state.settings)) chat.appendChild(bubbleEl(em, handlers));
        await persist(em);
      }
    }
  } finally {
    setStreamingUI(false);
    state.abortCtrl = null;
    // Reasoning/Toolcalls vor der Antwort persistieren, damit die id-Reihenfolge
    // der gewuenschten Anzeigereihenfolge entspricht (Thinking vor Antwort).
    if (hasThink && thinkMsg.text) await persist(thinkMsg);
    for (const entry of toolCalls.values()) if (entry.msg.text) await persist(entry.msg);
    if (aiMsg.text) {
      const saved = await persist(aiMsg);
      if (saved) aiMsg.id = saved.id;
    }
    await loadSessions();
    changed();
  }
}

export function renderHeader() {
  const s = activeSession();
  $("headerTitle").textContent = s ? `${state.appName} · ${s.name}` : state.appName;
}

export { esc };
