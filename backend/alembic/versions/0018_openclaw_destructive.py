"""OpenClaw destructive refactor.

Drops every legacy mirror, CRM and notification table; creates the new
``agent_memories`` scratchpad.

Tables dropped (no down-migration is provided — this is a one-way
destructive cut, matching the user-approved plan):

- ``rag_chunks`` (unified semantic index, replaced by per-tool live API
  search + ``agent_memories`` recall).
- ``email_attachments``, ``emails`` (Gmail/Graph mail mirror).
- ``events`` (Calendar mirror).
- ``drive_files`` (Drive/OneDrive mirror).
- ``connection_sync_state`` (per-resource cursor for the deleted sync jobs).
- ``automations`` (rules engine — gone).
- ``push_subscriptions`` (Web Push notifications — gone).
- ``deals``, ``contacts`` (CRM — gone).
- ``executed_actions``, ``attachments`` (auto-apply UNDO + chat file
  uploads — gone with the auto-apply service).

After this migration the only domain tables left are
``users``, ``user_ai_settings``, ``user_ai_provider_configs``,
``connector_connections``, ``instance_oauth_settings``,
``chat_threads``, ``chat_messages``, ``agent_runs``,
``agent_run_steps``, ``audit_logs``, ``pending_proposals`` (now used
only for outbound email approvals) and the new ``agent_memories``.

Revision ID: 0018_openclaw_destructive
Revises: 0017_envelope_encryption
Create Date: 2026-04-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0018_openclaw_destructive"
down_revision = "0017_envelope_encryption"
branch_labels = None
depends_on = None


_LEGACY_TABLES = (
    # Order matters: drop dependents before parents.
    "rag_chunks",
    "email_attachments",
    "emails",
    "events",
    "drive_files",
    "connection_sync_state",
    "automations",
    "push_subscriptions",
    "executed_actions",
    "attachments",
    "deals",
    "contacts",
)


def upgrade() -> None:
    # Drop legacy domain tables. ``IF EXISTS`` guards a forked dev DB
    # that may have skipped some intermediate migrations during the
    # OpenClaw rewrite (e.g. someone applied 0017 then re-cloned).
    for table in _LEGACY_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # Drop columns / FKs the chat tables held into now-deleted tables.
    # ``chat_threads.entity_type`` / ``entity_id`` keep their schema so
    # the column can be reused in the future, but the rows that
    # referenced ``email`` / ``contact`` / ``deal`` / ``event`` are
    # demoted to ``general`` so they don't break the UI.
    op.execute(
        """
        UPDATE chat_threads
           SET kind = 'general', entity_type = NULL, entity_id = NULL
         WHERE entity_type IN ('email', 'contact', 'deal', 'event', 'drive_file', 'attachment')
        """
    )

    # Pending proposals: anything other than email_send/email_reply is
    # obsolete after this migration. Mark them rejected so they don't
    # show up in the queue, then rename the connector_email_send / reply
    # kinds to the new short names.
    op.execute(
        """
        UPDATE pending_proposals
           SET status = 'rejected',
               resolution_note = COALESCE(resolution_note, '') || ' [obsolete after openclaw refactor]'
         WHERE status = 'pending'
           AND kind NOT IN ('connector_email_send', 'email_send', 'email_reply')
        """
    )
    op.execute(
        """
        UPDATE pending_proposals
           SET kind = 'email_send'
         WHERE kind = 'connector_email_send'
        """
    )

    # Remove the FK from chat_messages.agent_run_id only if it still
    # exists; it stays — agent runs survive — but referenced legacy
    # tables (executed_actions, attachments) might have constrained on
    # chat_threads with SET NULL. The CASCADE drop above takes care of
    # those.

    # Create the new ``agent_memories`` scratchpad.
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "importance", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("tags", postgresql.JSON(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("meta", postgresql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "key", name="uq_agent_memories_user_key"),
    )
    op.create_index(
        "ix_agent_memories_user_id", "agent_memories", ["user_id"], unique=False
    )


def downgrade() -> None:
    # Intentionally a no-op. The dropped tables held production data
    # (email mirror, contacts, attachments, …); recreating empty
    # tables would only mask the destructive cut. Restore from a
    # pre-0018 backup if you really need the old schema back.
    op.drop_index("ix_agent_memories_user_id", table_name="agent_memories")
    op.drop_table("agent_memories")
