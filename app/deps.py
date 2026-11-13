from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from user_registry.web.security import read_session

from .auth import TERMS_VERSION, display_name_from_email, user_identity
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
            registry.create_user(email, "Test-1234", display_name_from_email(email), TERMS_VERSION)

    if not email or not registry.user_exists(email):
        return None
    return email


def get_current_user(request: Request) -> dict:
    email = get_session_email(request)
    if email is None:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    return user_identity(request.app.state.config.secret, email)
