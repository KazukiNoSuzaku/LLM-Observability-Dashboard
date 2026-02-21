"""Pydantic request/response schemas for the FastAPI layer."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================ #
# Request schemas
# ============================================================================ #


class GenerateRequest(BaseModel):
    """Payload for POST /api/v1/generate."""

    prompt: str = Field(..., min_length=1, description="User message sent to the LLM")
    system: Optional[str] = Field(None, description="Optional system-level instruction")
    model: Optional[str] = Field(
        None,
        description="Override the default model (e.g. claude-sonnet-4-6)",
    )
    feedback_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Pre-assigned quality label (0 = worst, 1 = best)",
    )


class FeedbackRequest(BaseModel):
    """Payload for POST /api/v1/metrics/requests/{id}/feedback."""

    score: float = Field(..., ge=0.0, le=1.0, description="Quality score (0–1)")


# ============================================================================ #
# Response schemas
# ============================================================================ #


class GenerateResponse(BaseModel):
    """Response from POST /api/v1/generate."""

    response: Optional[str] = Field(None, description="LLM completion text")
    model: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float = Field(..., description="Estimated cost in USD")
    trace_id: str
    error: Optional[str] = None


class MetricsSummaryResponse(BaseModel):
    """Response from GET /api/v1/metrics/summary."""

    total_requests: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    total_cost_usd: float
    total_tokens: int
    avg_tokens: float
    error_count: int
    error_rate_pct: float
    hours: int = Field(..., description="Size of the observation window in hours")


class LLMRequestResponse(BaseModel):
    """One row from GET /api/v1/metrics/requests."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    model_name: str
    latency_ms: Optional[float]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    estimated_cost: Optional[float]
    is_error: bool
    feedback_score: Optional[float]
    response_length: Optional[int]
    trace_id: Optional[str]
    prompt: str
    response: Optional[str]


class TimeSeriesBucket(BaseModel):
    """One time bucket from GET /api/v1/metrics/timeseries."""

    timestamp: str
    request_count: int
    avg_latency_ms: float
    total_cost: float
    total_tokens: int
    error_count: int
