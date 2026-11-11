from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_current_user, get_db
from ..db.database import Database
from ..models import Credentials, LoginRequest, TokenResponse
from ..security import make_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(creds: Credentials, db: Database = Depends(get_db)) -> TokenResponse:
    try:
        user = db.create_user(creds.username, creds.password, creds.key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    token = make_token(user["uid"], user["username"], db.secret)
    return TokenResponse(token=token, username=user["username"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Database = Depends(get_db)) -> TokenResponse:
    user = db.verify_login(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Ungueltige Zugangsdaten")
    token = make_token(user["uid"], user["username"], db.secret)
    return TokenResponse(token=token, username=user["username"])


@router.post("/logout")
def logout() -> dict:
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"username": user["username"]}
