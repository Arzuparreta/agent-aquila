"""Automations table: user-defined rules that trigger agent runs on inbound events.

Revision ID: 0009_automations
Revises: 0008_drive_mirror
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_automations"
down_revision = "0008_drive_mirror"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("trigger", sa.String(length=64), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("prompt_template", sa.String(length=8000), nullable=False),
        sa.Column("default_connection_id", sa.Integer(), nullable=True),
        sa.Column("auto_approve", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["default_connection_id"], ["connector_connections.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automations_user_id", "automations", ["user_id"], unique=False)
    op.create_index("ix_automations_trigger", "automations", ["trigger"], unique=False)
    op.create_index("ix_automations_enabled", "automations", ["enabled"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_automations_enabled", table_name="automations")
    op.drop_index("ix_automations_trigger", table_name="automations")
    op.drop_index("ix_automations_user_id", table_name="automations")
    op.drop_table("automations")
