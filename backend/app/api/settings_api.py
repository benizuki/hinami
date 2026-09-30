"""システム全体の設定（接続方法：① Gemini APIキー／② Vertex AI、役割ごとのAIモデル、Google連携）。

変更はシステム管理者だけが行う。
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from ..core import k8s_token
from ..core.ai_models import effective_ai_models, environment_ai_models, load_ai_models, save_ai_models
from ..core.app_mode import load_app_mode, save_app_mode
from ..core.google_cloud_auth import (
    active_auth,
    environment_google_cloud,
    load_google_cloud_auth,
    save_google_cloud_auth,
)
from ..core.google_integrations import load_google_integrations, save_google_integrations
from ..schemas import (
    AiModelSettings,
    AppModeSettings,
    AiModelSettingsResponse,
    AiModelValues,
    ConnectionCheckResult,
    GeminiApiKeyUpdate,
    GeminiSettings,
    GoogleCloudAuthSettings,
    GoogleCloudEnvironment,
    GoogleCloudSettingsResponse,
    GoogleIntegrationSettings,
    WorkloadIdentityInfo,
)
from ..services.gemini import (
    GeminiError,
    check_ai_model,
    delete_stored_gemini_api_key,
    gemini_api_key,
    gemini_api_key_is_well_formed,
    gemini_api_key_source,
    save_gemini_api_key,
    verify_gemini_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _gemini_settings() -> GeminiSettings:
    source = gemini_api_key_source()
    key = gemini_api_key()
    return GeminiSettings(
        source=source,
        configured=bool(key),
        key_hint=key[-4:] if source == "stored" else None,
    )


@router.get("/api/settings/gemini", response_model=GeminiSettings, response_model_exclude_none=True)
def get_gemini_settings() -> GeminiSettings:
    return _gemini_settings()


@router.put("/api/settings/gemini", response_model=GeminiSettings, response_model_exclude_none=True)
async def update_gemini_api_key(payload: GeminiApiKeyUpdate) -> GeminiSettings:
    if gemini_api_key_source() == "environment":
        raise HTTPException(status_code=409, detail="GEMINI_API_KEY が設定されているため、画面からは変更できません。")
    api_key = payload.api_key.strip()
    if not gemini_api_key_is_well_formed(api_key):
        raise HTTPException(status_code=422, detail="Gemini APIキーの形式が正しくありません。")
    try:
        await run_in_threadpool(verify_gemini_api_key, api_key)
    except GeminiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await run_in_threadpool(save_gemini_api_key, api_key)
    logger.info("Gemini API key was updated from the settings screen.")
    return _gemini_settings()


@router.delete("/api/settings/gemini", status_code=204)
def delete_gemini_api_key() -> Response:
    if gemini_api_key_source() == "environment":
        raise HTTPException(status_code=409, detail="GEMINI_API_KEY が設定されているため、画面からは削除できません。")
    delete_stored_gemini_api_key()
    logger.info("Gemini API key was removed from the settings screen.")
    return Response(status_code=204)


# 画面の言葉づかいを決めるために全員が読む。変更は /api/settings 配下に置き、システム管理者に限る。
@router.get("/api/app-mode", response_model=AppModeSettings)
def get_app_mode() -> AppModeSettings:
    return AppModeSettings(mode=load_app_mode())


@router.put("/api/settings/app-mode", response_model=AppModeSettings)
def update_app_mode(payload: AppModeSettings) -> AppModeSettings:
    mode = save_app_mode(payload.mode)
    logger.info("App mode was updated: %s", mode)
    return AppModeSettings(mode=mode)


# 日報画面が使える機能を知るために全員が読む。変更は /api/settings 配下に置き、システム管理者に限る。
@router.get("/api/google-integrations", response_model=GoogleIntegrationSettings)
def get_google_integrations() -> GoogleIntegrationSettings:
    return GoogleIntegrationSettings(**load_google_integrations())


@router.put("/api/settings/google-integrations", response_model=GoogleIntegrationSettings)
def update_google_integrations(payload: GoogleIntegrationSettings) -> GoogleIntegrationSettings:
    settings = save_google_integrations(payload.model_dump())
    logger.info("Google integration settings were updated: %s", settings)
    return GoogleIntegrationSettings(**settings)


@router.get("/api/settings/google-cloud", response_model=GoogleCloudSettingsResponse)
def get_google_cloud() -> GoogleCloudSettingsResponse:
    return _google_cloud_response(load_google_cloud_auth())


def _google_cloud_response(settings: dict[str, str]) -> GoogleCloudSettingsResponse:
    return GoogleCloudSettingsResponse(
        **settings,
        environment=GoogleCloudEnvironment(**environment_google_cloud()),
        active_auth=active_auth(),
        running_on_kubernetes=k8s_token.running_on_kubernetes(),
    )


@router.put("/api/settings/google-cloud", response_model=GoogleCloudSettingsResponse)
def update_google_cloud(payload: GoogleCloudAuthSettings) -> GoogleCloudSettingsResponse:
    try:
        settings = save_google_cloud_auth(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info("Google Cloud settings were updated: active_auth=%s", active_auth())
    return _google_cloud_response(settings)


@router.get("/api/settings/google-cloud/workload-identity", response_model=WorkloadIdentityInfo)
async def get_workload_identity() -> WorkloadIdentityInfo:
    """GCP 側で信頼を登録するための値。Hinami の身元、クラスタの発行元、公開鍵（JWKS）。"""

    def read() -> WorkloadIdentityInfo:
        try:
            namespace, name = k8s_token.identity()
            discovery = k8s_token.cluster_get("/.well-known/openid-configuration")
            return WorkloadIdentityInfo(
                subject=k8s_token.subject(),
                namespace=namespace,
                service_account=name,
                issuer=str(discovery.get("issuer", "")),
                jwks=k8s_token.cluster_get("/openid/v1/jwks"),
            )
        except k8s_token.TokenUnavailable as exc:
            raise HTTPException(
                status_code=409,
                detail="Kubernetes 上で動いていないため、Workload Identity 連携の情報を読めません。",
            ) from exc

    return await run_in_threadpool(read)


def _ai_models_response(settings: dict[str, str]) -> AiModelSettingsResponse:
    return AiModelSettingsResponse(
        **settings,
        environment=AiModelValues(**environment_ai_models()),
        effective=AiModelValues(**effective_ai_models()),
    )


@router.get("/api/settings/ai-models", response_model=AiModelSettingsResponse)
def get_ai_models() -> AiModelSettingsResponse:
    return _ai_models_response(load_ai_models())


@router.put("/api/settings/ai-models", response_model=AiModelSettingsResponse)
def update_ai_models(payload: AiModelSettings) -> AiModelSettingsResponse:
    try:
        settings = save_ai_models(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info("AI model settings were updated: %s", effective_ai_models())
    return _ai_models_response(settings)


@router.post("/api/settings/ai-models/{role}/check", response_model=ConnectionCheckResult)
async def check_ai_model_connection(role: Literal["chat", "transcription", "speech"]) -> ConnectionCheckResult:
    """保存済みの設定で、その役割のモデルに届くかを確かめる。生成・音声合成はしない。"""
    return ConnectionCheckResult(**await run_in_threadpool(check_ai_model, role))
