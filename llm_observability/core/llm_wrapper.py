"""ObservedLLM — instrumented wrapper around multiple LLM providers.

Every call to ``generate()`` automatically:
  1.  Detects the provider from the model name and routes to the correct SDK.
  2.  Resolves a versioned prompt template (if provided) and renders variables.
  3.  Runs INPUT guardrails (PII detection / jailbreak scan via GuardrailsService).
  4.  Records wall-clock latency.
  5.  Extracts token usage from the API response.
  6.  Calculates estimated cost using model pricing tables.
  7.  Emits an OpenTelemetry span (forwarded to Arize Phoenix if configured).
  8.  Auto-scores the response with JudgeService (if JUDGE_ENABLED=true).
  9.  Runs OUTPUT guardrails (PII redaction / structured output validation).
  10. Persists the full trace record + guardrail violation events to the DB.
  11. Fires async webhook alerts (Slack/Discord) when thresholds are breached.

Supported providers
-------------------
  anthropic — any ``claude-*`` model
  openai    — any ``gpt-*``, ``o1-*``, ``o3-*`` model
  google    — any ``gemini-*`` model (requires ``google-genai`` package)
  mistral   — any ``mistral-*``, ``mixtral-*``, ``codestral-*``, ``pixtral-*`` model
              (requires ``mistralai`` package)
"""

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import anthropic

from llm_observability.core.config import settings
from llm_observability.core.pricing import calculate_cost
from llm_observability.db import crud
from llm_observability.db.database import AsyncSessionLocal
from llm_observability.services.tracing_service import TracingService

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Provider detection
# --------------------------------------------------------------------------- #

def _detect_provider(model_name: str) -> str:
    """Infer the provider from the model name prefix."""
    m = model_name.lower()
    if m.startswith(("gpt-", "o1-", "o1", "o3-", "o3", "o4-")):
        return "openai"
    if m.startswith("gemini-"):
        return "google"
    if m.startswith(("mistral-", "mixtral-", "codestral-", "pixtral-")):
        return "mistral"
    return "anthropic"


# --------------------------------------------------------------------------- #
# ObservedLLM
# --------------------------------------------------------------------------- #

class ObservedLLM:
    """Async multi-provider LLM client with built-in observability.

    Raw prompt example::

        llm = ObservedLLM()
        result = await llm.generate("Explain async/await in Python.")

    OpenAI model example::

        llm = ObservedLLM(model="gpt-4o-mini")
        result = await llm.generate("Summarise the Turing test.")

    Template example::

        result = await llm.generate(
            template_name="code-reviewer",
            variables={"language": "Python", "code": "def foo(): pass"},
        )
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        self.model = model or settings.default_model
        self.max_tokens = max_tokens or settings.max_tokens
        self.provider = _detect_provider(self.model)
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
            Dict with: response, model, provider, latency_ms, prompt_tokens,
            completion_tokens, total_tokens, estimated_cost, trace_id, error,
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

        # ---- INPUT guardrails ----------------------------------------- #
        from llm_observability.services.guardrails_service import GuardrailsService

        input_guard = await GuardrailsService.scan_input(prompt)
        if input_guard.blocked:
            # Persist the violation before raising so it appears in the logs
            async with AsyncSessionLocal() as db:
                for vrow in input_guard.to_log_rows("input"):
                    await crud.create_guardrail_log(db, **vrow)
            raise ValueError(input_guard.block_reason)

        # Use redacted prompt for the LLM call when PII was found
        effective_prompt = input_guard.pii_redacted_text or prompt

        # ---- instrumented generation ---------------------------------- #
        trace_id = str(uuid.uuid4())
        start_time = time.monotonic()

        response_text: Optional[str] = None
        error_text: Optional[str] = None
        prompt_tokens = 0
        completion_tokens = 0
        output_guard = None

        span_attrs: Dict[str, Any] = {
            "llm.model": self.model,
            "llm.provider": self.provider,
            "llm.prompt_length": len(prompt),
            "llm.max_tokens": self.max_tokens,
            "llm.trace_id": trace_id,
        }
        if tpl_name:
            span_attrs["llm.prompt_template"] = f"{tpl_name}:v{tpl_version}"

        with self._tracer.start_as_current_span("llm.generate", attributes=span_attrs) as span:
            try:
                response_text, prompt_tokens, completion_tokens = await self._call_provider(
                    prompt=effective_prompt, system=system
                )

                span.set_attribute("llm.prompt_tokens", prompt_tokens)
                span.set_attribute("llm.completion_tokens", completion_tokens)
                span.set_attribute("llm.response_length", len(response_text or ""))

                # ---- OUTPUT guardrails -------------------------------- #
                output_guard = None
                if response_text:
                    output_guard = await GuardrailsService.scan_output(
                        response_text, prompt=effective_prompt
                    )
                    if output_guard.pii_redacted_text:
                        response_text = output_guard.pii_redacted_text

                # ---- auto-judge (skipped when explicit feedback_score provided) #
                if response_text and feedback_score is None:
                    from llm_observability.services.judge_service import JudgeService
                    judge_score, _ = await JudgeService.score(effective_prompt, response_text)
                    if judge_score is not None:
                        feedback_score = judge_score

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
                    req_row = await crud.create_request(
                        db=db,
                        prompt=effective_prompt,
                        response=response_text,
                        model_name=self.model,
                        provider=self.provider,
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

                    # Persist guardrail violation events
                    _rid = req_row.id
                    for vrow in input_guard.to_log_rows("input"):
                        await crud.create_guardrail_log(db, request_id=_rid, **vrow)
                    if output_guard:
                        for vrow in output_guard.to_log_rows("output"):
                            await crud.create_guardrail_log(db, request_id=_rid, **vrow)

                await self._check_alerts(latency_ms=latency_ms, cost=estimated_cost)

        return {
            "response": response_text,
            "model": self.model,
            "provider": self.provider,
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
    # Provider routing
    # ------------------------------------------------------------------ #

    async def _call_provider(
        self, prompt: str, system: Optional[str]
    ) -> Tuple[str, int, int]:
        """Dispatch to the appropriate SDK and return (response_text, prompt_tokens, completion_tokens)."""
        if self.provider == "openai":
            return await self._call_openai(prompt, system)
        if self.provider == "google":
            return await self._call_google(prompt, system)
        if self.provider == "mistral":
            return await self._call_mistral(prompt, system)
        return await self._call_anthropic(prompt, system)

    async def _call_anthropic(
        self, prompt: str, system: Optional[str]
    ) -> Tuple[str, int, int]:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        call_kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            call_kwargs["system"] = system

        message = await client.messages.create(**call_kwargs)
        return (
            message.content[0].text,
            message.usage.input_tokens,
            message.usage.output_tokens,
        )

    async def _call_openai(
        self, prompt: str, system: Optional[str]
    ) -> Tuple[str, int, int]:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError(
                "openai package is required for OpenAI models. Run: pip install openai"
            )

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = await client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=messages,
        )
        return (
            resp.choices[0].message.content or "",
            resp.usage.prompt_tokens,
            resp.usage.completion_tokens,
        )

    async def _call_google(
        self, prompt: str, system: Optional[str]
    ) -> Tuple[str, int, int]:
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise RuntimeError(
                "google-genai package is required for Gemini models. "
                "Run: pip install google-genai"
            )

        client = genai.Client()  # reads GOOGLE_API_KEY from env
        config = types.GenerateContentConfig(
            max_output_tokens=self.max_tokens,
            system_instruction=system,
        )
        resp = await client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        usage = resp.usage_metadata
        return (
            resp.text or "",
            usage.prompt_token_count or 0,
            usage.candidates_token_count or 0,
        )

    async def _call_mistral(
        self, prompt: str, system: Optional[str]
    ) -> Tuple[str, int, int]:
        """Call the Mistral AI API via the ``mistralai`` SDK.

        Supports all models prefixed ``mistral-*``, ``mixtral-*``,
        ``codestral-*``, and ``pixtral-*``.

        Requires:
            pip install mistralai
            MISTRAL_API_KEY=<your key>
        """
        try:
            from mistralai import Mistral  # type: ignore
        except ImportError:
            raise RuntimeError(
                "mistralai package is required for Mistral models. "
                "Run: pip install mistralai"
            )

        client = Mistral(api_key=settings.mistral_api_key)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = await client.chat.complete_async(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
        )
        return (
            resp.choices[0].message.content or "",
            resp.usage.prompt_tokens,
            resp.usage.completion_tokens,
        )

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _render_template(content: str, variables: Dict[str, str]) -> str:
        """Substitute {placeholders} in a template with provided values."""
        try:
            return content.format_map(variables)
        except KeyError as exc:
            raise ValueError(
                f"Template variable {exc} was not supplied in 'variables'"
            ) from exc

    async def _check_alerts(self, *, latency_ms: float, cost: float) -> None:
        """Fire webhook alerts (with per-type cooldown) when thresholds are breached.

        Per-model overrides (MODEL_ALERT_THRESHOLDS_JSON) take priority over
        the global LATENCY_ALERT_THRESHOLD_MS / COST_ALERT_THRESHOLD_USD values.
        """
        from llm_observability.services.alerting_service import AlertingService

        _overrides = settings.model_alert_thresholds.get(self.model, {})
        lat_threshold  = _overrides.get("latency_ms", settings.latency_alert_threshold_ms)
        cost_threshold = _overrides.get("cost_usd",   settings.cost_alert_threshold_usd)

        if latency_ms > lat_threshold:
            await AlertingService.send_alert(
                alert_type=f"high_latency_{self.model}",
                title="High Latency Alert",
                message=(
                    f"Request took {latency_ms:,.0f}ms — "
                    f"threshold is {lat_threshold:,.0f}ms"
                ),
                details={
                    "Model": self.model,
                    "Provider": self.provider,
                    "Latency": f"{latency_ms:,.0f} ms",
                    "Threshold": f"{lat_threshold:,.0f} ms",
                },
                color="danger",
            )

        if cost > cost_threshold:
            await AlertingService.send_alert(
                alert_type=f"high_cost_{self.model}",
                title="High Cost Alert",
                message=(
                    f"Request cost ${cost:.6f} — "
                    f"threshold is ${cost_threshold:.2f}"
                ),
                details={
                    "Model": self.model,
                    "Provider": self.provider,
                    "Cost": f"${cost:.6f}",
                    "Threshold": f"${cost_threshold:.2f}",
                },
                color="warning",
            )
