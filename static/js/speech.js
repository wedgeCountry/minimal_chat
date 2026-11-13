import { state } from "./state.js";
import { voiceStatus } from "./voice.js";
import { speechControlsVisible } from "./visibility.js";

export const SPEECH_MODES = ["system", "server", "none"];

export const SYSTEM_UNAVAILABLE_MSG = "System-Sprachdienst im Browser nicht verfügbar.";

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
  return effectiveModeFor(kind) !== "none";
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
