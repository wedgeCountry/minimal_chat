from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_current_user
from ..models import ClientLogIn

router = APIRouter(prefix="/api/log", tags=["log"])

logger = logging.getLogger("leanchat.client")

RATE_LIMIT = 30
RATE_WINDOW_S = 60.0
_hits: dict[str, deque[float]] = defaultdict(deque)


@router.post("")
def post_client_log(body: ClientLogIn, user: dict = Depends(get_current_user)) -> dict:
    # Client-seitige Fehler landen so im Server-Konsolen-Log.
    # Nur authentifizierte Clients, mit Rate-Limit gegen Log-Spam.
    now = time.monotonic()
    hits = _hits[user["uid"]]
    while hits and now - hits[0] > RATE_WINDOW_S:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Zu viele Log-Eintraege, bitte spaeter erneut")
    hits.append(now)
    logger.log(getattr(logging, body.level.upper(), logging.ERROR), "client: %s", body.message)
    return {"ok": True}
