from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import (
    DBAPIError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)

from app.core.config import settings
from app.core.envelope_crypto import KeyDecryptError
from app.core.schema_probe import fail_fast_if_schema_stale
from app.routes import api_router
from app.services.llm_client import aclose_llm_http_client
from app.services.llm_errors import LLMProviderError, NoActiveProviderError
from app.services.ws_broker import aclose_subscriber_redis, run_redis_subscriber_loop

logger = logging.getLogger(__name__)

# Initialize Sentry if DSN is configured
if settings.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
        ],
        release="crm-ai-cockpit-backend@0.0.4",
    )


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    await fail_fast_if_schema_stale()
    sub_task: asyncio.Task | None = None
    if (settings.redis_url or "").strip():
        sub_task = asyncio.create_task(run_redis_subscriber_loop())
    yield
    if sub_task is not None:
        sub_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sub_task
    await aclose_subscriber_redis()
    await aclose_llm_http_client()


app = FastAPI(title="CRM + AI Cockpit API", version="0.0.8", lifespan=_app_lifespan)


def _is_connectivity_error(exc: SQLAlchemyError) -> bool:
    """Heuristic: only treat connection-class errors as Postgres reachability problems.

    Logic-level errors (``MultipleResultsFound``, ``IntegrityError`` on app data,
    statement compilation, etc.) used to be reported as "check DATABASE_URL", which
    sent operators chasing a config issue when the real cause was application code.
    """
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True
    return False


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request, exc: SQLAlchemyError):
    if _is_connectivity_error(exc):
        logger.exception("Database connectivity error on %s", request.url.path)
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Database error — check Postgres is reachable and "
                    "DATABASE_URL / POSTGRES_* settings."
                )
            },
        )
    # Most common after a git pull: model expects columns/tables Alembic has not applied yet.
    if isinstance(exc, ProgrammingError):
        raw = str(getattr(exc, "orig", None) or exc)
        lowered = raw.lower()
        orig = getattr(exc, "orig", None)
        sqlstate = getattr(orig, "sqlstate", None) if orig is not None else None
        # PostgreSQL: 42703 undefined_column, 42P01 undefined_table
        schema_sqlstates = frozenset({"42703", "42P01"})
        looks_like_missing_schema = sqlstate in schema_sqlstates or (
            "undefinedcolumn" in lowered
            or "undefinedtable" in lowered
            or "does not exist" in lowered
            or (
                "column" in lowered
                and ("does not exist" in lowered or "no existe" in lowered)
            )
            or (
                ("relation" in lowered or "table" in lowered)
                and ("does not exist" in lowered or "no existe" in lowered)
            )
        )
        if looks_like_missing_schema:
            logger.error(
                "Database schema mismatch on %s (run Alembic migrations): %s",
                request.url.path,
                raw[:300],
            )
            return JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "Database schema is out of date. Apply migrations, then retry: "
                        "`cd backend && alembic upgrade head`. "
                        "With Docker Compose: `docker compose up --build backend` "
                        "(the backend runs `alembic upgrade head` on start)."
                    ),
                    "kind": "schema_out_of_date",
                },
            )
    logger.exception("Unhandled database error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error — see backend logs for details."},
    )


@app.exception_handler(LLMProviderError)
async def llm_provider_exception_handler(request, exc: LLMProviderError):
    """Translate upstream provider failures into a structured 502 response.

    The chat UI looks at ``detail.kind == "provider_error"`` and renders an
    inline card with the hint + a "Probar conexión" / "Abrir ajustes"
    affordance instead of dropping the raw httpx error string into the
    assistant turn.
    """
    logger.warning(
        "LLM provider error on %s: provider=%s status=%s model=%s",
        request.url.path,
        exc.provider,
        exc.status_code,
        exc.model,
    )
    return JSONResponse(status_code=502, content={"detail": exc.to_dict()})


@app.exception_handler(NoActiveProviderError)
async def no_active_provider_handler(request, exc: NoActiveProviderError):
    """Returned when the agent loop has no provider config selected as active."""
    return JSONResponse(
        status_code=412,
        content={
            "detail": {
                "kind": "no_active_provider",
                "message": str(exc) or "No AI provider is selected as active.",
                "settings_url": "/settings#ai",
            }
        },
    )


@app.exception_handler(KeyDecryptError)
async def key_decrypt_exception_handler(request, exc: KeyDecryptError):
    """A stored API key could not be decrypted with the current KEK.

    Surfaces a precise message so the user can re-enter the key, instead of
    silently behaving as keyless.
    """
    logger.warning("Key decrypt error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=409,
        content={
            "detail": {
                "kind": "key_decrypt_error",
                "scope": exc.scope,
                "reason": exc.reason,
                "message": (
                    "An API key for this provider exists but cannot be decrypted "
                    "(the encryption key has changed). Re-enter the key in "
                    "Settings → AI to recover."
                ),
                "settings_url": "/settings#ai",
            }
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


