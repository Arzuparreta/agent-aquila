"""Optional startup check: ORM expects columns that Alembic must have applied."""

from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


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
        raw = str(exc).lower()
        if "undefinedcolumn" in raw or "does not exist" in raw:
            logger.critical(
                "Database schema is missing columns the app expects (e.g. after `git pull`). "
                "Run `alembic upgrade head` from `backend/`, or restart the Docker backend "
                "so its entrypoint runs migrations. Underlying error: %s",
                exc,
            )
            raise SystemExit(1) from exc
        raise
    except (OperationalError, OSError) as exc:
        logger.warning(
            "Schema probe skipped: database not reachable at startup (%s). "
            "The process will start; ensure Postgres is up before traffic.",
            exc,
        )
