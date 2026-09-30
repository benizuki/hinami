"""Google Cloud Text-to-Speech（Gemini-TTS）による読み上げ。HINAMI_TTS_ENGINE=cloud-tts のときに使う。

Gemini API キーではなく Google Cloud の認証情報（ADC）で呼ぶ。利用上限も Gemini API とは別枠になる。
話す速さを speaking_rate の数値で指定できるため、言葉の指示よりペースが安定する。
出力の形式は Gemini API の経路と同じにそろえる（ストリーミングは 24kHz・16bit・モノラルの PCM、
一括合成は RIFF ヘッダー付きの WAV）。画面側はどちらの方式かを意識しなくてよい。
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from functools import lru_cache
from threading import Lock
from typing import Any

from .tts import (
    STREAMING_TTS_SAMPLE_RATE,
    SpeechRateLimitError,
    SpeechSynthesisError,
)

DEFAULT_CLOUD_TTS_MODEL = "gemini-2.5-flash-tts"
DEFAULT_CLOUD_TTS_SPEAKING_RATE = 1.0
# 利用者が選ぶペースを、基準の速さに掛ける倍率にする。
PACE_SPEAKING_RATES = {"normal": 1.0, "slow": 0.85, "fast": 1.2}
CLOUD_TTS_LANGUAGE = "ja-JP"
_client_lock = Lock()


def cloud_speech_settings(pace: str) -> tuple[str, float]:
    """使うモデルと話す速さ。速さは Cloud Text-to-Speech の範囲（0.25〜2.0）に収める。"""
    from .tts import speech_model

    model = speech_model()
    raw = os.getenv("CLOUD_TTS_SPEAKING_RATE", str(DEFAULT_CLOUD_TTS_SPEAKING_RATE))
    try:
        base = float(raw)
    except ValueError as exc:
        raise SpeechSynthesisError("CLOUD_TTS_SPEAKING_RATE は0.25〜2.0の数値で指定してください。") from exc
    if not math.isfinite(base) or not 0.25 <= base <= 2.0:
        raise SpeechSynthesisError("CLOUD_TTS_SPEAKING_RATE は0.25〜2.0の範囲で指定してください。")
    rate = base * PACE_SPEAKING_RATES.get(pace, 1.0)
    return model, round(min(2.0, max(0.25, rate)), 3)


def begin_cloud_speech_stream(text: str, voice: str, prompt: str, pace: str) -> Iterator[bytes]:
    """Cloud Text-to-Speech のストリーミングを開き、最初の音声が届いてから PCM の塊を返す。"""
    texttospeech = _texttospeech()
    model, speaking_rate = cloud_speech_settings(pace)
    config_request = texttospeech.StreamingSynthesizeRequest(
        streaming_config=texttospeech.StreamingSynthesizeConfig(
            voice=texttospeech.VoiceSelectionParams(
                language_code=CLOUD_TTS_LANGUAGE,
                name=voice,
                model_name=model,
            ),
            streaming_audio_config=texttospeech.StreamingAudioConfig(
                audio_encoding=texttospeech.AudioEncoding.PCM,
                sample_rate_hertz=STREAMING_TTS_SAMPLE_RATE,
                speaking_rate=speaking_rate,
            ),
        )
    )
    input_request = texttospeech.StreamingSynthesizeRequest(
        input=texttospeech.StreamingSynthesisInput(text=text, **({"prompt": prompt} if prompt else {}))
    )
    try:
        with _client_lock:
            responses = _client().streaming_synthesize(requests=iter((config_request, input_request)))
            response_iterator = iter(responses)
            first_chunk = _next_audio_chunk(response_iterator)
    except SpeechSynthesisError:
        raise
    except Exception as exc:
        raise _translated_error(exc, "ストリーミングの開始に失敗しました") from exc

    def chunks() -> Iterator[bytes]:
        try:
            yield first_chunk
            for response in response_iterator:
                audio_content = getattr(response, "audio_content", b"")
                if audio_content:
                    yield bytes(audio_content)
        except Exception as exc:
            raise _translated_error(exc, "ストリーミングの受信に失敗しました") from exc
        finally:
            cancel = getattr(responses, "cancel", None)
            if callable(cancel):
                cancel()

    return chunks()


def synthesize_cloud_speech(text: str, voice: str, prompt: str, pace: str) -> bytes:
    """文章全体を WAV で返す。同じ文章と設定はキャッシュから返す。"""
    model, speaking_rate = cloud_speech_settings(pace)
    return _synthesize_cached(text, model, voice, prompt, speaking_rate)


@lru_cache(maxsize=128)
def _synthesize_cached(text: str, model: str, voice: str, prompt: str, speaking_rate: float) -> bytes:
    texttospeech = _texttospeech()
    try:
        with _client_lock:
            response = _client().synthesize_speech(
                input=texttospeech.SynthesisInput(text=text, **({"prompt": prompt} if prompt else {})),
                voice=texttospeech.VoiceSelectionParams(
                    language_code=CLOUD_TTS_LANGUAGE,
                    name=voice,
                    model_name=model,
                ),
                # LINEAR16 は RIFF ヘッダー付きの WAV で返る。Gemini API の経路と同じ形式にそろえる。
                audio_config=texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                    sample_rate_hertz=STREAMING_TTS_SAMPLE_RATE,
                    speaking_rate=speaking_rate,
                ),
            )
    except Exception as exc:
        raise _translated_error(exc, "呼び出しに失敗しました") from exc
    audio_content = getattr(response, "audio_content", b"")
    if not audio_content:
        raise SpeechSynthesisError("Cloud Text-to-Speech から音声データを取得できませんでした。")
    return bytes(audio_content)


def _next_audio_chunk(responses: Iterator[Any]) -> bytes:
    for response in responses:
        audio_content = getattr(response, "audio_content", b"")
        if audio_content:
            return bytes(audio_content)
    raise SpeechSynthesisError("Cloud Text-to-Speech から音声データを取得できませんでした。")


def _translated_error(exc: Exception, action: str) -> SpeechSynthesisError:
    """認証・権限・上限のエラーを、何をすればよいか分かる言葉にする。"""
    if isinstance(exc, SpeechSynthesisError):
        return exc
    name = type(exc).__name__
    if getattr(exc, "code", None) == 429 or name == "ResourceExhausted":
        return SpeechRateLimitError(
            f"Cloud Text-to-Speech の利用上限に達しました。時間をおいてから再度お試しください。（{exc}）"
        )
    if name in {"DefaultCredentialsError", "RefreshError"}:
        return SpeechSynthesisError(
            "Cloud Text-to-Speech の認証情報が見つかりません。"
            "`gcloud auth application-default login` を実行するか、サービスアカウントを設定してください。"
        )
    if name in {"PermissionDenied", "Forbidden"}:
        return SpeechSynthesisError(
            "Cloud Text-to-Speech を呼び出す権限がありません。"
            f"プロジェクトで Cloud Text-to-Speech API を有効にし、権限を確認してください。（{exc}）"
        )
    return SpeechSynthesisError(f"Cloud Text-to-Speech の{action}: {exc}")


def _texttospeech() -> Any:
    try:
        from google.cloud import texttospeech
    except ImportError as exc:
        raise SpeechSynthesisError(
            "google-cloud-texttospeech がインストールされていません。`uv sync` を実行してください。"
        ) from exc
    return texttospeech


def _client() -> Any:
    """認証の設定ごとに1つのクライアントを使い回す。設定を変えたら次の呼び出しから作り直す。"""
    from ..core.google_cloud_auth import credentials_key

    return _cached_client(credentials_key())


@lru_cache(maxsize=4)
def _cached_client(key: tuple[str, ...]) -> Any:
    from ..core.google_cloud_auth import google_cloud_credentials, quota_project

    project = quota_project()
    try:
        return _texttospeech().TextToSpeechClient(
            credentials=google_cloud_credentials(),
            **({"client_options": {"quota_project_id": project}} if project else {}),
        )
    except SpeechSynthesisError:
        raise
    except Exception as exc:
        raise _translated_error(exc, "クライアントを作成できませんでした") from exc


def check_cloud_tts() -> dict[str, Any]:
    """いまの認証の設定で Cloud Text-to-Speech に届くかを、音声を作らずに確かめる。

    認証情報の用意 → トークンの交換（WIF のとき）→ 声の一覧の取得、の順に進め、止まった段階を返す。
    声の一覧の取得は読み上げの利用量に数えられない。
    """
    from ..core.google_cloud_auth import describe_auth_error, refresh_google_cloud_credentials
    from ..core.k8s_token import TokenUnavailable

    step = "credentials"
    try:
        client = _client()
        step = "sts"
        refresh_google_cloud_credentials()
        step = "api"
        voices = client.list_voices(language_code=CLOUD_TTS_LANGUAGE).voices
    except (SpeechSynthesisError, TokenUnavailable) as exc:
        return {"ok": False, "step": step, "message": str(exc)}
    except Exception as exc:
        # 段階ごとに原因が違うので、交換と問い合わせの失敗は元の文言をそのまま見せる。
        if step == "sts":
            message = describe_auth_error(exc)
        elif step == "api":
            message = str(exc)
        else:
            message = str(_translated_error(exc, "準備に失敗しました"))
        return {"ok": False, "step": step, "message": message[:500]}
    return {"ok": True, "step": "api", "message": f"日本語の声を{len(voices)}件取得できました。"}
