import { api, streamChat } from "./api.js";
import { activeSession, state } from "./state.js";
import { $, esc } from "./util.js";
import { ICONS } from "./icons.js";
import { bubbleEl } from "./bubbles.js";
import { buildChatPayload } from "./payload.js";
import { parseSSE } from "./sse.js";
import { loadSessions, newSession, changed } from "./sessions.js";

const bodyOf = (el) => el.querySelector(".bubbleBody");

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

export function renderChat(messages) {
  const chat = $("chat");
  chat.innerHTML = "";
  const s = activeSession();
  if (!s || !messages?.length) {
    const empty = document.createElement("div");
    empty.style.cssText = "margin:auto;color:var(--muted);font-size:14px;text-align:center";
    empty.textContent = s ? "Neue Session – schreibe die erste Nachricht." : "Erstelle eine neue Session, um zu starten.";
    chat.appendChild(empty);
    return;
  }
  messages.forEach((m) => chat.appendChild(bubbleEl(m, handlers)));
  chat.scrollTop = chat.scrollHeight;
}

const handlers = {
  onToggleContext: (m) => {
    const s = activeSession();
    if (m.id != null && s)
      api.patch(`/sessions/${s.id}/messages/${m.id}`, { in_context: m.inContext }).catch(() => {});
  },
  onDelete: async (m) => {
    if (!confirm("Diese Nachricht löschen?")) return;
    const s = activeSession();
    if (m.id != null && s) await api.del(`/sessions/${s.id}/messages/${m.id}`).catch(() => {});
    changed();
  },
};

export async function send() {
  if (state.streaming) {
    abortStream();
    return;
  }
  const input = $("input");
  const text = input.value.trim();
  if (!text && !state.pendingAttachments.length) return;
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
    attachments: state.pendingAttachments.splice(0),
  });
  await loadSessions();
  input.value = "";
  input.style.height = "auto";
  changed();

  const aiMsg = { role: "assistant", type: "message", text: "", in_context: true };
  const thinkMsg = { role: "assistant", type: "reasoning", text: "", in_context: false };
  let hasThink = false;
  const toolMsgs = [];
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
      if (reasoning) {
        if (!hasThink) {
          hasThink = true;
          thinkEl = bubbleEl(thinkMsg, handlers);
          thinkEl.classList.remove("collapsed");
          chat.appendChild(thinkEl);
        }
        thinkMsg.text += reasoning;
        bodyOf(thinkEl).textContent = thinkMsg.text;
      }
      if (delta.content) {
        aiMsg.text += delta.content;
        bodyOf(aiEl).textContent = aiMsg.text;
      }
      if (delta.tool_calls) {
        for (const tc of delta.tool_calls) {
          const fn = tc.function?.name || "tool";
          const args = tc.function?.arguments || "";
          const tm = { role: "assistant", type: "toolcall", text: `${fn}(${args})`, in_context: false };
          toolMsgs.push(tm);
          chat.appendChild(bubbleEl(tm, handlers));
        }
      }
      chat.scrollTop = chat.scrollHeight;
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      const em = { role: "system", type: "message", text: "Fehler: " + err.message, in_context: false };
      chat.appendChild(bubbleEl(em, handlers));
      await persist(em);
    }
  } finally {
    setStreamingUI(false);
    state.abortCtrl = null;
    if (aiMsg.text) {
      const saved = await persist(aiMsg);
      if (saved) aiMsg.id = saved.id;
    }
    if (hasThink && thinkMsg.text) await persist(thinkMsg);
    for (const tm of toolMsgs) await persist(tm);
    await loadSessions();
    changed();
  }
}

export function renderHeader() {
  const s = activeSession();
  $("headerTitle").textContent = s ? `LeanChat · ${s.name}` : "LeanChat";
}

export { esc };
