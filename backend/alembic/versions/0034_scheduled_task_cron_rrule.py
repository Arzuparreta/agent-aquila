"""Add cron/rrule schedule fields to scheduled_tasks.

Revision ID: 0034_scheduled_task_cron_rrule
Revises: 0033_scheduled_tasks
Create Date: 2026-04-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_scheduled_task_cron_rrule"
down_revision = "0033_scheduled_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scheduled_tasks", sa.Column("cron_expr", sa.String(length=256), nullable=True))
    op.add_column("scheduled_tasks", sa.Column("rrule_expr", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("scheduled_tasks", "rrule_expr")
    op.drop_column("scheduled_tasks", "cron_expr")
