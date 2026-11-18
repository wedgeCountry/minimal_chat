import { $, spliceAtCursor } from "./util.js";
import { transcribeAudio, encodeWav, VOICE_UNAVAILABLE_MSG } from "./voice.js";
import {
  effectiveModeFor,
  controlsVisible,
  selectedModeAvailable,
  mergeTranscript,
  SYSTEM_UNAVAILABLE_MSG,
  isSpeaking,
  registerRecordingStopper,
} from "./ttsDetectionService.js";
import { showError } from "./confirm.js";

export const RECORDING_SUPPRESSED_MSG =
  "Wiedergabe läuft – Spracheingabe ist während der Wiedergabe unterdrückt.";

// Aktive Aufnahme: { rec?, stop({discard}) } – genau eine zur Zeit (WAV oder System).
let active = null;
let starting = false;

export function isRecording() {
  return !!active;
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
  let discarded = false;
  rec.onresult = (e) => {
    // nur neue Results ab e.resultIndex verarbeiten (Buffer leeren, keine Duplikate)
    const m = mergeTranscript(final, e.results, e.resultIndex);
    final = m.final;
    const r2 = spliceAtCursor(base, cursor, cursor, m.text);
    input.value = r2.value;
    input.dispatchEvent(new Event("input"));
  };
  const release = () => {
    if (active?.rec === rec) {
      active = null;
      $("micBtn").classList.remove("on");
    }
  };
  rec.onend = () => {
    release();
    // Interim-Puffer verwerfen, nur finalen Text an Cursor-Position uebernehmen
    if (final && !discarded) {
      const r2 = spliceAtCursor(base, cursor, cursor, final);
      input.value = r2.value;
      input.setSelectionRange(r2.cursor, r2.cursor);
      input.dispatchEvent(new Event("input"));
    }
    input.focus();
  };
  rec.onerror = release;
  rec.start();
  return {
    rec,
    stop: ({ discard = false } = {}) => {
      discarded = discard;
      try {
        rec.stop();
      } catch {}
    },
  };
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
    stop: async ({ discard = false } = {}) => {
      stopped = true;
      if (discard) chunks.length = 0; // Puffer verwerfen (z. B. nach Senden/Speaker)
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

// Stoppt die laufende Aufnahme. discard=true verwirft den Puffer (kein STT, kein
// Einfuegen in den Composer) – z. B. beim Senden oder wenn die Wiedergabe startet.
export function stopRecording({ discard = false } = {}) {
  const a = active;
  if (!a) return;
  active = null;
  $("micBtn")?.classList.remove("on");
  a.stop({ discard });
}

export async function onMicClick(input) {
  const mode = effectiveModeFor("stt");
  if (mode === "none" || !controlsVisible("stt")) {
    await showError("Sprachdienst nicht verfügbar.");
    return;
  }
  if (active) {
    stopRecording(); // manuelles Stoppen: Puffer transkribieren
    return;
  }
  if (isSpeaking()) {
    // Wiedergabe laeuft: Aufnahme wird unterdrueckt
    await showError(RECORDING_SUPPRESSED_MSG);
    return;
  }
  if (starting) return;
  starting = true;
  try {
    if (mode === "system") {
      if (!(await selectedModeAvailable("stt"))) {
        await showError(SYSTEM_UNAVAILABLE_MSG);
        return;
      }
      active = startSystemRecognition(input);
      $("micBtn").classList.add("on");
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
      active = await startWavRecorder(input);
    } catch {
      active = null;
      await showError("Mikrofon nicht verfügbar.");
      return;
    }
    $("micBtn").classList.add("on");
  } finally {
    starting = false;
  }
}

// speak() (TTS) und send() (Composer) stoppen die Aufnahme ueber diesen Hook,
// ohne dass recorder.js und ttsDetectionService.js zyklisch importieren.
registerRecordingStopper(stopRecording);
