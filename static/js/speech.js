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
  const ok =
    mode === "system"
      ? !!(speech?.systemStt && speech?.systemTts)
      : !!(speech?.serverStt && speech?.serverTts);
  return ok
    ? { text: "Verfügbar", cls: "ok" }
    : { text: "Nicht verfügbar", cls: "err" };
}
