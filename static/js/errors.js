import { $ } from "./util.js";
import { showError } from "./confirm.js";

export const ERROR_AUTO_CLOSE_MS = 10000;

export function normalizeErrorMessage(reason) {
  if (reason instanceof Error) return reason.stack || reason.message;
  if (typeof reason === "string") return reason;
  try {
    return JSON.stringify(reason);
  } catch {
    return String(reason);
  }
}

function reportToServer(message) {
  try {
    const body = JSON.stringify({ level: "error", message: String(message).slice(0, 4000) });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/log", new Blob([body], { type: "application/json" }));
    } else {
      fetch("/api/log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => {});
    }
  } catch {}
}

let lastMessage = null;

function handleGlobalError(reason) {
  const message = normalizeErrorMessage(reason) || "Unbekannter Fehler";
  console.error(message);
  reportToServer(message);
  if (message === lastMessage) return;
  lastMessage = message;
  if ($("errorOverlay")) showError(message, ERROR_AUTO_CLOSE_MS);
}

export function initGlobalErrorHandling() {
  window.addEventListener("error", (e) => {
    handleGlobalError(e.error || e.message || "Unbekannter Fehler");
  });
  window.addEventListener("unhandledrejection", (e) => {
    handleGlobalError(e.reason);
  });
}
