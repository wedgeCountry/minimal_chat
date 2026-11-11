import { $ } from "./util.js";

let resolver = null;

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
