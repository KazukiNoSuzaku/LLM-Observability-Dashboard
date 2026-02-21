"""SQLAlchemy ORM models for the LLM Observability system."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


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
    # Tracing
    # ------------------------------------------------------------------ #
    trace_id = Column(
        String(100),
        nullable=True,
        index=True,
        comment="UUID linking this DB row to an OTel/Phoenix trace",
    )

    def __repr__(self) -> str:
        return (
            f"<LLMRequest id={self.id} model={self.model_name} "
            f"latency={self.latency_ms:.0f}ms cost=${self.estimated_cost:.6f}>"
        )
