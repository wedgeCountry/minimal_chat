// Single Source of Truth fuer die boolschen User-Settings im Frontend.
// Muss zu BOOL_SETTINGS in app/services/settings.py passen (Namen + Defaults).
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
