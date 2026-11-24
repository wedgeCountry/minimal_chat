import { api } from "./api.js";
import { state } from "./state.js";
import { $ } from "./util.js";
import { applyTheme } from "./theme.js";
import { BOOL_SETTING_KEYS } from "./settingsKeys.js";
import { SPEECH_MODES, statusLabel, refreshSpeechAvailability } from "./ttsDetectionService.js";
import { renderModelTiles } from "./models.js";

const CHECK_IDS = {
  bubbles_deletable: "setDeletableAll",
  bubbles_checkable: "setCheckable",
  bubbles_speaker: "setSpeaker",
  bubbles_minimal: "setMinimalism",
  show_system_prompt: "setShowSystem",
  show_tool_output: "setShowTool",
  show_reasoning: "setShowReasoning",
  show_file_button: "setShowFile",
  show_image_button: "setShowImage",
  keep_keyboard_open: "setKeepKeyboard",
};

export async function loadSettings() {
  state.settings = { ...state.settings, ...(await api.get("/settings")) };
  applyTheme();
}

function selectedSpeechMode() {
  const r = document.querySelector('input[name="speechMode"]:checked');
  return r && SPEECH_MODES.includes(r.value) ? r.value : "server";
}

function normalizedSpeechMode() {
  return SPEECH_MODES.includes(state.settings.speech_mode) ? state.settings.speech_mode : "server";
}

function syncSpeechModeRadios() {
  const mode = normalizedSpeechMode();
  document.querySelectorAll('input[name="speechMode"]').forEach((r) => {
    r.checked = r.value === mode;
  });
}

// Stand beim Oeffnen des Overlays; Schliessen ohne Speichern stellt ihn wieder her
let openedSpeechMode = "server";

function closeSettings() {
  state.settings.speech_mode = openedSpeechMode;
  syncSpeechModeRadios();
  document.dispatchEvent(new CustomEvent("leanchat:speech-availability"));
  $("overlay").classList.remove("open");
}

export async function updateSpeechStatus() {
  const status = $("speechStatus");
  if (!status) return;
  const mode = selectedSpeechMode();
  // Auswahl sofort in den State uebernehmen, sonst schalten micBtn/Speaker erst beim Speichern um
  // (refreshSpeechAvailability feuert leanchat:speech-availability); persistiert wird erst bei Speichern
  state.settings.speech_mode = mode;
  status.textContent = "Prüfe…";
  status.className = "connStatus";
  await refreshSpeechAvailability();
  const label = statusLabel(mode);
  status.textContent = label.text;
  status.className = "connStatus" + (label.cls ? " " + label.cls : "");
}

export function initSettings() {
  $("setCancel").onclick = () => closeSettings();
  document.querySelectorAll('input[name="speechMode"]').forEach((r) => {
    r.addEventListener("change", () => updateSpeechStatus());
  });
  $("overlay").addEventListener("click", (e) => {
    if (e.target === $("overlay")) closeSettings();
  });
  $("setSave").onclick = async () => {
    const body = {
      system_prompt: $("setSystemPrompt").value,
      theme: $("setTheme").value,
      speech_mode: selectedSpeechMode(),
    };
    for (const key of BOOL_SETTING_KEYS) body[key] = $(CHECK_IDS[key]).checked;
    state.settings = { ...state.settings, ...(await api.put("/settings", body)) };
    await refreshSpeechAvailability();
    applyTheme();
    $("overlay").classList.remove("open");
    document.dispatchEvent(new CustomEvent("leanchat:changed"));
  };
}

export function openSettings(tab = "general") {
  $("settingsGeneral").hidden = tab !== "general";
  $("settingsLlm").hidden = tab !== "llm";
  // Speichern/Abbrechen gelten nur fuer den Allgemein-Tab; der LLM-Tab arbeitet mit Tiles + eigenem Modal
  $("settingsActions").hidden = tab !== "general";
  $("settings-title").textContent = tab === "llm" ? "LLM-Einstellungen" : "Einstellungen";
  if (tab === "llm") renderModelTiles();
  $("setSystemPrompt").value = state.settings.system_prompt || "";
  $("setTheme").value = state.settings.theme;
  for (const key of BOOL_SETTING_KEYS) $(CHECK_IDS[key]).checked = state.settings[key] !== false;
  openedSpeechMode = normalizedSpeechMode();
  syncSpeechModeRadios();
  $("overlay").classList.add("open");
  updateSpeechStatus();
}
