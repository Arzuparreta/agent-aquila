"""Mark a single auto-created "default" general thread per user.

Why
---
``get_or_create_general_thread`` used to identify the auto-created landing
thread by ``kind='general' AND entity_type IS NULL AND entity_id IS NULL``,
but free-form "Nueva conversación" threads (created via ``POST /threads``
without an entity) match the same predicate. Once the user created one of
those, the get-or-create query started returning multiple rows and crashing
``GET /threads`` with ``MultipleResultsFound`` (then surfaced to the user as
the misleading "Database error — check Postgres is reachable" 503).

The Postgres ``UNIQUE (user_id, entity_type, entity_id)`` constraint did not
catch this because NULLs are treated as distinct in standard unique indexes.

Fix
---
Add ``is_default`` to ``chat_threads``. The auto-created landing thread has
``is_default = TRUE``; all other threads (free-form general or entity-bound)
keep ``FALSE``. A partial unique index enforces "one default thread per
user" at the DB level so the race can never recur.

Backfill picks the oldest matching general+NULL thread per user as the
default. Existing extra "Nueva conversación" threads stay as regular
free-form generals (the artist can archive them from the UI).

Revision ID: 0015_chat_thread_default
Revises: 0014_inbound_triage
Create Date: 2026-04-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_chat_thread_default"
down_revision = "0014_inbound_triage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_threads",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Backfill: oldest general+NULL thread per user becomes the default.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY id) AS rn
            FROM chat_threads
            WHERE kind = 'general'
              AND entity_type IS NULL
              AND entity_id IS NULL
        )
        UPDATE chat_threads ct
           SET is_default = TRUE
          FROM ranked r
         WHERE ct.id = r.id
           AND r.rn = 1
        """
    )

    # Enforce one default thread per user at the DB layer.
    op.create_index(
        "uq_chat_threads_user_default",
        "chat_threads",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default = TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_chat_threads_user_default", table_name="chat_threads")
    op.drop_column("chat_threads", "is_default")
