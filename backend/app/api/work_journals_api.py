"""業務日報の一覧・保存・削除と、閲覧できるメンバー。"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from .. import runtime
from ..core.auth import auth_enabled, list_user_master_entries, role_rank, tenant_role
from ..schemas import WorkJournalMemberSummary, WorkJournalRecord, WorkJournalSaveRequest
from .common import (
    org_unit_subtree_ids,
    request_tenant_id,
    request_user_is_admin,
    request_user_org_unit_id,
    resolve_org_unit,
    tenant_org_units,
    user_org_unit_id,
    work_journal_owner,
)

router = APIRouter()


def _can_view_member_journals(request: Request) -> bool:
    """他人の業務日報を開けるのは、テナントのmanager以上とシステム管理者だけ。"""
    if not auth_enabled() or request_user_is_admin(request):
        return True
    role = str(getattr(request.state, "tenant_role", "") or "")
    return role_rank(role) >= role_rank("manager")


def _journal_member_summaries(request: Request) -> list[WorkJournalMemberSummary]:
    """業務日報を閲覧してよい相手の一覧。自分は常に含む。

    managerは自分が所属する組織単位とその配下に限る。組織別日報の判定
    （ensure_org_unit_access）と同じ範囲に揃え、権限の境界を1か所に保つ。
    """
    tenant_id = request_tenant_id(request)
    me = work_journal_owner(request)
    unit_names = {unit.id: unit.name for unit in tenant_org_units(tenant_id)}
    myself = WorkJournalMemberSummary(
        email=me,
        name=str((getattr(request.state, "user", None) or {}).get("name") or "") or me,
        org_unit_id=request_user_org_unit_id(request),
        is_self=True,
    )
    myself.org_unit_name = unit_names.get(myself.org_unit_id, "")
    if not auth_enabled() or not _can_view_member_journals(request):
        return [myself]
    scope: set[str] | None = None
    if not request_user_is_admin(request):
        viewer_unit = request_user_org_unit_id(request)
        # 所属が未設定のmanagerには配下が定まらないため、自分の日報だけを返す。
        if not viewer_unit:
            return [myself]
        scope = set(org_unit_subtree_ids(viewer_unit, tenant_id))
    members: list[WorkJournalMemberSummary] = []
    for entry in list_user_master_entries():
        email = str(entry.get("email") or "").strip().lower()
        if not email or not entry.get("enabled", True):
            continue
        if email != me and tenant_role(entry, tenant_id) is None:
            continue
        org_unit_id = user_org_unit_id(entry, tenant_id)
        if email != me and (scope is not None and org_unit_id not in scope):
            continue
        members.append(
            WorkJournalMemberSummary(
                email=email,
                name=str(entry.get("name") or "") or email,
                org_unit_id=org_unit_id,
                org_unit_name=unit_names.get(org_unit_id, ""),
                is_self=email == me,
            )
        )
    if not any(member.is_self for member in members):
        members.append(myself)
    members.sort(key=lambda member: (not member.is_self, member.org_unit_name, member.name))
    return members


def _journal_owner_for_request(request: Request, owner_email: str) -> str:
    """閲覧してよい日報の持ち主へ解決する。権限がなければ存在ごと伏せる。"""
    requested = owner_email.strip().lower()
    me = work_journal_owner(request)
    if not requested or requested == me:
        return me
    if any(member.email == requested for member in _journal_member_summaries(request)):
        return requested
    raise HTTPException(status_code=404, detail="指定されたユーザーの記録が見つかりません。")


@router.get("/api/work-journals/members", response_model=list[WorkJournalMemberSummary])
def list_work_journal_members(request: Request) -> list[WorkJournalMemberSummary]:
    """業務日報を閲覧できるメンバー。manager以外には自分だけが返る。"""
    return _journal_member_summaries(request)


@router.get("/api/work-journals", response_model=list[WorkJournalRecord])
def list_work_journals(
    request: Request,
    date_from: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
    date_to: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
    owner_email: str = Query(default="", max_length=254),
) -> list[WorkJournalRecord]:
    return runtime.store.list_work_journals(
        owner_email=_journal_owner_for_request(request, owner_email),
        tenant_id=request_tenant_id(request),
        date_from=date_from,
        date_to=date_to,
    )


@router.post("/api/work-journals", response_model=WorkJournalRecord)
def save_work_journal(payload: WorkJournalSaveRequest, request: Request) -> WorkJournalRecord:
    owner_email = work_journal_owner(request)
    tenant_id = request_tenant_id(request)
    # 所属は必ず組織マスターで解決してから保存する。未解決のまま別組織へ混ざるのを防ぐ。
    org_unit_id, org_unit_name = resolve_org_unit(
        payload.org_unit_id or payload.department_id or payload.department, tenant_id
    )
    if not org_unit_id:
        raise HTTPException(
            status_code=422,
            detail="組織マスターに登録された所属を指定してください。未設定の場合は管理者へ依頼してください。",
        )
    existing = runtime.store.list_work_journals(
        owner_email=owner_email,
        tenant_id=tenant_id,
        date_from=payload.journal_date,
        date_to=payload.journal_date,
    )
    now = datetime.now(timezone.utc).isoformat()
    record = WorkJournalRecord(
        **{**payload.model_dump(), "org_unit_id": org_unit_id, "org_unit_name": org_unit_name},
        owner_email=owner_email,
        created_at=existing[0].created_at if existing else now,
        updated_at=now,
    )
    return runtime.store.save_work_journal(record, tenant_id)


@router.delete("/api/work-journals/{journal_date}", status_code=204)
def delete_work_journal(journal_date: str, request: Request) -> Response:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", journal_date):
        raise HTTPException(status_code=422, detail="日付形式が正しくありません。")
    deleted = runtime.store.delete_work_journal(
        journal_date=journal_date,
        owner_email=work_journal_owner(request),
        tenant_id=request_tenant_id(request),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="記録が見つかりません。")
    return Response(status_code=204)
