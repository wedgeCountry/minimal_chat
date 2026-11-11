import { esc } from "./util.js";
import { ICONS } from "./icons.js";

const typeLabels = { message: "", toolcall: "Tool-Call", reasoning: "Thinking", system: "System" };

export function bubbleEl(m, handlers = {}) {
  const b = document.createElement("div");
  b.className = `bubble ${m.role} ${m.type}`;
  const collapsible = m.type === "reasoning" || m.type === "toolcall";
  if (collapsible) b.classList.add("collapsed");
  else b.classList.add("expanded");
  if (m.type === "message") b.classList.add(m.inContext !== false ? "selected" : "deselected");
  const label = m.type === "message" ? m.role : typeLabels[m.type] || m.role;
  const attach = (m.attachments || [])
    .map((a) => `<div class="attachChip">${ICONS.attach}${esc(a.name)}</div>`)
    .join("");
  b.innerHTML = `
    <div class="bubbleHead">
      ${collapsible ? `<button class="iconBtn chev" title="Ein-/Ausklappen">${ICONS.chev}</button>` : ""}
      <span class="role">${esc(label)}</span>
      <span class="grow"></span>
      ${m.type === "message" ? `<input type="checkbox" class="chk" ${m.inContext !== false ? "checked" : ""} title="Im Kontext senden" />` : ""}
      <button class="iconBtn ttsBtn" title="Vorlesen">${ICONS.tts}</button>
      <button class="iconBtn copyBtn" title="Kopieren">${ICONS.copy}</button>
      <button class="iconBtn delBtn" title="Löschen">${ICONS.x}</button>
    </div>
    ${attach}
    <div class="bubbleBody">${esc(m.text || "")}</div>`;
  const chev = b.querySelector(".chev");
  if (chev)
    chev.onclick = () => {
      b.classList.toggle("collapsed");
      b.classList.toggle("expanded");
    };
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
  b.querySelector(".delBtn").onclick = () => handlers.onDelete?.(m);
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
