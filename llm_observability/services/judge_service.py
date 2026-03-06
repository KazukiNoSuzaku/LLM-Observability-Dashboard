"""JudgeService — LLM-as-judge for automatic response quality scoring.

Uses a cheap, fast model (claude-haiku by default) to score every LLM
response on a 0–1 scale without human involvement.

The judge is called AFTER the main response is generated, so it never
adds latency from the user's perspective (it runs in the background
before the DB write, but the API call is already complete).

Enable via config:
    JUDGE_ENABLED=true
    JUDGE_MODEL=claude-haiku-4-5-20251001   # or any cheap model

The score is stored in ``feedback_score`` column.  If an explicit
``feedback_score`` was already provided by the caller, the judge is skipped
(human feedback wins over automated scoring).
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an expert AI response quality evaluator.
Given a PROMPT and a RESPONSE, evaluate the response quality on a 0.0–1.0 scale:

  1.0 = Perfect — accurate, complete, clear, directly addresses the prompt
  0.8 = Good    — mostly accurate, helpful, minor gaps
  0.6 = Adequate — answers the question but lacks depth or precision
  0.4 = Poor    — partially correct, unclear, or missing key parts
  0.2 = Bad     — mostly incorrect, off-topic, or unhelpful
  0.0 = Harmful or completely wrong

Respond with ONLY a valid JSON object (no markdown):
{"score": <float 0.0-1.0>, "reason": "<one concise sentence>"}"""


class JudgeService:
    """Auto-score LLM responses using a judge model."""

    @staticmethod
    async def score(
        prompt: str,
        response: str,
    ) -> Tuple[Optional[float], Optional[str]]:
        """Score a prompt-response pair.

        Returns:
            (score, reason) — both None if judge is disabled or fails.
            score is a float in [0.0, 1.0].
        """
        from llm_observability.core.config import settings  # lazy import

        if not settings.judge_enabled:
            return None, None

        if not settings.anthropic_api_key:
            logger.debug("Judge skipped — no Anthropic API key configured")
            return None, None

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            # Truncate to keep judge calls cheap
            prompt_excerpt = prompt[:600]
            response_excerpt = response[:1200]

            msg = await client.messages.create(
                model=settings.judge_model,
                max_tokens=120,
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"PROMPT:\n{prompt_excerpt}\n\n"
                            f"RESPONSE:\n{response_excerpt}"
                        ),
                    }
                ],
            )

            raw = msg.content[0].text.strip()
            # Strip accidental markdown fences
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)

            score = float(data.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            reason = str(data.get("reason", ""))

            logger.debug("Judge score=%.2f reason=%s", score, reason)
            return score, reason

        except json.JSONDecodeError as exc:
            logger.warning("Judge returned invalid JSON: %s", exc)
            return None, None
        except Exception as exc:
            logger.warning("Judge scoring failed: %s", exc)
            return None, None
