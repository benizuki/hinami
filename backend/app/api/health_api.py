from __future__ import annotations

from fastapi import APIRouter

from ..runtime import is_production
from ..schemas import HealthResponse
from ..services.gemini import connection_for, gemini_configured, model_for

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse, response_model_exclude_none=True)
def health() -> HealthResponse:
    if is_production():
        return HealthResponse(llm_configured=bool(gemini_configured()))
    return HealthResponse(
        llm_configured=bool(gemini_configured()),
        provider=connection_for(),
        model=model_for(),
    )
