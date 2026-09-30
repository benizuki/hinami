"""全リクエストに掛ける検査（Host・接続元・Origin・認可）と、AI機能の回数制限・記録。"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .. import runtime
from ..core.ai_usage import (
    BurstLimiter,
    TokenUsage,
    begin_token_capture,
    feature_for_path,
    rate_limit_per_day,
    rate_limit_per_minute,
    retention_cutoff,
    start_of_utc_day,
    summarize_tokens,
)
from ..core.auth import (
    AUTH_COOKIE_NAME,
    DEFAULT_TENANT_ID,
    auth_enabled,
    ensure_role,
    ensure_tenant_role,
    get_tenant,
    google_oauth_client_id,
    local_client_is_allowed,
    verify_app_token,
)

logger = logging.getLogger(__name__)


# APIボディ全体の上限。最大の入力は資料添付のbase64(12MB)なので、その2倍を既定にする。
# リバースプロキシ側の上限が外れていても、アプリだけで巨大ボディを弾けるようにする。
MAX_REQUEST_BYTES = int(os.getenv("HINAMI_MAX_REQUEST_BYTES", str(24 * 1024 * 1024)))


_ai_burst_limiter = BurstLimiter()


# 認証を無効にした開発モードで記録する擬似利用者。
LOCAL_USAGE_USER = "local"


allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "HINAMI_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]
# 同一オリジンからの更新を許可するホスト。未設定なら HINAMI_CORS_ORIGINS だけを見る。
allowed_hosts = [
    host.strip().lower()
    for host in os.getenv("HINAMI_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
# hostname[:port] または [IPv6][:port] のみ許可する。
HOST_HEADER_PATTERN = re.compile(
    r"[A-Za-z0-9._\-]+(?::\d{1,5})?|\[[0-9A-Fa-f:.]+\](?::\d{1,5})?"
)


def _required_role_for_request(method: str, path: str) -> str | None:
    if not auth_enabled():
        return None
    if method == "OPTIONS":
        return None
    if not path.startswith("/api"):
        return None
    if path in {"/api/health", "/api/auth/config", "/api/initial-data"} and method == "GET":
        return None
    if path in {"/api/auth/google", "/api/auth/demo"} and method == "POST":
        return None
    # ユーザー管理はシステム管理者とテナント管理者の両方が使う。誰が何を触れるかは
    # テナントを見ないと決まらないため、ここは認証だけ求めて各エンドポイントで判定する。
    if path.startswith("/api/users"):
        return "none"
    # バックアップは全テナントを含むDBを取得できるため、テナント管理者ではなく
    # システム管理者だけに許可する。
    if path == "/api/backups" or path.startswith("/api/backups/"):
        return "admin"
    # APIキーは全テナントのAI機能に効くため、システム管理者だけが扱う。
    if path == "/api/settings" or path.startswith("/api/settings/"):
        return "admin"
    if path.startswith("/api/tenants"):
        return "admin" if method != "GET" else "none"
    if path.startswith("/api/departments/") and path.endswith("/tenant"):
        return "admin"
    # 組織の階層は所属の基準になるため、参照は全員、変更はテナント管理者に限る。
    if path.startswith("/api/org-units"):
        return "viewer" if method == "GET" else "admin"
    # メール分類マスターは日報を書く全員が参照する。変更はテナント管理者に限る。
    if path.startswith("/api/mail-rules"):
        return "viewer" if method == "GET" else "admin"
    # 自分自身の確認とログアウトは、システムロールを持たない利用者にも必要。
    if path == "/api/auth/me":
        return "none"
    # ログアウトはトークンを失効させるため利用者の特定が要る。認証だけで通す。
    if path == "/api/auth/logout":
        return "none"
    # 本人の設定は閲覧のみの利用者でも変えられる。書き込むのは自分の分だけ。
    if path == "/api/user-preferences/speech":
        return "viewer"
    if method == "GET":
        return "viewer"
    return "user"


def request_is_https(request: Request) -> bool:
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded_proto == "https"


def _request_path(request: Request) -> str:
    """ルーティングが実際に使う生のパス。

    request.url はHostヘッダーを連結して再構成されるため、`Host: example.com/x`
    のような値でパスがずれる。認可判定とルーティングで別の値を見ると、
    保護対象を「APIではない」と誤認して認証を飛ばしてしまう。
    """
    return str(request.scope.get("path", ""))


def _request_host_is_valid(request: Request) -> bool:
    """Hostヘッダーが hostname[:port] の形かを確かめる。

    パスや空白を含む値を通すと、URL再構成に依存した判定がすべて崩れる。
    HINAMI_ALLOWED_HOSTS を設定した場合は、その一覧だけを受け付ける。
    """
    host = request.headers.get("Host", "").strip()
    if not host:
        # Hostが無い場合はrequest.urlがserver情報から組まれるため、ずれは起きない。
        return True
    if len(host) > 255 or not HOST_HEADER_PATTERN.fullmatch(host):
        return False
    return not allowed_hosts or host.lower() in allowed_hosts


def _declared_body_bytes(request: Request) -> int | None:
    """Content-Lengthが読めればそのバイト数を返す。無ければNone。

    chunked転送では宣言が無いため、これだけでは上限を保証できない。
    Gateway側のボディ上限と併用する前提の、二重防御のうちのアプリ側。
    """
    raw = request.headers.get("Content-Length", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """レート制限のキーに使う接続元。

    X-Forwarded-For は偽装できるため、信頼できるリバースプロキシ配下でのみ意味を持つ。
    HINAMI_TRUST_FORWARDED_FOR を有効にしたときだけ先頭の値を採用し、
    それ以外は直接の接続元を使う（直接公開された環境でヘッダーを偽装されても制限を逃れられない）。
    """
    if os.getenv("HINAMI_TRUST_FORWARDED_FOR", "").strip().lower() in {"1", "true", "yes"}:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    client = request.client
    return client.host if client else "unknown"


def _request_origin_is_allowed(request: Request) -> bool:
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        return True
    if origin in set(allowed_origins):
        return True
    host = request.headers.get("Host", "").strip()
    if not host:
        return False
    # 同一オリジンの許可はHostヘッダー由来で、送信元が値を選べる経路では信用できない。
    # ブラウザはHostを偽装できないためCSRF対策としては成立するが、
    # HINAMI_ALLOWED_HOSTS を設定した場合はその一覧だけへ絞る。
    if allowed_hosts and host.lower() not in allowed_hosts:
        return False
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    scheme = forwarded_proto or request.url.scheme
    return origin == f"{scheme}://{host}"


async def authorize_api_requests(request: Request, call_next):
    if not _request_host_is_valid(request):
        return JSONResponse(status_code=400, content={"detail": "Hostヘッダーが不正です。"})
    # Googleで確認しないログイン（なし・お試し）は、この端末（とComposeのゲートウェイ）からだけ使える。
    if not google_oauth_client_id() and not local_client_is_allowed(request.client.host if request.client else None):
        return JSONResponse(
            status_code=403,
            content={"detail": "ログインなし・お試しログインのモードは、この端末からのみ利用できます。"},
        )
    request_path = _request_path(request)
    oversize = _declared_body_bytes(request)
    if oversize is not None and oversize > MAX_REQUEST_BYTES:
        return JSONResponse(status_code=413, content={"detail": "リクエストが大きすぎます。"})
    required_role = _required_role_for_request(request.method.upper(), request_path)
    public_path = request_path in {
        "/api/health",
        "/api/auth/config",
        "/api/auth/google",
        "/api/auth/demo",
        "/api/initial-data",
    }
    if (
        auth_enabled()
        and request_path.startswith("/api")
        and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        and not _request_origin_is_allowed(request)
    ):
        return JSONResponse(status_code=403, content={"detail": "許可されていないOriginからの操作です。"})
    tenant_id = request.headers.get("X-Tenant-ID", DEFAULT_TENANT_ID).strip().lower() or DEFAULT_TENANT_ID
    feature = feature_for_path(request_path)
    if required_role is None:
        if (
            request_path.startswith("/api")
            and not public_path
            and not request_path.startswith("/api/tenants")
        ):
            try:
                get_tenant(tenant_id)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            request.state.tenant_id = tenant_id
        if not feature:
            return await call_next(request)
        # 認証を無効にした開発モードでも利用状況は残す。利用者は識別できないためlocalで束ねる。
        return await _call_with_ai_usage(request, call_next, tenant_id, LOCAL_USAGE_USER, feature)
    try:
        authorization = request.headers.get("Authorization", "")
        scheme, _, bearer_token = authorization.partition(" ")
        token = bearer_token.strip() if scheme.lower() == "bearer" else request.cookies.get(AUTH_COOKIE_NAME, "")
        if not token.strip():
            raise HTTPException(status_code=401, detail="ログインが必要です。")
        user = verify_app_token(token.strip())
        if required_role == "none":
            # 認証だけを求めるパス。テナント所属の有無は各エンドポイントが判断する。
            pass
        elif request_path.startswith(("/api/users", "/api/tenants", "/api/departments", "/api/backups", "/api/settings")):
            ensure_role(user, required_role)  # type: ignore[arg-type]
        else:
            request.state.tenant_role = ensure_tenant_role(
                user,
                tenant_id,
                required_role,  # type: ignore[arg-type]
            )
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    request.state.user = user
    request.state.tenant_id = tenant_id
    if not feature:
        return await call_next(request)
    return await _call_with_ai_usage(request, call_next, tenant_id, str(user.get("email", "")), feature)


async def _call_with_ai_usage(request: Request, call_next, tenant_id: str, user_email: str, feature: str):
    """AI呼び出しの回数を利用者ごとに制限し、結果を記録する。"""
    retry_after = _ai_burst_limiter.retry_after_seconds(
        tenant_id, user_email, rate_limit_per_minute()
    )
    daily_limit = rate_limit_per_day()
    daily_used = 0
    if not retry_after and daily_limit:
        daily_used = await run_in_threadpool(
            runtime.store.count_ai_usage_since,
            tenant_id=tenant_id,
            user_email=user_email,
            since=start_of_utc_day(),
        )
        if daily_used >= daily_limit:
            retry_after = _seconds_until_utc_tomorrow()
    if retry_after:
        await _record_ai_usage(tenant_id, user_email, feature, request, "rate-limited", 0)
        detail = (
            f"AI機能の1日あたりの上限（{daily_limit}回）に達しました。明日また利用できます。"
            if daily_limit and daily_used >= daily_limit
            else "AI機能の呼び出しが集中しています。少し待ってから試してください。"
        )
        return JSONResponse(
            status_code=429,
            content={"detail": detail},
            headers={"Retry-After": str(retry_after)},
        )
    _ai_burst_limiter.record(tenant_id, user_email)
    started = time.monotonic()
    # LLM側がこの器へトークン数を積む。1リクエストで複数回呼ぶ機能もあるため合算する。
    token_bucket = begin_token_capture()
    try:
        response = await call_next(request)
    except Exception:
        await _record_ai_usage(
            tenant_id, user_email, feature, request, "error",
            int((time.monotonic() - started) * 1000), summarize_tokens(token_bucket),
        )
        raise
    await _record_ai_usage(
        tenant_id, user_email, feature, request,
        "ok" if response.status_code < 400 else "error",
        int((time.monotonic() - started) * 1000), summarize_tokens(token_bucket),
    )
    return response


async def _record_ai_usage(
    tenant_id: str,
    user_email: str,
    feature: str,
    request: Request,
    outcome: str,
    duration_ms: int,
    tokens: TokenUsage | None = None,
) -> None:
    counted = tokens or TokenUsage(0, 0, 0)
    try:
        await run_in_threadpool(
            runtime.store.record_ai_usage,
            tenant_id=tenant_id,
            user_email=user_email,
            feature=feature,
            endpoint=_request_path(request),
            outcome=outcome,
            duration_ms=duration_ms,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            prompt_tokens=counted.prompt,
            output_tokens=counted.output,
            total_tokens=counted.total,
        )
    except Exception:
        # 記録の失敗でAI機能を止めない。
        logger.warning("AI usage record failed", exc_info=True)


def prune_ai_usage() -> None:
    """保存期間を過ぎた利用記録を消す。件数だけの記録なので長期保持しない。"""
    try:
        removed = runtime.store.prune_ai_usage(before=retention_cutoff())
    except Exception:
        logger.warning("AI usage prune failed", exc_info=True)
        return
    if removed:
        logger.info("Pruned %s AI usage records", removed)


def _seconds_until_utc_tomorrow() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))
