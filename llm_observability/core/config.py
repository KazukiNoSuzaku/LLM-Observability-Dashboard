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
    # LLM providers
    # ------------------------------------------------------------------ #
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    mistral_api_key: str = Field(default="", description="Mistral AI API key")

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
    # Supabase (optional — only needed when DATABASE_URL points at Supabase)
    # ------------------------------------------------------------------ #
    supabase_url: str = Field(
        default="",
        description=(
            "Supabase project URL (e.g. https://<ref>.supabase.co). "
            "Not required when connecting via DATABASE_URL directly."
        ),
    )
    supabase_anon_key: str = Field(
        default="",
        description="Supabase anon/public key (for the supabase-py client, optional).",
    )

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

    # ------------------------------------------------------------------ #
    # Webhook alerting
    # ------------------------------------------------------------------ #
    slack_webhook_url: str = Field(
        default="",
        description="Slack Incoming Webhook URL (leave empty to disable)",
    )
    discord_webhook_url: str = Field(
        default="",
        description="Discord Webhook URL (leave empty to disable)",
    )
    alert_cooldown_seconds: int = Field(
        default=300,
        description="Minimum seconds between repeated alerts of the same type",
    )

    # ------------------------------------------------------------------ #
    # Per-model alert threshold overrides
    # ------------------------------------------------------------------ #
    model_alert_thresholds_json: str = Field(
        default="{}",
        description=(
            'JSON dict overriding global thresholds per model. '
            'Example: \'{"gpt-4o": {"latency_ms": 3000, "cost_usd": 0.05}}\''
        ),
    )

    @property
    def model_alert_thresholds(self) -> dict:
        """Parsed per-model threshold overrides."""
        import json
        try:
            return json.loads(self.model_alert_thresholds_json)
        except Exception:
            return {}

    # ------------------------------------------------------------------ #
    # LLM-as-judge quality scoring
    # ------------------------------------------------------------------ #
    judge_enabled: bool = Field(
        default=False,
        description="Auto-score responses with a judge LLM after each generation",
    )
    judge_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Model used for automated quality scoring (cheap fast model recommended)",
    )

    # ------------------------------------------------------------------ #
    # Guardrails
    # ------------------------------------------------------------------ #
    guardrails_enabled: bool = Field(
        default=True,
        description="Master on/off switch for input/output guardrails",
    )
    guardrails_block_on_pii: bool = Field(
        default=False,
        description="Block (reject) requests that contain PII — if False, PII is redacted",
    )
    guardrails_block_on_jailbreak: bool = Field(
        default=True,
        description="Block requests that match jailbreak/prompt-injection patterns",
    )
    guardrails_redact_output_pii: bool = Field(
        default=True,
        description="Replace PII tokens in LLM responses with [REDACTED:TYPE] placeholders",
    )
    guardrails_use_presidio: bool = Field(
        default=True,
        description=(
            "Use Microsoft Presidio for PII detection when installed; "
            "falls back to compiled regex if presidio-analyzer is not available"
        ),
    )


# Module-level singleton — import from here everywhere
settings = Settings()
