"""Authentication middleware for the LLM Observability API.

Two complementary mechanisms are supported — enable either or both:

  1. OAuth2 Password Flow (JWT Bearer)
     POST /auth/token  with form fields ``username`` and ``password``
     → returns a short-lived JWT access token
     → send as ``Authorization: Bearer <token>`` on subsequent requests

  2. API Key (header)
     Set ``AUTH_API_KEY`` in .env and send ``X-API-Key: <key>`` on every request.
     Useful for scripts, CI, and non-interactive clients.

Both mechanisms are checked inside ``get_current_user()`` which is applied
as a FastAPI dependency to all ``/api/v1/*`` routes.

Configuration
-------------
    AUTH_ENABLED=false           # master switch — false means no auth required
    AUTH_USERNAME=admin          # username for the /auth/token endpoint
    AUTH_PASSWORD=               # password  (required when AUTH_ENABLED=true)
    AUTH_API_KEY=                # static API key (optional alternative to Bearer)
    AUTH_SECRET_KEY=             # JWT signing key (auto-derived if empty)
    AUTH_TOKEN_EXPIRE_MINUTES=60 # token lifetime

Install requirement
-------------------
    pip install PyJWT>=2.8.0
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWT import (optional — falls back to HMAC token if PyJWT is not installed)
# ---------------------------------------------------------------------------
try:
    import jwt as _jwt  # type: ignore

    _JWT_AVAILABLE = True
except ImportError:
    _jwt = None  # type: ignore
    _JWT_AVAILABLE = False
    logger.info(
        "PyJWT not installed — using HMAC fallback tokens. "
        "Run 'pip install PyJWT>=2.8.0' for standard JWT support."
    )

_ALGORITHM = "HS256"

# ---------------------------------------------------------------------------
# FastAPI security schemes (both optional so each can be used independently)
# ---------------------------------------------------------------------------
_oauth2_scheme  = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key",               auto_error=False)


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class Token(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    expires_in:   int  # seconds


class UserInfo(BaseModel):
    username:      str
    authenticated: bool
    auth_method:   str  # "bearer" | "api_key" | "disabled"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _signing_key() -> str:
    """Return the JWT / HMAC signing key.

    Uses ``AUTH_SECRET_KEY`` from settings when set.
    Falls back to a key derived from the configured password so the server
    can start without explicit key configuration (convenient for dev;
    not recommended for production — set ``AUTH_SECRET_KEY`` explicitly).
    """
    from llm_observability.core.config import settings

    if settings.auth_secret_key:
        return settings.auth_secret_key

    # Derive a deterministic key from the password so tokens survive restarts
    derived = hashlib.sha256(
        f"llm-obs:{settings.auth_password}:{settings.auth_username}".encode()
    ).hexdigest()
    return derived


def create_access_token(username: str) -> tuple[str, int]:
    """Create a signed token for *username*.

    Returns ``(token_string, expires_in_seconds)``.
    Uses PyJWT when available, falls back to a signed ``simple:`` token.
    """
    from llm_observability.core.config import settings

    expires_in = settings.auth_token_expire_minutes * 60

    if _JWT_AVAILABLE:
        expire = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        payload = {"sub": username, "exp": expire, "iat": datetime.now(timezone.utc)}
        token = _jwt.encode(payload, _signing_key(), algorithm=_ALGORITHM)
        return token, expires_in

    # HMAC fallback — not JWT but still cryptographically signed
    sig = hmac.new(
        _signing_key().encode(), username.encode(), hashlib.sha256
    ).hexdigest()
    return f"simple:{username}:{sig}", expires_in


def _verify_token(token: str) -> Optional[str]:
    """Return the ``username`` from a valid token, or ``None`` on failure."""
    if not token:
        return None

    if _JWT_AVAILABLE:
        try:
            payload = _jwt.decode(token, _signing_key(), algorithms=[_ALGORITHM])
            return payload.get("sub")
        except Exception:
            return None

    # HMAC fallback
    if token.startswith("simple:"):
        parts = token.split(":", 2)
        if len(parts) == 3:
            _, username, provided_sig = parts
            expected_sig = hmac.new(
                _signing_key().encode(), username.encode(), hashlib.sha256
            ).hexdigest()
            if hmac.compare_digest(provided_sig, expected_sig):
                return username
    return None


# ---------------------------------------------------------------------------
# FastAPI dependency — used on all /api/v1 routes
# ---------------------------------------------------------------------------

async def get_current_user(
    api_key: Optional[str] = Depends(_api_key_header),
    token:   Optional[str] = Depends(_oauth2_scheme),
) -> UserInfo:
    """Verify the request is authenticated.

    When ``AUTH_ENABLED=false`` (default) this is a no-op and every request
    is treated as the anonymous user — no credentials required.

    Authentication priority:
      1. X-API-Key header (if AUTH_API_KEY is configured)
      2. Authorization: Bearer <jwt> (if token is present)
      3. Raises 401 if neither succeeds
    """
    from llm_observability.core.config import settings

    if not settings.auth_enabled:
        return UserInfo(username="anonymous", authenticated=False, auth_method="disabled")

    # --- API key check ---------------------------------------------------- #
    if api_key and settings.auth_api_key:
        if hmac.compare_digest(api_key, settings.auth_api_key):
            return UserInfo(username="api-key-user", authenticated=True, auth_method="api_key")
        # Key was provided but wrong — fall through to give a 401 below
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Bearer token check ----------------------------------------------- #
    if token:
        username = _verify_token(token)
        if username:
            return UserInfo(username=username, authenticated=True, auth_method="bearer")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Neither credential provided ------------------------------------- #
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required — provide 'X-API-Key' header or 'Authorization: Bearer <token>'",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ---------------------------------------------------------------------------
# Auth router — /auth/token  and  /auth/me
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/token",
    response_model=Token,
    summary="Get a JWT access token",
    description=(
        "Exchange your username and password for a short-lived JWT Bearer token. "
        "Send the token as ``Authorization: Bearer <token>`` on all API requests."
    ),
)
async def login(form: OAuth2PasswordRequestForm = Depends()) -> Token:
    from llm_observability.core.config import settings

    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication is disabled (AUTH_ENABLED=false)",
        )
    if not settings.auth_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AUTH_PASSWORD is not configured — set it in your .env file",
        )

    # Constant-time comparison to prevent timing attacks
    username_ok = hmac.compare_digest(form.username, settings.auth_username)
    password_ok = hmac.compare_digest(form.password, settings.auth_password)

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = create_access_token(form.username)
    logger.info("Token issued for user '%s' (expires_in=%ds)", form.username, expires_in)
    return Token(access_token=token, token_type="bearer", expires_in=expires_in)


@router.get(
    "/me",
    response_model=UserInfo,
    summary="Return info about the authenticated caller",
)
async def me(current_user: UserInfo = Depends(get_current_user)) -> UserInfo:
    return current_user
