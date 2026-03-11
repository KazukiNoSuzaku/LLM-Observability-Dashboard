"""Pydantic request/response schemas for the FastAPI layer."""

from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ============================================================================ #
# Prompt template schemas
# ============================================================================ #


class PromptTemplateCreate(BaseModel):
    """Payload for POST /api/v1/prompts — creates the next version."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9\-_]+$",
        description="Template name (lowercase, hyphens/underscores allowed). "
        "Repeated calls with the same name auto-increment the version.",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Template body. Use {variable} placeholders, e.g. 'Summarize: {text}'",
    )
    system_prompt: Optional[str] = Field(
        None, description="Optional system instruction bundled with this template"
    )
    description: Optional[str] = Field(
        None,
        max_length=500,
        description="Human-readable changelog entry / notes for this version",
    )


class PromptTemplateResponse(BaseModel):
    """One template version returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: int
    content: str
    system_prompt: Optional[str]
    description: Optional[str]
    created_at: datetime
    is_active: bool


class VersionComparisonRow(BaseModel):
    """Per-version aggregate from GET /api/v1/prompts/{name}/compare."""

    version: int
    request_count: int
    avg_latency_ms: float
    p95_latency_ms: float
    total_cost: float
    avg_cost: float
    total_tokens: int
    avg_feedback: Optional[float]
    error_count: int
    error_rate_pct: float


# ============================================================================ #
# LLM generation schemas
# ============================================================================ #


class GenerateRequest(BaseModel):
    """Payload for POST /api/v1/generate.

    Supply either ``prompt`` (raw text) **or** ``template_name`` + optional
    ``variables`` dict.  Both cannot be absent simultaneously.
    """

    # Raw prompt path
    prompt: Optional[str] = Field(
        None, min_length=1, description="Raw user message sent directly to the LLM"
    )

    # Template path
    template_name: Optional[str] = Field(
        None,
        description="Name of a registered PromptTemplate (uses the latest active version)",
    )
    template_version: Optional[int] = Field(
        None, ge=1, description="Pin to a specific version; omit to use latest"
    )
    variables: Optional[Dict[str, str]] = Field(
        None,
        description="Values to substitute into template {placeholders}",
    )

    # Shared options
    system: Optional[str] = Field(None, description="Override the template's system prompt")
    model: Optional[str] = Field(None, description="Override the default model")
    feedback_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Pre-assigned quality label (0–1)"
    )

    @model_validator(mode="after")
    def _require_prompt_or_template(self) -> "GenerateRequest":
        if not self.prompt and not self.template_name:
            raise ValueError("Provide either 'prompt' or 'template_name'")
        return self


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
    provider: Optional[str] = None
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float = Field(..., description="Estimated cost in USD")
    trace_id: str
    error: Optional[str] = None
    # Template provenance (null when raw prompt was used)
    prompt_template_name: Optional[str] = None
    prompt_template_version: Optional[int] = None


# ============================================================================ #
# A/B test schemas
# ============================================================================ #


class ABTestRequest(BaseModel):
    """Payload for POST /api/v1/prompts/{name}/ab-generate."""

    version_a: int = Field(..., ge=1, description="First template version")
    version_b: int = Field(..., ge=1, description="Second template version")
    variables: Optional[Dict[str, str]] = Field(
        None, description="Variables to substitute into template placeholders"
    )
    prompt: Optional[str] = Field(
        None,
        min_length=1,
        description=(
            "Optional raw prompt. If the template contains a {prompt} placeholder "
            "this value is automatically injected into variables."
        ),
    )
    system: Optional[str] = Field(None, description="Optional system prompt override")


class ABTestResult(BaseModel):
    """Result from a single version in an A/B test."""

    version: int
    response: Optional[str]
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float
    feedback_score: Optional[float]
    error: Optional[str]
    trace_id: str


class ABTestResponse(BaseModel):
    """Response from POST /api/v1/prompts/{name}/ab-generate."""

    template_name: str
    result_a: ABTestResult
    result_b: ABTestResult


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
    # Template provenance
    prompt_template_name: Optional[str] = None
    prompt_template_version: Optional[int] = None


class TimeSeriesBucket(BaseModel):
    """One time bucket from GET /api/v1/metrics/timeseries."""

    timestamp: str
    request_count: int
    avg_latency_ms: float
    total_cost: float
    total_tokens: int
    error_count: int


# ============================================================================ #
# Guardrails schemas
# ============================================================================ #


class GuardrailLogResponse(BaseModel):
    """One guardrail violation event from GET /api/v1/guardrails/logs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: Optional[int]
    timestamp: datetime
    stage: str
    violation_type: str
    severity: str
    action_taken: str
    latency_ms: Optional[float]
    snippet: Optional[str]
    metadata_json: Optional[str]


class GuardrailStatsResponse(BaseModel):
    """Aggregate guardrail stats from GET /api/v1/guardrails/stats."""

    hours: int
    total_violations: int
    avg_guardrail_latency_ms: float
    total_blocked: int
    total_redacted: int
    by_type: Dict[str, int]
    by_stage: Dict[str, int]
