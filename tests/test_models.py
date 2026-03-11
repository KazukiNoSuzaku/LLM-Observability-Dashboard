"""Unit tests for ORM model behaviour."""

from llm_observability.db.models import GuardrailLog, LLMRequest, PromptTemplate


def test_llm_request_repr_with_none_values():
    """repr must not raise TypeError when latency/cost are None (error requests)."""
    row = LLMRequest()
    row.id = 42
    row.model_name = "claude-haiku-4-5-20251001"
    row.latency_ms = None
    row.estimated_cost = None

    text = repr(row)
    assert "N/A" in text
    assert "42" in text
    assert "claude-haiku" in text


def test_llm_request_repr_with_values():
    row = LLMRequest()
    row.id = 1
    row.model_name = "gpt-4o"
    row.latency_ms = 250.0
    row.estimated_cost = 0.000123

    text = repr(row)
    assert "250ms" in text
    assert "$0.000123" in text


def test_prompt_template_repr():
    tpl = PromptTemplate()
    tpl.name = "summarizer"
    tpl.version = 2
    tpl.is_active = True
    text = repr(tpl)
    assert "summarizer" in text
    assert "v2" in text


def test_guardrail_log_repr():
    log = GuardrailLog()
    log.id = 5
    log.stage = "input"
    log.violation_type = "jailbreak"
    log.action_taken = "block"
    text = repr(log)
    assert "jailbreak" in text
    assert "block" in text
