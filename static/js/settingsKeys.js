// Single Source of Truth im Frontend; muss zu BOOL_SETTINGS (app/services/settings.py) passen.
export const BOOL_SETTING_KEYS = [
  "bubbles_deletable",
  "bubbles_checkable",
  "bubbles_speaker",
  "show_system_prompt",
  "show_tool_output",
  "show_reasoning",
  "show_file_button",
  "show_image_button",
];

export const BOOL_SETTING_DEFAULTS = {
  bubbles_deletable: true,
  bubbles_checkable: true,
  bubbles_speaker: true,
  show_system_prompt: true,
  show_tool_output: true,
  show_reasoning: true,
  show_file_button: false,
  show_image_button: false,
};

export function defaultBoolSettings() {
  return Object.fromEntries(BOOL_SETTING_KEYS.map((k) => [k, BOOL_SETTING_DEFAULTS[k]]));
}
