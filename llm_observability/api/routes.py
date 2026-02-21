"""FastAPI router — all API endpoints for the LLM Observability system."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from llm_observability.api.schemas import (
    FeedbackRequest,
    GenerateRequest,
    GenerateResponse,
    LLMRequestResponse,
    MetricsSummaryResponse,
    TimeSeriesBucket,
)
from llm_observability.core.llm_wrapper import ObservedLLM
from llm_observability.db import crud
from llm_observability.db.database import get_db
from llm_observability.services.metrics_service import MetricsService

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================ #
# LLM generation
# ============================================================================ #


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Generate an LLM completion",
    description=(
        "Send a prompt to the configured LLM model. "
        "Latency, token usage, cost, and tracing are captured automatically."
    ),
)
async def generate(
    request: GenerateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GenerateResponse:
    llm = ObservedLLM(model=request.model)
    result = await llm.generate(
        prompt=request.prompt,
        system=request.system,
        feedback_score=request.feedback_score,
    )

    if result["error"] and result["response"] is None:
        raise HTTPException(status_code=502, detail=result["error"])

    return GenerateResponse(**result)


# ============================================================================ #
# Metrics — summary
# ============================================================================ #


@router.get(
    "/metrics/summary",
    response_model=MetricsSummaryResponse,
    summary="Aggregate metrics summary",
    description="Returns avg/p50/p95 latency, total cost, token usage, and error rate.",
)
async def get_metrics_summary(
    hours: int = Query(default=24, ge=1, le=720, description="Rolling window in hours"),
    model: Optional[str] = Query(default=None, description="Filter by model name"),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> MetricsSummaryResponse:
    summary = await crud.get_metrics_summary(db, hours=hours, model_name=model)
    return MetricsSummaryResponse(**summary)


# ============================================================================ #
# Metrics — paginated request log
# ============================================================================ #


@router.get(
    "/metrics/requests",
    response_model=List[LLMRequestResponse],
    summary="Paginated request log",
    description="Returns individual LLM request records, newest first.",
)
async def get_requests(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=1000),
    model: Optional[str] = Query(default=None, description="Filter by model name"),
    hours: int = Query(default=24, ge=1, le=720, description="Rolling window in hours"),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> List[LLMRequestResponse]:
    rows = await crud.get_requests(
        db, skip=skip, limit=limit, model_name=model, hours=hours
    )
    return [LLMRequestResponse.model_validate(r) for r in rows]


# ============================================================================ #
# Metrics — feedback
# ============================================================================ #


@router.post(
    "/metrics/requests/{request_id}/feedback",
    summary="Submit quality feedback",
    description="Attach a 0–1 quality score to a previously logged request.",
)
async def add_feedback(
    request_id: int,
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    updated = await crud.update_feedback(db, request_id, body.score)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")
    return {"status": "ok", "request_id": request_id, "score": body.score}


# ============================================================================ #
# Metrics — time series
# ============================================================================ #


@router.get(
    "/metrics/timeseries",
    response_model=List[TimeSeriesBucket],
    summary="Time-series metrics",
    description=(
        "Returns per-bucket aggregates suitable for rendering latency, "
        "cost, and token charts."
    ),
)
async def get_timeseries(
    hours: int = Query(default=24, ge=1, le=720, description="Rolling window in hours"),
    bucket_minutes: int = Query(
        default=5, ge=1, le=60, description="Bucket width in minutes"
    ),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> List[TimeSeriesBucket]:
    data = await MetricsService.get_timeseries(
        db, hours=hours, bucket_minutes=bucket_minutes
    )
    return [TimeSeriesBucket(**row) for row in data]


# ============================================================================ #
# Metrics — model breakdown
# ============================================================================ #


@router.get(
    "/metrics/models",
    summary="Per-model breakdown",
    description="Returns aggregated metrics grouped by model name.",
)
async def get_model_breakdown(
    hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list:
    return await MetricsService.get_model_breakdown(db, hours=hours)
