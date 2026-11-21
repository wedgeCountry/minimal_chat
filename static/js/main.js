import { api } from "./api.js";
import { state, activeSession, normalizeMessages } from "./state.js";
import { $ } from "./util.js";
import { goToLogin } from "./auth.js";
import { loadSessions, renderSessions, newSession } from "./sessions.js";
import { abortStream, initBubbleMenu, pollOnce, renderChatView, renderHeader, send, setStreamingUI, syncAllBubbleTts } from "./chat.js";
import { isToolbarMinimal } from "./visibility.js";
import { addAttachments } from "./attachments.js";
import { initSettings, loadSettings, openSettings } from "./settings.js";
import { initConfirm } from "./confirm.js";
import { controlsVisible, refreshSpeechAvailability } from "./ttsDetectionService.js";
import { onMicClick } from "./recorder.js";
import { initPartials } from "./html.js";
import { initGlobalErrorHandling } from "./errors.js";
import { initViewportSync } from "./viewport.js";
import { setSideHidden, initSidePanelHistory } from "./sidePanel.js";

let autoLoginEnabled = false;

function applyAutoLoginUI() {
  if (!autoLoginEnabled) return;
  document.documentElement.classList.add("auto-login");
}

export function isMobileInput() {
  return (
    (window.matchMedia && window.matchMedia("(hover: none) and (pointer: coarse)").matches) ||
    "ontouchstart" in window
  );
}

async function refreshChat() {
  const s = activeSession();
  if (!s) {
    state.messages = [];
    state.messagesSid = null;
  } else if (state.messagesSid !== s.id) {
    // Session-Detail nur bei Session-Wechsel laden; Mutationen pflegt der Client lokal (chat.js)
    state.messagesSid = s.id;
    state.messages = [];
    try {
      const detail = await api.get(`/sessions/${s.id}`);
      state.messages = normalizeMessages(detail.messages);
    } catch {
      state.messagesSid = null; // naechster Aufruf versucht es erneut
    }
  }
  renderChatView(); // SSE-Live-Stand (falls aktiv) statt des evtl. aelteren Poll-Stands
}

function applyComposerButtons() {
  $("attachBtn").classList.toggle("u-hidden", state.settings.show_file_button === false);
  $("camBtn").classList.toggle("u-hidden", state.settings.show_image_button === false);
  $("micBtn").classList.toggle("u-hidden", !controlsVisible("stt"));
}

function renderAll() {
  document.documentElement.classList.toggle("bubbles-minimal", isToolbarMinimal(state.settings));
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
  // serverseitig laufende Generierung (z. B. nach Reload) -> Abbrechen-Button statt Senden
  setStreamingUI(!!activeSession()?.generating);
  if (state.sessions.length === 0) await newSession(true);
  setSideHidden(true);
  renderAll();
  // Falls serverseitig noch eine Generierung laeuft (z.B. nach App-Neustart
  // oder Wechsel aus einer anderen App): sofort synchronisieren und polln.
  await pollOnce();
}

function initEvents() {
  initConfirm();
  $("panelBtn").onclick = () => setSideHidden(!$("side").classList.contains("hidden"));
  initSidePanelHistory();
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
  initViewportSync(window, document);
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
    $("composerWrap").addEventListener("pointerdown", () => setSideHidden(true));
    $("chat").addEventListener("pointerdown", () => setSideHidden(true));
  }

  $("micBtn").onclick = () => onMicClick(input);
  // Minimalismus: Tap auf eine Bubble -> Kontextmenue mit den Toolbar-Aktionen
  // (Langdruck/contextmenu bleibt nativ, siehe initBubbleMenu)
  initBubbleMenu();

  document.addEventListener("leanchat:changed", renderAll);
  // Speech-Verfuegbarkeit hat sich geaendert: Mikrofon-/Speaker-Symbole sofort aus-/einblenden
  document.addEventListener("leanchat:speech-availability", () => {
    applyComposerButtons();
    syncAllBubbleTts();
  });
  document.addEventListener("leanchat:session-selected", () => {
    if (isMobileInput()) setSideHidden(true);
  });
  document.addEventListener("leanchat:unauthorized", () => goToLogin());
  // Zurueck aus dem Hintergrund: Server-Stand sofort abrufen, damit eine
  // laufende Generierung (Progress-Bar, neue Bubbles) direkt sichtbar ist.
  const resync = () => {
    pollOnce();
    refreshSpeechAvailability(); // Voice-Companion evtl. inzwischen weg -> Symbole ausblenden
  };
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
