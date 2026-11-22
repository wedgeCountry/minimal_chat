// Single Source of Truth im Frontend; muss zu BOOL_SETTINGS (app/services/settings.py) passen.
export const BOOL_SETTING_KEYS = [
  "bubbles_deletable",
  "bubbles_checkable",
  "bubbles_speaker",
  "bubbles_minimal",
  "show_system_prompt",
  "show_tool_output",
  "show_reasoning",
  "show_file_button",
  "show_image_button",
];

export const BOOL_SETTING_DEFAULTS = {
  bubbles_deletable: false,
  bubbles_checkable: true,
  bubbles_speaker: true,
  bubbles_minimal: false,
  show_system_prompt: true,
  show_tool_output: true,
  show_reasoning: true,
  show_file_button: false,
  show_image_button: false,
};

export function defaultBoolSettings() {
  return Object.fromEntries(BOOL_SETTING_KEYS.map((k) => [k, BOOL_SETTING_DEFAULTS[k]]));
}

// Single Source of Truth fuer Session-Settings; muss zu SESSION_SETTING_KEYS (app/services/settings.py) passen.
export const SESSION_SETTING_KEYS = ["system_prompt", "model_id"];
