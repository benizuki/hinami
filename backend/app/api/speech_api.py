"""音声の文字起こしと読み上げ。"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse

from ..schemas import AudioTranscriptionResponse, SpeechSynthesisRequest
from ..services.gemini import GeminiError, connection_for, generate_audio_transcription, model_for
from ..services.tts import (
    STREAMING_TTS_SAMPLE_RATE,
    SpeechRateLimitError,
    SpeechSynthesisError,
    begin_speech_stream,
    synthesize_speech,
)
from .user_preferences_api import ensure_known_voice, load_speech_preferences, preference_owner

router = APIRouter()


TIMESTAMP_ONLY_PATTERN = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?\s*$")


MAX_AUDIO_BYTES = 8 * 1024 * 1024
MIN_AUDIO_BYTES = 8 * 1024
SUPPORTED_AUDIO_MIME_TYPES = {
    "audio/webm",
    "audio/mp4",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
}


@router.post("/api/speech/transcribe", response_model=AudioTranscriptionResponse)
async def transcribe_speech(request: Request) -> AudioTranscriptionResponse:
    mime_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime_type not in SUPPORTED_AUDIO_MIME_TYPES:
        raise HTTPException(status_code=415, detail="対応していない音声形式です。")
    # 全文を溜めてから測ると上限を超えた分までメモリへ載るため、読みながら止める。
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="音声データは8MB以下にしてください。")
    audio_bytes = bytes(buffer)
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="音声データが空です。")
    if len(audio_bytes) < MIN_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="録音が短すぎます。1秒以上話してから停止してください。")
    try:
        decision = await run_in_threadpool(generate_audio_transcription, audio_bytes, mime_type)
    except GeminiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    transcript = decision.transcript.strip()
    if TIMESTAMP_ONLY_PATTERN.fullmatch(transcript):
        transcript = ""
    if not transcript:
        raise HTTPException(status_code=422, detail="音声を聞き取れませんでした。マイクに近づいてもう一度お試しください。")
    return AudioTranscriptionResponse.model_validate(
        {
            **decision.model_dump(),
            "transcript": transcript,
            "provider": connection_for("transcription"),
            "model": model_for("transcription"),
        }
    )


def _speech_options(payload: SpeechSynthesisRequest, request: Request) -> tuple[str | None, str, str]:
    """読み上げに使う声・トーン・ペース。試聴なら指定の好み、それ以外は本人の保存済みの好みを使う。"""
    preferences = payload.preferences
    if preferences is None:
        preferences = load_speech_preferences(preference_owner(request))
    else:
        ensure_known_voice(preferences)
    return preferences.voice or None, preferences.tone, preferences.pace


@router.post("/api/speech", response_class=Response)
async def synthesize_speech_audio(payload: SpeechSynthesisRequest, request: Request) -> Response:
    voice, tone, pace = _speech_options(payload, request)
    try:
        audio_content = await run_in_threadpool(synthesize_speech, payload.text, voice, tone, pace)
    except SpeechRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except SpeechSynthesisError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=audio_content,
        media_type="audio/wav",
        headers={"X-Speech-Provider": "gemini-api-tts"},
    )


@router.post("/api/speech/stream", response_class=StreamingResponse)
async def stream_speech_audio(payload: SpeechSynthesisRequest, request: Request) -> StreamingResponse:
    voice, tone, pace = _speech_options(payload, request)
    try:
        audio_chunks = await run_in_threadpool(begin_speech_stream, payload.text, voice, tone, pace)
    except SpeechRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except SpeechSynthesisError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return StreamingResponse(
        audio_chunks,
        media_type=f"audio/pcm;rate={STREAMING_TTS_SAMPLE_RATE};channels=1",
        headers={
            "Cache-Control": "no-store",
            "X-Speech-Provider": "gemini-api-tts-streaming",
            "X-Audio-Sample-Rate": str(STREAMING_TTS_SAMPLE_RATE),
            "X-Audio-Format": "pcm-s16le",
        },
    )
