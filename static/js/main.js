import { api } from "./api.js";
import { state, activeSession, normalizeMessages } from "./state.js";
import { $, spliceAtCursor } from "./util.js";
import { goToLogin } from "./auth.js";
import { loadSessions, renderSessions, newSession } from "./sessions.js";
import { abortStream, pollOnce, renderChat, renderHeader, send } from "./chat.js";
import { addAttachments } from "./attachments.js";
import { initSettings, loadSettings, openSettings } from "./settings.js";
import { initConfirm, showError } from "./confirm.js";
import { transcribeAudio, encodeWav, VOICE_UNAVAILABLE_MSG } from "./voice.js";
import { speechMode, controlsVisible, selectedModeAvailable, refreshSpeechAvailability, mergeTranscript, SYSTEM_UNAVAILABLE_MSG } from "./speech.js";
import { initPartials } from "./html.js";
import { initGlobalErrorHandling } from "./errors.js";

let currentMessages = [];

const sysRecRef = { current: null };

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

function insertAtCursor(input, text) {
  if (!text) return;
  const r = spliceAtCursor(input.value, input.selectionStart, input.selectionEnd, text);
  input.value = r.value;
  input.setSelectionRange(r.cursor, r.cursor);
  input.dispatchEvent(new Event("input"));
}

function startSystemRecognition(input) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new SR();
  rec.lang = "de-DE";
  rec.interimResults = true;
  // continuous: nicht nach ~1s Stille automatisch stoppen (Android-Verhalten)
  rec.continuous = true;
  // Basis-Text und Cursor beim Start merken, damit der erkannte Text an der
  // Cursor-Position eingefuegt wird statt den vorhandenen Text zu ersetzen
  const base = input.value;
  const cursor = input.selectionStart ?? base.length;
  let final = "";
  rec.onresult = (e) => {
    // nur neue Results ab e.resultIndex verarbeiten (Buffer leeren, keine Duplikate)
    const m = mergeTranscript(final, e.results, e.resultIndex);
    final = m.final;
    const r2 = spliceAtCursor(base, cursor, cursor, m.text);
    input.value = r2.value;
    input.dispatchEvent(new Event("input"));
  };
  rec.onend = () => {
    sysRecRef.current = null;
    $("micBtn").classList.remove("on");
    // Interim-Puffer verwerfen, nur finalen Text an Cursor-Position uebernehmen
    if (final) {
      const r2 = spliceAtCursor(base, cursor, cursor, final);
      input.value = r2.value;
      input.setSelectionRange(r2.cursor, r2.cursor);
      input.dispatchEvent(new Event("input"));
    }
    input.focus();
  };
  rec.onerror = () => {
    sysRecRef.current = null;
    $("micBtn").classList.remove("on");
  };
  rec.start();
  return rec;
}

async function startWavRecorder(input) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const sampleRate = ctx.sampleRate;
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const gain = ctx.createGain();
  gain.gain.value = 0;
  const chunks = [];
  let stopped = false;
  proc.onaudioprocess = (e) => {
    if (!stopped) chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };
  src.connect(proc);
  proc.connect(gain);
  gain.connect(ctx.destination);
  return {
    stop: async () => {
      stopped = true;
      try {
        src.disconnect();
        proc.disconnect();
        gain.disconnect();
      } catch {}
      stream.getTracks().forEach((t) => t.stop());
      await ctx.close().catch(() => {});
      const n = chunks.reduce((a, c) => a + c.length, 0);
      if (!n) return;
      const samples = new Float32Array(n);
      let off = 0;
      for (const c of chunks) {
        samples.set(c, off);
        off += c.length;
      }
      try {
        const text = await transcribeAudio(encodeWav(samples, sampleRate));
        if (text) insertAtCursor(input, text);
        input.focus();
      } catch (err) {
        await showError(err.message || "Spracheingabe fehlgeschlagen.");
      }
    },
  };
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

  let recorder = null;
  const stopRecorder = () => {
    if (!recorder) return;
    const r = recorder;
    recorder = null;
    $("micBtn").classList.remove("on");
    r.stop();
  };
  const stopSystemRec = () => {
    if (!sysRecRef.current) return;
    const r = sysRecRef.current;
    sysRecRef.current = null;
    $("micBtn").classList.remove("on");
    r.stop();
  };
  $("micBtn").onclick = async () => {
    const mode = speechMode();
    if (mode === "none" || !controlsVisible("stt")) {
      await showError("Sprachdienst nicht verfügbar.");
      return;
    }
    if (mode === "system") {
      if (sysRecRef.current) {
        stopSystemRec();
        return;
      }
      if (!(await selectedModeAvailable("stt"))) {
        await showError(SYSTEM_UNAVAILABLE_MSG);
        return;
      }
      sysRecRef.current = startSystemRecognition(input);
      $("micBtn").classList.add("on");
      return;
    }
    if (recorder) {
      stopRecorder();
      return;
    }
    if (!(await selectedModeAvailable("stt"))) {
      await showError(VOICE_UNAVAILABLE_MSG);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      await showError("Mikrofon im Browser nicht verfügbar.");
      return;
    }
    try {
      recorder = await startWavRecorder(input);
    } catch {
      recorder = null;
      await showError("Mikrofon nicht verfügbar.");
      return;
    }
    $("micBtn").classList.add("on");
  };

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
