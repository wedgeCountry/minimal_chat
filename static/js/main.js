import { api } from "./api.js";
import { state, activeSession } from "./state.js";
import { $, } from "./util.js";
import { goToLogin } from "./auth.js";
import { loadSessions, renderSessions, changed } from "./sessions.js";
import { abortStream, renderChat, renderHeader, send } from "./chat.js";
import { addAttachments, renderAttachments } from "./attachments.js";
import { initSettings, loadSettings, openSettings } from "./settings.js";
import { initConfirm } from "./confirm.js";
import { applyTheme } from "./theme.js";
import { initPartials } from "./html.js";

let currentMessages = [];

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

function renderAll() {
  renderSessions();
  renderHeader();
  refreshChat();
}

async function bootstrap() {
  initSettings();
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
    document.documentElement.classList.add("dark");
  
  // Check if auto-login is enabled
  let autoLoginEnabled = false;
  try {
    const config = await api.get("/api/auth/config");
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
  await loadSessions();
  renderAll();
}

function initEvents() {
  initConfirm();
  $("panelBtn").onclick = () => $("side").classList.toggle("hidden");
  $("burgerBtn").onclick = (e) => {
    e.stopPropagation();
    $("burgerMenu").classList.toggle("open");
  };
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#burgerWrap")) $("burgerMenu").classList.remove("open");
  });
  $("settingsBtn").onclick = () => {
    $("burgerMenu").classList.remove("open");
    openSettings();
  };
  $("compactBtn").onclick = () => {
    $("burgerMenu").classList.remove("open");
    $("chat").classList.toggle("compact");
  };
  // Check if auto-login is enabled to hide logout button
  let autoLoginEnabled = false;
  try {
    api.get("/api/auth/config").then(config => {
      autoLoginEnabled = config.auto_login || false;
      if (autoLoginEnabled) {
        $("logoutBtn").style.display = "none";
      }
    });
  } catch {
    // If config endpoint fails, keep logout button visible
  }
  
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
  $("sendBtn").onclick = send;
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
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 180) + "px";
  });

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
}

await initPartials();
initEvents();
bootstrap();
