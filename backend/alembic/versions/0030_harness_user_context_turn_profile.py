"""User context overview cache + agent run turn_profile for harness observability."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_harness_user_context_turn_profile"
down_revision = "0029_user_device_file_ingest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_ai_settings",
        sa.Column("agent_context_overview", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_ai_settings",
        sa.Column("agent_context_overview_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "turn_profile",
            sa.String(length=32),
            nullable=False,
            server_default="user_chat",
        ),
    )
    op.alter_column("agent_runs", "turn_profile", server_default=None)


def downgrade() -> None:
    op.drop_column("agent_runs", "turn_profile")
    op.drop_column("user_ai_settings", "agent_context_overview_updated_at")
    op.drop_column("user_ai_settings", "agent_context_overview")
