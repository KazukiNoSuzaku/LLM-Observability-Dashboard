"""Google and GitHub OAuth2 social login via Authlib.

Flow
----
1. Browser hits  GET /auth/{provider}/login
   → redirected to provider's OAuth2 consent screen.
2. Provider redirects back to  GET /auth/{provider}/callback?code=...&state=...
3. We exchange the code for user-info, upsert an OAuthUser row in the DB,
   then return a standard JWT (same Token model as POST /auth/token) so the
   client can immediately use Bearer-token auth on all /api/v1/* endpoints.

Setup
-----
Google:
  1. Go to https://console.cloud.google.com/apis/credentials
  2. Create an "OAuth 2.0 Client ID" (Web application)
  3. Add Authorised redirect URI:  {OAUTH_REDIRECT_BASE_URL}/auth/google/callback
  4. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env

GitHub:
  1. Go to https://github.com/settings/developers → OAuth Apps → New OAuth App
  2. Set Homepage URL and Callback URL: {OAUTH_REDIRECT_BASE_URL}/auth/github/callback
  3. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in .env

SessionMiddleware (required by Authlib for CSRF state) must be added to the
FastAPI app before mounting this router — see main.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.requests import Request

from llm_observability.api.auth import Token, create_access_token
from llm_observability.core.config import settings
from llm_observability.db.database import AsyncSessionLocal
from llm_observability.db.models import OAuthUser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authlib OAuth registry (providers registered lazily at import time)
# ---------------------------------------------------------------------------

_oauth = OAuth()

if settings.google_client_id:
    _oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url=(
            "https://accounts.google.com/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid email profile"},
    )

if settings.github_client_id:
    _oauth.register(
        name="github",
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "read:user user:email"},
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _upsert_oauth_user(
    provider: str,
    provider_user_id: str,
    email: str,
    username: str,
) -> OAuthUser:
    """Insert or update an OAuthUser row and return it."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OAuthUser).where(
                OAuthUser.provider == provider,
                OAuthUser.provider_user_id == provider_user_id,
            )
        )
        user: Optional[OAuthUser] = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)

        if user is None:
            user = OAuthUser(
                provider=provider,
                provider_user_id=provider_user_id,
                email=email,
                username=username,
                created_at=now,
                last_login=now,
            )
            session.add(user)
        else:
            # Refresh profile fields in case the provider updated them
            user.email = email
            user.username = username
            user.last_login = now

        await session.commit()
        await session.refresh(user)
        return user


def _token_json(username: str) -> JSONResponse:
    """Return a JSON Token response identical to POST /auth/token."""
    access_token, expires_in = create_access_token(username)
    return JSONResponse(
        Token(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
        ).model_dump()
    )


def _err(detail: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/providers", summary="List configured OAuth providers")
async def list_providers() -> dict:
    """Returns which social-login providers are currently enabled."""
    return {
        "google": bool(settings.google_client_id),
        "github": bool(settings.github_client_id),
    }


# ── Google ──────────────────────────────────────────────────────────────────


@router.get("/google/login", summary="Start Google OAuth2 flow")
async def google_login(request: Request) -> JSONResponse:
    """Redirect the browser to Google's OAuth2 consent screen."""
    if not settings.google_client_id:
        return _err("Google OAuth is not configured on this server.", 501)
    redirect_uri = f"{settings.oauth_redirect_base_url}/auth/google/callback"
    return await _oauth.google.authorize_redirect(request, redirect_uri)


@router.get(
    "/google/callback",
    response_model=Token,
    summary="Google OAuth2 callback — returns JWT",
)
async def google_callback(request: Request) -> JSONResponse:
    """Exchange Google auth-code for user info; auto-provision user; return JWT."""
    if not settings.google_client_id:
        return _err("Google OAuth is not configured on this server.", 501)

    try:
        token = await _oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        logger.warning("Google OAuth error: %s", exc)
        return _err(f"Google OAuth failed: {exc}", 400)

    user_info = token.get("userinfo") or {}
    provider_user_id: str = user_info.get("sub", "")
    email: str = user_info.get("email", "")
    username: str = (
        user_info.get("name")
        or user_info.get("given_name")
        or email.split("@")[0]
    )

    if not provider_user_id or not email:
        return _err("Google did not return required user information.", 400)

    user = await _upsert_oauth_user("google", provider_user_id, email, username)
    logger.info("Google OAuth login: %s (%s)", user.username, user.email)
    return _token_json(user.username)


# ── GitHub ───────────────────────────────────────────────────────────────────


@router.get("/github/login", summary="Start GitHub OAuth2 flow")
async def github_login(request: Request) -> JSONResponse:
    """Redirect the browser to GitHub's OAuth2 consent screen."""
    if not settings.github_client_id:
        return _err("GitHub OAuth is not configured on this server.", 501)
    redirect_uri = f"{settings.oauth_redirect_base_url}/auth/github/callback"
    return await _oauth.github.authorize_redirect(request, redirect_uri)


@router.get(
    "/github/callback",
    response_model=Token,
    summary="GitHub OAuth2 callback — returns JWT",
)
async def github_callback(request: Request) -> JSONResponse:
    """Exchange GitHub auth-code for user info; auto-provision user; return JWT."""
    if not settings.github_client_id:
        return _err("GitHub OAuth is not configured on this server.", 501)

    try:
        token = await _oauth.github.authorize_access_token(request)
    except OAuthError as exc:
        logger.warning("GitHub OAuth error: %s", exc)
        return _err(f"GitHub OAuth failed: {exc}", 400)

    # Primary profile
    resp = await _oauth.github.get("user", token=token)
    profile: dict = resp.json()
    provider_user_id: str = str(profile.get("id", ""))
    username: str = profile.get("login", "")
    email: str = profile.get("email") or ""

    # GitHub can hide primary email — fetch from /user/emails
    if not email:
        try:
            emails_resp = await _oauth.github.get("user/emails", token=token)
            for entry in emails_resp.json():
                if entry.get("primary") and entry.get("verified"):
                    email = entry["email"]
                    break
        except Exception:
            pass

    if not provider_user_id or not username:
        return _err("GitHub did not return required user information.", 400)

    # Fallback email for users with entirely hidden emails
    email = email or f"{username}@github.invalid"

    user = await _upsert_oauth_user("github", provider_user_id, email, username)
    logger.info("GitHub OAuth login: %s (%s)", user.username, user.email)
    return _token_json(user.username)
