import { api } from "./api.js";
import { activeSession, state } from "./state.js";
import { $ } from "./util.js";
import { SESSION_SETTING_KEYS } from "./settingsKeys.js";
import { loadModels } from "./models.js";

// Effektiver System-Prompt der aktiven Session: nicht-leerer Session-Prompt gewinnt,
// sonst der globale Settings-Prompt (Backend-Pendant: resolve_system_prompt in app/services/settings.py)
export function resolveSystemPrompt(settings, sessionSettings) {
  const sessionPrompt = (sessionSettings?.system_prompt || "").trim();
  return sessionPrompt || settings.system_prompt || "";
}

export function pickSessionSettings(stored) {
  return Object.fromEntries(SESSION_SETTING_KEYS.map((k) => [k, stored?.[k] || ""]));
}

function fillModelSelect() {
  const sel = $("sessModel");
  const models = state.llmModels || [];
  const defaultId = state.settings.default_model_id || "";
  const def = models.find((m) => String(m.id) === defaultId);
  sel.innerHTML = "";
  const optDefault = document.createElement("option");
  optDefault.value = "";
  optDefault.textContent = def ? `Standard (${def.provider || def.model})` : "Standard-Modell";
  optDefault.dataset.testid = "session-model-option-default";
  sel.appendChild(optDefault);
  for (const m of models) {
    const o = document.createElement("option");
    o.value = String(m.id);
    o.textContent = `${m.provider || m.model} — ${m.model}${m.host ? " @ " + m.host : ""}`;
    o.dataset.testid = `session-model-option-${m.id}`;
    sel.appendChild(o);
  }
  sel.value = state.sessionSettings.model_id || "";
}

function closeSessionSettings() {
  $("sessionOverlay").classList.remove("open");
}

export async function openSessionSettings() {
  const s = activeSession();
  if (!s) return;
  // Beim Oeffnen immer frisch vom Server laden: Abbrechen heisst dann ohne weiteren Code "keine Aenderungen"
  await loadModels();
  state.sessionSettings = pickSessionSettings(await api.get(`/sessions/${s.id}/settings`));
  $("sessSystemPrompt").value = state.sessionSettings.system_prompt || "";
  fillModelSelect();
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
    const body = pickSessionSettings({ system_prompt: $("sessSystemPrompt").value, model_id: $("sessModel").value });
    state.sessionSettings = pickSessionSettings(await api.put(`/sessions/${s.id}/settings`, body));
    closeSessionSettings();
    document.dispatchEvent(new CustomEvent("leanchat:changed"));
  };
}
