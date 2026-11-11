// Reine Sichtbarkeitslogik der Bubbles anhand der User-Settings (unit-testbar).
export function isBubbleVisible(m, s) {
  if (m.role === "system" && s.show_system_prompt === false) return false;
  if (m.type === "reasoning" && s.show_reasoning === false) return false;
  if (m.type === "toolcall" && s.show_tool_output === false) return false;
  return true;
}

export function isBubbleDeletable(s) {
  return s.bubbles_deletable !== false;
}

export function isUserBubbleCheckable(s) {
  return s.bubbles_user_checkable !== false;
}

export function isUserBubbleDeletable(s) {
  return s.bubbles_user_deletable !== false;
}
