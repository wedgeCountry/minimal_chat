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
  // UI (Mikrofon-/Speaker-Buttons) sofort nachziehen, nicht erst beim naechsten Render
  if (typeof document !== "undefined")
    document.dispatchEvent(new CustomEvent("leanchat:speech-availability"));
  return state.speech;
}

// Verfuegbarkeit kommt nur aus speechControlsVisible (visibility.js)
function modeAvailableFor(mode, kind) {
  return speechControlsVisible(mode, kind, state.speech);
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
let systemSpeaking = false;

// Hook fuer das Aufnahme-Modul (recorder.js): speak() stoppt eine laufende
// Aufnahme, ohne dass die Module zyklisch importieren muessen.
let recordingStopper = null;
export function registerRecordingStopper(fn) {
  recordingStopper = fn;
}
export function stopRecording(opts) {
  if (recordingStopper) recordingStopper(opts);
}

export function isSpeaking() {
  return !!activeAudio || systemSpeaking;
}

export function stopSpeech() {
  if (activeAudio) {
    activeAudio.__stopped = true; // pause() unterbricht play() -> AbortError ist gewollt
    activeAudio.pause();
    activeAudio = null;
  }
  if (systemSpeaking) {
    systemSpeaking = false;
    try {
      speechSynthesis.cancel();
    } catch {}
  }
  document.querySelectorAll(".ttsBtn.on").forEach((x) => x.classList.remove("on"));
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
  // laufende Aufnahme stoppen und Puffer verwerfen (Wiedergabe gewinnt ueber STT)
  stopRecording({ discard: true });
  if (mode === "system") {
    const u = new SpeechSynthesisUtterance(text || "");
    u.lang = "de-DE";
    systemSpeaking = true;
    const done = () => {
      systemSpeaking = false;
      btn?.classList.remove("on");
    };
    u.onend = done;
    u.onerror = done;
    btn?.classList.add("on");
    speechSynthesis.speak(u);
    return;
  }
  const audio = new Audio();
  // sofort als aktiv markieren, damit ein schneller zweiter Klick stoppt
  activeAudio = audio;
  btn?.classList.add("on");
  try {
    const blob = await synthesizeSpeech(text || "");
    if (activeAudio !== audio) return; // inzwischen per stopSpeech() gestoppt
    audio.src = URL.createObjectURL(blob);
    audio.onended = () => {
      btn?.classList.remove("on");
      if (activeAudio === audio) activeAudio = null;
    };
    audio.onerror = audio.onended;
    await audio.play();
  } catch (err) {
    if (audio.__stopped) return; // durch stopSpeech() gewollt beendet -> kein Fehler
    if (activeAudio === audio) activeAudio = null;
    btn?.classList.remove("on");
    await onError?.(err.message || "Vorlesen fehlgeschlagen.");
  }
}
