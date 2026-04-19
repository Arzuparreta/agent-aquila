from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, SQLAlchemyError

from app.core.config import settings
from app.routes import api_router

logger = logging.getLogger(__name__)

app = FastAPI(title="CRM + AI Cockpit API", version="0.1.0")


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
    logger.exception("Unhandled database error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error — see backend logs for details."},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
