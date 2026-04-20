"""Alembic async environment.

Operational triage (for humans and coding agents)
-------------------------------------------------
**Symptom A — backend container exits during startup**

- ``docker compose ps``: ``backend`` is ``Exited (1)``.
- Logs show ``alembic upgrade head`` then::

    asyncpg.exceptions.StringDataRightTruncationError: value too long for type character varying(32)
    [SQL: UPDATE alembic_version SET version_num='...']

**Symptom B — UI shows 500 / Next.js proxy / BACKEND_INTERNAL_URL**

- Often the API never reached Uvicorn because migrations aborted (check backend logs first).

**Cause**

Alembic creates ``alembic_version.version_num`` as **VARCHAR(32)** by default. A
migration's ``revision`` string longer than 32 characters fails the version-row
UPDATE even when the migration DDL itself is valid.

**Mitigation**

:func:`_widen_alembic_version_num` runs before :func:`context.run_migrations`
and widens the column to :data:`ALEMBIC_VERSION_NUM_MAX_LENGTH` on PostgreSQL.
See also ``README.md`` (Troubleshooting) and ``.cursor/rules/alembic-version-column.mdc``.

**Grep anchors**

``StringDataRightTruncation``, ``alembic_version``, ``VARCHAR(32)``
"""
from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.models import base  # noqa: F401
import app.models  # noqa: F401  # register AgentRun, RagChunk, … on Base.metadata
from app.models.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_log = logging.getLogger("alembic.env")

# Widen alembic_version.version_num to at least this many characters (Postgres).
# Keep in sync with ``backend/tests/test_alembic_version_column.py``.
ALEMBIC_VERSION_NUM_MAX_LENGTH = 255


def _widen_alembic_version_num(connection: Connection) -> None:
    """Ensure ``alembic_version.version_num`` can store long ``revision`` strings.

    Alembic's default is VARCHAR(32); see module docstring for failure mode
    (``StringDataRightTruncation`` on ``UPDATE alembic_version``).
    """
    if connection.dialect.name != "postgresql":
        return
    row = connection.execute(
        text(
            """
            SELECT character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'alembic_version'
              AND column_name = 'version_num'
            """
        )
    ).fetchone()
    if row is None or row[0] is None:
        return
    prev = row[0]
    if prev >= ALEMBIC_VERSION_NUM_MAX_LENGTH:
        return
    connection.execute(
        text(
            f"ALTER TABLE alembic_version ALTER COLUMN version_num "
            f"TYPE VARCHAR({ALEMBIC_VERSION_NUM_MAX_LENGTH})"
        )
    )
    connection.commit()
    _log.info(
        "Widened alembic_version.version_num from VARCHAR(%s) to VARCHAR(%s) "
        "(Alembic default 32 is too short for some revision ids; see alembic/env.py docstring).",
        prev,
        ALEMBIC_VERSION_NUM_MAX_LENGTH,
    )


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _widen_alembic_version_num(connection)
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async def run() -> None:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()

    import asyncio

    asyncio.run(run())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
