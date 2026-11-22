from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..config import AppConfig
from ..deps import get_config, get_current_user, get_store
from ..domain import LlmModel
from ..models import LlmModelIn, LlmModelOut, LlmModelTestIn
from ..services.llm import check_llm_connection
from ..services.settings import default_base_url, model_base_url
from ..services.ssrf import validate_llm_base_url
from ..services.store import LlmModelNotFound, UserStoreProtocol
from ..types import UserIdentity

router = APIRouter(prefix="/api/settings/models", tags=["settings"])

# Felder eines Tiles, die per PUT geloescht werden duerfen (api_key nicht: write-only, leer = unveraendert)
_MODEL_FIELDS = ("provider", "host", "port", "base", "api_key", "model")
_CLEARABLE_MODEL_FIELDS = frozenset(_MODEL_FIELDS) - {"api_key"}


def _out(model: LlmModel) -> LlmModelOut:
    # api_key ist ein Secret und bleibt in der Antwort aussen vor
    return LlmModelOut(
        id=model.id,
        provider=model.provider,
        host=model.host,
        port=model.port,
        base=model.base,
        model=model.model,
    )


def _values_from(body: LlmModelIn) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in _MODEL_FIELDS:
        value = getattr(body, key)
        if value is not None and (value != "" or key in _CLEARABLE_MODEL_FIELDS):
            values[key] = value
    return values


async def _get_or_404(store: UserStoreProtocol, user: UserIdentity, model_id: int) -> LlmModel:
    model = await store.get_llm_model(user, model_id)
    if model is None:
        raise LlmModelNotFound(str(model_id))
    return model


@router.get("", response_model=list[LlmModelOut])
async def list_models(
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> list[LlmModelOut]:
    return [_out(m) for m in await store.list_llm_models(user)]


@router.post("", response_model=LlmModelOut, status_code=201)
async def create_model(
    body: LlmModelIn,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> LlmModelOut:
    return _out(await store.create_llm_model(user, _values_from(body)))


@router.post("/test")
async def test_connection(
    body: LlmModelTestIn,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
    config: AppConfig = Depends(get_config),
) -> dict[str, object]:
    """Verbindungstest: explizite base/api_key aus dem Body gewinnen sonst gegen das
    referenzierte Tile (body.model_id) bzw. die Server-Defaults."""
    model: LlmModel | None = None
    if body.model_id is not None:
        model = await _get_or_404(store, user, body.model_id)
    base = body.base or (model_base_url(model, config) if model else default_base_url(config))
    try:
        # DNS-Lookup in validate_llm_base_url ist blockierend -> nicht auf dem Event-Loop
        await asyncio.to_thread(validate_llm_base_url, base, config.allow_private_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    api_key = body.api_key or (model.api_key if model else "") or config.default_api_key
    # Modell-Verfuegbarkeit wird nur geprueft, wenn der Client explizit ein Modell sendet
    # (leeres Feld im Modal = nur Erreichbarkeit testen + models-Liste fuer das Dropdown)
    model_name = body.model or ""
    ok, detail, offered = await check_llm_connection(base, api_key, model_name)
    # offered: Modell-Liste aus GET /models (Client baut daraus bei leerem Modell-Feld ein Dropdown)
    return {"ok": ok, "detail": detail, "models": offered}


@router.get("/{model_id}", response_model=LlmModelOut)
async def get_model(
    model_id: int,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> LlmModelOut:
    return _out(await _get_or_404(store, user, model_id))


@router.put("/{model_id}", response_model=LlmModelOut)
async def update_model(
    model_id: int,
    body: LlmModelIn,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> LlmModelOut:
    await _get_or_404(store, user, model_id)
    updated = await store.update_llm_model(user, model_id, _values_from(body))
    assert updated is not None
    return _out(updated)


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: int,
    user: UserIdentity = Depends(get_current_user),
    store: UserStoreProtocol = Depends(get_store),
) -> None:
    if not await store.delete_llm_model(user, model_id):
        raise LlmModelNotFound(str(model_id))
