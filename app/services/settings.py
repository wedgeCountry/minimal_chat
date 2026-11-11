"""Boolesche User-Settings: Defaults und Umwandlung DB-String <-> bool."""

from __future__ import annotations

BOOL_SETTINGS: dict[str, bool] = {
    "bubbles_deletable": True,
    "bubbles_checkable": True,
    "bubbles_speaker": True,
    "show_system_prompt": True,
    "show_tool_output": True,
    "show_reasoning": True,
}

# Fruehere Schluessel (vor dem Umbenennen ohne User-Bezug)
LEGACY_KEYS = {
    "bubbles_checkable": "bubbles_user_checkable",
    "bubbles_deletable": "bubbles_user_deletable",
}


def stored_bool(stored: dict[str, str], key: str) -> bool:
    default = "1" if BOOL_SETTINGS[key] else "0"
    value = stored.get(key)
    if value is None:
        value = stored.get(LEGACY_KEYS.get(key, ""), default)
    return value not in ("0", "false", "")


def to_db(value: bool) -> str:
    return "1" if value else "0"
