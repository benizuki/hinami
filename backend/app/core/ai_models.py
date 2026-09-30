"""役割ごとのAIモデルと、その呼び出しに使う接続方法。システム管理者が画面から変える。

接続方法は2つ。
- gemini-api: ① Gemini API キー
- vertex:     ② Vertex AI（Google Cloud のプロジェクト・リージョン・認証。google_cloud_auth）

役割は3つ。
- chat:          対話・日報作成（業務名の名寄せも同じ接続を使う）。接続は ① / ②
- transcription: 音声入力の文字起こし。接続は ① / ②（空なら対話と同じ）
- speech:        読み上げ。方式が Gemini TTS なら ①、Cloud Text-to-Speech なら ② に決まる

画面で空のままの項目は環境変数に従う。
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping

from .google_cloud_auth import write_settings_file
from .paths import RUNTIME_DATA_DIR

AI_MODELS_FILE = RUNTIME_DATA_DIR / "settings" / "ai_models.json"
CONNECTIONS = ("gemini-api", "vertex")
SPEECH_ENGINES = ("gemini-tts", "cloud-tts")
ROLES = ("chat", "transcription", "speech")
DEFAULT_AI_MODELS: dict[str, str] = {
    "chat_connection": "",
    "chat_model": "",
    "transcription_connection": "",
    "transcription_model": "",
    "speech_engine": "",
    "speech_model": "",
}
MODEL_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,100}")
logger = logging.getLogger(__name__)


def load_ai_models() -> dict[str, str]:
    """画面で保存した値。空の項目は環境変数に従う（effective_ai_models を使う）。"""
    try:
        raw = json.loads(AI_MODELS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except (OSError, json.JSONDecodeError):
        logger.warning("AI model settings could not be read; using defaults.", exc_info=True)
        raw = {}
    settings = dict(DEFAULT_AI_MODELS)
    if isinstance(raw, dict):
        settings.update({key: str(raw[key]) for key in DEFAULT_AI_MODELS if isinstance(raw.get(key), str)})
    for key in ("chat_connection", "transcription_connection"):
        if settings[key] not in ("", *CONNECTIONS):
            settings[key] = ""
    if settings["speech_engine"] not in ("", *SPEECH_ENGINES):
        settings["speech_engine"] = ""
    return settings


def save_ai_models(values: Mapping[str, object]) -> dict[str, str]:
    """保存する前に形を確かめる。問題があれば ValueError（利用者向けの文言）。"""
    settings = {key: str(values.get(key, "") or "").strip() for key in DEFAULT_AI_MODELS}
    for key in ("chat_connection", "transcription_connection"):
        if settings[key] not in ("", *CONNECTIONS):
            raise ValueError("接続方法が正しくありません。")
    if settings["speech_engine"] not in ("", *SPEECH_ENGINES):
        raise ValueError("読み上げの方式が正しくありません。")
    for key, label in (("chat_model", "対話"), ("transcription_model", "文字起こし"), ("speech_model", "読み上げ")):
        if settings[key] and not MODEL_PATTERN.fullmatch(settings[key]):
            raise ValueError(f"{label}のモデル名の形式が正しくありません。")
    effective = _merge(settings)
    if "vertex" in (effective["chat_connection"], effective["transcription_connection"]):
        from .google_cloud_auth import effective_google_cloud

        if not effective_google_cloud()["project"]:
            raise ValueError("② Vertex AI を使うには、先に「② Vertex AI（Google Cloud）」でプロジェクトIDを設定してください。")
    write_settings_file(AI_MODELS_FILE, settings)
    return settings


def environment_speech_engine() -> str:
    raw = os.getenv("HINAMI_TTS_ENGINE", "").strip().lower()
    # 以前の値 gemini-api は Gemini TTS のこと。
    engine = {"": "gemini-tts", "gemini-api": "gemini-tts"}.get(raw, raw)
    if engine not in SPEECH_ENGINES:
        logger.warning("HINAMI_TTS_ENGINE=%s is not supported; using gemini-tts.", raw)
        return "gemini-tts"
    return engine


def environment_connection(name: str, fallback: str) -> str:
    connection = os.getenv(name, "").strip().lower() or fallback
    if connection not in CONNECTIONS:
        logger.warning("%s=%s is not supported; using %s.", name, connection, fallback)
        return fallback
    return connection


def default_speech_model(engine: str) -> str:
    if engine == "cloud-tts":
        from ..services.cloud_tts import DEFAULT_CLOUD_TTS_MODEL

        return os.getenv("CLOUD_TTS_MODEL", "").strip() or DEFAULT_CLOUD_TTS_MODEL
    from ..services.tts import DEFAULT_TTS_MODEL

    return os.getenv("GEMINI_TTS_MODEL", "").strip() or DEFAULT_TTS_MODEL


def _merge(saved: Mapping[str, str]) -> dict[str, str]:
    """画面の値を優先し、空の項目を環境変数（とその既定）で埋める。"""
    from ..services.gemini import DEFAULT_GEMINI_MODEL

    chat_connection = saved["chat_connection"] or environment_connection("GEMINI_BACKEND", "gemini-api")
    chat_model = saved["chat_model"] or os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
    speech_engine = saved["speech_engine"] or environment_speech_engine()
    return {
        "chat_connection": chat_connection,
        "chat_model": chat_model,
        "transcription_connection": (
            saved["transcription_connection"]
            or environment_connection("GEMINI_TRANSCRIPTION_BACKEND", chat_connection)
        ),
        "transcription_model": (
            saved["transcription_model"] or os.getenv("GEMINI_TRANSCRIPTION_MODEL", "").strip() or chat_model
        ),
        "speech_engine": speech_engine,
        "speech_model": saved["speech_model"] or default_speech_model(speech_engine),
    }


def effective_ai_models() -> dict[str, str]:
    """実際の呼び出しに使う値。"""
    return _merge(load_ai_models())


def environment_ai_models() -> dict[str, str]:
    """画面で何も選んでいないときに使われる値。画面に「環境の設定」として見せる。"""
    return _merge(DEFAULT_AI_MODELS)


def speech_connection(engine: str) -> str:
    """読み上げの方式で接続方法が決まる。Gemini TTS は ①、Cloud Text-to-Speech は ②。"""
    return "vertex" if engine == "cloud-tts" else "gemini-api"
