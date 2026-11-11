from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import AppConfig
from ..db import database as dbq
from ..db.database import Database
from ..deps import get_config, get_current_user, get_db
from ..models import SettingsIn, SettingsOut

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings(
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> SettingsOut:
    with db.user_db(user) as con:
        stored = dbq.q_get_user_settings(con)
    return SettingsOut(
        base=stored.get("base") or config.default_llm_base,
        model=stored.get("model") or config.default_model,
        theme=stored.get("theme") or "light",
    )


@router.put("", response_model=SettingsOut)
def put_settings(
    body: SettingsIn,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> SettingsOut:
    with db.user_db(user) as con:
        for key in ("base", "model", "theme", "api_key"):
            value = getattr(body, key)
            if value is not None and value != "":
                dbq.q_set_user_setting(con, key, value)
        stored = dbq.q_get_user_settings(con)
    return SettingsOut(
        base=stored.get("base") or config.default_llm_base,
        model=stored.get("model") or config.default_model,
        theme=stored.get("theme") or "light",
    )
