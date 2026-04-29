"""Agent trace events, run correlation IDs, channel thread bindings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_traces_channel_bindings"
down_revision = "0020_user_timezone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("root_trace_id", sa.String(length=32), nullable=True))
    op.add_column("agent_runs", sa.Column("chat_thread_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_agent_runs_chat_thread_id",
        "agent_runs",
        "chat_threads",
        ["chat_thread_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agent_runs_root_trace_id", "agent_runs", ["root_trace_id"])
    op.create_index("ix_agent_runs_chat_thread_id", "agent_runs", ["chat_thread_id"])

    op.create_table(
        "agent_trace_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=True),
        sa.Column("parent_span_id", sa.String(length=16), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_trace_events_run_id", "agent_trace_events", ["run_id"])
    op.create_index("ix_agent_trace_events_trace_id", "agent_trace_events", ["trace_id"])
    op.create_index("ix_agent_trace_events_event_type", "agent_trace_events", ["event_type"])

    op.create_table(
        "channel_thread_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("external_key", sa.String(length=512), nullable=False),
        sa.Column("chat_thread_id", sa.Integer(), sa.ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "channel", "external_key", name="uq_channel_thread_binding_user_channel_key"),
    )
    op.create_index("ix_channel_thread_bindings_user_id", "channel_thread_bindings", ["user_id"])
    op.create_index("ix_channel_thread_bindings_chat_thread_id", "channel_thread_bindings", ["chat_thread_id"])


def downgrade() -> None:
    op.drop_constraint("fk_agent_runs_chat_thread_id", "agent_runs", type_="foreignkey")
    op.drop_index("ix_channel_thread_bindings_chat_thread_id", table_name="channel_thread_bindings")
    op.drop_index("ix_channel_thread_bindings_user_id", table_name="channel_thread_bindings")
    op.drop_table("channel_thread_bindings")

    op.drop_index("ix_agent_trace_events_event_type", table_name="agent_trace_events")
    op.drop_index("ix_agent_trace_events_trace_id", table_name="agent_trace_events")
    op.drop_index("ix_agent_trace_events_run_id", table_name="agent_trace_events")
    op.drop_table("agent_trace_events")

    op.drop_index("ix_agent_runs_chat_thread_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_root_trace_id", table_name="agent_runs")
    op.drop_column("agent_runs", "chat_thread_id")
    op.drop_column("agent_runs", "root_trace_id")
