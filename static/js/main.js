import { api } from "./api.js";
import { state, activeSession } from "./state.js";
import { $, } from "./util.js";
import { initAuth, showAuth } from "./auth.js";
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
  try {
    const me = await api.get("/auth/me");
    state.username = me.email;
  } catch {
    showAuth();
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
  $("logoutBtn").onclick = async () => {
    $("burgerMenu").classList.remove("open");
    await api.post("/auth/logout", {}).catch(() => {});
    state.sessions = [];
    state.activeId = null;
    sessionStorage.removeItem("leanchat.active");
    document.documentElement.classList.remove("dark");
    showAuth();
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
  document.addEventListener("leanchat:unauthorized", () => showAuth());
}

await initPartials();
initEvents();
initAuth(bootstrap);
bootstrap();
