"""Boolesche User-Settings: Defaults und Umwandlung DB-String <-> bool."""

from __future__ import annotations

BOOL_SETTINGS: dict[str, bool] = {
    "bubbles_deletable": True,
    "bubbles_checkable": True,
    "bubbles_speaker": True,
    "show_system_prompt": True,
    "show_tool_output": True,
    "show_reasoning": True,
    "show_file_button": False,
    "show_image_button": False,
}

def stored_bool(stored: dict[str, str], key: str) -> bool:
    default = "1" if BOOL_SETTINGS[key] else "0"
    value = stored.get(key, default)
    return value not in ("0", "false", "")


def to_db(value: bool) -> str:
    return "1" if value else "0"


def base_from_host_port(host: str, port: str) -> str | None:
    """Berechnete Base-URL aus Host/Port: http://<host>[:<port>]/v1."""
    host = (host or "").strip()
    if not host:
        return None
    port = (port or "").strip()
    return f"http://{host}{':' + port if port else ''}/v1"


def resolve_base_url(stored: dict[str, str], config) -> str:
    """Single Source of Truth fuer die LLM-Base-URL.

    Prioritaet: aus User-host/port berechnet > gespeicherte User-base (Legacy)
    > aus Server-Default-host/port berechnet (LEANCHAT_LLM_HOST/PORT)
    > Default 127.0.0.1:1234.
    Wird von Settings-GET/PUT-Test und vom Chat-Router verwendet.
    """
    return (
        base_from_host_port(stored.get("host") or "", stored.get("port") or "")
        or stored.get("base")
        or base_from_host_port(config.default_llm_host, config.default_llm_port)
        or base_from_host_port("127.0.0.1", "1234")
    )
