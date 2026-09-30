from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.auth import create_tenant_entry, list_tenants, update_tenant_entry
from ..schemas import TenantRecord, TenantUpdate
from .common import ensure_root_org_unit

router = APIRouter()


@router.get("/api/tenants", response_model=list[TenantRecord])
def tenants(request: Request) -> list[TenantRecord]:
    all_tenants = list_tenants()
    user = getattr(request.state, "user", None)
    # システムadminとシステムviewerは全テナントを見る。viewerの書き込みは各APIで止まる。
    if isinstance(user, dict) and user.get("role") not in {"admin", "viewer"}:
        permitted_ids = {
            membership.get("tenant_id")
            for membership in user.get("tenant_memberships", [])
            if isinstance(membership, dict)
        }
        all_tenants = [tenant for tenant in all_tenants if tenant["id"] in permitted_ids]
    return [TenantRecord(**tenant) for tenant in all_tenants]


@router.post("/api/tenants", response_model=TenantRecord)
def create_tenant(payload: TenantRecord) -> TenantRecord:
    tenant = create_tenant_entry(
        tenant_id=payload.id,
        name=payload.name,
        description=payload.description,
        enabled=payload.enabled,
    )
    ensure_root_org_unit(tenant["id"])
    return TenantRecord(**tenant)


@router.put("/api/tenants/{tenant_id}", response_model=TenantRecord)
def update_tenant(tenant_id: str, payload: TenantUpdate) -> TenantRecord:
    tenant = update_tenant_entry(tenant_id, payload.model_dump())
    return TenantRecord(**tenant)
