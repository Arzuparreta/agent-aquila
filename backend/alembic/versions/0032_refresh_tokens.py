"""Refresh tokens for secure session management.

Revision ID: 0032_refresh_tokens
Revises: 0031_telegram_ui_integration_cancel_run
Create Date: 2024-04-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision = "0032_refresh_tokens"
down_revision = "0031_telegram_ui_cancel_run"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create refresh_tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token", sa.String(512), unique=True, nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("replaced_by_token", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("refresh_tokens")
