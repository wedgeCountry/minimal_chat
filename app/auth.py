"""Login/Registrierung ueber die externe user_registry-Bibliothek.

Integration wie in docs/user_registry_implementation_guidelines.md beschrieben:
eigene Registry-DB (plain SQLite, von der Bibliothek verwaltet), signierte
Session-Cookies (``auth_session``) ueber ``mount_auth`` sowie die
professionellen Auth-Seiten unter ``/auth`` (Login, Registrieren,
Passwort aendern/loeschen, AGB, Impressum). Die lokalen User-Daten
(verschluesselte per-user DBs) werden ueber eine credential-freie lokale
``users``-Tabelle per E-Mail zugeordnet (siehe db/database.py).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Response

from user_registry import UserRegistry
from user_registry.web import AuthConfig, mount_auth
from user_registry.web.security import make_serializer, sign_session

from .config import REPO_ROOT, AppConfig

TERMS_VERSION = "2025-01"


def init_auth(app: FastAPI, cfg: AppConfig) -> AuthConfig:
    registry = UserRegistry(cfg.registry_path)
    registry.init_db()
    _, config = mount_auth(
        app,
        registry,
        prefix="/auth",
        secret_key=cfg.secret,
        terms={"version": TERMS_VERSION},
        imprint={"document": str(REPO_ROOT / "docs" / "impressum.html")},
        login_redirect="/",
        cookie_secure=False,
    )
    app.state.registry = registry
    app.state.auth_config = config
    app.state.auth_serializer = make_serializer(config)
    return config


def set_auth_cookie(response: Response, app: FastAPI, email: str) -> None:
    config: AuthConfig = app.state.auth_config
    response.set_cookie(
        config.session_cookie,
        sign_session(config, app.state.auth_serializer, email),
        max_age=config.session_max_age,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure,
    )


def clear_auth_cookie(response: Response, app: FastAPI) -> None:
    config: AuthConfig = app.state.auth_config
    response.delete_cookie(config.session_cookie)


def display_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0].strip()
    return local or email
