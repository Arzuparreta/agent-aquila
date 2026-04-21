"""Optional separate provider for embeddings (agent memory).

Adds user_ai_settings.embedding_provider_kind. NULL means embeddings use the
same saved row as chat (active provider).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_embedding_provider_kind"
down_revision = "0024_chat_message_idempotency_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_ai_settings",
        sa.Column("embedding_provider_kind", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_ai_settings", "embedding_provider_kind")
