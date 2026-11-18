import { state } from "./state.js";

export function applyTheme() {
  document.documentElement.classList.toggle("dark", state.settings.theme === "dark");
}
