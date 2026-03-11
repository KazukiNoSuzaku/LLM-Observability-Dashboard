"""Tests for health and root endpoints."""

import pytest


@pytest.mark.asyncio
async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "LLM Observability Dashboard"
    assert "/docs" in data["docs"]


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "llm-observability"


@pytest.mark.asyncio
async def test_docs_accessible(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200
