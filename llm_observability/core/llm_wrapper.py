"""ObservedLLM — instrumented wrapper around the Anthropic Messages API.

Every call to ``generate()`` automatically:
  1. Records wall-clock latency.
  2. Extracts token usage from the API response.
  3. Calculates estimated cost using model pricing tables.
  4. Emits an OpenTelemetry span (forwarded to Arize Phoenix if configured).
  5. Persists the full trace record to the database.
  6. Logs WARNING-level alerts when latency or cost thresholds are breached.
"""

import logging
import time
import uuid
from typing import Any, Dict, Optional

import anthropic

from llm_observability.core.config import settings
from llm_observability.core.pricing import calculate_cost
from llm_observability.db import crud
from llm_observability.db.database import AsyncSessionLocal
from llm_observability.services.tracing_service import TracingService

logger = logging.getLogger(__name__)


class ObservedLLM:
    """Async LLM client with built-in observability.

    Example::

        llm = ObservedLLM(model="claude-haiku-4-5-20251001")
        result = await llm.generate("Explain async/await in Python.")
        print(result["response"])
        print(f"Cost: ${result['estimated_cost']:.6f}  Latency: {result['latency_ms']:.0f}ms")
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        self.model = model or settings.default_model
        self.max_tokens = max_tokens or settings.max_tokens
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._tracer = TracingService.get_tracer()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        feedback_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Send a prompt to the LLM and return an enriched result dict.

        Args:
            prompt:         User message.
            system:         Optional system-level instruction.
            feedback_score: Pre-assigned quality label (0.0 – 1.0).

        Returns:
            A dict with keys: response, model, latency_ms, prompt_tokens,
            completion_tokens, total_tokens, estimated_cost, trace_id, error.

        Raises:
            anthropic.APIError: Re-raised after the trace record is stored.
        """
        trace_id = str(uuid.uuid4())
        start_time = time.monotonic()

        response_text: Optional[str] = None
        error_text: Optional[str] = None
        prompt_tokens = 0
        completion_tokens = 0

        with self._tracer.start_as_current_span(
            "llm.generate",
            attributes={
                "llm.model": self.model,
                "llm.prompt_length": len(prompt),
                "llm.max_tokens": self.max_tokens,
                "llm.trace_id": trace_id,
            },
        ) as span:
            try:
                messages = [{"role": "user", "content": prompt}]
                call_kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "messages": messages,
                }
                if system:
                    call_kwargs["system"] = system

                message = await self._client.messages.create(**call_kwargs)

                response_text = message.content[0].text
                prompt_tokens = message.usage.input_tokens
                completion_tokens = message.usage.output_tokens

                span.set_attribute("llm.prompt_tokens", prompt_tokens)
                span.set_attribute("llm.completion_tokens", completion_tokens)
                span.set_attribute("llm.response_length", len(response_text))

            except Exception as exc:
                error_text = str(exc)
                span.set_attribute("error", True)
                span.set_attribute("error.message", error_text)
                logger.error("LLM request failed [trace=%s]: %s", trace_id, exc)

            finally:
                latency_ms = (time.monotonic() - start_time) * 1000
                total_tokens = prompt_tokens + completion_tokens
                estimated_cost = calculate_cost(
                    self.model, prompt_tokens, completion_tokens
                )

                span.set_attribute("llm.latency_ms", latency_ms)
                span.set_attribute("llm.total_tokens", total_tokens)
                span.set_attribute("llm.estimated_cost_usd", estimated_cost)

                # Persist to database
                async with AsyncSessionLocal() as db:
                    await crud.create_request(
                        db=db,
                        prompt=prompt,
                        response=response_text,
                        model_name=self.model,
                        latency_ms=latency_ms if error_text is None else None,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        estimated_cost=estimated_cost,
                        error=error_text,
                        is_error=error_text is not None,
                        trace_id=trace_id,
                        feedback_score=feedback_score,
                    )

                # Alert checks
                self._check_alerts(latency_ms=latency_ms, cost=estimated_cost)

        return {
            "response": response_text,
            "model": self.model,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": estimated_cost,
            "trace_id": trace_id,
            "error": error_text,
        }

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _check_alerts(self, *, latency_ms: float, cost: float) -> None:
        """Log WARNING when observability thresholds are breached."""
        if latency_ms > settings.latency_alert_threshold_ms:
            logger.warning(
                "HIGH LATENCY ALERT — %.0fms exceeds threshold %.0fms [model=%s]",
                latency_ms,
                settings.latency_alert_threshold_ms,
                self.model,
            )
        if cost > settings.cost_alert_threshold_usd:
            logger.warning(
                "HIGH COST ALERT — $%.6f exceeds threshold $%.2f [model=%s]",
                cost,
                settings.cost_alert_threshold_usd,
                self.model,
            )
