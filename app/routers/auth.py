from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from ..auth import clear_auth_cookie
from ..deps import get_current_user
from ..types import UserIdentity

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/logout")
def logout(request: Request) -> Response:
    resp = JSONResponse({"ok": True})
    clear_auth_cookie(resp, request.app)
    return resp


@router.get("/me")
def me(user: UserIdentity = Depends(get_current_user)) -> dict[str, str]:
    return {"email": user["email"], "username": user["username"]}


@router.get("/config")
def get_auth_config(request: Request) -> dict[str, bool]:
    """Get authentication configuration, including auto-login status."""
    auto_login: bool = request.app.state.config.auto_login
    return {"auto_login": auto_login}
