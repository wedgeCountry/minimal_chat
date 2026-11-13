from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from ..config import AppConfig
from ..deps import get_config, get_current_user
from ..models import VoiceTTSRequest
from ..services.voice import (
    VoiceServiceUnavailable,
    VoiceUpstreamError,
    check_voice_service,
    synthesize_speech,
    transcribe_speech,
)

router = APIRouter(prefix="/api/voice", tags=["voice"])

UNAVAILABLE_DETAIL = "Sprachdienst nicht verfügbar"


@router.get("/status")
async def voice_status(
    user: dict = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
) -> dict:
    """Funktionspruefung des Voice-Companion (STT + TTS ueber /health)."""
    available = await check_voice_service(config.voice_base)
    return {"available": available, "stt": available, "tts": available}


@router.post("/stt")
async def voice_stt(
    file: UploadFile = File(...),
    language: str | None = None,
    user: dict = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
) -> dict:
    data = await file.read()
    try:
        return await transcribe_speech(
            config.voice_base,
            data,
            file.filename or "audio.wav",
            file.content_type or "audio/wav",
            language,
        )
    except VoiceServiceUnavailable:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)
    except VoiceUpstreamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/tts")
async def voice_tts(
    req: VoiceTTSRequest,
    user: dict = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
) -> Response:
    try:
        content, content_type = await synthesize_speech(config.voice_base, req.text, req.language, req.voice)
    except VoiceServiceUnavailable:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)
    except VoiceUpstreamError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return Response(content=content, media_type=content_type)
