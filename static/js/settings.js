import { api } from "./api.js";
import { state } from "./state.js";
import { $ } from "./util.js";
import { applyTheme } from "./theme.js";

export async function loadSettings() {
  state.settings = await api.get("/settings");
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
    if ($("setKey").value.trim()) body.api_key = $("setKey").value.trim();
    state.settings = await api.put("/settings", body);
    $("setKey").value = "";
    applyTheme();
    $("overlay").classList.remove("open");
  };
}

export function openSettings() {
  $("setBase").value = state.settings.base;
  $("setKey").value = "";
  $("setModel").value = state.settings.model;
  $("setTheme").value = state.settings.theme;
  $("overlay").classList.add("open");
}
