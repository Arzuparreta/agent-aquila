"""Optional separate provider for ranking/auxiliary LLM (classify_model row).

Adds user_ai_settings.ranking_provider_kind. NULL means the same saved row
as the active chat provider is used for auxiliary chat completions.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_ranking_provider_kind"
down_revision = "0025_embedding_provider_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_ai_settings",
        sa.Column("ranking_provider_kind", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_ai_settings", "ranking_provider_kind")
