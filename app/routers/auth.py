from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from user_registry import UserAlreadyExistsError

from ..auth import TERMS_VERSION, clear_auth_cookie, display_name_from_email, set_auth_cookie
from ..deps import get_current_user, get_db
from ..db.database import Database
from ..models import LoginRequest, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _email(payload_email: str) -> str:
    email = payload_email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Ungueltige E-Mail-Adresse")
    return email


@router.post("/register", status_code=201)
def register(req: RegisterRequest, request: Request, db: Database = Depends(get_db)) -> Response:
    email = _email(req.email)
    registry = request.app.state.registry
    try:
        user_id = registry.create_user(email, req.password, display_name_from_email(email), TERMS_VERSION)
    except UserAlreadyExistsError:
        raise HTTPException(status_code=409, detail="E-Mail bereits registriert") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    key = registry.get_encryption_key(email, req.password)
    if key is None:
        raise HTTPException(status_code=500, detail="Schluessel konnte nicht erzeugt werden")
    db.create_local_user(user_id, email, base64.urlsafe_b64encode(key).decode("ascii"))
    resp = JSONResponse({"email": email}, status_code=201)
    set_auth_cookie(resp, request.app, email)
    return resp


@router.post("/login")
def login(req: LoginRequest, request: Request, db: Database = Depends(get_db)) -> Response:
    email = _email(req.email)
    registry = request.app.state.registry
    if not registry.verify_password(email, req.password):
        raise HTTPException(status_code=401, detail="Ungueltige Zugangsdaten")
    if not db.get_user_by_email(email):
        raise HTTPException(status_code=401, detail="Unbekannter Benutzer")
    resp = JSONResponse({"email": email})
    set_auth_cookie(resp, request.app, email)
    return resp


@router.post("/logout")
def logout(request: Request) -> Response:
    resp = JSONResponse({"ok": True})
    clear_auth_cookie(resp, request.app)
    return resp


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"email": user["email"], "username": user["username"]}
