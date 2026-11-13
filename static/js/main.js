import { api } from "./api.js";
import { state, activeSession, normalizeMessages } from "./state.js";
import { $ } from "./util.js";
import { goToLogin } from "./auth.js";
import { loadSessions, renderSessions, newSession } from "./sessions.js";
import { abortStream, pollOnce, renderChat, renderHeader, send } from "./chat.js";
import { addAttachments } from "./attachments.js";
import { initSettings, loadSettings, openSettings } from "./settings.js";
import { initConfirm } from "./confirm.js";
import { controlsVisible, refreshSpeechAvailability } from "./ttsDetectionService.js";
import { onMicClick } from "./recorder.js";
import { initPartials } from "./html.js";
import { initGlobalErrorHandling } from "./errors.js";

let currentMessages = [];
let autoLoginEnabled = false;

function applyAutoLoginUI() {
  if (!autoLoginEnabled) return;
  document.documentElement.classList.add("auto-login");
  $("logoutBtn").style.display = "none";
  $("changePwBtn").style.display = "none";
}
function setSideHidden(hidden) {
  $("side").classList.toggle("hidden", hidden);
}

export function isMobileInput() {
  return (
    (window.matchMedia && window.matchMedia("(hover: none) and (pointer: coarse)").matches) ||
    "ontouchstart" in window
  );
}

async function refreshChat() {
  const s = activeSession();
  if (s) {
    try {
      const detail = await api.get(`/sessions/${s.id}`);
      currentMessages = normalizeMessages(detail.messages);
    } catch {
      currentMessages = [];
    }
  } else {
    currentMessages = [];
  }
  renderChat(currentMessages);
}

function applyComposerButtons() {
  $("attachBtn").style.display = state.settings.show_file_button === false ? "none" : "";
  $("camBtn").style.display = state.settings.show_image_button === false ? "none" : "";
  $("micBtn").style.display = controlsVisible("stt") ? "" : "none";
}

function renderAll() {
  renderSessions();
  renderHeader();
  refreshChat();
  applyComposerButtons();
}

async function bootstrap() {
  initSettings();
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
    document.documentElement.classList.add("dark");
  
  // einmalig ermitteln; applyAutoLoginUI wendet das Ergebnis an
  try {
    const config = await api.get("/auth/config");
    autoLoginEnabled = config.auto_login || false;
  } catch {
    // If config endpoint fails, continue with normal flow
  }
  applyAutoLoginUI();

  try {
    await api.get("/auth/me");
  } catch (err) {
    // Only redirect to the auth page if auto-login is not enabled
    if (!autoLoginEnabled) {
      goToLogin();
      return;
    }
    // If auto-login is enabled but /auth/me still fails, something is wrong
    // Try to reload the page
    console.error("Auto-login enabled but /auth/me failed:", err);
    location.reload();
    return;
  }
  await loadSettings();
  await refreshSpeechAvailability();
  try {
    const meta = await api.get("/meta");
    if (meta?.app_name) {
      state.appName = meta.app_name;
      document.title = meta.app_name;
    }
  } catch {}
  await loadSessions();
  if (state.sessions.length === 0) await newSession(true);
  $("side").classList.add("hidden");
  renderAll();
  // Falls serverseitig noch eine Generierung laeuft (z.B. nach App-Neustart
  // oder Wechsel aus einer anderen App): sofort synchronisieren und polln.
  await pollOnce();
}

function initEvents() {
  initConfirm();
  $("panelBtn").onclick = () => setSideHidden(!$("side").classList.contains("hidden"));
  $("burgerBtn").onclick = (e) => {
    e.stopPropagation();
    $("burgerMenu").classList.toggle("open");
  };
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#burgerWrap")) $("burgerMenu").classList.remove("open");
  });
  $("settingsBtn").onclick = () => {
    $("burgerMenu").classList.remove("open");
    openSettings("general");
  };
  $("llmSettingsBtn").onclick = () => {
    $("burgerMenu").classList.remove("open");
    openSettings("llm");
  };
  $("compactBtn").onclick = () => {
    $("burgerMenu").classList.remove("open");
    $("chat").classList.toggle("compact");
  };
  $("changePwBtn").onclick = () => {
    $("burgerMenu").classList.remove("open");
    window.location.href = "/auth/change-password";
  };
  $("logoutBtn").onclick = async () => {
    $("burgerMenu").classList.remove("open");
    await api.post("/auth/logout", {}).catch(() => {});
    state.sessions = [];
    state.activeId = null;
    sessionStorage.removeItem("leanchat.active");
    document.documentElement.classList.remove("dark");
    goToLogin();
  };
  $("abortBtnSide").onclick = abortStream;
  $("sendBtn").onclick = () => send();
  $("attachBtn").onclick = () => $("fileInput").click();
  $("camBtn").onclick = () => $("camInput").click();
  $("fileInput").onchange = (e) => {
    addAttachments([...e.target.files]);
    e.target.value = "";
  };
  $("camInput").onchange = (e) => {
    addAttachments([...e.target.files]);
    e.target.value = "";
  };

  const input = $("input");
  const mobile = isMobileInput();
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !mobile) {
      e.preventDefault();
      send();
    }
  });
  const fieldSizingSupported = !!(window.CSS && CSS.supports && CSS.supports("field-sizing", "content"));
  const updateInputOverflow = () => {
    input.style.overflowY = input.scrollHeight > input.clientHeight + 1 ? "auto" : "hidden";
  };
  const resizeInput = () => {
    if (fieldSizingSupported) return;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 180) + "px";
  };
  const syncInputSize = () => {
    resizeInput();
    updateInputOverflow();
  };
  input.addEventListener("input", syncInputSize);
  window.addEventListener("resize", syncInputSize);
  syncInputSize();
  if (mobile) {
    $("composerWrap").addEventListener("pointerdown", () => $("side").classList.add("hidden"));
    $("chat").addEventListener("pointerdown", () => $("side").classList.add("hidden"));
  }

  $("micBtn").onclick = () => onMicClick(input);

  document.addEventListener("leanchat:changed", renderAll);
  document.addEventListener("leanchat:session-selected", () => {
    if (isMobileInput()) $("side").classList.add("hidden");
  });
  document.addEventListener("leanchat:unauthorized", () => goToLogin());
  // Zurueck aus dem Hintergrund: Server-Stand sofort abrufen, damit eine
  // laufende Generierung (Progress-Bar, neue Bubbles) direkt sichtbar ist.
  const resync = () => pollOnce();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) resync();
  });
  window.addEventListener("pageshow", resync);
  window.addEventListener("focus", resync);
}

initGlobalErrorHandling();
await initPartials();
initEvents();
bootstrap();
