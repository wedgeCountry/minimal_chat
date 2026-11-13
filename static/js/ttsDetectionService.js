import { state } from "./state.js";
import { speechControlsVisible } from "./visibility.js";
import { voiceStatus, synthesizeSpeech, VOICE_UNAVAILABLE_MSG } from "./voice.js";

export const SPEECH_MODES = ["system", "server", "none"];

export const SYSTEM_UNAVAILABLE_MSG = "System-Sprachdienst im Browser nicht verfügbar.";
export const SPEECH_UNAVAILABLE_MSG = "Sprachdienst nicht verfügbar.";

export function speechMode() {
  return SPEECH_MODES.includes(state.settings.speech_mode) ? state.settings.speech_mode : "server";
}

export function systemSttAvailable() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

export function systemTtsAvailable() {
  return "speechSynthesis" in window;
}

export async function refreshSpeechAvailability() {
  state.speech.systemStt = systemSttAvailable();
  state.speech.systemTts = systemTtsAvailable();
  const s = await voiceStatus();
  state.speech.serverStt = !!s.stt;
  state.speech.serverTts = !!s.tts;
  return state.speech;
}

function modeAvailableFor(mode, kind) {
  if (mode === "system") return kind === "stt" ? !!state.speech.systemStt : !!state.speech.systemTts;
  if (mode === "server") return kind === "stt" ? !!state.speech.serverStt : !!state.speech.serverTts;
  return false;
}

// Effektiver Modus: gewaehlter Modus, Fallback auf den anderen Modus wenn der
// gewaehlte nicht verfuegbar ist (z.B. Server down -> Browser), sonst "none".
export function effectiveModeFor(kind) {
  const mode = speechMode();
  if (mode === "none") return "none";
  if (modeAvailableFor(mode, kind)) return mode;
  const other = mode === "system" ? "server" : "system";
  if (modeAvailableFor(other, kind)) return other;
  return "none";
}

export function controlsVisible(kind) {
  return speechControlsVisible(speechMode(), kind, state.speech);
}

export async function selectedModeAvailable(kind) {
  const mode = speechMode();
  if (mode === "system") return kind === "stt" ? systemSttAvailable() : systemTtsAvailable();
  if (mode === "server") {
    const s = await voiceStatus();
    return kind === "stt" ? !!s.stt : !!s.tts;
  }
  return false;
}

// Verarbeitet nur die neuen Results ab resultIndex (verarbeitete Ergebnisse
// werden nicht erneut gezaehlt -> keine Duplikate) und liefert final+interim.
export function mergeTranscript(finalSoFar, results, resultIndex) {
  let final = finalSoFar || "";
  let interim = "";
  for (let i = resultIndex; i < results.length; i++) {
    const r = results[i];
    const t = r?.[0]?.transcript || "";
    if (r?.isFinal) final += t;
    else interim += t;
  }
  return { final, text: final + interim };
}

export function speechStatusLabel(mode, speech) {
  if (mode === "none") return { text: "Deaktiviert", cls: "" };
  const avail = (m) =>
    m === "system"
      ? !!(speech?.systemStt && speech?.systemTts)
      : !!(speech?.serverStt && speech?.serverTts);
  if (avail(mode)) return { text: "Verfügbar", cls: "ok" };
  const other = mode === "system" ? "server" : "system";
  if (avail(other))
    return { text: "Nicht verfügbar – Fallback: " + (other === "system" ? "System-API" : "Server"), cls: "err" };
  return { text: "Nicht verfügbar", cls: "err" };
}

// Single Source of Truth fuer das Settings-Menue: Label zum gewaehlten Modus.
export function statusLabel(mode) {
  return speechStatusLabel(mode, state.speech);
}

let activeAudio = null;

export function isSpeaking() {
  return !!activeAudio;
}

export function stopSpeech() {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio = null;
    document.querySelectorAll(".ttsBtn.on").forEach((x) => x.classList.remove("on"));
  }
}

// TTS-Aktion inkl. Modus-Erkennung: system -> speechSynthesis, server -> Voice
// Companion. onError(reason) wird bei nicht verfuegbarem Modus/Fehler gerufen.
export async function speak(text, btn, { onError } = {}) {
  const mode = effectiveModeFor("tts");
  if (mode === "none" || !controlsVisible("tts")) {
    await onError?.(SPEECH_UNAVAILABLE_MSG);
    return;
  }
  if (!(await selectedModeAvailable("tts"))) {
    await onError?.(mode === "system" ? SYSTEM_UNAVAILABLE_MSG : VOICE_UNAVAILABLE_MSG);
    return;
  }
  if (mode === "system") {
    const u = new SpeechSynthesisUtterance(text || "");
    u.lang = "de-DE";
    u.onend = () => btn?.classList.remove("on");
    btn?.classList.add("on");
    speechSynthesis.speak(u);
    return;
  }
  try {
    const blob = await synthesizeSpeech(text || "");
    const audio = new Audio(URL.createObjectURL(blob));
    activeAudio = audio;
    btn?.classList.add("on");
    audio.onended = () => {
      btn?.classList.remove("on");
      if (activeAudio === audio) activeAudio = null;
    };
    audio.onerror = audio.onended;
    await audio.play();
  } catch (err) {
    btn?.classList.remove("on");
    if (activeAudio) activeAudio = null;
    await onError?.(err.message || "Vorlesen fehlgeschlagen.");
  }
}
