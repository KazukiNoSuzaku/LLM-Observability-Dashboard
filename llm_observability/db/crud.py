"""Async CRUD operations and analytics queries for the llm_requests table."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Integer, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from llm_observability.db.models import LLMRequest


# ============================================================================ #
# Write operations
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
    """Set the feedback_score for an existing request.

    Returns True if the record was found and updated, False otherwise.
    """
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
# Read operations
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
    """Compute aggregate observability metrics over a rolling time window.

    Percentile latencies (p50, p95) are calculated in Python from the raw
    list of latencies to avoid SQLite-specific percentile UDFs.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    base_filter = [LLMRequest.timestamp >= since]
    if model_name:
        base_filter.append(LLMRequest.model_name == model_name)

    # ------------------------------------------------------------------ #
    # Aggregate counts / sums
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    # Percentile latencies (successful requests only)
    # ------------------------------------------------------------------ #
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
