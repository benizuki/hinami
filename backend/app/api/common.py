"""複数のルーターが使う、リクエストの利用者・テナント・組織の解決。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from .. import runtime
from ..core.auth import DEFAULT_TENANT_ID, auth_enabled
from ..schemas import OrgUnitRecord


def request_tenant_id(request: Request) -> str:
    return str(getattr(request.state, "tenant_id", DEFAULT_TENANT_ID)).strip().lower()


def header_tenant_id(request: Request) -> str:
    """認証前でも参照できる選択中テナント。ログイン応答の所属解決に使う。"""
    header = request.headers.get("X-Tenant-ID", "").strip().lower()
    return header or request_tenant_id(request)


def request_user_email_or_empty(request: Request) -> str:
    user = getattr(request.state, "user", None)
    return str(user.get("email", "") if isinstance(user, dict) else "").strip().lower()


def work_journal_owner(request: Request) -> str:
    return request_user_email_or_empty(request) or "local-user"


def tenant_org_units(tenant_id: str) -> list[OrgUnitRecord]:
    """人の所属を表す組織単位。"""
    return runtime.store.list_org_units(tenant_id)


def resolve_org_unit(value: str, tenant_id: str) -> tuple[str, str]:
    """組織単位のIDまたは名前から(ID, 名前)を引く。解決できない場合は空を返す。"""
    target = value.strip()
    if not target:
        return "", ""
    for unit in tenant_org_units(tenant_id):
        if target in {unit.id, unit.name}:
            return unit.id, unit.name
    return "", ""


def org_unit_subtree_ids(org_unit_id: str, tenant_id: str) -> list[str]:
    """指定した組織単位と、その配下すべてのIDを返す。

    種別が「全社」の組織は全部門を統括するポジションなので、部門を配下へ
    ぶら下げ直さなくてもテナント内の全組織を範囲に含める。
    """
    units = tenant_org_units(tenant_id)
    if any(unit.id == org_unit_id and unit.kind == "全社" for unit in units):
        return [org_unit_id, *[unit.id for unit in units if unit.id != org_unit_id]]
    children: dict[str, list[str]] = {}
    for unit in units:
        children.setdefault(unit.parent_id, []).append(unit.id)
    collected: list[str] = []
    pending = [org_unit_id]
    while pending:
        current = pending.pop()
        if current in collected:
            continue
        collected.append(current)
        pending.extend(children.get(current, []))
    return collected


def user_org_unit_id(user: dict[str, Any], tenant_id: str) -> str:
    """そのテナントでの所属組織。組織はテナントごとに別なので所属も所属先で持つ。"""
    for membership in user.get("tenant_memberships", []):
        if not isinstance(membership, dict) or membership.get("tenant_id") != tenant_id:
            continue
        resolved, _ = resolve_org_unit(str(membership.get("org_unit_id") or ""), tenant_id)
        if resolved:
            return resolved
    # 移行前の利用者は、テナントを持たないorg_unit_idや部門の値からの解決を試みる。
    for key in ("org_unit_id", "department_id", "department"):
        resolved, _ = resolve_org_unit(str(user.get(key) or ""), tenant_id)
        if resolved:
            return resolved
    return ""


def request_user_org_unit_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict):
        return ""
    return user_org_unit_id(user, request_tenant_id(request))


def request_user_is_admin(request: Request) -> bool:
    user = getattr(request.state, "user", None)
    return isinstance(user, dict) and str(user.get("role", "")).strip().lower() == "admin"


def ensure_org_unit_access(request: Request, org_unit_id: str) -> tuple[str, str]:
    """日報の組織共有は、自分が所属する組織単位とその配下に限る。

    上位の組織に所属する利用者ほど広く見えるため、部門長は配下の課も参照できる。
    """
    tenant_id = request_tenant_id(request)
    resolved, name = resolve_org_unit(org_unit_id, tenant_id)
    if not resolved:
        # 存在しない組織と他組織を、応答から区別できないようにする。
        raise HTTPException(status_code=404, detail="指定された組織の記録が見つかりません。")
    if not auth_enabled() or request_user_is_admin(request):
        return resolved, name
    viewer_unit = request_user_org_unit_id(request)
    if not viewer_unit or resolved not in org_unit_subtree_ids(viewer_unit, tenant_id):
        raise HTTPException(status_code=404, detail="指定された組織の記録が見つかりません。")
    return resolved, name


def request_user_email(request: Request) -> str:
    user = getattr(request.state, "user", None)
    email = str(user.get("email", "") if isinstance(user, dict) else "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="ログインが必要です。")
    return email
