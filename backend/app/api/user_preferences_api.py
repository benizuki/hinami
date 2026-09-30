"""利用者ごとの設定（読み上げの声・トーン・ペース）。本人の設定だけを読み書きする。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from .. import runtime
from ..schemas import SpeechOption, SpeechPreferences, SpeechPreferencesResponse
from ..services.tts import PACE_STYLES, TONE_STYLES, VOICE_CATALOG, VOICE_NAMES, default_voice
from .common import request_user_email_or_empty

SPEECH_PREFERENCE_KIND = "speech"
# ログインなしの開発モードでは利用者を識別できないため、1人分として束ねる。
LOCAL_PREFERENCE_OWNER = "local-user"

router = APIRouter()


def preference_owner(request: Request) -> str:
    return request_user_email_or_empty(request) or LOCAL_PREFERENCE_OWNER


def load_speech_preferences(owner: str) -> SpeechPreferences:
    """保存済みの好み。無い・読めない・使えなくなった声は、既定に戻して返す。"""
    record = runtime.store.get_user_preference(owner, SPEECH_PREFERENCE_KIND) or {}
    try:
        preferences = SpeechPreferences.model_validate(record)
    except ValidationError:
        preferences = SpeechPreferences()
    if preferences.voice and preferences.voice not in VOICE_NAMES:
        preferences.voice = ""
    return preferences


def ensure_known_voice(preferences: SpeechPreferences) -> None:
    if preferences.voice and preferences.voice not in VOICE_NAMES:
        raise HTTPException(status_code=422, detail="選べない声が指定されています。")


def _response(preferences: SpeechPreferences) -> SpeechPreferencesResponse:
    return SpeechPreferencesResponse(
        **preferences.model_dump(),
        default_voice=default_voice(),
        voices=[SpeechOption(id=name, label=label) for name, label in VOICE_CATALOG],
        tones=[SpeechOption(id=key, label=label) for key, (_, label) in TONE_STYLES.items()],
        paces=[SpeechOption(id=key, label=label) for key, (_, label) in PACE_STYLES.items()],
    )


@router.get("/api/user-preferences/speech", response_model=SpeechPreferencesResponse)
def get_speech_preferences(request: Request) -> SpeechPreferencesResponse:
    return _response(load_speech_preferences(preference_owner(request)))


@router.put("/api/user-preferences/speech", response_model=SpeechPreferencesResponse)
def update_speech_preferences(payload: SpeechPreferences, request: Request) -> SpeechPreferencesResponse:
    ensure_known_voice(payload)
    runtime.store.save_user_preference(
        preference_owner(request), SPEECH_PREFERENCE_KIND, payload.model_dump()
    )
    return _response(payload)
