"""Add is_admin column to users table.

Revision ID: 0037_user_is_admin
Revises: 0036_scheduled_task_src_channel
Create Date: 2026-04-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_user_is_admin"
down_revision = "0036_scheduled_task_src_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
