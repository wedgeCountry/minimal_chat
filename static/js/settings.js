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
};

export async function loadSettings() {
  state.settings = { ...state.settings, ...(await api.get("/settings")) };
  applyTheme();
}

export function initSettings() {
  $("setCancel").onclick = () => $("overlay").classList.remove("open");
  $("overlay").addEventListener("click", (e) => {
    if (e.target === $("overlay")) $("overlay").classList.remove("open");
  });
  $("setSave").onclick = async () => {
    const body = {
      base: $("setBase").value.trim(),
      model: $("setModel").value.trim(),
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
  $("setBase").value = state.settings.base;
  $("setKey").value = "";
  $("setModel").value = state.settings.model;
  $("setTheme").value = state.settings.theme;
  for (const [key, id] of Object.entries(CHECK_IDS)) $(id).checked = state.settings[key] !== false;
  $("overlay").classList.add("open");
}
