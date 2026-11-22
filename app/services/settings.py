"""Setting-Keys (Single Source of Truth) + Defaults und Umwandlung DB-String <-> bool.

``BOOL_SETTINGS``/``STRING_SETTING_KEYS`` definieren die Keys einmalig; die API-Models
in app/models.py und das Frontend (static/js/settingsKeys.js) werden dagegen geprueft
(Import-Zeit-Assert unten bzw. Test in tests/test_settings_api.py).
"""

from __future__ import annotations

from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from ..config import AppConfig
from ..domain import LlmConnection, LlmModel

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

# LLM-Verbindungsdaten liegen nicht mehr als flache Keys hier, sondern in der
# Tabelle llm_models (siehe LlmModel in app/domain.py); default_model_id zeigt auf
# das Standard-Tile (user_settings), das neue Sessions ohne eigenes model_id nutzen.
STRING_SETTING_KEYS: tuple[str, ...] = ("default_model_id", "system_prompt", "theme", "speech_mode")
# system_prompt darf per leerem String geloescht werden
CLEARABLE_WITH_EMPTY: frozenset[str] = frozenset({"system_prompt"})

# Session-Settings (pro Session, key/value in der Tabelle session_settings)
SESSION_SETTING_KEYS: tuple[str, ...] = ("system_prompt", "model_id")
# system_prompt/model_id duerfen per leerem String geloescht werden (model_id leer = Standard-Tile)
SESSION_CLEARABLE_WITH_EMPTY: frozenset[str] = frozenset({"system_prompt", "model_id"})


def resolve_system_prompt(session_settings: dict[str, str], stored: dict[str, str]) -> str:
    """Effektiver System-Prompt: ein nicht-leerer Session-Prompt gewinnt, sonst der globale Settings-Prompt."""
    prompt = (session_settings.get("system_prompt") or "").strip()
    return prompt or (stored.get("system_prompt") or "")

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


def default_base_url(config: AppConfig) -> str:
    """Base-URL aus den Server-Defaults (LEANCHAT_LLM_HOST/PORT)."""
    base = base_from_host_port(config.default_llm_host, config.default_llm_port)
    assert base is not None  # default_llm_host ist nicht leer (min_length=1)
    return base


def model_base_url(model: LlmModel, config: AppConfig) -> str:
    """Base-URL eines Tiles: aus host/port berechnet > gespeicherte base > Server-Default."""
    return base_from_host_port(model.host, model.port) or model.base or default_base_url(config)


def resolve_llm_connection(
    session_settings: dict[str, str],
    user_settings: dict[str, str],
    models: list[LlmModel],
    config: AppConfig,
) -> LlmConnection:
    """Single Source of Truth fuer die effektive LLM-Verbindung eines Chat-Requests.

    Prioritaet: Session-model_id > User-default_model_id > Server-Defaults (ohne Tile).
    Ungueltige/fehlende Tile-Referenzen fallen auf die naechste Stufe zurueck.
    """
    by_id = {m.id: m for m in models}
    for source, key in ((session_settings, "model_id"), (user_settings, "default_model_id")):
        raw = (source.get(key) or "").strip()
        if raw.isdigit():
            model = by_id.get(int(raw))
            if model is not None:
                return LlmConnection(
                    base_url=model_base_url(model, config),
                    api_key=model.api_key or config.default_api_key,
                    model=model.model or config.default_model,
                )
    return LlmConnection(base_url=default_base_url(config), api_key=config.default_api_key, model=config.default_model)


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
    from ..models import SessionSettingsIn, SessionSettingsOut, SettingsIn, SettingsOut

    assert set(BOOL_SETTINGS) == _field_names(SettingsIn, bool), "SettingsIn: Bool-Felder != BOOL_SETTINGS"
    assert set(BOOL_SETTINGS) == _field_names(SettingsOut, bool), "SettingsOut: Bool-Felder != BOOL_SETTINGS"
    assert set(STRING_SETTING_KEYS) == _field_names(SettingsIn, str), "SettingsIn: String-Felder != STRING_SETTING_KEYS"
    assert _field_names(SettingsOut, str) == set(STRING_SETTING_KEYS), "SettingsOut: String-Felder != STRING_SETTING_KEYS"
    assert set(CLEARABLE_WITH_EMPTY) <= set(STRING_SETTING_KEYS), "CLEARABLE_WITH_EMPTY enthaelt unbekannte Keys"
    assert set(SESSION_SETTING_KEYS) == _field_names(SessionSettingsIn, str), "SessionSettingsIn: String-Felder != SESSION_SETTING_KEYS"
    # session_id ist zusaetzlich in der Antwort, damit der Client sie nicht selbst einsetzen muss
    assert _field_names(SessionSettingsOut, str) == set(SESSION_SETTING_KEYS) | {"session_id"}, "SessionSettingsOut: String-Felder != SESSION_SETTING_KEYS + session_id"
    assert set(SESSION_CLEARABLE_WITH_EMPTY) <= set(SESSION_SETTING_KEYS), "SESSION_CLEARABLE_WITH_EMPTY enthaelt unbekannte Keys"


_assert_api_models_match()
