from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from user_registry.web.security import read_session

from .config import AppConfig, is_auto_login_enabled
from .db.database import Database


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_current_user(request: Request, db: Database = Depends(get_db)) -> dict:
    config = request.app.state.auth_config
    email = read_session(request, config, request.app.state.auth_serializer)
    
    # Auto-login mode: return the default test user if no valid session
    if (not email or not request.app.state.registry.user_exists(email)) and is_auto_login_enabled():
        registry = request.app.state.registry
        test_email = "testuser@example.com"
        test_password = "Test-1234"
        
        # Check if user exists in registry, create if not
        if not registry.user_exists(test_email):
            from .auth import display_name_from_email, TERMS_VERSION
            registry.create_user(test_email, test_password, display_name_from_email(test_email), TERMS_VERSION)
        
        # Get or create local user entry
        user = db.get_user_by_email(test_email)
        if not user:
            # For auto-login, use the email as the uid (simpler approach)
            from .db.crypto import new_key
            user_key = new_key()
            user = db.create_local_user(test_email, test_email, user_key)
        
        return user
    
    if not email or not request.app.state.registry.user_exists(email):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    user = db.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Unbekannter Benutzer")
    return user
