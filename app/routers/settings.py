from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import AppConfig
from ..db import database as dbq
from ..db.database import Database
from ..deps import get_config, get_current_user, get_db
from ..models import SettingsIn, SettingsOut, SettingsTestIn
from ..services.chat import check_llm_connection
from ..services.settings import BOOL_SETTINGS, resolve_base_url, stored_bool, stored_speech_mode, to_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings_out(stored: dict[str, str], config: AppConfig) -> SettingsOut:
    host = stored.get("host") or config.default_llm_host
    port = stored.get("port") or config.default_llm_port
    base = resolve_base_url(stored, config)
    return SettingsOut(
        base=base,
        host=host,
        port=port,
        model=stored.get("model") or config.default_model,
        system_prompt=stored.get("system_prompt") or "",
        theme=stored.get("theme") or "light",
        speech_mode=stored_speech_mode(stored),
        **{key: stored_bool(stored, key) for key in BOOL_SETTINGS},
    )


@router.get("", response_model=SettingsOut)
def get_settings(
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> SettingsOut:
    with db.user_db(user) as con:
        stored = dbq.q_get_user_settings(con)
    return _settings_out(stored, config)


@router.post("/test")
async def test_connection(
    body: SettingsTestIn,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict:
    with db.user_db(user) as con:
        stored = dbq.q_get_user_settings(con)
    base = body.base or resolve_base_url(stored, config)
    api_key = body.api_key or stored.get("api_key") or config.default_api_key
    ok, detail = await check_llm_connection(base, api_key)
    return {"ok": ok, "detail": detail}


@router.put("", response_model=SettingsOut)
def put_settings(
    body: SettingsIn,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> SettingsOut:
    with db.user_db(user) as con:
        for key in ("base", "host", "port", "model", "system_prompt", "theme", "api_key", "speech_mode"):
            value = getattr(body, key)
            # host/port/system_prompt duerfen per leerem String geloescht werden
            if value is not None and (value != "" or key in ("host", "port", "system_prompt")):
                dbq.q_set_user_setting(con, key, value)
        for key in BOOL_SETTINGS:
            value = getattr(body, key)
            if value is not None:
                dbq.q_set_user_setting(con, key, to_db(value))
        stored = dbq.q_get_user_settings(con)
    return _settings_out(stored, config)
