import { esc } from "./util.js";
import { ICONS } from "./icons.js";
import { state } from "./state.js";
import { isBubbleDeletable, isBubbleCheckable, isBubbleSpeaker } from "./visibility.js";
import { BUBBLE_MODES, clampText, nextBubbleMode, bubbleModeTitle } from "./bubbleMode.js";

const typeLabels = { message: "", toolcall: "Tool-Call", reasoning: "Thinking", system: "System" };

let tmpBubbleSeq = 0;

const MIN_BUBBLE_WIDTH = 260;
const _ss = typeof sessionStorage !== "undefined" ? sessionStorage : null;

function _widthKey(id) {
  return `leanchat.bubblew-${id}`;
}

function _widthCap(b) {
  // nie breiter als die CSS-Maximalbreite der Rolle (z. B. system 88%)
  // und nie breiter als das Chat-Fenster
  const chat = document.getElementById("chat");
  const chatW = chat ? chat.getBoundingClientRect().width : 0;
  const cssMax = getComputedStyle(b).maxWidth;
  let cap = chatW > 0 ? chatW * 0.95 : Infinity;
  if (cssMax.endsWith("%")) cap = Math.min(cap, chatW > 0 ? (parseFloat(cssMax) / 100) * chatW : Infinity);
  else if (cssMax && cssMax !== "none") cap = Math.min(cap, parseFloat(cssMax));
  return cap;
}

function _applySavedWidth(b, m) {
  if (m.id == null || !_ss) return;
  const w = parseInt(_ss.getItem(_widthKey(m.id)), 10);
  if (w <= 0) return;
  b.style.maxWidth = `${w}px`;
  // im naechsten Frame (Element attached) gegen Rollen-CSS-Maxbreite clampen
  requestAnimationFrame(() => {
    if (b.isConnected) b.style.maxWidth = `${Math.min(w, _widthCap(b))}px`;
  });
}

function _makeResizable(b, m) {
  const handle = document.createElement("div");
  handle.className = "resizeHandle";
  handle.dataset.testid = "bubble-resize-handle";
  handle.title = "Breite per Drag anpassen";
  b.appendChild(handle);
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    e.stopPropagation();
    handle.setPointerCapture(e.pointerId);
    handle.classList.add("dragging");
    const startX = e.clientX;
    const startW = b.getBoundingClientRect().width;
    // Griff sitzt unten rechts: Drag nach rechts = breiter, nach links = schmaler
    const maxW = _widthCap(b);
    const onMove = (ev) => {
      const w = Math.min(Math.max(startW + (ev.clientX - startX), MIN_BUBBLE_WIDTH), maxW);
      b.style.maxWidth = `${Math.round(w)}px`;
    };
    const onUp = (ev) => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.classList.remove("dragging");
      onMove(ev);
      if (m.id != null && _ss) _ss.setItem(_widthKey(m.id), b.style.maxWidth);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
  });
}

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

export function bubbleEl(m, handlers = {}, opts = {}) {
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
  const showChk = m.type === "message" && isBubbleCheckable(state.settings);
  const showDel = isBubbleDeletable(state.settings);
  const showTts = isBubbleSpeaker(state.settings);
  const showResend = m.role === "user" && m.type === "message" && opts.showResend === true;
  const attach = (m.attachments || [])
    .map((a) => `<div class="attachChip" data-testid="bubble-attachment">${ICONS.attach}<span data-testid="bubble-attachment-name">${esc(a.name)}</span></div>`)
    .join("");
  b.innerHTML = `
    <div class="bubbleHead" data-testid="bubble-head">
      ${showDel ? `<button class="iconBtn delBtn" data-testid="bubble-delete-btn" title="Löschen">${ICONS.x}</button>` : ""}
      <span class="role" data-testid="bubble-role">${esc(label)}</span>
      <span class="grow"></span>
      ${showChk ? `<input type="checkbox" class="chk" data-testid="bubble-context-chk" ${m.inContext !== false ? "checked" : ""} title="Im Kontext senden" />` : ""}
      ${showResend ? `<button class="iconBtn resendBtn" data-testid="bubble-resend-btn" title="Erneut senden">${ICONS.refresh}</button>` : ""}
      ${showTts ? `<button class="iconBtn ttsBtn" data-testid="bubble-tts-btn" title="Vorlesen">${ICONS.tts}</button>` : ""}
      <button class="iconBtn copyBtn" data-testid="bubble-copy-btn" title="Kopieren">${ICONS.copy}</button>
      <button class="iconBtn chev" data-testid="bubble-toggle-btn" title="${bubbleModeTitle(mode)}">${ICONS.chev}</button>
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
  const resendBtn = b.querySelector(".resendBtn");
  if (resendBtn) resendBtn.onclick = () => handlers.onResend?.(m);
  _applySavedWidth(b, m);
  _makeResizable(b, m);
  const tts = b.querySelector(".ttsBtn");
  if (tts)
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
