"""Async CRUD operations and analytics queries for llm_requests and prompt_templates."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Integer, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from llm_observability.db.models import LLMRequest, PromptTemplate


# ============================================================================ #
# LLMRequest — write operations
# ============================================================================ #


async def create_request(
    db: AsyncSession,
    *,
    prompt: str,
    response: Optional[str],
    model_name: str,
    latency_ms: Optional[float],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    total_tokens: Optional[int],
    estimated_cost: Optional[float],
    error: Optional[str] = None,
    is_error: bool = False,
    trace_id: Optional[str] = None,
    feedback_score: Optional[float] = None,
    timestamp: Optional[datetime] = None,
    # Prompt version control (all optional)
    prompt_template_id: Optional[int] = None,
    prompt_template_name: Optional[str] = None,
    prompt_template_version: Optional[int] = None,
    prompt_variables: Optional[str] = None,  # pre-serialised JSON string
) -> LLMRequest:
    """Insert a new LLM request record and return the persisted row."""
    row = LLMRequest(
        prompt=prompt,
        response=response,
        model_name=model_name,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost=estimated_cost,
        error=error,
        is_error=is_error,
        trace_id=trace_id,
        feedback_score=feedback_score,
        response_length=len(response) if response else 0,
        prompt_template_id=prompt_template_id,
        prompt_template_name=prompt_template_name,
        prompt_template_version=prompt_template_version,
        prompt_variables=prompt_variables,
    )
    if timestamp is not None:
        row.timestamp = timestamp

    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_feedback(
    db: AsyncSession,
    request_id: int,
    score: float,
) -> bool:
    """Set the feedback_score for an existing request."""
    result = await db.execute(
        select(LLMRequest).where(LLMRequest.id == request_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    row.feedback_score = score
    await db.commit()
    return True


# ============================================================================ #
# LLMRequest — read operations
# ============================================================================ #


async def get_requests(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    model_name: Optional[str] = None,
    hours: Optional[int] = 24,
) -> List[LLMRequest]:
    """Return a paginated, optionally filtered list of requests (newest first)."""
    query = select(LLMRequest)

    if model_name:
        query = query.where(LLMRequest.model_name == model_name)

    if hours:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = query.where(LLMRequest.timestamp >= since)

    query = query.order_by(desc(LLMRequest.timestamp)).offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_metrics_summary(
    db: AsyncSession,
    *,
    hours: int = 24,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute aggregate observability metrics over a rolling time window."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    base_filter = [LLMRequest.timestamp >= since]
    if model_name:
        base_filter.append(LLMRequest.model_name == model_name)

    agg_result = await db.execute(
        select(
            func.count(LLMRequest.id).label("total_requests"),
            func.avg(LLMRequest.latency_ms).label("avg_latency_ms"),
            func.sum(LLMRequest.estimated_cost).label("total_cost"),
            func.sum(LLMRequest.total_tokens).label("total_tokens"),
            func.avg(LLMRequest.total_tokens).label("avg_tokens"),
            func.sum(cast(LLMRequest.is_error, Integer)).label("error_count"),
        ).where(*base_filter)
    )
    agg = agg_result.one()

    lat_result = await db.execute(
        select(LLMRequest.latency_ms)
        .where(*base_filter)
        .where(LLMRequest.latency_ms.isnot(None))
        .where(LLMRequest.is_error == False)  # noqa: E712
        .order_by(LLMRequest.latency_ms)
    )
    latencies: List[float] = [row[0] for row in lat_result.all()]

    def _percentile(data: List[float], pct: float) -> float:
        if not data:
            return 0.0
        idx = max(0, int(len(data) * pct / 100) - 1)
        return data[min(idx, len(data) - 1)]

    total_requests: int = agg.total_requests or 0
    error_count: int = int(agg.error_count or 0)
    error_rate = (error_count / total_requests * 100) if total_requests > 0 else 0.0

    return {
        "total_requests": total_requests,
        "avg_latency_ms": round(float(agg.avg_latency_ms or 0), 2),
        "p50_latency_ms": round(_percentile(latencies, 50), 2),
        "p95_latency_ms": round(_percentile(latencies, 95), 2),
        "total_cost_usd": round(float(agg.total_cost or 0), 6),
        "total_tokens": int(agg.total_tokens or 0),
        "avg_tokens": round(float(agg.avg_tokens or 0), 2),
        "error_count": error_count,
        "error_rate_pct": round(error_rate, 2),
        "hours": hours,
    }


# ============================================================================ #
# PromptTemplate — write operations
# ============================================================================ #


async def create_prompt_template(
    db: AsyncSession,
    *,
    name: str,
    content: str,
    system_prompt: Optional[str] = None,
    description: Optional[str] = None,
) -> PromptTemplate:
    """Create the next version of a named prompt template.

    The version number is auto-assigned as max(existing_versions) + 1,
    so calling this twice with the same name gives v1 then v2.
    """
    result = await db.execute(
        select(func.max(PromptTemplate.version)).where(PromptTemplate.name == name)
    )
    max_version: int = result.scalar() or 0

    tpl = PromptTemplate(
        name=name,
        version=max_version + 1,
        content=content,
        system_prompt=system_prompt,
        description=description,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return tpl


async def deactivate_prompt_template(
    db: AsyncSession,
    *,
    name: str,
    version: int,
) -> bool:
    """Soft-delete a specific template version. Returns False if not found."""
    result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.name == name,
            PromptTemplate.version == version,
        )
    )
    tpl = result.scalar_one_or_none()
    if tpl is None:
        return False
    tpl.is_active = False
    await db.commit()
    return True


# ============================================================================ #
# PromptTemplate — read operations
# ============================================================================ #


async def get_prompt_template(
    db: AsyncSession,
    *,
    name: str,
    version: Optional[int] = None,
    active_only: bool = True,
) -> Optional[PromptTemplate]:
    """Fetch a template by name and optional version.

    If ``version`` is omitted, returns the highest active version.
    """
    query = select(PromptTemplate).where(PromptTemplate.name == name)
    if active_only:
        query = query.where(PromptTemplate.is_active == True)  # noqa: E712
    if version is not None:
        query = query.where(PromptTemplate.version == version)
    else:
        query = query.order_by(desc(PromptTemplate.version)).limit(1)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_prompt_templates(
    db: AsyncSession,
    *,
    name: Optional[str] = None,
    active_only: bool = True,
) -> List[PromptTemplate]:
    """List templates, optionally filtered by name."""
    query = select(PromptTemplate)
    if name:
        query = query.where(PromptTemplate.name == name)
    if active_only:
        query = query.where(PromptTemplate.is_active == True)  # noqa: E712
    query = query.order_by(PromptTemplate.name, PromptTemplate.version)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_prompt_template_names(db: AsyncSession) -> List[str]:
    """Return a sorted list of unique active template names."""
    result = await db.execute(
        select(PromptTemplate.name)
        .where(PromptTemplate.is_active == True)  # noqa: E712
        .distinct()
        .order_by(PromptTemplate.name)
    )
    return [row[0] for row in result.all()]


async def get_version_comparison(
    db: AsyncSession,
    *,
    name: str,
    hours: int = 24,
) -> List[Dict[str, Any]]:
    """Aggregate per-version metrics for a named template.

    Returns one dict per version containing request_count, avg/p95 latency,
    total/avg cost, avg feedback, and error rate.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    agg_result = await db.execute(
        select(
            LLMRequest.prompt_template_version.label("version"),
            func.count(LLMRequest.id).label("request_count"),
            func.avg(LLMRequest.latency_ms).label("avg_latency_ms"),
            func.sum(LLMRequest.estimated_cost).label("total_cost"),
            func.avg(LLMRequest.estimated_cost).label("avg_cost"),
            func.sum(LLMRequest.total_tokens).label("total_tokens"),
            func.avg(LLMRequest.feedback_score).label("avg_feedback"),
            func.sum(cast(LLMRequest.is_error, Integer)).label("error_count"),
        )
        .where(LLMRequest.prompt_template_name == name)
        .where(LLMRequest.timestamp >= since)
        .where(LLMRequest.prompt_template_version.isnot(None))
        .group_by(LLMRequest.prompt_template_version)
        .order_by(LLMRequest.prompt_template_version)
    )
    rows = agg_result.all()

    comparison: List[Dict[str, Any]] = []
    for row in rows:
        # Compute p95 latency in Python for this version
        lat_result = await db.execute(
            select(LLMRequest.latency_ms)
            .where(LLMRequest.prompt_template_name == name)
            .where(LLMRequest.prompt_template_version == row.version)
            .where(LLMRequest.timestamp >= since)
            .where(LLMRequest.latency_ms.isnot(None))
            .where(LLMRequest.is_error == False)  # noqa: E712
            .order_by(LLMRequest.latency_ms)
        )
        latencies = [r[0] for r in lat_result.all()]
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

        total = int(row.request_count or 0)
        errors = int(row.error_count or 0)

        comparison.append(
            {
                "version": row.version,
                "request_count": total,
                "avg_latency_ms": round(float(row.avg_latency_ms or 0), 2),
                "p95_latency_ms": round(p95, 2),
                "total_cost": round(float(row.total_cost or 0), 6),
                "avg_cost": round(float(row.avg_cost or 0), 8),
                "total_tokens": int(row.total_tokens or 0),
                "avg_feedback": (
                    round(float(row.avg_feedback), 3) if row.avg_feedback is not None else None
                ),
                "error_count": errors,
                "error_rate_pct": round((errors / total * 100) if total else 0.0, 2),
            }
        )

    return comparison
