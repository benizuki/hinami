"""Googleログイン、ログイン中の利用者、ログアウト。"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..core.ai_usage import BurstLimiter
from ..core.auth import (
    AUTH_COOKIE_NAME,
    DEFAULT_TENANT_ID,
    auth_token_ttl_seconds,
    authenticate_demo_email,
    authenticate_google_credential,
    demo_login_enabled,
    google_oauth_client_id,
    issue_app_token,
    revoke_user_tokens,
    validate_auth_configuration,
    verify_app_token,
)
from ..schemas import (
    AuthConfig,
    AuthDemoLoginRequest,
    AuthGoogleLoginRequest,
    AuthLoginResponse,
    AuthUser,
)
from .common import ensure_root_org_unit, header_tenant_id, user_org_unit_id
from .middleware import client_ip, request_is_https

router = APIRouter()


# 未認証で呼べるログインエンドポイントの、IPあたりの1分間の試行回数。
LOGIN_RATE_PER_MINUTE = int(os.getenv("HINAMI_LOGIN_RATE_PER_MINUTE", "10"))


# ログインは未認証で呼べるため、利用者ではなく接続元IPで数える。
_login_limiter = BurstLimiter()
LOGIN_LIMIT_SCOPE = "__login__"


def _auth_user_from_dict(user: dict[str, Any], tenant_id: str = DEFAULT_TENANT_ID) -> AuthUser:
    """画面が使う利用者情報。所属組織は選択中テナントのものへ解決して返す。"""
    return AuthUser(
        email=user["email"],
        name=user.get("name") or user["email"],
        google_subject=user.get("google_subject"),
        oauth_name=user.get("oauth_name"),
        oauth_picture=user.get("oauth_picture"),
        department=user.get("department"),
        department_id=user.get("department_id"),
        org_unit_id=user_org_unit_id(user, tenant_id) or None,
        role=user.get("role", "viewer"),
        tenant_memberships=user.get("tenant_memberships", []),
    )


@router.get("/api/auth/config", response_model=AuthConfig)
def auth_config() -> AuthConfig:
    validate_auth_configuration()
    return AuthConfig(
        google_oauth_enabled=bool(google_oauth_client_id()),
        google_client_id=google_oauth_client_id(),
        demo_login_enabled=demo_login_enabled(),
    )


def _limit_login_attempts(request: Request) -> None:
    # 未認証で呼べるため、接続元ごとに連打を止める。
    retry_after = _login_limiter.try_acquire(
        LOGIN_LIMIT_SCOPE, client_ip(request), LOGIN_RATE_PER_MINUTE
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="ログイン試行が集中しています。少し待ってから試してください。",
            headers={"Retry-After": str(retry_after)},
        )


def _start_session(request: Request, response: Response, user: dict[str, Any]) -> AuthLoginResponse:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=issue_app_token(user),
        max_age=auth_token_ttl_seconds(),
        httponly=True,
        secure=request_is_https(request),
        samesite="lax",
        path="/",
    )
    return AuthLoginResponse(user=_auth_user_from_dict(user, header_tenant_id(request)))


@router.post("/api/auth/google", response_model=AuthLoginResponse, response_model_exclude_none=True)
def auth_google(payload: AuthGoogleLoginRequest, request: Request, response: Response) -> AuthLoginResponse:
    # 1回ごとにGoogleのトークン検証へ進むため、接続元ごとに連打を止める。
    _limit_login_attempts(request)
    return _start_session(request, response, authenticate_google_credential(
            payload.credential,
            root_org_unit_id=ensure_root_org_unit(DEFAULT_TENANT_ID),
        ),
    )


@router.post("/api/auth/demo", response_model=AuthLoginResponse, response_model_exclude_none=True)
def auth_demo(payload: AuthDemoLoginRequest, request: Request, response: Response) -> AuthLoginResponse:
    """メールアドレスだけで入るお試しログイン。Docker Composeでの体験用。"""
    if not demo_login_enabled():
        raise HTTPException(status_code=404, detail="お試しログインは有効ではありません。")
    _limit_login_attempts(request)
    user = authenticate_demo_email(payload.email, root_org_unit_id=ensure_root_org_unit(DEFAULT_TENANT_ID))
    return _start_session(request, response, user)


@router.get("/api/auth/me", response_model=AuthUser)
def auth_me(request: Request) -> AuthUser:
    user = getattr(request.state, "user", None)
    if not user:
        authorization = request.headers.get("Authorization", "")
        scheme, _, bearer_token = authorization.partition(" ")
        token = bearer_token.strip() if scheme.lower() == "bearer" else request.cookies.get(AUTH_COOKIE_NAME, "")
        user = verify_app_token(token)
    return _auth_user_from_dict(user, header_tenant_id(request))


@router.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict[str, bool]:
    # Cookieを消すだけでは、窃取済みのトークンが有効期限まで使えてしまう。
    # 世代を進めて、その利用者の発行済みトークンをすべて失効させる。
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("email"):
        revoke_user_tokens(str(user["email"]))
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    return {"ok": True}
