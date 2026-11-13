import { api } from "./api.js";
import { state } from "./state.js";
import { $, esc } from "./util.js";
import { ICONS } from "./icons.js";

export function addAttachments(files) {
  for (const f of files) {
    if (!f) continue;
    state.pendingAttachments.push({ name: f.name, type: f.type || "application/octet-stream", file: f });
  }
  renderAttachments();
}

// Laedt die angehaengten Rohdateien zur Session hoch (Multipart, ohne Base64-Overhead);
// das Lesen/Dekodieren passiert serverseitig (POST /api/sessions/{sid}/attachments).
// Liefert References.
export async function uploadPendingAttachments(sid) {
  const refs = [];
  for (const a of state.pendingAttachments.splice(0)) {
    if (a.file) {
      const form = new FormData();
      form.append("file", a.file, a.name);
      const res = await api.postForm(`/sessions/${sid}/attachments`, form);
      refs.push({ id: res.id, name: res.name, type: res.mime });
    } else {
      refs.push(a);
    }
  }
  renderAttachments();
  return refs;
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
