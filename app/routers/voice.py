from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response

from ..config import AppConfig
from ..deps import get_config, get_current_user
from ..models import VoiceTTSRequest
from ..services.files import read_upload_capped
from ..types import UserIdentity
from ..services.voice import (
    check_voice_service,
    synthesize_speech,
    transcribe_speech,
)

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.get("/status")
async def voice_status(
    user: UserIdentity = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
) -> dict[str, bool]:
    """Funktionspruefung des Voice-Companion (STT + TTS ueber /health)."""
    available = await check_voice_service(config.voice_base)
    return {"available": available, "stt": available, "tts": available}


@router.post("/stt")
async def voice_stt(
    file: UploadFile = File(...),
    language: str | None = None,
    user: UserIdentity = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    # UploadTooLarge/VoiceServiceUnavailable/VoiceUpstreamError werden zentral in app/main.py gemappt
    data = await read_upload_capped(file, config.max_upload_bytes)
    return await transcribe_speech(
        config.voice_base,
        data,
        file.filename or "audio.wav",
        file.content_type or "audio/wav",
        language,
    )


@router.post("/tts")
async def voice_tts(
    req: VoiceTTSRequest,
    user: UserIdentity = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
) -> Response:
    content, content_type = await synthesize_speech(config.voice_base, req.text, req.language, req.voice)
    return Response(content=content, media_type=content_type)
