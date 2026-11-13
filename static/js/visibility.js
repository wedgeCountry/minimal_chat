// Reine Sichtbarkeitslogik der Bubbles anhand der User-Settings (unit-testbar).
export function isBubbleVisible(m, s) {
  if (m.role === "system" && s.show_system_prompt === false) return false;
  if (m.type === "reasoning" && s.show_reasoning === false) return false;
  if ((m.type === "toolcall" || m.type === "toolresult") && s.show_tool_output === false) return false;
  return true;
}

export function isBubbleDeletable(s) {
  return s.bubbles_deletable !== false;
}

export function isBubbleCheckable(s) {
  return s.bubbles_checkable !== false;
}

export function isBubbleSpeaker(s) {
  return s.bubbles_speaker !== false;
}

// Speech-Controls (Mikrofon/Speaker) sichtbar? Modus "none" oder nicht
// verfuegbarer Modus blendet das jeweilige Control aus (kind: "stt" | "tts").
export function speechControlsVisible(mode, kind, speech) {
  if (mode === "none") return false;
  if (mode === "system") return kind === "stt" ? !!speech?.systemStt : !!speech?.systemTts;
  if (mode === "server") return kind === "stt" ? !!speech?.serverStt : !!speech?.serverTts;
  return false;
}
