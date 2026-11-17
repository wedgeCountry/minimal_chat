from __future__ import annotations

from fastapi import HTTPException, Request

from user_registry.web.security import read_session

from .auth import TERMS_VERSION, display_name_from_email, user_identity
from .config import AppConfig
from .services.chat import MessageService
from .services.store import UserStoreProtocol
from .types import UserIdentity


def get_config(request: Request) -> AppConfig:
    config: AppConfig = request.app.state.config
    return config


def get_store(request: Request) -> UserStoreProtocol:
    store: UserStoreProtocol = request.app.state.store
    return store


def get_message_service(request: Request) -> MessageService:
    service: MessageService = request.app.state.message_service
    return service


def get_session_email(request: Request) -> str | None:
    """E-Mail der gueltigen Session (inkl. Auto-Login-Testmodus) oder None."""
    registry = request.app.state.registry
    email: str | None = read_session(request, request.app.state.auth_config, request.app.state.auth_serializer)

    # Auto-login mode: serve the default test user if no valid session
    if (not email or not registry.user_exists(email)) and request.app.state.config.auto_login:
        email = "testuser@example.com"
        if not registry.user_exists(email):
            registry.create_user(email, "Test-1234", display_name_from_email(email), TERMS_VERSION)

    if not email or not registry.user_exists(email):
        return None
    return email


def get_current_user(request: Request) -> UserIdentity:
    email = get_session_email(request)
    if email is None:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    secret: str = request.app.state.config.secret
    return user_identity(secret, email)
