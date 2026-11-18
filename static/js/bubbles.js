import { esc, isFinePointer } from "./util.js";
import { ICONS } from "./icons.js";
import { state } from "./state.js";
import { isBubbleDeletable, isBubbleContextToggleable, isBubbleSpeaker, isToolbarMinimal } from "./visibility.js";
import { controlsVisible, speak, isSpeaking, stopSpeech } from "./ttsDetectionService.js";
import { showError } from "./confirm.js";
import { BUBBLE_MODES, clampText, isClamped, nextBubbleMode, bubbleModeTitle, defaultBubbleMode } from "./bubbleMode.js";

const typeLabels = { message: "", toolcall: "Tool-Call", toolresult: "Tool-Result", reasoning: "Thinking", system: "System" };

let tmpBubbleSeq = 0;

export function setBubbleMode(b, mode) {
  // Modus-Wechsel aendert die Bubble-Hoehe sofort; schrumpft sie, clamped der Browser
  // scrollTop ans neue Maximum (Sprung ans untere Ende). Deshalb scrollTop vorab
  // merken und nachtraeglich um die Verschiebung der oberen Viewport-Kante korrigieren.
  const chat = typeof b.closest === "function" ? b.closest("#chat") : null;
  const prevTop = chat ? chat.scrollTop : 0;
  const prevEdge = chat ? prevTop + (b.getBoundingClientRect().bottom - chat.getBoundingClientRect().top) : 0;
  const prevH = chat ? b.getBoundingClientRect().height : 0;
  for (const m of BUBBLE_MODES) b.classList.remove(m);
  b.classList.add(mode);
  b.dataset.mode = mode;
  const chev = b.querySelector(".chev");
  if (chev) chev.title = bubbleModeTitle(mode);
  renderBubbleBody(b); // liest body.scrollHeight -> Layout ist danach synchron aktualisiert
  if (chat) {
    const shrink = prevH - b.getBoundingClientRect().height; // >0 beim Einklappen
    let shift = 0;
    if (shrink >= 0) {
      // Die Kollaps-Verschiebung sitzt an der unteren Bubble-Kante: solange die obere
      // Viewport-Kante innerhalb der (kollabierten) Bubble bleibt, aendert sich nichts.
      shift = Math.min(Math.max(prevTop - (prevEdge - shrink), 0), shrink);
    } else if (prevTop > prevEdge) {
      shift = shrink; // Bubble waechst oberhalb des Viewports -> Inhalt darunter rueckt nach unten
    }
    chat.scrollTop = prevTop - shift;
  }
}

export function setBubbleText(b, text) {
  b._fullText = text || "";
  renderBubbleBody(b);
}

function renderBubbleBody(b) {
  const body = b.querySelector(".bubbleBody");
  if (!body) return;
  const mode = b.dataset.mode || "normal";
  const full = b._fullText ?? body.textContent;
  // Tool-Argumente/-Ergebnisse kommen als JSON-String-Literale und behalten
  // literale "\n" - fuer die Anzeige und Zeilen-Kuerzung als echte Umbrueche behandeln
  const display =
    b.dataset.type === "toolcall" || b.dataset.type === "toolresult" ? full.replace(/\\n/g, "\n") : full;
  body.textContent = clampText(display, mode);
  // GUI-basiert gekuerzt, wenn der gerenderte Inhalt die Zeilenkappe
  // (CSS line-clamp) ueberschreitet - unabhaengig von Textzeilenumbruechen
  const clipped = body.scrollHeight > body.clientHeight + 1;
  body.classList.toggle("clamped", clipped || isClamped(display, mode));
  b._normalTruncated = isClamped(display, "normal") || (mode === "normal" && clipped);
}

// Inline-Edit: der Bubble-Body wird durch ein Textarea + Speichern/Abbrechen ersetzt.
export function enterBubbleEdit(b, text) {
  const body = b.querySelector(".bubbleBody");
  if (!body || b.dataset.editing === "true") return null;
  b.dataset.editing = "true";
  body.classList.remove("clamped");
  // Hoehe des Bodys merken, damit die Bubble im Edit-Modus nicht springt
  const bodyH = body.getBoundingClientRect().height;
  // kein Whitespace zwischen den Tags: .bubbleBody hat white-space:pre-wrap
  body.innerHTML = `<div class="editRow"><textarea class="editInput" data-testid="bubble-edit-input" rows="1"></textarea><button class="iconBtn editCancelBtn" data-testid="bubble-edit-cancel-btn" title="Abbrechen">${ICONS.x}</button></div>`;
  const textarea = body.querySelector(".editInput");
  textarea.value = text ?? b._fullText ?? "";
  const grow = () => {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(Math.max(textarea.scrollHeight, bodyH), 180) + "px";
  };
  textarea.addEventListener("input", grow);
  grow();
  return { textarea, cancelBtn: body.querySelector(".editCancelBtn") };
}

export function exitBubbleEdit(b) {
  if (b.dataset.editing !== "true") return;
  delete b.dataset.editing;
  renderBubbleBody(b);
}

export function bubbleEl(m, handlers = {}, opts = {}) {
  const b = document.createElement("div");
  b._msg = m; // aktuelle Nachricht; renderChat aktualisiert sie bei wiederverwendeten Bubbles
  b._handlers = handlers;
  const uid = m.id != null ? `msg-${m.id}` : `tmp-${++tmpBubbleSeq}`;
  b.dataset.testid = `bubble-${uid}`;
  b.dataset.role = m.role;
  b.dataset.type = m.type;
  if (m.id != null) b.dataset.msgId = String(m.id);
  b.className = `bubble ${m.role} ${m.type}`;
  const mode = defaultBubbleMode(m.type);
  b.classList.add(mode);
  b.dataset.mode = mode;
  if (m.type !== "reasoning") b.classList.add(m.inContext !== false ? "selected" : "deselected");
  const label = m.type === "message" ? m.role : typeLabels[m.type] || m.role;
  const showChk = isBubbleContextToggleable(m, state.settings);
  const showDel = isBubbleDeletable(state.settings);
  const showTts = bubbleShowTts();
  // Edit/Resend existieren fuer ALLE User-Messages im DOM (nur per display sichtbar), damit
  // sie nach dem Loeschen der letzten User-Message an der neuen letzten Bubble sofort da sind
  const canEditResend = m.role === "user" && m.type === "message";
  const showResend = canEditResend && opts.showResend === true;
  const showEdit = canEditResend && opts.showEdit === true;
  const attach = (m.attachments || [])
    .map((a) => `<div class="attachChip" data-testid="bubble-attachment">${ICONS.attach}<span data-testid="bubble-attachment-name">${esc(a.name)}</span></div>`)
    .join("");
  b.innerHTML = `
    <div class="bubbleHead" data-testid="bubble-head">
      ${showDel ? `<button class="iconBtn delBtn" data-testid="bubble-delete-btn" title="Löschen">${ICONS.x}</button>` : ""}
      <span class="role" data-testid="bubble-role">${esc(label)}</span>
      <span class="grow"></span>
      ${showChk ? `<input type="checkbox" class="chk" data-testid="bubble-context-chk" ${m.inContext !== false ? "checked" : ""} title="Im Kontext senden" />` : ""}
      ${canEditResend ? `<button class="iconBtn editBtn${showEdit ? "" : " u-hidden"}" data-testid="bubble-edit-btn" title="Bearbeiten">${ICONS.edit}</button>` : ""}
      ${canEditResend ? `<button class="iconBtn resendBtn${showResend ? "" : " u-hidden"}" data-testid="bubble-resend-btn" title="Erneut senden">${ICONS.refresh}</button>` : ""}
      ${showTts ? `<button class="iconBtn ttsBtn" data-testid="bubble-tts-btn" title="Vorlesen">${ICONS.tts}</button>` : ""}
      <button class="iconBtn copyBtn" data-testid="bubble-copy-btn" title="Kopieren">${ICONS.copy}</button>
      <button class="iconBtn chev" data-testid="bubble-toggle-btn" title="${bubbleModeTitle(mode)}">${ICONS.chev}</button>
    </div>
    ${attach}
    <div class="bubbleBody" data-testid="bubble-body">${esc(m.text || "")}</div>`;
  setBubbleText(b, m.text || "");
  const chev = b.querySelector(".chev");
  if (chev)
    chev.onclick = () => setBubbleMode(b, nextBubbleMode(b.dataset.mode || "normal", b._normalTruncated));
  const body = b.querySelector(".bubbleBody");
  if (body)
    body.addEventListener("click", () => {
      // Klick auf gekuerzten Text ([...]) schaltet wie der Chevron weiter. Im Minimalismus auf
      // Touch-Geraeten uebernimmt stattdessen onBubbleTap in chat.js jeden Tap (jede Bubble,
      // nicht nur gekuerzte) und achtet dabei auf Doppel-Tap (Kontextmenue) und Scroll-Gesten.
      if (isToolbarMinimal(state.settings) && !isFinePointer()) return; // Touch: Doppel-Tap/Tap behandelt onBubbleTap in chat.js
      if (body.classList.contains("clamped")) setBubbleMode(b, nextBubbleMode(b.dataset.mode || "normal", b._normalTruncated));
    });
  b.querySelector(".copyBtn").onclick = () => copyBubbleText(b);
  const chk = b.querySelector(".chk");
  if (chk)
    chk.onchange = () => {
      b._msg.inContext = chk.checked;
      b.classList.toggle("selected", chk.checked);
      b.classList.toggle("deselected", !chk.checked);
      handlers.onToggleContext?.(b._msg);
    };
  const delBtn = b.querySelector(".delBtn");
  if (delBtn) wireDelButton(b, delBtn);
  const resendBtn = b.querySelector(".resendBtn");
  if (resendBtn) resendBtn.onclick = () => handlers.onResend?.(b._msg);
  const editBtn = b.querySelector(".editBtn");
  if (editBtn) editBtn.onclick = () => handlers.onEdit?.(b._msg, b);
  const collapseBtn = document.createElement("button");
  collapseBtn.className = "iconBtn collapseBtn";
  collapseBtn.dataset.testid = "bubble-collapse-btn";
  collapseBtn.title = "Einklappen";
  collapseBtn.innerHTML = ICONS.chev;
  collapseBtn.onclick = () => setBubbleMode(b, "collapsed");
  b.appendChild(collapseBtn);
  const tts = b.querySelector(".ttsBtn");
  if (tts) wireTtsButton(b, tts);
  return b;
}

function wireDelButton(b, del) {
  del.onclick = () => b._handlers?.onDelete?.(b._msg);
}

// Bubble-Text in die Zwischenablage (Toolbar-Button und Kontextmenue); true bei Erfolg
export async function copyBubbleText(b) {
  const text = b._msg?.text || "";
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    await showError("Kopieren fehlgeschlagen – Zwischenablage nicht verfügbar.");
    return false;
  }
  const btn = b.querySelector(".copyBtn");
  if (btn) {
    btn.classList.add("ok");
    setTimeout(() => btn.classList.remove("ok"), 900);
  }
  return true;
}

// Loeschen-Button (Muelleimer) folgt dem Setting auch bei wiederverwendeten Bubbles
export function syncBubbleDelete(b) {
  const show = isBubbleDeletable(state.settings);
  let del = b.querySelector(".delBtn");
  if (show && !del) {
    del = document.createElement("button");
    del.className = "iconBtn delBtn";
    del.dataset.testid = "bubble-delete-btn";
    del.title = "Löschen";
    del.innerHTML = ICONS.x;
    wireDelButton(b, del);
    const head = b.querySelector(".bubbleHead");
    if (head) head.insertBefore(del, head.firstChild);
  } else if (!show && del) {
    del.remove();
    del = null;
  }
  return del;
}

export function bubbleShowTts() {
  return isBubbleSpeaker(state.settings) && controlsVisible("tts");
}

function wireTtsButton(b, tts) {
  tts.onclick = async () => {
    if (isSpeaking()) {
      stopSpeech();
      return;
    }
    await speak(b._msg?.text || "", tts, { onError: showError });
  };
}

export function syncBubbleTts(b) {
  const show = bubbleShowTts();
  let tts = b.querySelector(".ttsBtn");
  if (show && !tts) {
    tts = document.createElement("button");
    tts.className = "iconBtn ttsBtn";
    tts.dataset.testid = "bubble-tts-btn";
    tts.title = "Vorlesen";
    tts.innerHTML = ICONS.tts;
    wireTtsButton(b, tts);
    const head = b.querySelector(".bubbleHead");
    if (head) head.insertBefore(tts, b.querySelector(".copyBtn"));
  } else if (!show && tts) {
    tts.remove();
    tts = null;
  }
  return tts;
}
