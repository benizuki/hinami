"""日報を書くときのAI補助（対話・資料の解析・メールの要約）。どれも保存しない。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..core.google_integrations import google_integration_enabled
from ..schemas import (
    WorkJournalAttachmentAnalysis,
    WorkJournalAttachmentAnalysisRequest,
    WorkJournalEmailContext,
    WorkJournalEmailSummaryRequest,
    WorkJournalTurnRequest,
    WorkJournalTurnResponse,
)
from ..services.gemini import GeminiError, connection_for, model_for
from ..services.llm_work_journal import (
    analyze_work_journal_attachments,
    generate_work_journal_turn,
    summarize_work_journal_emails,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/work-journal/turn", response_model=WorkJournalTurnResponse)
async def work_journal_turn(payload: WorkJournalTurnRequest) -> WorkJournalTurnResponse:
    """会話はリクエスト内だけで処理し、確定操作までは永続化しない。"""
    try:
        decision = await run_in_threadpool(generate_work_journal_turn, payload)
    except GeminiError as exc:
        logger.exception("Work journal Gemini request failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return WorkJournalTurnResponse.model_validate(
        {
            **decision.model_dump(),
            "provider": connection_for(),
            "model": model_for(),
        }
    )


@router.post("/api/work-journal/attachment-insights", response_model=WorkJournalAttachmentAnalysis)
async def work_journal_attachment_insights(
    payload: WorkJournalAttachmentAnalysisRequest,
) -> WorkJournalAttachmentAnalysis:
    """資料本文は保存せず1回だけ解析し、以降の会話では要約だけを使い回す。"""
    insights = await run_in_threadpool(analyze_work_journal_attachments, payload.attachments)
    return WorkJournalAttachmentAnalysis(insights=insights)


@router.post("/api/work-journal/email-summary", response_model=WorkJournalEmailContext)
async def work_journal_email_summary(payload: WorkJournalEmailSummaryRequest) -> WorkJournalEmailContext:
    """Gmailの件数・候補は保存せず、日報を開始するまでの一時情報として要約する。"""
    if not google_integration_enabled("gmail"):
        raise HTTPException(status_code=403, detail="Gmail連携は管理者によって無効にされています。")
    try:
        return await run_in_threadpool(summarize_work_journal_emails, payload)
    except GeminiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
