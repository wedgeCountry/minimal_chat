from __future__ import annotations

import logging

from fastapi import APIRouter

from ..models import ClientLogIn

router = APIRouter(prefix="/api/log", tags=["log"])

logger = logging.getLogger("leanchat.client")


@router.post("")
def post_client_log(body: ClientLogIn) -> dict:
    # Client-seitige Fehler landen so im Server-Konsolen-Log.
    logger.log(getattr(logging, body.level.upper(), logging.ERROR), "client: %s", body.message)
    return {"ok": True}
