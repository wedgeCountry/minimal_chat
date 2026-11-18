"""Setting-Keys (Single Source of Truth) + Defaults und Umwandlung DB-String <-> bool.

``BOOL_SETTINGS``/``STRING_SETTING_KEYS`` definieren die Keys einmalig; die API-Models
in app/models.py und das Frontend (static/js/settingsKeys.js) werden dagegen geprueft
(Import-Zeit-Assert unten bzw. Test in tests/test_settings_api.py).
"""

from __future__ import annotations

from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from ..config import AppConfig

BOOL_SETTINGS: dict[str, bool] = {
    "bubbles_deletable": False,
    "bubbles_checkable": False,
    "bubbles_speaker": True,
    "bubbles_minimal": True,
    "show_system_prompt": True,
    "show_tool_output": True,
    "show_reasoning": True,
    "show_file_button": False,
    "show_image_button": False,
}

STRING_SETTING_KEYS: tuple[str, ...] = ("base", "host", "port", "model", "system_prompt", "theme", "api_key", "speech_mode")
# host/port/system_prompt duerfen per leerem String geloescht werden
CLEARABLE_WITH_EMPTY: frozenset[str] = frozenset({"host", "port", "system_prompt"})

def stored_bool(stored: dict[str, str], key: str) -> bool:
    default = "1" if BOOL_SETTINGS[key] else "0"
    value = stored.get(key, default)
    return value not in ("0", "false", "")


def to_db(value: bool) -> str:
    return "1" if value else "0"


SPEECH_MODES = ("system", "server", "none")
DEFAULT_SPEECH_MODE = "server"


def stored_speech_mode(stored: dict[str, str]) -> str:
    """Gueltiger Speech-Modus aus den gespeicherten Settings (Default: server)."""
    value = stored.get("speech_mode")
    return value if value in SPEECH_MODES else DEFAULT_SPEECH_MODE


def base_from_host_port(host: str, port: str) -> str | None:
    """Berechnete Base-URL aus Host/Port: http://<host>[:<port>]/v1."""
    host = (host or "").strip()
    if not host:
        return None
    port = (port or "").strip()
    return f"http://{host}{':' + port if port else ''}/v1"


def resolve_base_url(stored: dict[str, str], config: AppConfig) -> str:
    """Single Source of Truth fuer die LLM-Base-URL.

    Prioritaet: aus User-host/port berechnet > gespeicherte User-base (Legacy)
    > aus Server-Default-host/port berechnet (LEANCHAT_LLM_HOST/PORT)
    > Default 127.0.0.1:1234.
    Wird von Settings-GET/PUT-Test und vom Chat-Router verwendet.
    """
    base = (
        base_from_host_port(stored.get("host") or "", stored.get("port") or "")
        or stored.get("base")
        or base_from_host_port(config.default_llm_host, config.default_llm_port)
    )
    fallback = base_from_host_port("127.0.0.1", "1234")
    assert fallback is not None  # Host ist nicht leer -> base_from_host_port liefert nie None
    return base or fallback


def _base_annotation(annotation: Any) -> Any:
    """Union (inkl. ``X | None``) auf den Nicht-None-Teil reduzieren."""
    args = get_args(annotation)
    if args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


def _field_names(model: type[BaseModel], kind: type[Any]) -> set[str]:
    """Namen aller Model-Felder, deren Annotation ``kind`` ist (bei str inkl. Literal-Felder)."""
    names: set[str] = set()
    for name, info in model.model_fields.items():
        base = _base_annotation(info.annotation)
        if base is kind or (kind is str and get_origin(base) is Literal):
            names.add(name)
    return names


def _assert_api_models_match() -> None:
    """Import-Zeit-Check: die API-Models in app/models.py duerfen nicht von den
    Setting-Keys hier abweichen (sonst wuerde z. B. ein neuer BOOL_SETTINGS-Eintrag
    im Settings-Response landen, den SettingsOut nicht kennt, oder nie persistiert)."""
    from ..models import SettingsIn, SettingsOut

    assert set(BOOL_SETTINGS) == _field_names(SettingsIn, bool), "SettingsIn: Bool-Felder != BOOL_SETTINGS"
    assert set(BOOL_SETTINGS) == _field_names(SettingsOut, bool), "SettingsOut: Bool-Felder != BOOL_SETTINGS"
    assert set(STRING_SETTING_KEYS) == _field_names(SettingsIn, str), "SettingsIn: String-Felder != STRING_SETTING_KEYS"
    # api_key ist das einzige beschreibbare String-Setting, das nie in die API-Antwort rausgeht (Secret)
    assert _field_names(SettingsOut, str) == set(STRING_SETTING_KEYS) - {"api_key"}, "SettingsOut: String-Felder != STRING_SETTING_KEYS ohne api_key"
    assert set(CLEARABLE_WITH_EMPTY) <= set(STRING_SETTING_KEYS), "CLEARABLE_WITH_EMPTY enthaelt unbekannte Keys"


_assert_api_models_match()
