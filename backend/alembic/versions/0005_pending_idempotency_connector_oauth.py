"""Pending idempotency + connector OAuth metadata

Revision ID: 0005_pending_oauth
Revises: 0004_pending_summary_connectors
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_pending_oauth"
down_revision = "0004_pending_summary_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pending_proposals", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.create_index(
        "uq_pending_proposals_user_idempotency",
        "pending_proposals",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.add_column(
        "connector_connections",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("connector_connections", sa.Column("oauth_scopes", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("connector_connections", "oauth_scopes")
    op.drop_column("connector_connections", "token_expires_at")
    op.drop_index("uq_pending_proposals_user_idempotency", table_name="pending_proposals")
    op.drop_column("pending_proposals", "idempotency_key")
