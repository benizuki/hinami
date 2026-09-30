"""アプリの組み立て。ミドルウェアとルーターの登録だけを行う。

各機能のエンドポイントは api/ 配下に1機能1ファイルで置く。
"""

from __future__ import annotations

from dotenv import load_dotenv

# 各モジュールは読み込み時に環境変数を読む。どれよりも先に .env を反映する。
load_dotenv()

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from .api import (  # noqa: E402
    ai_usage_api,
    auth_api,
    backups_api,
    frontend_api,
    health_api,
    journal_assist_api,
    mail_rules_api,
    org_units_api,
    organization_api,
    settings_api,
    speech_api,
    tenants_api,
    user_preferences_api,
    users_api,
    work_journals_api,
)
from .api.common import ensure_root_org_unit  # noqa: E402
from .api.middleware import allowed_origins, authorize_api_requests, prune_ai_usage  # noqa: E402
from .core.auth import ensure_auth_secret, ensure_user_master, list_tenants, validate_auth_configuration  # noqa: E402
from .core.security_headers import SecurityHeadersMiddleware  # noqa: E402
from .runtime import is_production  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_configuration()
    ensure_user_master()
    ensure_auth_secret()
    for tenant in list_tenants():
        ensure_root_org_unit(tenant["id"])
    prune_ai_usage()
    yield


app = FastAPI(
    title="Hinami API",
    version="0.1.0",
    lifespan=lifespan,
    # 本番では保護APIを含む全スキーマを未認証で公開しないよう、API仕様を配信しない。
    docs_url=None if is_production() else "/docs",
    redoc_url=None if is_production() else "/redoc",
    openapi_url=None if is_production() else "/openapi.json",
)

# 後から登録したミドルウェアほど外側で動く。認可の検査を最も外側に置く。
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.middleware("http")(authorize_api_requests)

for module in (
    health_api,
    settings_api,
    backups_api,
    auth_api,
    tenants_api,
    users_api,
    journal_assist_api,
    ai_usage_api,
    work_journals_api,
    org_units_api,
    mail_rules_api,
    organization_api,
    speech_api,
    user_preferences_api,
):
    app.include_router(module.router)
# 全パスを受けるSPAフォールバックを含むため、必ず最後に登録する。
app.include_router(frontend_api.router)
