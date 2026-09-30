"""組織マスター（組織の階層）。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from .. import runtime
from ..core.auth import ensure_tenant_role
from ..schemas import OrgUnitRecord, OrgUnitUpsert
from .common import org_unit_subtree_ids, request_tenant_id, tenant_org_units

router = APIRouter()


def _ensure_org_unit_parent(parent_id: str, tenant_id: str) -> None:
    if not parent_id.strip():
        return
    if parent_id.strip() not in {unit.id for unit in tenant_org_units(tenant_id)}:
        raise HTTPException(status_code=422, detail="親の組織が見つかりません。")


@router.get("/api/org-units", response_model=list[OrgUnitRecord])
def list_org_units(
    request: Request,
    tenant_id: str = Query(default="", max_length=80),
) -> list[OrgUnitRecord]:
    """tenant_idを指定すると、そのテナントの組織を返す。

    所属はテナントごとに決めるため、ユーザー管理画面は他テナントの組織も
    選択肢として必要になる。権限はそのテナントの所属で判定する。
    """
    target = tenant_id.strip().lower() or request_tenant_id(request)
    if target != request_tenant_id(request):
        user = getattr(request.state, "user", None)
        if isinstance(user, dict):
            ensure_tenant_role(user, target, "viewer")
    return tenant_org_units(target)


@router.post("/api/org-units", response_model=OrgUnitRecord)
def create_org_unit(payload: OrgUnitUpsert, request: Request) -> OrgUnitRecord:
    tenant_id = request_tenant_id(request)
    _ensure_org_unit_parent(payload.parent_id, tenant_id)
    record = OrgUnitRecord(
        id=uuid4().hex[:8],
        tenant_id=tenant_id,
        parent_id=payload.parent_id.strip(),
        name=payload.name.strip(),
        kind=payload.kind,
        sort_order=payload.sort_order,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    runtime.store.save_org_unit(record, tenant_id)
    return record


@router.put("/api/org-units/{org_unit_id}", response_model=OrgUnitRecord)
def update_org_unit(org_unit_id: str, payload: OrgUnitUpsert, request: Request) -> OrgUnitRecord:
    tenant_id = request_tenant_id(request)
    units = {unit.id: unit for unit in tenant_org_units(tenant_id)}
    if org_unit_id not in units:
        raise HTTPException(status_code=404, detail="組織が見つかりません。")
    parent_id = payload.parent_id.strip()
    _ensure_org_unit_parent(parent_id, tenant_id)
    if parent_id and parent_id in org_unit_subtree_ids(org_unit_id, tenant_id):
        # 自分自身や配下を親にすると循環して階層が壊れる。
        raise HTTPException(status_code=422, detail="自分自身または配下の組織は親に指定できません。")
    record = OrgUnitRecord(
        id=org_unit_id,
        tenant_id=tenant_id,
        parent_id=parent_id,
        name=payload.name.strip(),
        kind=payload.kind,
        sort_order=payload.sort_order,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    runtime.store.save_org_unit(record, tenant_id)
    return record


@router.delete("/api/org-units/{org_unit_id}", status_code=204)
def delete_org_unit(org_unit_id: str, request: Request) -> Response:
    tenant_id = request_tenant_id(request)
    children = [
        unit for unit in tenant_org_units(tenant_id) if unit.parent_id == org_unit_id
    ]
    if children:
        raise HTTPException(
            status_code=422,
            detail="配下の組織があるため削除できません。先に配下を移動または削除してください。",
        )
    journals = runtime.store.list_org_unit_work_journals([org_unit_id], tenant_id)
    if journals:
        raise HTTPException(
            status_code=422,
            detail=f"この組織には{len(journals)}件の記録が紐づいているため削除できません。",
        )
    if not runtime.store.delete_org_unit(org_unit_id, tenant_id):
        raise HTTPException(status_code=404, detail="組織が見つかりません。")
    return Response(status_code=204)
