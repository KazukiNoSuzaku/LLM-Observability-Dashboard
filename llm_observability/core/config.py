"""Application configuration loaded from environment variables / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """All configuration is driven by environment variables.

    Precedence (highest → lowest):
      1. Real environment variables
      2. Values in .env file
      3. Defaults defined here
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # LLM provider
    # ------------------------------------------------------------------ #
    anthropic_api_key: str = Field(default="", description="Anthropic API key")

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    database_url: str = Field(
        default="sqlite+aiosqlite:///./llm_observability.db",
        description="SQLAlchemy async database URL",
    )

    # ------------------------------------------------------------------ #
    # Arize Phoenix tracing
    # ------------------------------------------------------------------ #
    phoenix_endpoint: str = Field(
        default="http://localhost:6006/v1/traces",
        description="OTLP HTTP endpoint for Phoenix (or any OTel collector)",
    )
    phoenix_enabled: bool = Field(
        default=True,
        description="Enable Phoenix/OTLP tracing export",
    )

    # ------------------------------------------------------------------ #
    # LLM defaults
    # ------------------------------------------------------------------ #
    default_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Default Anthropic model ID",
    )
    max_tokens: int = Field(default=1024, description="Max completion tokens")

    # ------------------------------------------------------------------ #
    # FastAPI server
    # ------------------------------------------------------------------ #
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # ------------------------------------------------------------------ #
    # Alerting thresholds
    # ------------------------------------------------------------------ #
    latency_alert_threshold_ms: float = Field(
        default=5000.0,
        description="Log WARNING when a single request exceeds this latency (ms)",
    )
    cost_alert_threshold_usd: float = Field(
        default=0.10,
        description="Log WARNING when cumulative cost in any window exceeds this (USD)",
    )


# Module-level singleton — import from here everywhere
settings = Settings()
