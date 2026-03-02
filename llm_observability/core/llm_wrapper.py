"""ObservedLLM — instrumented wrapper around the Anthropic Messages API.

Every call to ``generate()`` automatically:
  1. Resolves a versioned prompt template (if provided) and renders variables.
  2. Records wall-clock latency.
  3. Extracts token usage from the API response.
  4. Calculates estimated cost using model pricing tables.
  5. Emits an OpenTelemetry span (forwarded to Arize Phoenix if configured).
  6. Persists the full trace record (including template provenance) to the DB.
  7. Logs WARNING-level alerts when latency or cost thresholds are breached.
"""

import json
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
    """Async LLM client with built-in observability and prompt version control.

    Raw prompt example::

        llm = ObservedLLM()
        result = await llm.generate("Explain async/await in Python.")

    Template example::

        result = await llm.generate(
            template_name="code-reviewer",
            variables={"language": "Python", "code": "def foo(): pass"},
        )
        # result["prompt_template_name"]    → "code-reviewer"
        # result["prompt_template_version"] → 2
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
        prompt: Optional[str] = None,
        *,
        # Prompt version control
        template_name: Optional[str] = None,
        template_version: Optional[int] = None,
        variables: Optional[Dict[str, str]] = None,
        # Common options
        system: Optional[str] = None,
        feedback_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generate a completion with full observability instrumentation.

        Args:
            prompt:           Raw user message.  Mutually exclusive with template_name.
            template_name:    Name of a registered PromptTemplate to use.
            template_version: Pin to a specific version; omit to use the latest.
            variables:        Dict of ``{placeholder: value}`` for template rendering.
            system:           Override the template's system prompt.
            feedback_score:   Pre-assigned quality label (0.0 – 1.0).

        Returns:
            Dict with: response, model, latency_ms, prompt_tokens, completion_tokens,
            total_tokens, estimated_cost, trace_id, error,
            prompt_template_name, prompt_template_version.
        """
        if not prompt and not template_name:
            raise ValueError("Provide either 'prompt' or 'template_name'")

        # ---- resolve template ----------------------------------------- #
        template_id: Optional[int] = None
        tpl_name: Optional[str] = None
        tpl_version: Optional[int] = None

        if template_name:
            async with AsyncSessionLocal() as db:
                tpl = await crud.get_prompt_template(
                    db, name=template_name, version=template_version
                )
            if tpl is None:
                ver_str = f" v{template_version}" if template_version else " (latest)"
                raise ValueError(
                    f"Prompt template '{template_name}'{ver_str} not found or inactive"
                )
            template_id = tpl.id
            tpl_name = tpl.name
            tpl_version = tpl.version
            prompt = self._render_template(tpl.content, variables or {})
            if system is None and tpl.system_prompt:
                system = tpl.system_prompt

        # ---- instrumented generation ---------------------------------- #
        trace_id = str(uuid.uuid4())
        start_time = time.monotonic()

        response_text: Optional[str] = None
        error_text: Optional[str] = None
        prompt_tokens = 0
        completion_tokens = 0

        span_attrs: Dict[str, Any] = {
            "llm.model": self.model,
            "llm.prompt_length": len(prompt),
            "llm.max_tokens": self.max_tokens,
            "llm.trace_id": trace_id,
        }
        if tpl_name:
            span_attrs["llm.prompt_template"] = f"{tpl_name}:v{tpl_version}"

        with self._tracer.start_as_current_span("llm.generate", attributes=span_attrs) as span:
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
                        prompt_template_id=template_id,
                        prompt_template_name=tpl_name,
                        prompt_template_version=tpl_version,
                        prompt_variables=(
                            json.dumps(variables) if variables else None
                        ),
                    )

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
            "prompt_template_name": tpl_name,
            "prompt_template_version": tpl_version,
        }

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _render_template(content: str, variables: Dict[str, str]) -> str:
        """Substitute {placeholders} in a template with provided values.

        Raises:
            ValueError: If a required placeholder is missing from variables.
        """
        try:
            return content.format_map(variables)
        except KeyError as exc:
            raise ValueError(
                f"Template variable {exc} was not supplied in 'variables'"
            ) from exc

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
