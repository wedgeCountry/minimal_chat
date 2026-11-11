from __future__ import annotations

import json
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

PATH_FIELDS = ("data_dir", "registry_path", "users_dir", "app_config_path")


@dataclass
class AppConfig:
    """Alle globalen Variablen der App.

    Wird beim Programmstart aus den Umgebungsvariablen generiert und als
    App-Config-Datei (JSON) abgelegt; Tests koennen das Objekt direkt
    uebergeben, ohne auf Systemvariablen zugreifen zu muessen.
    """

    data_dir: Path
    secret: str
    registry_path: Path
    users_dir: Path
    default_llm_base: str = "https://api.openai.com/v1"
    default_api_key: str = ""
    default_model: str = "gpt-4o-mini"
    host: str = "127.0.0.1"
    port: int = 8000
    app_config_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "data_dir": str(self.data_dir),
            "secret": self.secret,
            "registry_path": str(self.registry_path),
            "users_dir": str(self.users_dir),
            "default_llm_base": self.default_llm_base,
            "default_api_key": self.default_api_key,
            "default_model": self.default_model,
            "host": self.host,
            "port": self.port,
            "app_config_path": str(self.app_config_path) if self.app_config_path else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        kwargs = dict(data)
        for key in PATH_FIELDS:
            if kwargs.get(key) is not None:
                kwargs[key] = Path(kwargs[key])
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
    """Erzeugt die .env beim ersten Programmstart aus der .env-Example."""
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
    data_dir: str | os.PathLike | None = None,
    secret: str | None = None,
) -> AppConfig:
    data = Path(data_dir or os.environ.get("LEANCHAT_DATA_DIR", "data")).resolve()
    data.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        data_dir=data,
        secret=secret or os.environ.get("LEANCHAT_SECRET") or _load_or_create_secret(data / ".secret"),
        registry_path=Path(os.environ.get("LEANCHAT_REGISTRY_PATH", str(data / "user_registry.db"))).resolve(),
        users_dir=Path(os.environ.get("LEANCHAT_USERS_DIR", str(data / "users"))).resolve(),
        default_llm_base=os.environ.get("LEANCHAT_LLM_BASE", "https://api.openai.com/v1"),
        default_api_key=os.environ.get("LEANCHAT_API_KEY", ""),
        default_model=os.environ.get("LEANCHAT_MODEL", "gpt-4o-mini"),
        host=os.environ.get("LEANCHAT_HOST", "127.0.0.1"),
        port=int(os.environ.get("LEANCHAT_PORT", "8000")),
        app_config_path=Path(os.environ["LEANCHAT_CONFIG_PATH"]) if os.environ.get("LEANCHAT_CONFIG_PATH") else None,
    )
