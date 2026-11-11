from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    data_dir: Path
    secret: str
    default_llm_base: str = "https://api.openai.com/v1"
    default_api_key: str = ""
    default_model: str = "gpt-4o-mini"


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
        default_llm_base=os.environ.get("LEANCHAT_LLM_BASE", "https://api.openai.com/v1"),
        default_api_key=os.environ.get("LEANCHAT_API_KEY", ""),
        default_model=os.environ.get("LEANCHAT_MODEL", "gpt-4o-mini"),
    )
