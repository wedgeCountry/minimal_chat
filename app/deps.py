from __future__ import annotations

from fastapi import HTTPException, Request

from user_registry.web.security import read_session

from .auth import AUTO_LOGIN_PASSWORD, TERMS_VERSION, display_name_from_email, user_identity
from .config import AppConfig, is_auto_login_enabled
from .db.database import Database


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_session_email(request: Request) -> str | None:
    """E-Mail der gueltigen Session (inkl. Auto-Login-Testmodus) oder None."""
    registry = request.app.state.registry
    email = read_session(request, request.app.state.auth_config, request.app.state.auth_serializer)

    # Auto-login mode: serve the default test user if no valid session
    if (not email or not registry.user_exists(email)) and is_auto_login_enabled():
        email = "testuser@example.com"
        if not registry.user_exists(email):
            registry.create_user(email, AUTO_LOGIN_PASSWORD, display_name_from_email(email), TERMS_VERSION)

    if not email or not registry.user_exists(email):
        return None
    return email


def get_current_user(request: Request) -> dict:
    app = request.app
    email = get_session_email(request)
    if email is None:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    token = request.cookies.get(app.state.auth_config.session_cookie)
    if token:
        # DB-Schluessel liegt serverseitig pro Session (beim Login abgeleitet); ein Cookie
        # ohne hinterlegten Schluessel (z. B. nach Server-Neustart) hat keinen DB-Zugriff
        identity = app.state.session_keys.get(token)
        if identity is not None and identity["email"] == email:
            return dict(identity)
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    if is_auto_login_enabled():
        return user_identity(email, AUTO_LOGIN_PASSWORD, app.state.keystore)
    raise HTTPException(status_code=401, detail="Nicht authentifiziert")
