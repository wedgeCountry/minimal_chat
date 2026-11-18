from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..config import AppConfig
from ..deps import get_config, get_current_user, get_store
from ..models import SettingsIn, SettingsOut, SettingsTestIn
from ..services.llm import check_llm_connection
from ..services.ssrf import validate_llm_base_url
from ..services.settings import BOOL_SETTINGS, CLEARABLE_WITH_EMPTY, STRING_SETTING_KEYS, resolve_base_url, stored_bool, stored_speech_mode, to_db
from ..services.store import UserStoreProtocol
from ..types import UserIdentity

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
async def get_settings(
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
    config: AppConfig = Depends(get_config),
) -> SettingsOut:
    stored = await store.get_user_settings(user)
    return _settings_out(stored, config)


@router.post("/test")
async def test_connection(
    body: SettingsTestIn,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
    config: AppConfig = Depends(get_config),
) -> dict[str, object]:
    stored = await store.get_user_settings(user)
    base = body.base or resolve_base_url(stored, config)
    try:
        # DNS-Lookup in validate_llm_base_url ist blockierend -> nicht auf dem Event-Loop
        await asyncio.to_thread(validate_llm_base_url, base, config.allow_private_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    api_key = body.api_key or stored.get("api_key") or config.default_api_key
    ok, detail = await check_llm_connection(base, api_key)
    return {"ok": ok, "detail": detail}


@router.put("", response_model=SettingsOut)
async def put_settings(
    body: SettingsIn,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
    config: AppConfig = Depends(get_config),
) -> SettingsOut:
    values: dict[str, str] = {}
    for key in STRING_SETTING_KEYS:
        value = getattr(body, key)
        if value is not None and (value != "" or key in CLEARABLE_WITH_EMPTY):
            values[key] = value
    for key in BOOL_SETTINGS:
        value = getattr(body, key)
        if value is not None:
            values[key] = to_db(value)
    stored = await store.update_user_settings(user, values)
    return _settings_out(stored, config)
