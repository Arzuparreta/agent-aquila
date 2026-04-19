"""Add harness_mode to user_ai_settings (native / prompted tool calling)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_agent_harness_mode"
down_revision = "0018_openclaw_destructive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_ai_settings",
        sa.Column(
            "harness_mode",
            sa.String(length=16),
            nullable=False,
            server_default="auto",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_ai_settings", "harness_mode")
