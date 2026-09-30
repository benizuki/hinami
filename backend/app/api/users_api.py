"""ユーザー管理。システム管理者は全テナント、テナント管理者は自テナントだけを扱う。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..core.auth import (
    create_user_master_entry,
    delete_user_master_entry,
    get_tenant,
    list_user_master_entries,
    tenant_role,
    update_user_master_entry,
)
from ..schemas import UserMasterEntry, UserMasterUpdate
from .common import request_tenant_id, request_user_email_or_empty, resolve_org_unit

router = APIRouter()


def _user_admin_scope(request: Request, *, write: bool) -> str | None:
    """ユーザー管理の権限範囲。

    Noneは全テナント、文字列はそのテナントに限った権限を表す。参照はシステム
    viewerも全テナントに及ぶが、更新はシステムadminかテナントadminだけが行える。
    """
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict):
        # 認証を無効にした開発モードでは利用者を特定できないため制限しない。
        return None
    role = str(user.get("role", ""))
    if role == "admin":
        return None
    if not write and role == "viewer":
        return None
    tenant_id = request_tenant_id(request)
    if tenant_role(user, tenant_id) == "admin":
        get_tenant(tenant_id)
        return tenant_id
    raise HTTPException(status_code=403, detail="ユーザーを管理する権限がありません。")


def _visible_to_tenant_admin(entry: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    """テナント管理者へ返す表現。他テナントの所属は伏せる。"""
    return {
        **entry,
        "tenant_memberships": [
            membership
            for membership in entry.get("tenant_memberships", [])
            if isinstance(membership, dict) and membership.get("tenant_id") == tenant_id
        ],
    }


def _tenant_managed_entry(email: str, tenant_id: str) -> dict[str, Any]:
    """テナント管理者が操作してよい既存ユーザーを取り出す。"""
    normalized_email = email.strip().lower()
    for entry in list_user_master_entries():
        if entry["email"] != normalized_email:
            continue
        if tenant_role(entry, tenant_id) is None:
            break
        if entry.get("role") == "admin":
            # システム管理者のアカウントはテナント管理者から触らせない。
            raise HTTPException(status_code=403, detail="システム管理者は編集できません。")
        return entry
    raise HTTPException(status_code=404, detail="このテナントに所属するユーザーが見つかりません。")


def _validated_memberships(memberships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """所属を保存する前に、テナントと、そのテナントの組織であることを確かめる。"""
    for membership in memberships:
        tenant_id = str(membership.get("tenant_id") or "").strip().lower()
        get_tenant(tenant_id, require_enabled=False)
        org_unit_id = str(membership.get("org_unit_id") or "").strip()
        if not org_unit_id:
            membership["org_unit_id"] = ""
            continue
        resolved, _ = resolve_org_unit(org_unit_id, tenant_id)
        if not resolved:
            raise HTTPException(
                status_code=422,
                detail="所属組織は、そのテナントの組織マスターに登録されたものを選んでください。",
            )
        membership["org_unit_id"] = resolved
    return memberships


def _membership_for(memberships: list[Any], tenant_id: str) -> dict[str, Any] | None:
    for membership in memberships:
        if isinstance(membership, dict) and membership.get("tenant_id") == tenant_id:
            return membership
    return None


def _merged_memberships(
    current: list[Any],
    requested: list[dict[str, Any]],
    tenant_id: str,
) -> list[dict[str, Any]]:
    """自テナントの所属だけを差し替え、他テナントの所属はそのまま残す。"""
    merged = [
        membership
        for membership in current
        if isinstance(membership, dict) and membership.get("tenant_id") != tenant_id
    ]
    requested_membership = _membership_for(list(requested), tenant_id)
    if requested_membership:
        merged.append({
            "tenant_id": tenant_id,
            "role": requested_membership.get("role", "viewer"),
            "org_unit_id": str(requested_membership.get("org_unit_id") or "").strip(),
        })
    return merged


@router.get("/api/users", response_model=list[UserMasterEntry])
def users(request: Request) -> list[UserMasterEntry]:
    scope = _user_admin_scope(request, write=False)
    entries = list_user_master_entries()
    if scope is None:
        return [UserMasterEntry(**entry) for entry in entries]
    return [
        UserMasterEntry(**_visible_to_tenant_admin(entry, scope))
        for entry in entries
        if tenant_role(entry, scope) is not None
    ]


@router.post("/api/users", response_model=UserMasterEntry)
def create_user(payload: UserMasterEntry, request: Request) -> UserMasterEntry:
    scope = _user_admin_scope(request, write=True)
    memberships = [membership.model_dump() for membership in payload.tenant_memberships]
    role = payload.role
    if scope is not None:
        # テナント管理者が作るのは自テナント専用の利用者。システム権限は持たせない。
        requested_membership = _membership_for(memberships, scope)
        memberships = [{
            "tenant_id": scope,
            "role": requested_membership.get("role", "viewer") if requested_membership else "viewer",
            "org_unit_id": (
                str(requested_membership.get("org_unit_id") or "").strip()
                if requested_membership else ""
            ),
        }]
        role = "none"
    memberships = _validated_memberships(memberships)
    entry = create_user_master_entry(
        email=payload.email,
        name=payload.name,
        department=payload.department,
        department_id=payload.department_id,
        org_unit_id=payload.org_unit_id,
        role=role,
        enabled=payload.enabled,
        google_subject=payload.google_subject,
        tenant_memberships=(
            memberships
            if scope is not None or "tenant_memberships" in payload.model_fields_set
            else None
        ),
    )
    if scope is not None:
        return UserMasterEntry(**_visible_to_tenant_admin(entry, scope))
    return UserMasterEntry(**entry)


@router.put("/api/users/{email}", response_model=UserMasterEntry)
def update_user(email: str, payload: UserMasterUpdate, request: Request) -> UserMasterEntry:
    scope = _user_admin_scope(request, write=True)
    changes = payload.model_dump(exclude_unset=True)
    if scope is not None:
        current = _tenant_managed_entry(email, scope)
        # システムロールと他テナントの所属は、テナント管理者の変更対象外。
        changes["role"] = current["role"]
        changes["tenant_memberships"] = _merged_memberships(
            current.get("tenant_memberships", []),
            changes.get("tenant_memberships", []),
            scope,
        )
        if email.strip().lower() == request_user_email_or_empty(request):
            # 自分の管理権限を落とすと、このテナントを管理できる人がいなくなりうる。
            own_membership = _membership_for(changes["tenant_memberships"], scope)
            if not own_membership or own_membership.get("role") != "admin":
                raise HTTPException(status_code=400, detail="自分自身の管理権限は変更できません。")
    if "tenant_memberships" in changes:
        changes["tenant_memberships"] = _validated_memberships(changes["tenant_memberships"])
    entry = update_user_master_entry(email, changes)
    if scope is not None:
        return UserMasterEntry(**_visible_to_tenant_admin(entry, scope))
    return UserMasterEntry(**entry)


@router.delete("/api/users/{email}", status_code=204)
def delete_user(email: str, request: Request) -> Response:
    scope = _user_admin_scope(request, write=True)
    if scope is None:
        delete_user_master_entry(email)
        return Response(status_code=204)
    if email.strip().lower() == request_user_email_or_empty(request):
        raise HTTPException(status_code=400, detail="自分自身をテナントから外すことはできません。")
    current = _tenant_managed_entry(email, scope)
    remaining = [
        membership
        for membership in current.get("tenant_memberships", [])
        if isinstance(membership, dict) and membership.get("tenant_id") != scope
    ]
    if not remaining and current["role"] == "none":
        # このテナント専用の利用者なので、アカウントごと片付ける。
        delete_user_master_entry(email)
        return Response(status_code=204)
    # 他テナントでも使う利用者は、所属を外すだけにとどめる。
    update_user_master_entry(email, {
        **current,
        "tenant_memberships": remaining,
    })
    return Response(status_code=204)
