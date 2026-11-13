import { api } from "./api.js";
import { state } from "./state.js";
import { $ } from "./util.js";
import { applyTheme } from "./theme.js";
import { BOOL_SETTING_KEYS } from "./settingsKeys.js";
import { SPEECH_MODES, statusLabel, refreshSpeechAvailability } from "./ttsDetectionService.js";

const CHECK_IDS = {
  bubbles_deletable: "setDeletableAll",
  bubbles_checkable: "setCheckable",
  bubbles_speaker: "setSpeaker",
  show_system_prompt: "setShowSystem",
  show_tool_output: "setShowTool",
  show_reasoning: "setShowReasoning",
  show_file_button: "setShowFile",
  show_image_button: "setShowImage",
};

export function buildBaseUrl(host, port) {
  const h = (host || "").trim();
  if (!h) return "";
  const p = (port || "").trim();
  return `http://${h}${p ? ":" + p : ""}/v1`;
}

export async function loadSettings() {
  state.settings = { ...state.settings, ...(await api.get("/settings")) };
  applyTheme();
}

function selectedSpeechMode() {
  const r = document.querySelector('input[name="speechMode"]:checked');
  return r && SPEECH_MODES.includes(r.value) ? r.value : "server";
}

export async function updateSpeechStatus() {
  const status = $("speechStatus");
  if (!status) return;
  const mode = selectedSpeechMode();
  status.textContent = "Prüfe…";
  status.className = "connStatus";
  await refreshSpeechAvailability();
  const label = statusLabel(mode);
  status.textContent = label.text;
  status.className = "connStatus" + (label.cls ? " " + label.cls : "");
}

export function initSettings() {
  $("setCancel").onclick = () => $("overlay").classList.remove("open");
  document.querySelectorAll('input[name="speechMode"]').forEach((r) => {
    r.addEventListener("change", () => updateSpeechStatus());
  });
  $("setTestConn").onclick = async () => {
    const btn = $("setTestConn");
    const status = $("connStatus");
    btn.disabled = true;
    status.textContent = "Teste Verbindung…";
    status.className = "connStatus";
    try {
      const res = await api.post("/settings/test", {
        base: $("setBase").value.trim(),
        api_key: $("setKey").value.trim() || undefined,
      });
      if (res.ok) {
        status.textContent = "Erreichbar ✓ " + (res.detail || "");
        status.classList.add("ok");
      } else {
        status.textContent = "Nicht erreichbar: " + (res.detail || "unbekannter Fehler");
        status.classList.add("err");
      }
    } catch (err) {
      status.textContent = "Nicht erreichbar: " + err.message;
      status.classList.add("err");
    } finally {
      btn.disabled = false;
    }
  };
  $("overlay").addEventListener("click", (e) => {
    if (e.target === $("overlay")) $("overlay").classList.remove("open");
  });
  const updateBasePreview = () => {
    $("setBase").value = buildBaseUrl($("setHost").value, $("setPort").value);
  };
  $("setHost").addEventListener("input", updateBasePreview);
  $("setPort").addEventListener("input", updateBasePreview);
  $("setSave").onclick = async () => {
    const body = {
      base: $("setBase").value.trim(),
      host: $("setHost").value.trim(),
      port: $("setPort").value.trim(),
      model: $("setModel").value.trim(),
      system_prompt: $("setSystemPrompt").value,
      theme: $("setTheme").value,
      speech_mode: selectedSpeechMode(),
    };
    for (const key of BOOL_SETTING_KEYS) body[key] = $(CHECK_IDS[key]).checked;
    if ($("setKey").value.trim()) body.api_key = $("setKey").value.trim();
    state.settings = { ...state.settings, ...(await api.put("/settings", body)) };
    $("setKey").value = "";
    await refreshSpeechAvailability();
    applyTheme();
    $("overlay").classList.remove("open");
    document.dispatchEvent(new CustomEvent("leanchat:changed"));
  };
}

export function openSettings(tab = "general") {
  $("settingsGeneral").hidden = tab !== "general";
  $("settingsLlm").hidden = tab !== "llm";
  $("settings-title").textContent = tab === "llm" ? "LLM-Einstellungen" : "Einstellungen";
  $("setHost").value = state.settings.host || "";
  $("setPort").value = state.settings.port || "";
  $("setBase").value = state.settings.host
    ? buildBaseUrl(state.settings.host, state.settings.port)
    : state.settings.base;
  $("setKey").value = "";
  $("setModel").value = state.settings.model;
  $("setSystemPrompt").value = state.settings.system_prompt || "";
  $("setTheme").value = state.settings.theme;
  for (const key of BOOL_SETTING_KEYS) $(CHECK_IDS[key]).checked = state.settings[key] !== false;
  const mode = SPEECH_MODES.includes(state.settings.speech_mode) ? state.settings.speech_mode : "server";
  document.querySelectorAll('input[name="speechMode"]').forEach((r) => {
    r.checked = r.value === mode;
  });
  $("overlay").classList.add("open");
  updateSpeechStatus();
}
