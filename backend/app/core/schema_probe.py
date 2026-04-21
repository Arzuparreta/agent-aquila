"""Optional startup check: ORM expects columns that Alembic must have applied."""

from __future__ import annotations

import logging
import os
import sys

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _looks_like_missing_column_or_table(exc: ProgrammingError) -> bool:
    raw = str(getattr(exc, "orig", None) or exc).lower()
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) if orig is not None else None
    if sqlstate in ("42703", "42P01"):
        return True
    return (
        "undefinedcolumn" in raw
        or "undefinedtable" in raw
        or "does not exist" in raw
        or ("column" in raw and ("does not exist" in raw or "no existe" in raw))
        or (
            ("relation" in raw or "table" in raw)
            and ("does not exist" in raw or "no existe" in raw)
        )
    )


def _stderr_schema_help(exc: BaseException) -> None:
    """Docker/uvicorn often truncates log context; stderr banner is hard to miss."""
    banner = (
        "\n"
        "================================================================\n"
        "AQUILA: Database schema is missing columns/tables the app expects.\n"
        "Most often: run migrations against the SAME database the API uses.\n"
        "\n"
        "  docker compose exec backend alembic upgrade head\n"
        "\n"
        "Emergency bypass (avoid in production): AQUILA_SKIP_SCHEMA_PROBE=1\n"
        "\n"
        "Underlying error:\n"
        f"{exc}\n"
        "================================================================\n"
    )
    sys.stderr.write(banner)
    sys.stderr.flush()


async def fail_fast_if_schema_stale() -> None:
    """Exit the process when the DB is reachable but missing required columns.

    Set ``AQUILA_SKIP_SCHEMA_PROBE=1`` to disable. If Postgres is not reachable yet,
    log a warning and return (Docker healthchecks / slow DB).
    """
    if os.environ.get("AQUILA_SKIP_SCHEMA_PROBE", "").strip().lower() in ("1", "true", "yes"):
        return
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT agent_processing_paused FROM user_ai_settings LIMIT 0"))
    except ProgrammingError as exc:
        if _looks_like_missing_column_or_table(exc):
            logger.critical(
                "Schema probe failed — DB missing expected objects. "
                "Run `alembic upgrade head` (same DB as POSTGRES_* / DATABASE_URL). Error: %s",
                exc,
            )
            _stderr_schema_help(exc)
            raise SystemExit(1) from exc
        raise
    except (OperationalError, OSError) as exc:
        logger.warning(
            "Schema probe skipped: database not reachable at startup (%s). "
            "The process will start; ensure Postgres is up before traffic.",
            exc,
        )
