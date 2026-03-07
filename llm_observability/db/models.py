"""SQLAlchemy ORM models for the LLM Observability system."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class PromptTemplate(Base):
    """Versioned prompt template registry.

    Each row is one immutable version of a named template.
    Versions are auto-incremented integers (1, 2, 3 …) scoped to ``name``.

    Example::

        name="summarizer"  version=1  content="Summarize: {text}"
        name="summarizer"  version=2  content="Give a concise summary of: {text}. Max 3 sentences."
    """

    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_template_name_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    name = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Logical template name, e.g. 'summarizer' or 'code-reviewer'",
    )
    version = Column(
        Integer,
        nullable=False,
        comment="Auto-incremented version number, scoped to name",
    )

    # ------------------------------------------------------------------ #
    # Content
    # ------------------------------------------------------------------ #
    content = Column(
        Text,
        nullable=False,
        comment="Template body. Use {variable} placeholders for substitution.",
    )
    system_prompt = Column(
        Text,
        nullable=True,
        comment="Optional system-level instruction shipped with this template",
    )
    description = Column(
        String(500),
        nullable=True,
        comment="Human-readable changelog / notes for this version",
    )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="Soft-delete flag — deactivated versions are hidden by default",
    )

    # Relationship back to requests (lazy loaded)
    requests = relationship("LLMRequest", back_populates="prompt_template", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<PromptTemplate name={self.name!r} v{self.version} active={self.is_active}>"


class LLMRequest(Base):
    """One row per LLM API call, capturing all observability signals."""

    __tablename__ = "llm_requests"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # ------------------------------------------------------------------ #
    # Timing
    # ------------------------------------------------------------------ #
    timestamp = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="UTC time when the request was initiated",
    )

    # ------------------------------------------------------------------ #
    # Payload (truncation happens at API layer, not here)
    # ------------------------------------------------------------------ #
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=True)

    # ------------------------------------------------------------------ #
    # Model identity
    # ------------------------------------------------------------------ #
    model_name = Column(
        String(100),
        nullable=False,
        index=True,
        comment="e.g. claude-haiku-4-5-20251001",
    )

    # ------------------------------------------------------------------ #
    # Latency
    # ------------------------------------------------------------------ #
    latency_ms = Column(
        Float,
        nullable=True,
        comment="End-to-end request duration in milliseconds",
    )

    # ------------------------------------------------------------------ #
    # Token usage
    # ------------------------------------------------------------------ #
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)

    # ------------------------------------------------------------------ #
    # Cost
    # ------------------------------------------------------------------ #
    estimated_cost = Column(
        Float,
        nullable=True,
        comment="Estimated cost in USD based on model pricing",
    )

    # ------------------------------------------------------------------ #
    # Error tracking
    # ------------------------------------------------------------------ #
    error = Column(Text, nullable=True, comment="Exception or API error message")
    is_error = Column(Boolean, nullable=False, default=False, index=True)

    # ------------------------------------------------------------------ #
    # Quality signals
    # ------------------------------------------------------------------ #
    feedback_score = Column(
        Float,
        nullable=True,
        comment="Human or automated quality score (0.0–1.0)",
    )
    response_length = Column(
        Integer,
        nullable=True,
        comment="Character count of the response",
    )

    # ------------------------------------------------------------------ #
    # Provider
    # ------------------------------------------------------------------ #
    provider = Column(
        String(50),
        nullable=True,
        index=True,
        comment="LLM provider: 'anthropic', 'openai', 'google', etc.",
    )

    # ------------------------------------------------------------------ #
    # Tracing
    # ------------------------------------------------------------------ #
    trace_id = Column(
        String(100),
        nullable=True,
        index=True,
        comment="UUID linking this DB row to an OTel/Phoenix trace",
    )

    # ------------------------------------------------------------------ #
    # Prompt version control
    # ------------------------------------------------------------------ #
    prompt_template_id = Column(
        Integer,
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK to the PromptTemplate used to generate this request",
    )
    # Denormalised copies for fast filtering without joins
    prompt_template_name = Column(
        String(100),
        nullable=True,
        index=True,
        comment="Denormalised template name for zero-join queries",
    )
    prompt_template_version = Column(
        Integer,
        nullable=True,
        index=True,
        comment="Denormalised template version for zero-join queries",
    )
    prompt_variables = Column(
        Text,
        nullable=True,
        comment="JSON-encoded dict of variables substituted into the template",
    )

    # Relationship to template
    prompt_template = relationship("PromptTemplate", back_populates="requests")

    def __repr__(self) -> str:
        return (
            f"<LLMRequest id={self.id} model={self.model_name} "
            f"latency={self.latency_ms:.0f}ms cost=${self.estimated_cost:.6f}>"
        )


class GuardrailLog(Base):
    """One row per guardrail violation event.

    Linked to a parent LLMRequest but persisted independently so that
    violation analytics can be queried without joining the full request table.
    """

    __tablename__ = "guardrail_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Link to the parent request (nullable — blocked requests may have no row)
    request_id = Column(
        Integer,
        ForeignKey("llm_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    timestamp = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # "input" or "output"
    stage = Column(String(20), nullable=False)

    # "pii" | "jailbreak" | "output_invalid" | "none"
    violation_type = Column(String(50), nullable=False, index=True)

    # "none" | "low" | "medium" | "high" | "critical"
    severity = Column(String(20), nullable=False)

    # "pass" | "block" | "redact" | "log"
    action_taken = Column(String(20), nullable=False)

    # Guardrail check overhead in milliseconds
    latency_ms = Column(Float, nullable=True)

    # Truncated prompt/response snippet (first 200 chars)
    snippet = Column(Text, nullable=True)

    # JSON blob — pii_types, jailbreak_patterns, etc.
    metadata_json = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<GuardrailLog id={self.id} stage={self.stage!r} "
            f"type={self.violation_type!r} action={self.action_taken!r}>"
        )
