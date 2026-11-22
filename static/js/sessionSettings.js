import { api } from "./api.js";
import { activeSession, state } from "./state.js";
import { $ } from "./util.js";
import { SESSION_SETTING_KEYS } from "./settingsKeys.js";

// Effektiver System-Prompt der aktiven Session: nicht-leerer Session-Prompt gewinnt,
// sonst der globale Settings-Prompt (Backend-Pendant: resolve_system_prompt in app/services/settings.py)
export function resolveSystemPrompt(settings, sessionSettings) {
  const sessionPrompt = (sessionSettings?.system_prompt || "").trim();
  return sessionPrompt || settings.system_prompt || "";
}

export function pickSessionSettings(stored) {
  return Object.fromEntries(SESSION_SETTING_KEYS.map((k) => [k, stored?.[k] || ""]));
}

function closeSessionSettings() {
  $("sessionOverlay").classList.remove("open");
}

export async function openSessionSettings() {
  const s = activeSession();
  if (!s) return;
  // Beim Oeffnen immer frisch vom Server laden: Abbrechen heisst dann ohne weiteren Code "keine Aenderungen"
  state.sessionSettings = pickSessionSettings(await api.get(`/sessions/${s.id}/settings`));
  $("sessSystemPrompt").value = state.sessionSettings.system_prompt || "";
  $("sessionOverlay").classList.add("open");
}

export function initSessionSettings() {
  $("sessionSettingsBtn").onclick = () => openSessionSettings();
  $("sessSettingsCancel").onclick = () => closeSessionSettings();
  $("sessionOverlay").addEventListener("click", (e) => {
    if (e.target === $("sessionOverlay")) closeSessionSettings();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("sessionOverlay").classList.contains("open")) closeSessionSettings();
  });
  $("sessSettingsSave").onclick = async () => {
    const s = activeSession();
    if (!s) return;
    const body = pickSessionSettings({ system_prompt: $("sessSystemPrompt").value });
    state.sessionSettings = pickSessionSettings(await api.put(`/sessions/${s.id}/settings`, body));
    closeSessionSettings();
    document.dispatchEvent(new CustomEvent("leanchat:changed"));
  };
}
