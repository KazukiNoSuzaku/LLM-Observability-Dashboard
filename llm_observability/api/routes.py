"""FastAPI router — all API endpoints for the LLM Observability system."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from llm_observability.api.schemas import (
    ABTestRequest,
    ABTestResponse,
    ABTestResult,
    FeedbackRequest,
    GenerateRequest,
    GenerateResponse,
    LLMRequestResponse,
    MetricsSummaryResponse,
    PromptTemplateCreate,
    PromptTemplateResponse,
    TimeSeriesBucket,
    VersionComparisonRow,
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
        "Send a prompt (raw or from a versioned template) to the LLM. "
        "Latency, token usage, cost, tracing, and prompt version are captured automatically."
    ),
)
async def generate(
    request: GenerateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> GenerateResponse:
    llm = ObservedLLM(model=request.model)
    result = await llm.generate(
        prompt=request.prompt,
        template_name=request.template_name,
        template_version=request.template_version,
        variables=request.variables,
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
)
async def get_metrics_summary(
    hours: int = Query(default=24, ge=1, le=720),
    model: Optional[str] = Query(default=None),
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
)
async def get_requests(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=1000),
    model: Optional[str] = Query(default=None),
    hours: int = Query(default=24, ge=1, le=720),
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
)
async def get_timeseries(
    hours: int = Query(default=24, ge=1, le=720),
    bucket_minutes: int = Query(default=5, ge=1, le=60),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> List[TimeSeriesBucket]:
    data = await MetricsService.get_timeseries(
        db, hours=hours, bucket_minutes=bucket_minutes
    )
    return [TimeSeriesBucket(**row) for row in data]


# ============================================================================ #
# Metrics — model breakdown
# ============================================================================ #


@router.get("/metrics/models", summary="Per-model breakdown")
async def get_model_breakdown(
    hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list:
    return await MetricsService.get_model_breakdown(db, hours=hours)


# ============================================================================ #
# Prompt version control
# ============================================================================ #


@router.post(
    "/prompts",
    response_model=PromptTemplateResponse,
    status_code=201,
    summary="Create a new prompt template version",
    description=(
        "Each call creates the next version for the given ``name``. "
        "First call → v1, second call with same name → v2, etc."
    ),
)
async def create_prompt_template(
    body: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> PromptTemplateResponse:
    tpl = await crud.create_prompt_template(
        db,
        name=body.name,
        content=body.content,
        system_prompt=body.system_prompt,
        description=body.description,
    )
    return PromptTemplateResponse.model_validate(tpl)


@router.get(
    "/prompts",
    response_model=List[PromptTemplateResponse],
    summary="List all prompt templates",
    description="Returns all active template versions, grouped by name.",
)
async def list_prompt_templates(
    name: Optional[str] = Query(default=None, description="Filter by template name"),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> List[PromptTemplateResponse]:
    templates = await crud.get_prompt_templates(db, name=name)
    return [PromptTemplateResponse.model_validate(t) for t in templates]


@router.get(
    "/prompts/{name}",
    response_model=List[PromptTemplateResponse],
    summary="Get all versions of a named template",
)
async def get_prompt_template_versions(
    name: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> List[PromptTemplateResponse]:
    templates = await crud.get_prompt_templates(db, name=name, active_only=False)
    if not templates:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
    return [PromptTemplateResponse.model_validate(t) for t in templates]


@router.get(
    "/prompts/{name}/compare",
    response_model=List[VersionComparisonRow],
    summary="Compare metrics across template versions",
    description=(
        "Returns per-version aggregates (latency, cost, feedback, error rate) "
        "so you can measure the impact of prompt changes."
    ),
)
async def compare_prompt_versions(
    name: str,
    hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> List[VersionComparisonRow]:
    data = await crud.get_version_comparison(db, name=name, hours=hours)
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No request data found for template '{name}' in the last {hours}h",
        )
    return [VersionComparisonRow(**row) for row in data]


@router.post(
    "/prompts/{name}/ab-generate",
    response_model=ABTestResponse,
    summary="Run an A/B test across two prompt versions",
    description=(
        "Sends the same prompt to two different versions of a template simultaneously "
        "and returns both results for direct comparison. Both calls are fully observed "
        "(latency, cost, tokens, and judge score if enabled)."
    ),
)
async def ab_generate(
    name: str,
    body: ABTestRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ABTestResponse:
    import asyncio

    async def _run(version: int) -> ABTestResult:
        llm = ObservedLLM()
        try:
            result = await llm.generate(
                template_name=name,
                template_version=version,
                variables=body.variables,
                system=body.system,
            )
            return ABTestResult(
                version=version,
                response=result["response"],
                latency_ms=result["latency_ms"],
                prompt_tokens=result["prompt_tokens"],
                completion_tokens=result["completion_tokens"],
                estimated_cost=result["estimated_cost"],
                feedback_score=None,
                error=result["error"],
                trace_id=result["trace_id"],
            )
        except Exception as exc:
            return ABTestResult(
                version=version,
                response=None,
                latency_ms=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost=0.0,
                feedback_score=None,
                error=str(exc),
                trace_id="",
            )

    result_a, result_b = await asyncio.gather(_run(body.version_a), _run(body.version_b))
    return ABTestResponse(template_name=name, result_a=result_a, result_b=result_b)


@router.delete(
    "/prompts/{name}/{version}",
    summary="Deactivate a template version",
    description="Soft-deletes a version — it remains in the DB but is excluded from active lookups.",
)
async def deactivate_prompt_template(
    name: str,
    version: int,
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict:
    ok = await crud.deactivate_prompt_template(db, name=name, version=version)
    if not ok:
        raise HTTPException(
            status_code=404, detail=f"Template '{name}' v{version} not found"
        )
    return {"status": "deactivated", "name": name, "version": version}
