import { esc } from "./util.js";
import { ICONS } from "./icons.js";
import { state } from "./state.js";
import { isBubbleDeletable, isUserBubbleCheckable, isUserBubbleDeletable } from "./visibility.js";
import { BUBBLE_MODES, clampText, nextBubbleMode, bubbleModeTitle } from "./bubbleMode.js";

const typeLabels = { message: "", toolcall: "Tool-Call", reasoning: "Thinking", system: "System" };

let tmpBubbleSeq = 0;

export function setBubbleMode(b, mode) {
  for (const m of BUBBLE_MODES) b.classList.remove(m);
  b.classList.add(mode);
  b.dataset.mode = mode;
  const chev = b.querySelector(".chev");
  if (chev) chev.title = bubbleModeTitle(mode);
  renderBubbleBody(b);
}

export function setBubbleText(b, text) {
  b._fullText = text || "";
  renderBubbleBody(b);
}

function renderBubbleBody(b) {
  const body = b.querySelector(".bubbleBody");
  if (body) body.textContent = clampText(b._fullText ?? body.textContent, b.dataset.mode || "normal");
}

export function bubbleEl(m, handlers = {}) {
  const b = document.createElement("div");
  const uid = m.id != null ? `msg-${m.id}` : `tmp-${++tmpBubbleSeq}`;
  b.dataset.testid = `bubble-${uid}`;
  b.dataset.role = m.role;
  b.dataset.type = m.type;
  if (m.id != null) b.dataset.msgId = String(m.id);
  b.className = `bubble ${m.role} ${m.type}`;
  const collapsible = m.type === "reasoning" || m.type === "toolcall";
  const mode = collapsible ? "collapsed" : "normal";
  b.classList.add(mode);
  b.dataset.mode = mode;
  if (m.type === "message") b.classList.add(m.inContext !== false ? "selected" : "deselected");
  const label = m.type === "message" ? m.role : typeLabels[m.type] || m.role;
  const isUser = m.role === "user";
  const showChk = m.type === "message" && isUser && isUserBubbleCheckable(state.settings);
  const showDel = isBubbleDeletable(state.settings) && (!isUser || isUserBubbleDeletable(state.settings));
  const attach = (m.attachments || [])
    .map((a) => `<div class="attachChip" data-testid="bubble-attachment">${ICONS.attach}<span data-testid="bubble-attachment-name">${esc(a.name)}</span></div>`)
    .join("");
  b.innerHTML = `
    <div class="bubbleHead" data-testid="bubble-head">
      <button class="iconBtn chev" data-testid="bubble-toggle-btn" title="${bubbleModeTitle(mode)}">${ICONS.chev}</button>
      <span class="role" data-testid="bubble-role">${esc(label)}</span>
      <span class="grow"></span>
      ${showChk ? `<input type="checkbox" class="chk" data-testid="bubble-context-chk" ${m.inContext !== false ? "checked" : ""} title="Im Kontext senden" />` : ""}
      <button class="iconBtn ttsBtn" data-testid="bubble-tts-btn" title="Vorlesen">${ICONS.tts}</button>
      <button class="iconBtn copyBtn" data-testid="bubble-copy-btn" title="Kopieren">${ICONS.copy}</button>
      ${showDel ? `<button class="iconBtn delBtn" data-testid="bubble-delete-btn" title="Löschen">${ICONS.x}</button>` : ""}
    </div>
    ${attach}
    <div class="bubbleBody" data-testid="bubble-body">${esc(m.text || "")}</div>`;
  setBubbleText(b, m.text || "");
  const chev = b.querySelector(".chev");
  if (chev)
    chev.onclick = () => setBubbleMode(b, nextBubbleMode(b.dataset.mode || "normal"));
  b.querySelector(".copyBtn").onclick = async (e) => {
    const btn = e.currentTarget;
    try {
      await navigator.clipboard.writeText(m.text || "");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = m.text || "";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    btn.classList.add("ok");
    setTimeout(() => btn.classList.remove("ok"), 900);
  };
  const chk = b.querySelector(".chk");
  if (chk)
    chk.onchange = () => {
      m.inContext = chk.checked;
      b.classList.toggle("selected", chk.checked);
      b.classList.toggle("deselected", !chk.checked);
      handlers.onToggleContext?.(m);
    };
  const delBtn = b.querySelector(".delBtn");
  if (delBtn) delBtn.onclick = () => handlers.onDelete?.(m);
  const tts = b.querySelector(".ttsBtn");
  tts.onclick = () => {
    if (!("speechSynthesis" in window)) return;
    if (speechSynthesis.speaking) {
      speechSynthesis.cancel();
      document.querySelectorAll(".ttsBtn.on").forEach((x) => x.classList.remove("on"));
      return;
    }
    const u = new SpeechSynthesisUtterance(m.text || "");
    u.lang = "de-DE";
    u.onend = () => tts.classList.remove("on");
    tts.classList.add("on");
    speechSynthesis.speak(u);
  };
  return b;
}
