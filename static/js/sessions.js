import { api } from "./api.js";
import { activeSession, setActiveId, state } from "./state.js";
import { $, esc } from "./util.js";
import { ICONS } from "./icons.js";
import { confirmModal } from "./confirm.js";

export const changed = () => document.dispatchEvent(new CustomEvent("leanchat:changed"));

const selected = () => document.dispatchEvent(new CustomEvent("leanchat:session-selected"));

export function sortedSessions() {
  return [...state.sessions].sort((a, b) => b.ts - a.ts);
}

export async function loadSessions() {
  state.sessions = await api.get("/sessions");
  if (!state.activeId || !activeSession()) setActiveId(state.sessions[0]?.id || null);
}

export function renderSessions() {
  const box = $("sessions");
  box.innerHTML = "";
  const nt = document.createElement("div");
  nt.className = "tile";
  nt.id = "newTile";
  nt.dataset.testid = "new-session-tile";
  nt.innerHTML = `${ICONS.plus}<span data-testid="new-session-label">Neue Session</span>`;
  nt.onclick = () => newSession(true);
  box.appendChild(nt);
  for (const s of sortedSessions()) {
    const t = document.createElement("div");
    t.className = "tile" + (s.id === state.activeId ? " active" : "");
    t.dataset.testid = `session-tile-${s.id}`;
    t.dataset.sessionId = s.id;
    t.innerHTML = `
      <div class="sessionRow" data-testid="session-row-${s.id}">
        <span class="sessionName" data-name="${s.id}" data-testid="session-name-${s.id}">${esc(s.name)}</span>
        <button class="iconBtn editBtn" data-testid="session-rename-btn-${s.id}" title="Umbenennen">${ICONS.edit}</button>
        <button class="iconBtn delBtn" data-testid="session-delete-btn-${s.id}" title="Löschen">${ICONS.trash}</button>
      </div>`;
    t.onclick = (e) => {
      if (e.target.closest("button")) return;
      openSession(s.id);
    };
    t.querySelector(".editBtn").onclick = () => renameSession(s.id);
    t.querySelector(".delBtn").onclick = () => deleteSession(s.id);
    box.appendChild(t);
  }
}

export async function newSession(open = true) {
  const s = await api.post("/sessions", { name: "Neue Session" });
  state.sessions.unshift(s);
  if (open) {
    setActiveId(s.id);
    selected();
  }
  changed();
}

export function openSession(id) {
  setActiveId(id);
  selected();
  changed();
}

export async function renameSession(id) {
  const s = state.sessions.find((x) => x.id === id);
  if (!s) return;
  const nameEl = document.querySelector(`[data-name="${id}"]`);
  if (!nameEl) return;
  const inp = document.createElement("input");
  inp.dataset.testid = `session-rename-input-${id}`;
  inp.value = s.name;
  nameEl.replaceChildren(inp);
  inp.focus();
  inp.select();
  let finished = false;
  const done = async (ok) => {
    if (finished) return; // Escape (done(false)) darf nicht durch das anschliessende blur (done(true)) ueberschrieben werden
    finished = true;
    const name = inp.value.trim();
    if (ok && name && name !== s.name) {
      await api.patch(`/sessions/${id}`, { name });
      await loadSessions();
    }
    changed();
  };
  inp.onkeydown = (e) => {
    if (e.key === "Enter") done(true);
    if (e.key === "Escape") done(false);
    e.stopPropagation();
  };
  inp.onblur = () => done(true);
}

export async function deleteSession(id) {
  const s = state.sessions.find((x) => x.id === id);
  if (!s) return;
  const ok = await confirmModal({ title: "Session löschen", text: `Session „${s.name}“ wirklich löschen?` });
  if (!ok) return;
  await api.del(`/sessions/${id}`);
  state.sessions = state.sessions.filter((x) => x.id !== id);
  if (state.activeId === id) setActiveId(state.sessions[0]?.id || null);
  changed();
}
