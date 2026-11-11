from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import AppConfig
from ..deps import get_config

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
def get_meta(config: AppConfig = Depends(get_config)) -> dict:
    return {"app_name": config.app_name}
