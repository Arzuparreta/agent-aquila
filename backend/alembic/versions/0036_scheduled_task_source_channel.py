"""Add source_channel to scheduled_tasks for delivery routing.

Revision ID: 0036_scheduled_task_source_channel
Revises: 0035_scheduled_task_scheduled_at
Create Date: 2026-04-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_scheduled_task_source_channel"
down_revision = "0035_scheduled_task_scheduled_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_tasks",
        sa.Column("source_channel", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheduled_tasks", "source_channel")