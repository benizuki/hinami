from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request

from .. import runtime
from ..core.ai_usage import current_feature_label, rate_limit_per_day, rate_limit_per_minute, start_of_utc_day
from ..core.auth import auth_enabled
from ..schemas import AiUsageDayRow, AiUsageFeatureRow, AiUsageReport, AiUsageUserRow
from .common import request_tenant_id, request_user_email, request_user_is_admin
from .middleware import LOCAL_USAGE_USER

router = APIRouter()


@router.get("/api/ai-usage", response_model=AiUsageReport)
def ai_usage_report(
    request: Request,
    date_from: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
    date_to: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
) -> AiUsageReport:
    """AI機能の利用状況。管理者はテナント全体、それ以外は自分の分だけ見える。"""
    tenant_id = request_tenant_id(request)
    # 認証を無効にした開発モードでは利用者を識別できないため、記録側と同じ擬似利用者で見る。
    email = request_user_email(request) if auth_enabled() else LOCAL_USAGE_USER
    # システム管理者、またはこのテナントのadminはテナント全体を見る。
    is_admin = (
        not auth_enabled()
        or request_user_is_admin(request)
        or getattr(request.state, "tenant_role", "") == "admin"
    )
    today = datetime.now(timezone.utc).date()
    start = date_from or (today - timedelta(days=29)).isoformat()
    # occurred_atはISO文字列のため、終端は翌日の00:00と比較して当日を含める。
    end_exclusive = (
        (datetime.fromisoformat(date_to).date() + timedelta(days=1)).isoformat()
        if date_to
        else (today + timedelta(days=1)).isoformat()
    )
    summary = runtime.store.summarize_ai_usage(
        tenant_id=tenant_id,
        date_from=start,
        date_to=end_exclusive,
        user_email="" if is_admin else email,
    )
    by_user = [
        AiUsageUserRow(
            user_email=str(row[0]),
            calls=int(row[1] or 0),
            total_duration_ms=int(row[2] or 0),
            errors=int(row[3] or 0),
            rate_limited=int(row[4] or 0),
            prompt_tokens=int(row[5] or 0),
            output_tokens=int(row[6] or 0),
            total_tokens=int(row[7] or 0),
        )
        for row in summary["by_user"]
    ]
    return AiUsageReport(
        date_from=start,
        date_to=date_to or today.isoformat(),
        scope="tenant" if is_admin else "self",
        total_calls=sum(row.calls for row in by_user),
        total_tokens=sum(row.total_tokens for row in by_user),
        rate_limit_per_minute=rate_limit_per_minute(),
        rate_limit_per_day=rate_limit_per_day(),
        used_today=runtime.store.count_ai_usage_since(
            tenant_id=tenant_id, user_email=email, since=start_of_utc_day()
        ),
        by_user=by_user,
        by_feature=_merged_feature_rows(summary["by_feature"]),
        by_day=[
            AiUsageDayRow(day=str(row[0]), calls=int(row[1] or 0), total_tokens=int(row[2] or 0))
            for row in summary["by_day"]
        ],
    )


def _merged_feature_rows(rows) -> list[AiUsageFeatureRow]:
    """名前を変えた機能の過去の記録を、新しい名前へ寄せて合算する。"""
    merged: dict[str, AiUsageFeatureRow] = {}
    for row in rows:
        feature = current_feature_label(str(row[0]))
        current = merged.setdefault(feature, AiUsageFeatureRow(feature=feature, calls=0, total_duration_ms=0, total_tokens=0))
        current.calls += int(row[1] or 0)
        current.total_duration_ms += int(row[2] or 0)
        current.total_tokens += int(row[3] or 0)
    return sorted(merged.values(), key=lambda item: item.calls, reverse=True)
