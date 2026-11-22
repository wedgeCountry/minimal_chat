import { defaultBoolSettings } from "./settingsKeys.js";

const _ss = typeof sessionStorage !== "undefined" ? sessionStorage : null;

export const state = {
  appName: "LeanChat",
  sessions: [],
  activeId: _ss?.getItem("leanchat.active") || null,
  // Gecachte History der aktiven Session (zu messagesSid gehoerend); Mutationen werden
  // lokal aus den Endpoint-Antworten uebernommen, Poll/Fetch bleibt Quelle der Wahrheit
  messages: [],
  messagesSid: null,
  // Session-Settings der aktiven Session (nur die bekannten Keys, siehe settingsKeys.js)
  sessionSettings: {},
  // LLM-Modell-Tiles (GET /api/settings/models, ohne api_key); default_model_id in settings
  llmModels: [],
  settings: {
    default_model_id: "",
    system_prompt: "",
    theme: "light",
    speech_mode: "server",
    ...defaultBoolSettings(),
  },
  streaming: false,
  pendingAttachments: [],
  speech: { systemStt: false, systemTts: false, serverStt: null, serverTts: null },
};

export const activeSession = () => state.sessions.find((s) => s.id === state.activeId) || null;

// Server liefert in_context (snake_case), die UI arbeitet mit inContext (camelCase).
export function normalizeMessage(m) {
  return { ...m, inContext: m.in_context != null ? m.in_context : m.inContext !== false };
}

export const normalizeMessages = (msgs) => (msgs || []).map(normalizeMessage);

export function setActiveId(id) {
  state.activeId = id;
  if (!_ss) return;
  if (id) _ss.setItem("leanchat.active", id);
  else _ss.removeItem("leanchat.active");
}
