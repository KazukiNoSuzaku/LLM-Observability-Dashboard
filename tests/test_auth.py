"""Tests for authentication endpoints and middleware."""

import os

import pytest

# ── Auth-disabled (default in conftest) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_no_auth_required_when_disabled(client):
    """With AUTH_ENABLED=false all API routes should be open."""
    resp = await client.get("/api/v1/metrics/summary")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_me_anonymous(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "anonymous"
    assert data["auth_method"] == "disabled"


# ── Token endpoint behaviour when auth is disabled ───────────────────────────


@pytest.mark.asyncio
async def test_token_endpoint_returns_400_when_auth_disabled(client):
    resp = await client.post(
        "/auth/token",
        data={"username": "admin", "password": "secret"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400


# ── Auth helper unit tests ───────────────────────────────────────────────────


def test_create_and_verify_jwt_token():
    """create_access_token → _verify_token round-trip (JWT path)."""
    os.environ["AUTH_SECRET_KEY"] = "test-secret-key-for-unit-tests"
    from importlib import reload

    import llm_observability.api.auth as auth_module

    reload(auth_module)  # pick up env change

    token, expires_in = auth_module.create_access_token("testuser")
    assert isinstance(token, str)
    assert expires_in > 0

    username = auth_module._verify_token(token)
    assert username == "testuser"


def test_verify_invalid_token_returns_none():
    from llm_observability.api.auth import _verify_token

    assert _verify_token("") is None
    assert _verify_token("not.a.valid.token") is None
    assert _verify_token("Bearer garbage") is None


def test_hmac_fallback_token_expiry():
    """HMAC fallback tokens should be rejected after expiry."""
    import time
    import hashlib
    import hmac as _hmac

    # Build an already-expired token manually
    key = "test-signing-key"
    username = "admin"
    exp_ts = int(time.time()) - 10  # 10 seconds in the past
    msg = f"{username}:{exp_ts}".encode()
    sig = _hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()
    token = f"simple:{username}:{exp_ts}:{sig}"

    # Patch the signing key and test verification
    import llm_observability.api.auth as auth_mod
    original = auth_mod._signing_key

    auth_mod._signing_key = lambda: key  # type: ignore[assignment]
    try:
        result = auth_mod._verify_token(token)
        assert result is None, "Expired HMAC token should return None"
    finally:
        auth_mod._signing_key = original  # type: ignore[assignment]
