"""メール分類マスター（差出人と、申請・依頼種別の判定語）。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
# pathlib.Pathと名前が衝突するため、パスパラメータの宣言だけ別名で受ける。
from fastapi import Path as PathParam
from fastapi.responses import Response

from .. import runtime
from ..schemas import (
    MailClassificationRules,
    MailRequestTypeRule,
    MailRequestTypeRuleUpsert,
    MailSourceRule,
    MailSourceRuleUpsert,
)
from ..services.mail_classification import (
    MAIL_REQUEST_TYPE_RULE_KIND,
    MAIL_SOURCE_RULE_KIND,
    default_request_type_rules,
)
from .common import request_tenant_id

router = APIRouter()


MAIL_RULE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,80}$"
# 既定値を配布済みかどうかの印。判定に使うマスターとは別の種別で持つ。
MAIL_RULE_SEED_KIND = "seed"


def _tenant_mail_source_rules(tenant_id: str) -> list[MailSourceRule]:
    return [
        MailSourceRule.model_validate(record)
        for record in runtime.store.list_mail_rules(MAIL_SOURCE_RULE_KIND, tenant_id)
    ]


def _tenant_mail_request_type_rules(tenant_id: str) -> list[MailRequestTypeRule]:
    records = runtime.store.list_mail_rules(MAIL_REQUEST_TYPE_RULE_KIND, tenant_id)
    if records or runtime.store.list_mail_rules(MAIL_RULE_SEED_KIND, tenant_id):
        return [MailRequestTypeRule.model_validate(record) for record in records]
    # 未登録のテナントには既定の判定語を配り、マスターを作る前から分類が動く状態にする。
    # 配布済みの印を残し、管理者が既定値を全部消しても復活しないようにする。
    now = datetime.now(timezone.utc).isoformat()
    defaults = default_request_type_rules(now)
    for rule in defaults:
        runtime.store.save_mail_rule(
            MAIL_REQUEST_TYPE_RULE_KIND, rule.model_dump(mode="json"), tenant_id
        )
    runtime.store.save_mail_rule(
        MAIL_RULE_SEED_KIND,
        {"id": MAIL_REQUEST_TYPE_RULE_KIND, "sort_order": 0, "updated_at": now},
        tenant_id,
    )
    return defaults


def _cleaned_mail_keywords(keywords: list[str]) -> list[str]:
    cleaned: list[str] = []
    for keyword in keywords:
        text = keyword.strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _validated_mail_source_ids(source_ids: list[str], tenant_id: str) -> list[str]:
    known = {rule.id for rule in _tenant_mail_source_rules(tenant_id)}
    targets: list[str] = []
    for source_id in source_ids:
        value = source_id.strip()
        if not value or value in targets:
            continue
        if value not in known:
            raise HTTPException(status_code=422, detail="登録されていない差出人が指定されています。")
        targets.append(value)
    return targets


@router.get("/api/mail-rules", response_model=MailClassificationRules)
def list_mail_rules(request: Request) -> MailClassificationRules:
    tenant_id = request_tenant_id(request)
    return MailClassificationRules(
        sources=_tenant_mail_source_rules(tenant_id),
        request_types=_tenant_mail_request_type_rules(tenant_id),
    )


def _store_mail_source_rule(
    rule_id: str,
    payload: MailSourceRuleUpsert,
    tenant_id: str,
) -> MailSourceRule:
    record = MailSourceRule(
        id=rule_id,
        name=payload.name.strip(),
        kind=payload.kind,
        match_type=payload.match_type,
        # 照合はブラウザ側で小文字にして行うため、登録時から揃えておく。
        match_value=payload.match_value.strip().lower().lstrip("@"),
        default_category=payload.default_category,
        sort_order=payload.sort_order,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    runtime.store.save_mail_rule(MAIL_SOURCE_RULE_KIND, record.model_dump(mode="json"), tenant_id)
    return record


@router.post("/api/mail-rules/sources", response_model=MailSourceRule)
def create_mail_source_rule(payload: MailSourceRuleUpsert, request: Request) -> MailSourceRule:
    return _store_mail_source_rule(uuid4().hex[:8], payload, request_tenant_id(request))


@router.put("/api/mail-rules/sources/{rule_id}", response_model=MailSourceRule)
def update_mail_source_rule(
    payload: MailSourceRuleUpsert,
    request: Request,
    rule_id: str = PathParam(pattern=MAIL_RULE_ID_PATTERN),
) -> MailSourceRule:
    tenant_id = request_tenant_id(request)
    if rule_id not in {rule.id for rule in _tenant_mail_source_rules(tenant_id)}:
        raise HTTPException(status_code=404, detail="差出人の登録が見つかりません。")
    return _store_mail_source_rule(rule_id, payload, tenant_id)


@router.delete("/api/mail-rules/sources/{rule_id}", status_code=204)
def delete_mail_source_rule(
    request: Request,
    rule_id: str = PathParam(pattern=MAIL_RULE_ID_PATTERN),
) -> Response:
    tenant_id = request_tenant_id(request)
    if not runtime.store.delete_mail_rule(MAIL_SOURCE_RULE_KIND, rule_id, tenant_id):
        raise HTTPException(status_code=404, detail="差出人の登録が見つかりません。")
    # 参照を残すと、判定対象が無い種別として黙って一致しなくなる。
    for rule in _tenant_mail_request_type_rules(tenant_id):
        if rule_id not in rule.source_ids:
            continue
        rule.source_ids = [value for value in rule.source_ids if value != rule_id]
        rule.updated_at = datetime.now(timezone.utc).isoformat()
        runtime.store.save_mail_rule(
            MAIL_REQUEST_TYPE_RULE_KIND, rule.model_dump(mode="json"), tenant_id
        )
    return Response(status_code=204)


def _store_mail_request_type_rule(
    rule_id: str,
    payload: MailRequestTypeRuleUpsert,
    tenant_id: str,
) -> MailRequestTypeRule:
    record = MailRequestTypeRule(
        id=rule_id,
        name=payload.name.strip(),
        category=payload.category,
        source_ids=_validated_mail_source_ids(payload.source_ids, tenant_id),
        keywords=_cleaned_mail_keywords(payload.keywords),
        sort_order=payload.sort_order,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    runtime.store.save_mail_rule(
        MAIL_REQUEST_TYPE_RULE_KIND, record.model_dump(mode="json"), tenant_id
    )
    return record


@router.post("/api/mail-rules/request-types", response_model=MailRequestTypeRule)
def create_mail_request_type_rule(
    payload: MailRequestTypeRuleUpsert, request: Request
) -> MailRequestTypeRule:
    tenant_id = request_tenant_id(request)
    # 既定値の配布より先に新規登録すると、後から既定値が混ざる。先に配っておく。
    _tenant_mail_request_type_rules(tenant_id)
    return _store_mail_request_type_rule(uuid4().hex[:8], payload, tenant_id)


@router.put("/api/mail-rules/request-types/{rule_id}", response_model=MailRequestTypeRule)
def update_mail_request_type_rule(
    payload: MailRequestTypeRuleUpsert,
    request: Request,
    rule_id: str = PathParam(pattern=MAIL_RULE_ID_PATTERN),
) -> MailRequestTypeRule:
    tenant_id = request_tenant_id(request)
    if rule_id not in {rule.id for rule in _tenant_mail_request_type_rules(tenant_id)}:
        raise HTTPException(status_code=404, detail="申請・依頼種別の登録が見つかりません。")
    return _store_mail_request_type_rule(rule_id, payload, tenant_id)


@router.delete("/api/mail-rules/request-types/{rule_id}", status_code=204)
def delete_mail_request_type_rule(
    request: Request,
    rule_id: str = PathParam(pattern=MAIL_RULE_ID_PATTERN),
) -> Response:
    tenant_id = request_tenant_id(request)
    # 既定値を1件だけ消したいとき、配る前に消すと次の参照で復活してしまう。
    _tenant_mail_request_type_rules(tenant_id)
    if not runtime.store.delete_mail_rule(MAIL_REQUEST_TYPE_RULE_KIND, rule_id, tenant_id):
        raise HTTPException(status_code=404, detail="申請・依頼種別の登録が見つかりません。")
    return Response(status_code=204)
