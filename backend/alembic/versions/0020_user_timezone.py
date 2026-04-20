"""User timezone + clock display preference for agent date/time context."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_user_timezone"
down_revision = "0019_agent_harness_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_ai_settings",
        sa.Column("user_timezone", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "user_ai_settings",
        sa.Column(
            "time_format",
            sa.String(length=8),
            nullable=False,
            server_default="auto",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_ai_settings", "time_format")
    op.drop_column("user_ai_settings", "user_timezone")
