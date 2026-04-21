"""Add user_ai_settings.agent_runtime_config JSON overrides."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_agent_runtime_cfg"
down_revision = "0026_ranking_provider_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_ai_settings",
        sa.Column("agent_runtime_config", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_ai_settings", "agent_runtime_config")
