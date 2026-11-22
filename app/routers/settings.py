from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_current_user, get_store
from ..models import SettingsIn, SettingsOut
from ..services.settings import BOOL_SETTINGS, CLEARABLE_WITH_EMPTY, STRING_SETTING_KEYS, stored_bool, stored_queue_behavior, stored_speech_mode, to_db
from ..services.store import LlmModelNotFound, UserStoreProtocol
from ..types import UserIdentity

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings_out(stored: dict[str, str]) -> SettingsOut:
    return SettingsOut(
        default_model_id=stored.get("default_model_id") or "",
        system_prompt=stored.get("system_prompt") or "",
        theme=stored.get("theme") or "light",
        speech_mode=stored_speech_mode(stored),
        queue_behavior=stored_queue_behavior(stored),
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
    # default_model_id wird ueber eine eigene Store-Methode geschrieben: Validierung
    # (Tile existiert) und Schreiben laufen in einem einzigen DB-Oeffnen
    stored: dict[str, str] | None = None
    default_raw = values.pop("default_model_id", "")
    if default_raw:
        if not default_raw.isdigit():
            raise HTTPException(status_code=422, detail="default_model_id muss eine numerische Modell-ID sein")
        try:
            stored = await store.set_default_model(user, int(default_raw))
        except LlmModelNotFound:
            raise HTTPException(status_code=422, detail=f"Unbekanntes Modell: {default_raw}")
    for key in BOOL_SETTINGS:
        value = getattr(body, key)
        if value is not None:
            values[key] = to_db(value)
    if values:
        stored = await store.update_user_settings(user, values)
    if stored is None:
        stored = await store.get_user_settings(user)
    return _settings_out(stored)
