"""Pending proposal summary + connector connections

Revision ID: 0004_pending_summary_connectors
Revises: 0003_rag_agent
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_pending_summary_connectors"
down_revision = "0003_rag_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pending_proposals", sa.Column("summary", sa.String(length=500), nullable=True))
    op.create_table(
        "connector_connections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_connector_connections_user_id", "connector_connections", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_connector_connections_user_id", table_name="connector_connections")
    op.drop_table("connector_connections")
    op.drop_column("pending_proposals", "summary")
