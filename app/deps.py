from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from .config import AppConfig
from .db.database import Database
from .security import verify_token


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Database = Depends(get_db),
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    payload = verify_token(authorization.removeprefix("Bearer "), db.secret)
    if not payload:
        raise HTTPException(status_code=401, detail="Ungueltiger oder abgelaufener Token")
    user = db.get_user_by_id(payload["uid"])
    if not user:
        raise HTTPException(status_code=401, detail="Unbekannter Benutzer")
    return user
