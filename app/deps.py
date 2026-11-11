from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from user_registry.web.security import read_session

from .config import AppConfig
from .db.database import Database


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_current_user(request: Request, db: Database = Depends(get_db)) -> dict:
    config = request.app.state.auth_config
    email = read_session(request, config, request.app.state.auth_serializer)
    if not email or not request.app.state.registry.user_exists(email):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    user = db.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Unbekannter Benutzer")
    return user
