"""Telegram pairing codes and account links."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_telegram_channel"
down_revision = "0022_user_ai_agent_processing_paused"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_pairing_codes",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index("ix_telegram_pairing_codes_user_id", "telegram_pairing_codes", ["user_id"])

    op.create_table(
        "telegram_account_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_chat_id"),
    )
    op.create_index("ix_telegram_account_links_user_id", "telegram_account_links", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_account_links_user_id", table_name="telegram_account_links")
    op.drop_table("telegram_account_links")
    op.drop_index("ix_telegram_pairing_codes_user_id", table_name="telegram_pairing_codes")
    op.drop_table("telegram_pairing_codes")
