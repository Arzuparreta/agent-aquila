"""Chat message idempotency token.

Stores a client-generated token so retried send/retry HTTP requests can be
deduplicated safely.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_chat_message_idempotency_token"
down_revision = "0023_telegram_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("client_token", sa.String(length=128), nullable=True))
    op.create_index("ix_chat_messages_client_token", "chat_messages", ["client_token"])
    op.create_index(
        "uq_chat_messages_thread_client_token",
        "chat_messages",
        ["thread_id", "client_token"],
        unique=True,
        postgresql_where=sa.text("client_token IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_chat_messages_thread_client_token", table_name="chat_messages")
    op.drop_index("ix_chat_messages_client_token", table_name="chat_messages")
    op.drop_column("chat_messages", "client_token")
