"""Pause agent processing flag on user_ai_settings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_user_ai_processing_paused"
down_revision = "0021_traces_channel_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_ai_settings",
        sa.Column("agent_processing_paused", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("user_ai_settings", "agent_processing_paused")
