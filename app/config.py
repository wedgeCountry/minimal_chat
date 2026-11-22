from __future__ import annotations

import json
import os
import secrets
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / "env-example"

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_USER_STORAGE_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_REQUEST_BYTES = 25 * 1024 * 1024
DEFAULT_VISIT_STACK_SIZE = 20


def _parse_env_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _parse_env_path(value: str) -> Path | None:
    # env-example schreibt "=None" fuer nicht gesetzte Pfade; "None"/leer = nicht gesetzt
    v = value.strip()
    if not v or v.lower() == "none":
        return None
    return Path(v)


class AppConfig(BaseModel):
    """Alle globalen Variablen der App (Pydantic-Model: Typen + Constraints werden
    bei jeder Erzeugung geprueft, z. B. Port 1-65535 und positive Byte-Limits).

    Wird beim Programmstart aus den Umgebungsvariablen generiert (load_config) und als
    App-Config-Datei (JSON) abgelegt; Tests koennen das Objekt direkt
    uebergeben, ohne auf Systemvariablen zugreifen zu muessen. Bewusst kein
    BaseSettings: die Umgebung wird nur in load_config explizit gelesen, damit
    ein uebergebenes Config-Objekt nie von Umgebungsvariablen ueberschrieben wird.
    """

    model_config = ConfigDict(extra="forbid")

    data_dir: Path
    secret: str
    registry_path: Path
    users_dir: Path
    default_llm_host: str = Field(default="127.0.0.1", min_length=1)
    default_llm_port: str = "1234"
    default_api_key: str = ""
    default_model: str = "gpt-4o-mini"
    app_name: str = Field(default="LeanChat", min_length=1)
    voice_base: str = Field(default="http://127.0.0.1:8001", min_length=1)
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    ssl_certfile: Path | None = None
    ssl_keyfile: Path | None = None
    app_config_path: Path | None = None
    allow_private_llm: bool = False
    auto_login: bool = False
    max_upload_bytes: int = Field(default=DEFAULT_MAX_UPLOAD_BYTES, ge=1)
    max_user_storage_bytes: int = Field(default=DEFAULT_MAX_USER_STORAGE_BYTES, ge=1)
    max_request_bytes: int = Field(default=DEFAULT_MAX_REQUEST_BYTES, ge=1)
    hot_session_ttl_s: float = Field(default=300.0, ge=0)  # In-Memory-Session-State im MessageService
    visit_stack_size: int = Field(default=DEFAULT_VISIT_STACK_SIZE, ge=1)  # Page-Visit-Stack pro User/Session

    @model_validator(mode="after")
    def _loopback_allows_private_llm(self) -> "AppConfig":
        # Loopback-Bind = nur lokal erreichbar, daher private LLM-Ziele ok
        if self.host in LOOPBACK_HOSTS:
            self.allow_private_llm = True
        return self

    def to_dict(self) -> dict[str, Any]:
        # secret und default_api_key werden bewusst NICHT persistiert:
        # keine Secrets at rest in der app_config.json (liegen in .env/.secret).
        return {
            "data_dir": str(self.data_dir),
            "registry_path": str(self.registry_path),
            "users_dir": str(self.users_dir),
            "default_llm_host": self.default_llm_host,
            "default_llm_port": self.default_llm_port,
            "default_model": self.default_model,
            "app_name": self.app_name,
            "voice_base": self.voice_base,
            "host": self.host,
            "port": self.port,
            "ssl_certfile": str(self.ssl_certfile) if self.ssl_certfile else None,
            "ssl_keyfile": str(self.ssl_keyfile) if self.ssl_keyfile else None,
            "app_config_path": str(self.app_config_path) if self.app_config_path else None,
            "allow_private_llm": self.allow_private_llm,
            "auto_login": self.auto_login,
            "max_upload_bytes": self.max_upload_bytes,
            "max_user_storage_bytes": self.max_user_storage_bytes,
            "max_request_bytes": self.max_request_bytes,
            "hot_session_ttl_s": self.hot_session_ttl_s,
            "visit_stack_size": self.visit_stack_size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        # str-Pfade werden vom Model automatisch nach Path koerziert
        kwargs = dict(data)
        kwargs.setdefault("secret", "")
        kwargs.setdefault("default_api_key", "")
        return cls(**kwargs)

    def config_file(self) -> Path:
        return self.app_config_path or self.data_dir / "app_config.json"

    def save(self, path: Path | None = None) -> Path:
        """Schreibt die App-Config als JSON-Datei (Default: <data_dir>/app_config.json)."""
        target = Path(path) if path else self.config_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# AppConfig-Feld <- (Env-Variable, Parser). Single Source of Truth fuer das Env-Mapping;
# jede Env-Variable muss in env-example dokumentiert sein (AGENTS.md Regel 14,
# wird von tests/test_config.py gegen env-example geprueft).
ENV_FIELD_SPEC: dict[str, tuple[str, Callable[[str], Any]]] = {
    "default_llm_host": ("LEANCHAT_LLM_HOST", str),
    "default_llm_port": ("LEANCHAT_LLM_PORT", str),
    "default_api_key": ("LEANCHAT_API_KEY", str),
    "default_model": ("LEANCHAT_MODEL", str),
    "app_name": ("LEANCHAT_APP_NAME", str),
    "voice_base": ("LEANCHAT_VOICE_BASE", str),
    "host": ("LEANCHAT_HOST", str),
    "port": ("LEANCHAT_PORT", int),
    "ssl_certfile": ("LEANCHAT_SSL_CERTFILE", _parse_env_path),
    "ssl_keyfile": ("LEANCHAT_SSL_KEYFILE", _parse_env_path),
    "app_config_path": ("LEANCHAT_CONFIG_PATH", _parse_env_path),
    "allow_private_llm": ("LEANCHAT_ALLOW_PRIVATE_LLM", _parse_env_bool),
    "auto_login": ("LEANCHAT_AUTO_LOGIN", _parse_env_bool),
    "max_upload_bytes": ("LEANCHAT_MAX_UPLOAD_BYTES", int),
    "max_user_storage_bytes": ("LEANCHAT_MAX_USER_STORAGE_BYTES", int),
    "max_request_bytes": ("LEANCHAT_MAX_REQUEST_BYTES", int),
    "hot_session_ttl_s": ("LEANCHAT_HOT_SESSION_TTL_S", float),
    "visit_stack_size": ("LEANCHAT_VISIT_STACK_SIZE", int),
}


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_env_file(path: Path) -> dict[str, str]:
    """Laedt eine .env-Datei in os.environ; bestehende Variablen gewinnen."""
    if not path.exists():
        return {}
    values = parse_env_text(path.read_text(encoding="utf-8"))
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values


def ensure_env_file(env_file: Path = ENV_FILE, example: Path = ENV_EXAMPLE) -> Path:
    """Erzeugt die .env beim ersten Programmstart aus der env-example."""
    if not env_file.exists() and example.exists():
        shutil.copyfile(example, env_file)
    return env_file


def bootstrap_env() -> Path:
    """Programmstart: .env falls noetig generieren und laden."""
    env_file = ensure_env_file()
    load_env_file(env_file)
    return env_file


def _load_or_create_secret(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secret, encoding="utf-8")
    path.chmod(0o600)
    return secret


def load_config(
    data_dir: str | os.PathLike[str] | None = None,
    secret: str | None = None,
) -> AppConfig:
    data = Path(data_dir or os.environ.get("LEANCHAT_DATA_DIR", "data")).resolve()
    data.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "data_dir": data,
        "secret": secret or os.environ.get("LEANCHAT_SECRET") or _load_or_create_secret(data / ".secret"),
        "registry_path": Path(os.environ.get("LEANCHAT_REGISTRY_PATH", str(data / "user_registry.db"))).resolve(),
        "users_dir": Path(os.environ.get("LEANCHAT_USERS_DIR", str(data / "users"))).resolve(),
    }
    # Nicht gesetzte Env-Variablen fehlen im kwargs -> Pydantic-Default greift
    for field, (env_name, parse) in ENV_FIELD_SPEC.items():
        raw = os.environ.get(env_name)
        if raw is not None:
            kwargs[field] = parse(raw)
    return AppConfig(**kwargs)
