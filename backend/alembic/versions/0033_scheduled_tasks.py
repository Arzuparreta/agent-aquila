"""User-defined recurring scheduled tasks.

Revision ID: 0033_scheduled_tasks
Revises: 0032_refresh_tokens
Create Date: 2026-04-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_scheduled_tasks"
down_revision = "0032_refresh_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("schedule_type", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=128), nullable=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("hour_local", sa.Integer(), nullable=True),
        sa.Column("minute_local", sa.Integer(), nullable=True),
        sa.Column("weekdays", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            server_onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_scheduled_tasks_user_id", "scheduled_tasks", ["user_id"], unique=False)
    op.create_index("ix_scheduled_tasks_next_run_at", "scheduled_tasks", ["next_run_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scheduled_tasks_next_run_at", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_user_id", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")
