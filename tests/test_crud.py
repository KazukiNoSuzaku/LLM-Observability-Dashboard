"""Unit tests for CRUD operations."""

from datetime import datetime, timezone

import pytest

from llm_observability.db import crud
from llm_observability.db.models import LLMRequest


@pytest.mark.asyncio
async def test_create_request_basic(db_session):
    row = await crud.create_request(
        db=db_session,
        prompt="Tell me a joke",
        response="Why did the chicken cross the road?",
        model_name="claude-haiku-4-5-20251001",
        provider="anthropic",
        latency_ms=450.0,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        estimated_cost=0.000015,
    )
    assert row.id is not None
    assert row.prompt == "Tell me a joke"
    assert row.latency_ms == 450.0
    assert row.is_error is False


@pytest.mark.asyncio
async def test_create_error_request(db_session):
    """Error requests have None latency — repr should not crash."""
    row = await crud.create_request(
        db=db_session,
        prompt="This will fail",
        response=None,
        model_name="claude-haiku-4-5-20251001",
        provider="anthropic",
        latency_ms=None,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        estimated_cost=0.0,
        is_error=True,
        error="API timeout",
    )
    # Should not raise TypeError for None latency/cost
    assert "N/A" in repr(row)
    assert row.is_error is True


@pytest.mark.asyncio
async def test_update_feedback(db_session):
    row = await crud.create_request(
        db=db_session,
        prompt="Rate me",
        response="I am great",
        model_name="gpt-4o-mini",
        provider="openai",
        latency_ms=300.0,
        prompt_tokens=5,
        completion_tokens=5,
        total_tokens=10,
        estimated_cost=0.000005,
    )
    ok = await crud.update_feedback(db_session, row.id, 0.9)
    assert ok is True

    # Verify persisted
    from sqlalchemy import select
    result = await db_session.execute(
        select(LLMRequest).where(LLMRequest.id == row.id)
    )
    updated = result.scalar_one()
    assert updated.feedback_score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_update_feedback_not_found(db_session):
    ok = await crud.update_feedback(db_session, 99999, 0.5)
    assert ok is False


@pytest.mark.asyncio
async def test_get_metrics_summary_empty(db_session):
    summary = await crud.get_metrics_summary(db_session, hours=24)
    assert summary["total_requests"] == 0
    assert summary["error_rate_pct"] == 0.0
    assert summary["p50_latency_ms"] == 0.0
    assert summary["p95_latency_ms"] == 0.0


@pytest.mark.asyncio
async def test_get_metrics_summary_with_data(db_session):
    for i in range(10):
        await crud.create_request(
            db=db_session,
            prompt=f"prompt {i}",
            response=f"response {i}",
            model_name="claude-haiku-4-5-20251001",
            provider="anthropic",
            latency_ms=float(100 + i * 50),
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            estimated_cost=0.00001,
        )

    summary = await crud.get_metrics_summary(db_session, hours=24)
    assert summary["total_requests"] >= 10
    assert summary["p95_latency_ms"] > 0
    assert summary["total_cost_usd"] > 0


@pytest.mark.asyncio
async def test_create_and_get_prompt_template(db_session):
    tpl = await crud.create_prompt_template(
        db_session,
        name="my-template",
        content="Hello {name}!",
        description="A greeting template",
    )
    assert tpl.id is not None
    assert tpl.version == 1
    assert tpl.is_active is True

    fetched = await crud.get_prompt_template(db_session, name="my-template")
    assert fetched is not None
    assert fetched.content == "Hello {name}!"


@pytest.mark.asyncio
async def test_template_version_auto_increments(db_session):
    name = "increment-test"
    for expected_version in range(1, 4):
        tpl = await crud.create_prompt_template(
            db_session, name=name, content=f"v{expected_version}"
        )
        assert tpl.version == expected_version


@pytest.mark.asyncio
async def test_deactivate_template(db_session):
    name = "deactivate-me"
    await crud.create_prompt_template(db_session, name=name, content="content")

    ok = await crud.deactivate_prompt_template(db_session, name=name, version=1)
    assert ok is True

    # Should not be returned by active-only lookup
    result = await crud.get_prompt_template(db_session, name=name, active_only=True)
    assert result is None


@pytest.mark.asyncio
async def test_deactivate_nonexistent_returns_false(db_session):
    ok = await crud.deactivate_prompt_template(db_session, name="ghost", version=99)
    assert ok is False


@pytest.mark.asyncio
async def test_guardrail_log_create_and_query(db_session):
    log = await crud.create_guardrail_log(
        db_session,
        stage="input",
        violation_type="jailbreak",
        severity="critical",
        action_taken="block",
        snippet="ignore all instructions",
        metadata_json='{"patterns": ["ignore_instructions"]}',
    )
    assert log.id is not None

    logs = await crud.get_guardrail_logs(db_session, hours=24)
    assert any(l.id == log.id for l in logs)

    stats = await crud.get_guardrail_stats(db_session, hours=24)
    assert stats["total_violations"] >= 1
    assert stats["total_blocked"] >= 1
