import { $ } from "./util.js";

let resolver = null;
let errorResolver = null;

export function initConfirm() {
  const overlay = $("confirmOverlay");
  const close = (value) => {
    overlay.classList.remove("open");
    if (resolver) {
      resolver(value);
      resolver = null;
    }
  };
  $("confirmCancel").onclick = () => close(false);
  $("confirmOk").onclick = () => close(true);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("open")) close(false);
  });
  
  const errorOverlay = $("errorOverlay");
  const errorClose = () => {
    errorOverlay.classList.remove("open");
    if (errorResolver) {
      errorResolver();
      errorResolver = null;
    }
  };
  $("errorOk").onclick = errorClose;
  errorOverlay.addEventListener("click", (e) => {
    if (e.target === errorOverlay) errorClose();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && errorOverlay.classList.contains("open")) errorClose();
  });
}

export function confirmModal({ title, text, okLabel = "Löschen" }) {
  return new Promise((resolve) => {
    resolver = resolve;
    $("confirmTitle").textContent = title;
    $("confirmText").textContent = text;
    $("confirmOk").textContent = okLabel;
    $("confirmOverlay").classList.add("open");
  });
}

export function showError(message) {
  return new Promise((resolve) => {
    errorResolver = resolve;
    $("errorTitle").textContent = "Fehler";
    $("errorText").textContent = message;
    $("errorOverlay").classList.add("open");
  });
}
