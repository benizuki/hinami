"""Gemini API（Google AI Studio の APIキー方式）の呼び出しをまとめる。

構造化出力（JSON）の生成と、音声の文字起こしをここに集める。
業務日報・組織サマリー・業務の棚卸しの各サービスは、このモジュールだけを通して Gemini を使う。
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from ..core.ai_usage import record_model_tokens
from ..core.paths import RUNTIME_DATA_DIR
from ..schemas import AudioTranscriptionDecision


logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_CHAT_THINKING_LEVEL = "LOW"
DEFAULT_DOCUMENT_THINKING_LEVEL = "HIGH"
DEFAULT_REQUEST_TIMEOUT_MS = 120_000
SUPPORTED_THINKING_LEVELS = {"MINIMAL", "LOW", "MEDIUM", "HIGH"}
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
# 画面から登録したAPIキーの保存先。SQLiteの外に置き、バックアップに含めない。
GEMINI_API_KEY_FILE = RUNTIME_DATA_DIR / "secrets" / "gemini_api_key"
# キーの形式は種類によって違う（AIza… や、. を含む AQ. … など）。使えるかは保存前に
# 実際に問い合わせて確かめるため、ここでは空白・改行・制御文字・非ASCIIの混入だけを弾く。
GEMINI_API_KEY_PATTERN = re.compile(r"[\x21-\x7e]{10,512}")
VERIFY_REQUEST_TIMEOUT_MS = 15_000
GeminiApiKeySource = Literal["environment", "stored", "none"]

AUDIO_TRANSCRIPTION_SYSTEM_INSTRUCTION = """あなたは日本語の音声を正確に文字起こしする専門家です。
- 音声で話された内容だけを文字にし、質問への回答、要約、補足、推測はしない。
- 録音時間、タイムスタンプ、経過秒数、時刻表示は出力しない。
- 発話がなく、時刻や録音時間しか判断できない場合はtranscriptを空文字にする。
- 製品名、システム名、部署名、略語、数値、単位は聞こえた表現をできるだけ保持する。
- 自然な句読点を補い、フィラー（えー、あのー等）は意味を損なわない範囲で除く。
- 聞き取れない重要箇所は「[聞き取れず]」とする。
- 人間の発話を明瞭に聞き取れない場合は、推測や例文を出さずtranscriptを空文字にする。
- JSON以外を出力しない。

出力JSON:
{
  "transcript": "文字起こし結果"
}
"""


class GeminiError(RuntimeError):
    pass


@dataclass(frozen=True)
class InlineAttachment:
    name: str
    mime_type: str
    data: str


def gemini_api_key() -> str:
    """環境変数を優先し、無ければ画面から登録したキーを使う。"""
    return os.getenv("GEMINI_API_KEY", "").strip() or stored_gemini_api_key()


def gemini_api_key_source() -> GeminiApiKeySource:
    if os.getenv("GEMINI_API_KEY", "").strip():
        return "environment"
    return "stored" if stored_gemini_api_key() else "none"


def stored_gemini_api_key() -> str:
    # 複数ワーカーで更新を揃えるため、キャッシュせず毎回読む（数十バイトのファイル）。
    try:
        return GEMINI_API_KEY_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def gemini_api_key_is_well_formed(api_key: str) -> bool:
    return bool(GEMINI_API_KEY_PATTERN.fullmatch(api_key))


def save_gemini_api_key(api_key: str) -> None:
    """画面から登録したキーを、所有者だけが読めるファイルへ置き換える。"""
    if not gemini_api_key_is_well_formed(api_key):
        raise ValueError("Gemini APIキーの形式が正しくありません。")
    path = GEMINI_API_KEY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # 書き終えてから置き換える。読み手が書きかけのキーを使うことはない。
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".gemini_api_key.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(api_key)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def delete_stored_gemini_api_key() -> None:
    GEMINI_API_KEY_FILE.unlink(missing_ok=True)


def verify_gemini_api_key(api_key: str) -> None:
    """キーでモデル一覧を1件だけ取得し、使えるかを確かめる。トークンは消費しない。"""
    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as exc:
        raise GeminiError("google-genai がインストールされていません。`uv sync` を実行してください。") from exc
    client = genai.Client(api_key=api_key, http_options=_build_http_options(types, VERIFY_REQUEST_TIMEOUT_MS))
    try:
        next(iter(client.models.list(config={"page_size": 1})), None)
    except errors.ClientError as exc:
        # 応答本文はそのまま返さない。キーの種類や権限の詳細を利用者画面に出す必要はない。
        raise GeminiError(f"このAPIキーは使えませんでした（HTTP {exc.code}）。キーを確認してください。") from exc
    except Exception as exc:
        logger.warning("Gemini API key verification failed", exc_info=True)
        raise GeminiError("Gemini APIに接続できませんでした。時間をおいて再度お試しください。") from exc


@lru_cache(maxsize=1)
def _client(api_key: str, timeout_ms: int) -> Any:
    from google import genai
    from google.genai import types

    return genai.Client(api_key=api_key, http_options=_build_http_options(types, timeout_ms))


@lru_cache(maxsize=4)
def _vertex_client(project: str, location: str, credentials_key: tuple[str, ...], timeout_ms: int) -> Any:
    from google import genai
    from google.genai import types

    from ..core.google_cloud_auth import google_cloud_credentials

    return genai.Client(
        vertexai=True,
        project=project,
        location=location,
        credentials=google_cloud_credentials(),
        http_options=_build_http_options(types, timeout_ms),
    )


def connection_for(role: str = "chat") -> str:
    """役割（chat / transcription）が使う接続方法。gemini-api（①）か vertex（②）。"""
    from ..core.ai_models import effective_ai_models

    return effective_ai_models()[f"{role}_connection"]


def model_for(role: str = "chat") -> str:
    """役割（chat / transcription）が使うモデル。"""
    from ..core.ai_models import effective_ai_models

    return effective_ai_models()[f"{role}_model"]


def gemini_configured(role: str = "chat") -> bool:
    """その役割のAI機能を呼べる状態か。① はキー、② はプロジェクトが要る。"""
    from ..core.google_cloud_auth import effective_google_cloud

    if connection_for(role) == "vertex":
        return bool(effective_google_cloud()["project"])
    return bool(gemini_api_key())


def _request_timeout_ms(timeout_ms: int | None) -> int:
    return timeout_ms or int(os.getenv("GEMINI_REQUEST_TIMEOUT_MS", str(DEFAULT_REQUEST_TIMEOUT_MS)))


def gemini_client(timeout_ms: int | None = None, role: str = "chat") -> Any:
    """役割の接続方法に応じて、Gemini API（①）か Vertex AI（②）のクライアントを返す。

    設定ごとに1つを使い回す。必要な設定が無ければ呼び出し前に止める。
    """
    if connection_for(role) == "vertex":
        return vertex_client(timeout_ms)
    return gemini_api_key_client(timeout_ms)


def vertex_client(timeout_ms: int | None = None) -> Any:
    """② Vertex AI のクライアント。プロジェクト・リージョン・認証は「② Vertex AI（Google Cloud）」の設定。"""
    from ..core.google_cloud_auth import credentials_key, effective_google_cloud

    settings = effective_google_cloud()
    if not settings["project"]:
        raise GeminiError(
            "Vertex AI のプロジェクトが設定されていません。管理者が「システム設定」か GOOGLE_CLOUD_PROJECT で設定してください。"
        )
    try:
        return _vertex_client(settings["project"], settings["location"], credentials_key(), _request_timeout_ms(timeout_ms))
    except ImportError as exc:
        raise GeminiError("google-genai がインストールされていません。`uv sync` を実行してください。") from exc


def gemini_api_key_client(timeout_ms: int | None = None) -> Any:
    """① Gemini API（APIキー）のクライアント。読み上げの Gemini TTS は常にこちらを使う。"""
    api_key = gemini_api_key()
    if not api_key:
        raise GeminiError("Gemini APIキーが設定されていません。管理者が「システム設定」画面か GEMINI_API_KEY で設定してください。")
    try:
        return _client(api_key, _request_timeout_ms(timeout_ms))
    except ImportError as exc:
        raise GeminiError("google-genai がインストールされていません。`uv sync` を実行してください。") from exc


def check_ai_model(role: str) -> dict[str, Any]:
    """役割のモデルに、その接続方法で届くかを確かめる。モデル情報を引くだけで、生成はしない。"""
    from ..core.ai_models import effective_ai_models, speech_connection
    from ..core.google_cloud_auth import describe_auth_error, refresh_google_cloud_credentials
    from ..core.k8s_token import TokenUnavailable

    settings = effective_ai_models()
    if role == "speech" and settings["speech_engine"] == "cloud-tts":
        from .cloud_tts import check_cloud_tts

        return check_cloud_tts()
    connection = speech_connection(settings["speech_engine"]) if role == "speech" else settings[f"{role}_connection"]
    model = settings[f"{role}_model"]
    step = "credentials"
    try:
        client = vertex_client(VERIFY_REQUEST_TIMEOUT_MS) if connection == "vertex" else gemini_api_key_client(VERIFY_REQUEST_TIMEOUT_MS)
        if connection == "vertex":
            step = "sts"
            refresh_google_cloud_credentials()
        step = "api"
        client.models.get(model=model)
    except (GeminiError, TokenUnavailable) as exc:
        return {"ok": False, "step": step, "message": str(exc)}
    except Exception as exc:
        return {"ok": False, "step": step, "message": describe_auth_error(exc) if step == "sts" else str(exc)[:500]}
    return {"ok": True, "step": "api", "message": f"{model} を使えます。"}


def generate_structured(
    prompt: str,
    response_schema: Any,
    system_instruction: str,
    attachments: list[Any] | None = None,
    *,
    model_override: str | None = None,
    thinking_level_override: str | None = None,
    media_resolution_override: str | None = None,
    attachments_first: bool = False,
    request_timeout_ms_override: int | None = None,
    role: str = "chat",
) -> Any:
    """JSON で応答させ、Pydantic モデルで厳密に検証して返す。"""
    from google.genai import types

    client = gemini_client(request_timeout_ms_override, role=role)
    model = model_override or model_for(role)
    try:
        # 入れ子の深いスキーマは response_schema で弾かれることがあるため、
        # JSON だけを要求し、生成後に Pydantic で検証する。
        config = _build_generate_content_config(
            types,
            system_instruction,
            thinking_level_override,
            media_resolution_override,
        )
        contents: Any = prompt
        if attachments:
            attachment_parts = []
            for attachment in attachments:
                try:
                    attachment_bytes = base64.b64decode(attachment.data, validate=True)
                except (ValueError, TypeError) as exc:
                    raise GeminiError(f"添付ファイル「{attachment.name}」を読み込めませんでした。") from exc
                if len(attachment_bytes) > MAX_ATTACHMENT_BYTES:
                    raise GeminiError(f"添付ファイル「{attachment.name}」が8MBを超えています。")
                attachment_parts.append(types.Part.from_bytes(data=attachment_bytes, mime_type=attachment.mime_type))
            prompt_part = types.Part.from_text(text=prompt)
            parts = [*attachment_parts, prompt_part] if attachments_first else [prompt_part, *attachment_parts]
            contents = [types.Content(role="user", parts=parts)]
        response = client.models.generate_content(model=model, contents=contents, config=config)
    except GeminiError:
        raise
    except Exception as exc:
        raise GeminiError(f"Gemini API の呼び出しに失敗しました: {exc}") from exc

    # 課金対象のトークン数を利用状況へ積む。応答の解析に失敗しても消費済みなので先に記録する。
    record_model_tokens(getattr(response, "usage_metadata", None))

    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise GeminiError("Gemini 応答テキストを取得できませんでした。")

    try:
        raw = json.loads(_normalize_json_text(text))
    except json.JSONDecodeError as exc:
        raise GeminiError(f"Gemini 応答のJSON形式が想定と異なります: {exc.msg}") from exc
    try:
        return response_schema.model_validate(_normalize_generated_values(raw))
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors())
        raise GeminiError(f"Gemini 応答の項目形式が想定と異なります: {details}") from exc


def generate_audio_transcription(audio_bytes: bytes, mime_type: str) -> AudioTranscriptionDecision:
    attachment = InlineAttachment(
        name="voice-input",
        mime_type=mime_type,
        data=base64.b64encode(audio_bytes).decode("ascii"),
    )
    return generate_structured(
        "添付された音声を日本語で文字起こししてください。",
        AudioTranscriptionDecision,
        AUDIO_TRANSCRIPTION_SYSTEM_INSTRUCTION,
        [attachment],
        role="transcription",
    )


def _build_generate_content_config(
    types: Any,
    system_instruction: str,
    thinking_level: str | None = None,
    media_resolution: str | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "system_instruction": system_instruction,
        "response_mime_type": "application/json",
        "temperature": 0.2,
    }
    if media_resolution:
        kwargs["media_resolution"] = media_resolution
    normalized_thinking_level = (thinking_level or "").strip().upper()
    if normalized_thinking_level and normalized_thinking_level not in SUPPORTED_THINKING_LEVELS:
        raise GeminiError(
            "thinking levelはMINIMAL、LOW、MEDIUM、HIGHのいずれかを指定してください: "
            f"{thinking_level}"
        )
    try:
        thinking_kwargs: dict[str, Any] = {"include_thoughts": False}
        if normalized_thinking_level:
            thinking_kwargs["thinking_level"] = normalized_thinking_level
        kwargs["thinking_config"] = types.ThinkingConfig(**thinking_kwargs)
        return types.GenerateContentConfig(**kwargs)
    except (AttributeError, TypeError):
        kwargs.pop("thinking_config", None)
        return types.GenerateContentConfig(**kwargs)


def _build_http_options(types: Any, timeout_ms: int) -> Any:
    return types.HttpOptions(
        timeout=timeout_ms,
        retry_options=types.HttpRetryOptions(
            attempts=3,
            initial_delay=2.0,
            max_delay=20.0,
            http_status_codes=[408, 429, 500, 502, 503, 504],
        ),
    )


def _normalize_generated_values(value: Any, *, field_name: str = "") -> Any:
    """Gemini がまれに返す表記ゆれを、厳密な検証の前に整える。"""
    if isinstance(value, dict):
        return {key: _normalize_generated_values(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_generated_values(item, field_name=field_name) for item in value]
    if (
        field_name == "confidence"
        and isinstance(value, float)
        and math.isfinite(value)
        and not value.is_integer()
    ):
        # 確率（0.0〜1.0）や小数つきの百分率で返ることがあるので、整数の百分率へ揃える。
        percentage = value * 100 if 0 < value < 1 else value
        return int(percentage + 0.5) if percentage >= 0 else int(percentage - 0.5)
    return value


def _normalize_json_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        return stripped[index:index + end]
    return stripped
