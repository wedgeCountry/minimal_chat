import { api, parseErrorResponse } from "./api.js";

export const VOICE_UNAVAILABLE_MSG =
  "Sprachdienst nicht verfügbar – bitte Voice-Companion-Server prüfen.";

export async function voiceStatus() {
  try {
    return await api.get("/voice/status");
  } catch {
    return { available: false, stt: false, tts: false };
  }
}

export async function voiceAvailable() {
  const s = await voiceStatus();
  return !!s.available;
}

export async function transcribeAudio(blob, language) {
  const fd = new FormData();
  fd.append("file", blob, "recording.wav");
  const params = language ? `?language=${encodeURIComponent(language)}` : "";
  const res = await fetch("/api/voice/stt" + params, { method: "POST", body: fd });
  if (res.status === 503) throw new Error(VOICE_UNAVAILABLE_MSG);
  if (!res.ok) throw new Error(await parseErrorResponse(res, "Spracheingabe fehlgeschlagen."));
  const data = await res.json();
  return data.text || "";
}

export async function synthesizeSpeech(text, language) {
  const res = await fetch("/api/voice/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(language ? { text, language } : { text }),
  });
  if (res.status === 503) throw new Error(VOICE_UNAVAILABLE_MSG);
  if (!res.ok) throw new Error(await parseErrorResponse(res, "Vorlesen fehlgeschlagen."));
  return await res.blob();
}

export function encodeWav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buf);
  const writeStr = (offset, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([view], { type: "audio/wav" });
}
