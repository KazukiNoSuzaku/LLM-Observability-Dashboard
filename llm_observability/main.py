"""FastAPI application entry point.

Start the server:
    uvicorn llm_observability.main:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from llm_observability.api.auth import get_current_user
from llm_observability.api.auth import router as auth_router
from llm_observability.api.oauth import router as oauth_router
from llm_observability.api.routes import router
from llm_observability.core.config import settings
from llm_observability.db.database import init_db
from llm_observability.services.tracing_service import TracingService

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup tasks before yielding, then teardown tasks on shutdown."""
    # ---- startup ----

    # Security checks — warn loudly about insecure defaults
    if settings.oauth_session_secret == "change-me-in-production":
        logger.warning(
            "SECURITY WARNING: OAUTH_SESSION_SECRET is set to the default value. "
            "Set a random 32-character string in your .env file before deploying."
        )
    if settings.auth_enabled and not settings.auth_secret_key:
        logger.warning(
            "SECURITY WARNING: AUTH_SECRET_KEY is not set. JWT signing key is "
            "derived from AUTH_PASSWORD — set AUTH_SECRET_KEY explicitly in production "
            "so tokens survive server restarts."
        )

    logger.info("Initialising database …")
    await init_db()
    logger.info("Database ready.")

    logger.info("Initialising distributed tracing …")
    TracingService.initialize(settings)
    logger.info(
        "Tracing ready (Phoenix enabled=%s, endpoint=%s).",
        settings.phoenix_enabled,
        settings.phoenix_endpoint,
    )

    logger.info(
        "LLM Observability API is live on http://%s:%s",
        settings.api_host,
        settings.api_port,
    )
    logger.info("Interactive docs → http://%s:%s/docs", settings.api_host, settings.api_port)

    yield

    # ---- shutdown ----
    logger.info("Shutting down LLM Observability API …")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LLM Observability Dashboard API",
    description=(
        "Production-grade observability backend for LLM applications.\n\n"
        "Tracks latency, token usage, cost, error rates, and quality metrics "
        "for every LLM request."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# SessionMiddleware must be added BEFORE OAuth routes — Authlib uses the
# session to store the OAuth2 state parameter for CSRF protection.
app.add_middleware(SessionMiddleware, secret_key=settings.oauth_session_secret)

# CORS: Bearer-token auth (Authorization header) does not need allow_credentials=True.
# allow_credentials=True is only for cookie/session auth and CANNOT be combined with
# allow_origins=["*"] — browsers reject that combination.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth endpoints (/auth/token, /auth/me) — no auth required on these
app.include_router(auth_router)

# OAuth2 social login (/auth/google/login|callback, /auth/github/login|callback)
app.include_router(oauth_router)

# Mount all API routes under /api/v1, protected by auth dependency
app.include_router(
    router,
    prefix="/api/v1",
    tags=["observability"],
    dependencies=[Depends(get_current_user)],
)


# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse(
        {
            "service": "LLM Observability Dashboard",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health",
            "api_prefix": "/api/v1",
        }
    )


@app.get("/health", tags=["ops"])
async def health() -> dict:
    """Liveness probe — returns 200 when the service is running."""
    return {"status": "healthy", "service": "llm-observability"}
