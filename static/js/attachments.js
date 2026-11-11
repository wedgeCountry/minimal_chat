import { state } from "./state.js";
import { $, esc } from "./util.js";
import { ICONS } from "./icons.js";

const TEXT_MIME_TYPES = new Set([
  "application/json",
  "application/xml",
  "application/javascript",
  "application/x-yaml",
  "application/yaml",
]);
const TEXT_EXTENSIONS = new Set([
  "txt", "md", "markdown", "json", "csv", "tsv", "log", "xml", "yaml", "yml",
  "py", "js", "mjs", "cjs", "ts", "html", "htm", "css", "ini", "cfg", "conf",
  "env", "c", "h", "cpp", "java", "go", "rs", "sh", "sql", "toml",
]);
const MAX_TEXT_CHARS = 1000000;

export function isTextFile(name, type) {
  const t = (type || "").toLowerCase();
  if (t.startsWith("image/")) return false;
  if (t.startsWith("text/")) return true;
  if (TEXT_MIME_TYPES.has(t) || t.endsWith("+json") || t.endsWith("+xml")) return true;
  if (!t && name.includes(".")) {
    return TEXT_EXTENSIONS.has(name.split(".").pop().toLowerCase());
  }
  return false;
}

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
    } else if (isTextFile(f.name, f.type)) {
      const rd = new FileReader();
      rd.onload = () => {
        let text = String(rd.result);
        if (text.length > MAX_TEXT_CHARS) {
          text = text.slice(0, MAX_TEXT_CHARS) + "\n[… gekuertzt: Datei zu lang fuer Inline-Uebertragung]";
        }
        state.pendingAttachments.push({ name: f.name, type: f.type || "text/plain", text });
        renderAttachments();
      };
      rd.readAsText(f, "utf-8");
    } else {
      state.pendingAttachments.push({
        name: f.name,
        type: f.type || "application/octet-stream",
        text: `(Binaerdatei, ${f.size} Bytes – wird nicht als Text uebertragen)`,
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
