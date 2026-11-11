import { api } from "./api.js";
import { state } from "./state.js";
import { $ } from "./util.js";
import { applyTheme } from "./theme.js";

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

export function initSettings() {
  $("setCancel").onclick = () => $("overlay").classList.remove("open");
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
    };
    for (const [key, id] of Object.entries(CHECK_IDS)) body[key] = $(id).checked;
    if ($("setKey").value.trim()) body.api_key = $("setKey").value.trim();
    state.settings = { ...state.settings, ...(await api.put("/settings", body)) };
    $("setKey").value = "";
    applyTheme();
    $("overlay").classList.remove("open");
    document.dispatchEvent(new CustomEvent("leanchat:changed"));
  };
}

export function openSettings() {
  $("setHost").value = state.settings.host || "";
  $("setPort").value = state.settings.port || "";
  $("setBase").value = state.settings.host
    ? buildBaseUrl(state.settings.host, state.settings.port)
    : state.settings.base;
  $("setKey").value = "";
  $("setModel").value = state.settings.model;
  $("setSystemPrompt").value = state.settings.system_prompt || "";
  $("setTheme").value = state.settings.theme;
  for (const [key, id] of Object.entries(CHECK_IDS)) $(id).checked = state.settings[key] !== false;
  $("overlay").classList.add("open");
}
