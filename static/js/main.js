import { api } from "./api.js";
import { state, activeSession } from "./state.js";
import { $, } from "./util.js";
import { goToLogin } from "./auth.js";
import { loadSessions, renderSessions, changed } from "./sessions.js";
import { abortStream, pollOnce, renderChat, renderHeader, send } from "./chat.js";
import { addAttachments, renderAttachments } from "./attachments.js";
import { initSettings, loadSettings, openSettings } from "./settings.js";
import { initConfirm } from "./confirm.js";
import { applyTheme } from "./theme.js";
import { initPartials } from "./html.js";
import { initGlobalErrorHandling } from "./errors.js";

let currentMessages = [];

const SIDE_HIDDEN_KEY = "leanchat.sideHidden";

function sideHidden() {
  try {
    return localStorage.getItem(SIDE_HIDDEN_KEY) === "1";
  } catch {
    return true;
  }
}

function setSideHidden(hidden) {
  $("side").classList.toggle("hidden", hidden);
  try {
    localStorage.setItem(SIDE_HIDDEN_KEY, hidden ? "1" : "0");
  } catch {}
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
      currentMessages = detail.messages;
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
  
  // Check if auto-login is enabled
  let autoLoginEnabled = false;
  try {
    const config = await api.get("/auth/config");
    autoLoginEnabled = config.auto_login || false;
    if (autoLoginEnabled) {
      document.documentElement.classList.add("auto-login");
    }
  } catch {
    // If config endpoint fails, continue with normal flow
  }
  
  try {
    const me = await api.get("/auth/me");
    state.username = me.email;
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
  try {
    const meta = await api.get("/meta");
    if (meta?.app_name) {
      state.appName = meta.app_name;
      document.title = meta.app_name;
    }
  } catch {}
  await loadSessions();
  $("side").classList.toggle("hidden", sideHidden());
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
  // Check if auto-login is enabled to hide logout button
  let autoLoginEnabled = false;
  try {
    api.get("/auth/config").then(config => {
      autoLoginEnabled = config.auto_login || false;
      if (autoLoginEnabled) {
        $("logoutBtn").style.display = "none";
        $("changePwBtn").style.display = "none";
      }
    });
  } catch {
    // If config endpoint fails, keep logout button visible
  }
  
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
  const updateInputOverflow = () => {
    input.style.overflowY = input.scrollHeight > input.clientHeight + 1 ? "auto" : "hidden";
  };
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 180) + "px";
    updateInputOverflow();
  });
  updateInputOverflow();
  if (mobile) {
    $("composerWrap").addEventListener("pointerdown", () => $("side").classList.add("hidden"));
    $("chat").addEventListener("pointerdown", () => $("side").classList.add("hidden"));
  }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    $("micBtn").style.display = "none";
  } else {
    let rec = null;
    let recOn = false;
    $("micBtn").onclick = () => {
      if (recOn) {
        rec.stop();
        return;
      }
      rec = new SR();
      rec.lang = "de-DE";
      rec.interimResults = true;
      rec.continuous = false;
      let final = "";
      rec.onresult = (e) => {
        let interim = "";
        for (const r of e.results) {
          if (r.isFinal) final += r[0].transcript;
          else interim += r[0].transcript;
        }
        input.value = final + interim;
      };
      rec.onend = () => {
        recOn = false;
        $("micBtn").classList.remove("on");
        input.focus();
      };
      rec.onerror = () => {
        recOn = false;
        $("micBtn").classList.remove("on");
      };
      recOn = true;
      $("micBtn").classList.add("on");
      rec.start();
    };
  }

  document.addEventListener("leanchat:changed", renderAll);
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
