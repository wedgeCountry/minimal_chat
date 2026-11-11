"""Boolesche User-Settings: Defaults und Umwandlung DB-String <-> bool."""

from __future__ import annotations

BOOL_SETTINGS: dict[str, bool] = {
    "bubbles_deletable": True,
    "bubbles_user_checkable": True,
    "bubbles_user_deletable": True,
    "show_system_prompt": True,
    "show_tool_output": True,
    "show_reasoning": True,
}


def stored_bool(stored: dict[str, str], key: str) -> bool:
    default = "1" if BOOL_SETTINGS[key] else "0"
    return stored.get(key, default) not in ("0", "false", "")


def to_db(value: bool) -> str:
    return "1" if value else "0"
