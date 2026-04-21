"""Agent user events outbox for WebSocket / audit."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_agent_user_events"
down_revision = "0027_agent_runtime_cfg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_user_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_user_events_user_id", "agent_user_events", ["user_id"], unique=False)
    op.create_index("ix_agent_user_events_run_id", "agent_user_events", ["run_id"], unique=False)
    op.create_index("ix_agent_user_events_created_at", "agent_user_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_user_events_created_at", table_name="agent_user_events")
    op.drop_index("ix_agent_user_events_run_id", table_name="agent_user_events")
    op.drop_index("ix_agent_user_events_user_id", table_name="agent_user_events")
    op.drop_table("agent_user_events")
