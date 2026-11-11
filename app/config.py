from __future__ import annotations

import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"


@dataclass
class AppConfig:
    data_dir: Path
    secret: str
    registry_path: Path
    users_dir: Path
    default_llm_base: str = "https://api.openai.com/v1"
    default_api_key: str = ""
    default_model: str = "gpt-4o-mini"
    host: str = "127.0.0.1"
    port: int = 8000


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
        registry_path=Path(os.environ.get("LEANCHAT_REGISTRY_PATH", str(data / "user_registry.db.enc"))).resolve(),
        users_dir=Path(os.environ.get("LEANCHAT_USERS_DIR", str(data / "users"))).resolve(),
        default_llm_base=os.environ.get("LEANCHAT_LLM_BASE", "https://api.openai.com/v1"),
        default_api_key=os.environ.get("LEANCHAT_API_KEY", ""),
        default_model=os.environ.get("LEANCHAT_MODEL", "gpt-4o-mini"),
        host=os.environ.get("LEANCHAT_HOST", "127.0.0.1"),
        port=int(os.environ.get("LEANCHAT_PORT", "8000")),
    )
