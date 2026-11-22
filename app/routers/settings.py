from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_current_user, get_store
from ..models import SettingsIn, SettingsOut
from ..services.settings import BOOL_SETTINGS, CLEARABLE_WITH_EMPTY, STRING_SETTING_KEYS, stored_bool, stored_speech_mode, to_db
from ..services.store import UserStoreProtocol
from ..types import UserIdentity

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings_out(stored: dict[str, str]) -> SettingsOut:
    return SettingsOut(
        default_model_id=stored.get("default_model_id") or "",
        system_prompt=stored.get("system_prompt") or "",
        theme=stored.get("theme") or "light",
        speech_mode=stored_speech_mode(stored),
        **{key: stored_bool(stored, key) for key in BOOL_SETTINGS},
    )


@router.get("", response_model=SettingsOut)
async def get_settings(
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> SettingsOut:
    stored = await store.get_user_settings(user)
    return _settings_out(stored)


@router.put("", response_model=SettingsOut)
async def put_settings(
    body: SettingsIn,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> SettingsOut:
    values: dict[str, str] = {}
    for key in STRING_SETTING_KEYS:
        value = getattr(body, key)
        if value is not None and (value != "" or key in CLEARABLE_WITH_EMPTY):
            values[key] = value
    if "default_model_id" in values and values["default_model_id"]:
        raw = values["default_model_id"]
        if not raw.isdigit():
            raise HTTPException(status_code=422, detail="default_model_id muss eine numerische Modell-ID sein")
        if await store.get_llm_model(user, int(raw)) is None:
            raise HTTPException(status_code=422, detail=f"Unbekanntes Modell: {raw}")
    for key in BOOL_SETTINGS:
        value = getattr(body, key)
        if value is not None:
            values[key] = to_db(value)
    stored = await store.update_user_settings(user, values)
    return _settings_out(stored)
