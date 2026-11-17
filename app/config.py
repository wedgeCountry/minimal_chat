from __future__ import annotations

import json
import os
import secrets
import shutil
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


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


def _env_path(name: str) -> Path | None:
    # env-example schreibt "=None" fuer nicht gesetzte Pfade; "None"/leer = nicht gesetzt
    value = os.environ.get(name, "").strip()
    if not value or value.lower() == "none":
        return None
    return Path(value)


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
    return AppConfig(
        data_dir=data,
        secret=secret or os.environ.get("LEANCHAT_SECRET") or _load_or_create_secret(data / ".secret"),
        registry_path=Path(os.environ.get("LEANCHAT_REGISTRY_PATH", str(data / "user_registry.db"))).resolve(),
        users_dir=Path(os.environ.get("LEANCHAT_USERS_DIR", str(data / "users"))).resolve(),
        default_llm_host=os.environ.get("LEANCHAT_LLM_HOST", "127.0.0.1"),
        default_llm_port=os.environ.get("LEANCHAT_LLM_PORT", "1234"),
        default_api_key=os.environ.get("LEANCHAT_API_KEY", ""),
        default_model=os.environ.get("LEANCHAT_MODEL", "gpt-4o-mini"),
        app_name=os.environ.get("LEANCHAT_APP_NAME", "LeanChat"),
        voice_base=os.environ.get("LEANCHAT_VOICE_BASE", "http://127.0.0.1:8001"),
        host=os.environ.get("LEANCHAT_HOST", "127.0.0.1"),
        port=int(os.environ.get("LEANCHAT_PORT", "8000")),
        ssl_certfile=_env_path("LEANCHAT_SSL_CERTFILE"),
        ssl_keyfile=_env_path("LEANCHAT_SSL_KEYFILE"),
        app_config_path=_env_path("LEANCHAT_CONFIG_PATH"),
        allow_private_llm=_env_bool("LEANCHAT_ALLOW_PRIVATE_LLM"),
        auto_login=_env_bool("LEANCHAT_AUTO_LOGIN"),
        max_upload_bytes=int(os.environ.get("LEANCHAT_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))),
        max_user_storage_bytes=int(os.environ.get("LEANCHAT_MAX_USER_STORAGE_BYTES", str(DEFAULT_MAX_USER_STORAGE_BYTES))),
        max_request_bytes=int(os.environ.get("LEANCHAT_MAX_REQUEST_BYTES", str(DEFAULT_MAX_REQUEST_BYTES))),
        hot_session_ttl_s=float(os.environ.get("LEANCHAT_HOT_SESSION_TTL_S", "300")),
    )
