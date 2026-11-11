import { state } from "./state.js";
import { $, esc } from "./util.js";
import { ICONS } from "./icons.js";

export function addAttachments(files) {
  for (const f of files) {
    if (!f) continue;
    if (f.type.startsWith("image/")) {
      const rd = new FileReader();
      rd.onload = () => {
        state.pendingAttachments.push({ name: f.name, type: f.type, data: rd.result });
        renderAttachments();
      };
      rd.readAsDataURL(f);
    } else if (f.size < 200000) {
      const rd = new FileReader();
      rd.onload = () => {
        state.pendingAttachments.push({ name: f.name, type: f.type, text: String(rd.result) });
        renderAttachments();
      };
      rd.readAsText(f);
    } else {
      state.pendingAttachments.push({
        name: f.name,
        type: f.type || "application/octet-stream",
        text: "(Datei zu groß für Inline-Übertragung)",
      });
      renderAttachments();
    }
  }
}

export function renderAttachments() {
  const box = $("attachments");
  box.innerHTML = "";
  state.pendingAttachments.forEach((a, i) => {
    const el = document.createElement("div");
    el.className = "att";
    el.dataset.testid = `attachment-chip-${i}`;
    el.innerHTML = `${a.data ? `<img src="${a.data}" alt="" data-testid="attachment-image-${i}">` : ""}<span data-testid="attachment-name-${i}">${esc(a.name)}</span><button data-testid="attachment-remove-btn-${i}" title="Entfernen">${ICONS.x}</button>`;
    el.querySelector("button").onclick = () => {
      state.pendingAttachments.splice(i, 1);
      renderAttachments();
    };
    box.appendChild(el);
  });
}
