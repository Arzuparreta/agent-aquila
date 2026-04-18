"""User AI settings and embedding columns

Revision ID: 0002_ai_embeddings
Revises: 0001_initial
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_ai_embeddings"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_ai_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_kind", sa.String(length=32), nullable=False, server_default="openai_compatible"),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=False, server_default="text-embedding-3-small"),
        sa.Column("chat_model", sa.String(length=128), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("classify_model", sa.String(length=128), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("extras", sa.JSON(), nullable=True),
        sa.Column("ai_disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_ai_settings_id", "user_ai_settings", ["id"])
    op.create_index("uq_user_ai_settings_user_id", "user_ai_settings", ["user_id"], unique=True)

    for table in ("contacts", "emails", "deals", "events"):
        op.add_column(table, sa.Column("embedding_model", sa.String(length=128), nullable=True))
        op.add_column(table, sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN embedding vector(1536)"))


def downgrade() -> None:
    for table in ("events", "deals", "emails", "contacts"):
        op.drop_column(table, "embedding")
        op.drop_column(table, "embedding_updated_at")
        op.drop_column(table, "embedding_model")

    op.drop_index("uq_user_ai_settings_user_id", table_name="user_ai_settings")
    op.drop_index("ix_user_ai_settings_id", table_name="user_ai_settings")
    op.drop_table("user_ai_settings")
