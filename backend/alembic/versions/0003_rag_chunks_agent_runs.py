"""RAG chunks, hybrid search support, agent runs, pending proposals

Revision ID: 0003_rag_agent
Revises: 0002_ai_embeddings
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_rag_agent"
down_revision = "0002_ai_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.UniqueConstraint("entity_type", "entity_id", "chunk_index", name="uq_rag_chunks_entity_chunk"),
    )
    op.execute(sa.text("ALTER TABLE rag_chunks ADD COLUMN embedding vector(1536) NOT NULL"))
    op.create_index("ix_rag_chunks_entity_type", "rag_chunks", ["entity_type"])
    op.create_index("ix_rag_chunks_entity_id", "rag_chunks", ["entity_id"])
    op.create_index("ix_rag_chunks_entity_type_id", "rag_chunks", ["entity_type", "entity_id"])
    op.execute(
        sa.text(
            "CREATE INDEX ix_rag_chunks_embedding_hnsw ON rag_chunks USING hnsw (embedding vector_cosine_ops)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_rag_chunks_content_fts ON rag_chunks USING gin (to_tsvector('english', content))"
        )
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("assistant_reply", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])

    op.create_table(
        "agent_run_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_run_steps_run_id", "agent_run_steps", ["run_id"])

    op.create_table(
        "pending_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("resolution_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pending_proposals_user_id", "pending_proposals", ["user_id"])
    op.create_index("ix_pending_proposals_status", "pending_proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pending_proposals_status", table_name="pending_proposals")
    op.drop_index("ix_pending_proposals_user_id", table_name="pending_proposals")
    op.drop_table("pending_proposals")

    op.drop_index("ix_agent_run_steps_run_id", table_name="agent_run_steps")
    op.drop_table("agent_run_steps")

    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.execute(sa.text("DROP INDEX IF EXISTS ix_rag_chunks_content_fts"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_rag_chunks_embedding_hnsw"))
    op.drop_index("ix_rag_chunks_entity_type_id", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_entity_id", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_entity_type", table_name="rag_chunks")
    op.drop_table("rag_chunks")
