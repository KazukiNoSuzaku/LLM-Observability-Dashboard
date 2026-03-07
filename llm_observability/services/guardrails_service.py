"""GuardrailsService — real-time input/output validation middleware.

Architecture
------------
This service sits as middleware in the LLM request pipeline:

    User Input
        |
        v
    [ Input Guardrails ]  ← scan_input()
        |  block / redact / log
        v
    LLM API Call
        |
        v
    [ Output Guardrails ] ← scan_output()
        |  redact / log
        v
    User Response

Three validation layers
-----------------------
1. PII Detection (input + output)
   Uses Microsoft Presidio when installed, falls back to compiled regex.
   Detects: EMAIL, PHONE_NUMBER, US_SSN, CREDIT_CARD, IP_ADDRESS,
            CRYPTO (wallet addresses), API keys / bearer tokens.

2. Jailbreak / Prompt Injection (input only)
   Compiled regex patterns covering DAN, instruction-override, role-play
   bypass, system-prompt-leak, developer-mode, and base64 injection.

3. Structured Output Validation (output only)
   Uses Guardrails AI when installed to validate free-form responses
   against a minimal Pydantic schema (non-empty, max length).
   Falls back to a simple length/content check.

All results are returned as ``GuardrailResult`` and persisted to the
``guardrail_logs`` table via the CRUD layer in ``llm_wrapper.py``.

Configuration (environment variables / .env)
--------------------------------------------
    GUARDRAILS_ENABLED=true           # master on/off switch
    GUARDRAILS_BLOCK_ON_PII=false     # reject requests containing PII
    GUARDRAILS_BLOCK_ON_JAILBREAK=true  # reject jailbreak attempts
    GUARDRAILS_REDACT_OUTPUT_PII=true   # replace PII in responses
    GUARDRAILS_USE_PRESIDIO=true        # prefer Presidio over regex
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =========================================================================== #
# Result dataclass
# =========================================================================== #

@dataclass
class GuardrailResult:
    """Full result of a single guardrail scan pass (input or output)."""

    # Pass / fail
    blocked: bool = False
    block_reason: Optional[str] = None

    # PII
    pii_detected: bool = False
    pii_types: List[str] = field(default_factory=list)
    pii_redacted_text: Optional[str] = None   # set when redaction is applied

    # Jailbreak
    jailbreak_detected: bool = False
    jailbreak_patterns: List[str] = field(default_factory=list)

    # Output validation
    output_invalid: bool = False
    output_reasons: List[str] = field(default_factory=list)

    # Overhead tracking
    guardrail_latency_ms: float = 0.0

    # High-level outcome for DB storage
    action_taken: str = "pass"     # "pass" | "block" | "redact" | "log"
    violation_type: str = "none"   # "pii" | "jailbreak" | "output_invalid" | "none"
    severity: str = "none"         # "none" | "low" | "medium" | "high" | "critical"

    # Truncated snippet for the violation log
    snippet: str = ""

    def to_log_rows(self, stage: str) -> List[Dict]:
        """Return one log-row dict per distinct violation for DB persistence."""
        rows: List[Dict] = []
        meta = {
            "pii_types": self.pii_types,
            "jailbreak_patterns": self.jailbreak_patterns,
            "output_reasons": self.output_reasons,
            "block_reason": self.block_reason,
        }
        if self.jailbreak_detected:
            rows.append({
                "stage": stage,
                "violation_type": "jailbreak",
                "severity": "critical" if self.blocked else "high",
                "action_taken": self.action_taken,
                "latency_ms": self.guardrail_latency_ms,
                "snippet": self.snippet,
                "metadata_json": json.dumps(meta),
            })
        if self.pii_detected:
            rows.append({
                "stage": stage,
                "violation_type": "pii",
                "severity": "high" if self.blocked else ("medium" if self.pii_redacted_text else "low"),
                "action_taken": self.action_taken,
                "latency_ms": self.guardrail_latency_ms,
                "snippet": self.snippet,
                "metadata_json": json.dumps(meta),
            })
        if self.output_invalid:
            rows.append({
                "stage": stage,
                "violation_type": "output_invalid",
                "severity": "medium",
                "action_taken": self.action_taken,
                "latency_ms": self.guardrail_latency_ms,
                "snippet": self.snippet,
                "metadata_json": json.dumps(meta),
            })
        return rows


# =========================================================================== #
# Regex fallback patterns (used when Presidio is not installed)
# =========================================================================== #

_REGEX_PII: List[Tuple[str, re.Pattern]] = [
    ("EMAIL_ADDRESS",   re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("PHONE_NUMBER",    re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b")),
    ("US_SSN",          re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("CREDIT_CARD",     re.compile(
        r"\b(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"
    )),
    ("IP_ADDRESS",      re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    )),
    ("AWS_ACCESS_KEY",  re.compile(r"\b(?:AKIA|AIPA|ABIA|ACCA)[A-Z0-9]{16}\b")),
    ("API_KEY_BEARER",  re.compile(
        r"(?i)\b(?:bearer\s+|api[_\-]?key[:\s=]+|token[:\s=]+)[A-Za-z0-9\-_\.]{20,}\b"
    )),
]

_JAILBREAK_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("dan_jailbreak",       re.compile(
        r"\b(?:do\s+anything\s+now|DAN\b|jailbreak|jail\s*break)\b", re.IGNORECASE
    )),
    ("ignore_instructions", re.compile(
        r"(?i)(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:previous\s+|above\s+)?"
        r"(?:instructions?|constraints?|rules?|guidelines?|prompts?)"
    )),
    ("system_prompt_leak",  re.compile(
        r"(?i)(?:repeat|print|output|reveal|show|tell\s+me)\s+(?:your\s+)?"
        r"(?:system\s+prompt|instructions?|context|full\s+prompt)"
    )),
    ("role_play_bypass",    re.compile(
        r"(?i)(?:pretend|act\s+as|you\s+are\s+now|roleplay\s+as|play\s+the\s+role\s+of)\s+"
        r"(?:an?\s+)?(?:evil|unfiltered|unrestricted|uncensored|jailbroken|hacked)"
    )),
    ("hypothetical_bypass", re.compile(
        r"(?i)(?:hypothetically|in\s+a\s+fictional\s+(?:world|scenario)|"
        r"imagine\s+you\s+(?:could|had\s+no)\s+(?:restrictions?|filters?|guidelines?))"
    )),
    ("prompt_injection_tag", re.compile(
        r"(?i)<\s*(?:system|assistant|human|user|instruction)\s*>"
    )),
    ("developer_mode",      re.compile(
        r"(?i)(?:developer\s+mode|god\s+mode|sudo\s+mode|maintenance\s+mode)"
    )),
    ("base64_bypass",       re.compile(
        r"(?i)(?:decode|base64|b64decode).*(?:and\s+(?:follow|execute|run|do))"
    )),
    ("token_smuggling",     re.compile(
        r"(?i)(?:previous\s+instructions?|new\s+instructions?\s*:)"
    )),
    ("competitor_imperson",  re.compile(
        r"(?i)you\s+(?:are|were|will\s+be)\s+(?:now\s+)?(?:GPT-?[34]|ChatGPT|Gemini|LLaMA|Mistral)"
    )),
]


# =========================================================================== #
# Internal helpers
# =========================================================================== #

def _regex_scan_pii(text: str) -> List[str]:
    """Return list of detected PII entity types via regex patterns."""
    return [label for label, pat in _REGEX_PII if pat.search(text)]


def _presidio_scan_pii(text: str) -> List[str]:
    """Return list of detected PII entity types via Presidio (if installed)."""
    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore
        _analyzer = AnalyzerEngine()
        results = _analyzer.analyze(text=text, language="en")
        return list({r.entity_type for r in results})
    except ImportError:
        return _regex_scan_pii(text)
    except Exception as exc:
        logger.debug("Presidio scan failed, falling back to regex: %s", exc)
        return _regex_scan_pii(text)


def _presidio_redact(text: str, entity_types: List[str]) -> str:
    """Redact PII from *text* using Presidio (falls back to regex substitution)."""
    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore
        from presidio_anonymizer import AnonymizerEngine  # type: ignore
        analyzer = AnalyzerEngine()
        anonymizer = AnonymizerEngine()
        results = analyzer.analyze(text=text, language="en")
        if not results:
            return text
        anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
        return anonymized.text
    except ImportError:
        # Regex fallback
        for label, pat in _REGEX_PII:
            if label in entity_types:
                text = pat.sub(f"[REDACTED:{label}]", text)
        return text
    except Exception as exc:
        logger.debug("Presidio redaction failed: %s", exc)
        return text


def _guardrails_validate_output(text: str) -> Tuple[bool, List[str]]:
    """Validate output with Guardrails AI (falls back to simple checks).

    Returns (is_valid, list_of_failure_reasons).
    """
    reasons: List[str] = []

    # Basic sanity checks that always run
    if not text or not text.strip():
        reasons.append("empty_response")
    if len(text) > 50_000:
        reasons.append("response_exceeds_max_length")

    # Guardrails AI structured validation (optional)
    try:
        from guardrails import Guard  # type: ignore
        from pydantic import BaseModel, field_validator  # type: ignore

        class _ResponseSchema(BaseModel):
            content: str

            @field_validator("content")
            @classmethod
            def _not_empty(cls, v: str) -> str:
                if not v.strip():
                    raise ValueError("Response must not be empty")
                return v

        guard = Guard.from_pydantic(_ResponseSchema)
        validated, *_ = guard.validate({"content": text})
        # If Guardrails itself raised an exception it was caught above
    except ImportError:
        pass  # Guardrails AI not installed — simple checks suffice
    except Exception as exc:
        reasons.append(f"guardrails_validation_failed: {exc}")

    return (len(reasons) == 0), reasons


def _scan_jailbreak(text: str) -> List[str]:
    return [label for label, pat in _JAILBREAK_PATTERNS if pat.search(text)]


def _truncate_snippet(text: str, max_len: int = 200) -> str:
    return text[:max_len] + ("…" if len(text) > max_len else "")


# =========================================================================== #
# GuardrailsService
# =========================================================================== #

class GuardrailsService:
    """Stateless guardrail service — call class methods directly.

    Usage::

        result = GuardrailsService.scan_input(user_prompt)
        if result.blocked:
            raise HTTPException(400, result.block_reason)

        response = await llm.generate(result.pii_redacted_text or user_prompt)

        out_result = GuardrailsService.scan_output(response, stage="output")
        safe_response = out_result.pii_redacted_text or response
    """

    # ---------------------------------------------------------------------- #
    # Input scan
    # ---------------------------------------------------------------------- #

    @classmethod
    def scan_input(cls, prompt: str) -> GuardrailResult:
        """Scan a user prompt for PII and jailbreak patterns.

        Blocking and redaction behaviour is controlled by config flags.
        """
        from llm_observability.core.config import settings

        result = GuardrailResult(snippet=_truncate_snippet(prompt))

        if not settings.guardrails_enabled:
            return result

        t0 = time.monotonic()

        # ---- Jailbreak scan ------------------------------------------- #
        found_jailbreak = _scan_jailbreak(prompt)
        if found_jailbreak:
            result.jailbreak_detected = True
            result.jailbreak_patterns = found_jailbreak
            result.violation_type = "jailbreak"
            result.severity = "critical"
            logger.warning(
                "Guardrails [input]: jailbreak patterns detected — %s",
                found_jailbreak,
            )

        # ---- PII scan -------------------------------------------------- #
        if settings.guardrails_use_presidio:
            pii_types = _presidio_scan_pii(prompt)
        else:
            pii_types = _regex_scan_pii(prompt)

        if pii_types:
            result.pii_detected = True
            result.pii_types = pii_types
            if not result.violation_type or result.violation_type == "none":
                result.violation_type = "pii"
                result.severity = "high"
            logger.info(
                "Guardrails [input]: PII detected — %s", pii_types
            )

        # ---- Blocking / redaction -------------------------------------- #
        if result.jailbreak_detected and settings.guardrails_block_on_jailbreak:
            result.blocked = True
            result.block_reason = (
                f"Blocked: jailbreak/prompt-injection attempt "
                f"({', '.join(result.jailbreak_patterns)})"
            )
            result.action_taken = "block"
        elif result.pii_detected and settings.guardrails_block_on_pii:
            result.blocked = True
            result.block_reason = (
                f"Blocked: PII detected in prompt ({', '.join(result.pii_types)})"
            )
            result.action_taken = "block"
        elif result.pii_detected:
            # Redact PII instead of blocking
            result.pii_redacted_text = _presidio_redact(prompt, pii_types)
            result.action_taken = "redact"
        elif result.jailbreak_detected:
            result.action_taken = "log"
        else:
            result.action_taken = "pass"

        result.guardrail_latency_ms = (time.monotonic() - t0) * 1000
        return result

    # ---------------------------------------------------------------------- #
    # Output scan
    # ---------------------------------------------------------------------- #

    @classmethod
    def scan_output(cls, response: str) -> GuardrailResult:
        """Scan an LLM response for PII leakage and structural validity.

        PII is redacted when ``GUARDRAILS_REDACT_OUTPUT_PII=true``.
        """
        from llm_observability.core.config import settings

        result = GuardrailResult(snippet=_truncate_snippet(response))

        if not settings.guardrails_enabled:
            return result

        t0 = time.monotonic()

        # ---- Output validation (Guardrails AI) ------------------------- #
        is_valid, reasons = _guardrails_validate_output(response)
        if not is_valid:
            result.output_invalid = True
            result.output_reasons = reasons
            result.violation_type = "output_invalid"
            result.severity = "medium"
            result.action_taken = "log"
            logger.info("Guardrails [output]: validation failed — %s", reasons)

        # ---- PII in output --------------------------------------------- #
        if settings.guardrails_use_presidio:
            pii_types = _presidio_scan_pii(response)
        else:
            pii_types = _regex_scan_pii(response)

        if pii_types:
            result.pii_detected = True
            result.pii_types = pii_types
            if not result.violation_type or result.violation_type == "none":
                result.violation_type = "pii"
                result.severity = "high"
            logger.warning(
                "Guardrails [output]: PII leakage detected — %s", pii_types
            )
            if settings.guardrails_redact_output_pii:
                result.pii_redacted_text = _presidio_redact(response, pii_types)
                result.action_taken = "redact"
            else:
                result.action_taken = "log"

        if result.action_taken == "pass" and (result.output_invalid or result.pii_detected):
            result.action_taken = "log"

        result.guardrail_latency_ms = (time.monotonic() - t0) * 1000
        return result
