"""組織単位の日報の集計・サマリー・業務の棚卸し。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool

from .. import runtime
from ..schemas import (
    WorkGraph,
    WorkJournalDigestRequest,
    WorkJournalDigestResponse,
    WorkJournalDocumentFlowReport,
    WorkJournalOrganizationActivity,
    WorkJournalWorkMap,
)
from ..services.gemini import connection_for, model_for
from ..services.llm_work_journal_digest import (
    build_organization_activity,
    summarize_organization_journals,
)
from ..services.llm_work_journal_mining import build_document_flows, build_work_map
from ..services.work_graph import build_work_graph
from .common import ensure_org_unit_access, org_unit_subtree_ids, request_tenant_id

router = APIRouter()


@router.get("/api/work-journals/organization", response_model=WorkJournalOrganizationActivity)
def list_organization_work_journals(
    request: Request,
    org_unit_id: str = Query(min_length=1, max_length=80),
    date_from: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
    date_to: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
) -> WorkJournalOrganizationActivity:
    target, name = ensure_org_unit_access(request, org_unit_id)
    records = runtime.store.list_org_unit_work_journals(
        org_unit_ids=org_unit_subtree_ids(target, request_tenant_id(request)),
        tenant_id=request_tenant_id(request),
        date_from=date_from,
        date_to=date_to,
    )
    return build_organization_activity(target, name, date_from, date_to, records)


@router.post("/api/work-journals/organization/summary", response_model=WorkJournalDigestResponse)
async def summarize_organization_work_journals(
    payload: WorkJournalDigestRequest, request: Request
) -> WorkJournalDigestResponse:
    """本人が確認して保存した分類データだけを材料に、組織サマリーを生成する。"""
    target, name = ensure_org_unit_access(request, payload.org_unit_id)
    records = runtime.store.list_org_unit_work_journals(
        org_unit_ids=org_unit_subtree_ids(target, request_tenant_id(request)),
        tenant_id=request_tenant_id(request),
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    activity = build_organization_activity(
        target, name, payload.date_from, payload.date_to, records
    )
    digest = await run_in_threadpool(summarize_organization_journals, activity)
    return WorkJournalDigestResponse.model_validate(
        {
            **digest.model_dump(),
            "activity": activity.model_dump(),
            "provider": connection_for(),
            "model": model_for(),
        }
    )


@router.get("/api/work-journals/organization/document-flows", response_model=WorkJournalDocumentFlowReport)
def list_organization_document_flows(
    request: Request,
    org_unit_id: str = Query(min_length=1, max_length=80),
    date_from: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
    date_to: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
) -> WorkJournalDocumentFlowReport:
    """同じ資料に複数人が触れた流れを、受け渡しの実態として返す。"""
    target, name = ensure_org_unit_access(request, org_unit_id)
    records = runtime.store.list_org_unit_work_journals(
        org_unit_ids=org_unit_subtree_ids(target, request_tenant_id(request)),
        tenant_id=request_tenant_id(request),
        date_from=date_from,
        date_to=date_to,
    )
    report = build_document_flows(name, date_from, date_to, records)
    report.org_unit_id = target
    return report


@router.get("/api/work-journals/organization/work-graph", response_model=WorkGraph)
def build_organization_work_graph(
    request: Request,
    org_unit_id: str = Query(min_length=1, max_length=80),
    date_from: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
    date_to: str = Query(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$"),
) -> WorkGraph:
    """蓄積した業務辞書と資料の受け渡しから、手を入れる場所を構造として示す。"""
    target, name = ensure_org_unit_access(request, org_unit_id)
    tenant_id = request_tenant_id(request)
    records = runtime.store.list_org_unit_work_journals(
        org_unit_ids=org_unit_subtree_ids(target, tenant_id),
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
    )
    graph = build_work_graph(
        name,
        date_from,
        date_to,
        runtime.store.list_work_profiles(org_unit_id=target, tenant_id=tenant_id),
        build_document_flows(name, date_from, date_to, records),
    )
    graph.org_unit_id = target
    return graph


@router.post("/api/work-journals/organization/work-map", response_model=WorkJournalWorkMap)
async def build_organization_work_map(
    payload: WorkJournalDigestRequest, request: Request
) -> WorkJournalWorkMap:
    """日報の仕事を業務ごとにまとめ、属人化している業務を洗い出す。"""
    target, name = ensure_org_unit_access(request, payload.org_unit_id)
    tenant_id = request_tenant_id(request)
    records = runtime.store.list_org_unit_work_journals(
        org_unit_ids=org_unit_subtree_ids(target, tenant_id),
        tenant_id=tenant_id,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    # 確定済みの業務辞書を渡して名称の揺れを抑え、結果を辞書へ戻して次回の基準にする。
    known_profiles = runtime.store.list_work_profiles(org_unit_id=target, tenant_id=tenant_id)
    work_map = await run_in_threadpool(
        build_work_map, name, payload.date_from, payload.date_to, records, known_profiles
    )
    work_map.org_unit_id = target
    if work_map.profiles:
        runtime.store.save_work_profiles(work_map.profiles, org_unit_id=target, tenant_id=tenant_id)
    work_map.model = model_for()
    return work_map
