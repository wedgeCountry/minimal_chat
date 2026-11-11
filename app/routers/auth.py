from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from ..auth import clear_auth_cookie
from ..deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/logout")
def logout(request: Request) -> Response:
    resp = JSONResponse({"ok": True})
    clear_auth_cookie(resp, request.app)
    return resp


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"email": user["email"], "username": user["username"]}


@router.get("/config")
def get_auth_config() -> dict:
    """Get authentication configuration, including auto-login status."""
    from ..config import is_auto_login_enabled
    return {"auto_login": is_auto_login_enabled()}
