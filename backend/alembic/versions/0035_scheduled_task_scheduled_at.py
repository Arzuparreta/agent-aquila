"""Add scheduled_at for one-time tasks.

Revision ID: 0035_scheduled_task_scheduled_at
Revises: 0034_scheduled_task_cron_rrule
Create Date: 2026-04-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_scheduled_task_scheduled_at"
down_revision = "0034_scheduled_task_cron_rrule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_tasks",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheduled_tasks", "scheduled_at")