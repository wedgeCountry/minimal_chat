from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import get_current_user
from ..models import VisitIn
from ..types import UserIdentity
from ..visit_stack import session_key

router = APIRouter(prefix="/api", tags=["visits"])


def _is_local_path(path: str) -> bool:
    # nur lokale Pfade (ggf. mit Fragment); nie "//host" oder ein Schema
    return path.startswith("/") and not path.startswith("//") and "\\" not in path


@router.post("/visits")
def record_visit(payload: VisitIn, request: Request, user: UserIdentity = Depends(get_current_user)) -> dict[str, bool]:
    """Haelt einen besuchten In-App-View (gleiche URL, anderer Zustand) im
    Page-Visit-Stack der Session fest (Limit: ``visit_stack_size``), damit ein
    Zurueck-Navigieren aus der App auf die zuletzt besuchte Seite fuehrt."""
    if not _is_local_path(payload.path):
        raise HTTPException(status_code=422, detail="Nur lokale Pfade erlaubt")
    key = session_key(request)
    if key is not None:
        request.app.state.visit_stacks.push(key, payload.path)
    return {"ok": True}
