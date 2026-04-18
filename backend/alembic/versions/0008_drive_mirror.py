"""Drive mirror: drive_files table

Revision ID: 0008_drive_mirror
Revises: 0007_calendar_mirror
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0008_drive_mirror"
down_revision = "0007_calendar_mirror"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drive_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="google_drive"),
        sa.Column("provider_file_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("parents", sa.JSON(), nullable=True),
        sa.Column("owners", sa.JSON(), nullable=True),
        sa.Column("web_view_link", sa.String(length=1024), nullable=True),
        sa.Column("modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_trashed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_text_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["connection_id"], ["connector_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "provider_file_id", name="uq_drive_files_connection_provider_file"
        ),
    )
    op.create_index("ix_drive_files_connection_id", "drive_files", ["connection_id"], unique=False)
    op.create_index("ix_drive_files_provider_file_id", "drive_files", ["provider_file_id"], unique=False)
    op.create_index("ix_drive_files_mime_type", "drive_files", ["mime_type"], unique=False)
    op.create_index("ix_drive_files_modified_time", "drive_files", ["modified_time"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_drive_files_modified_time", table_name="drive_files")
    op.drop_index("ix_drive_files_mime_type", table_name="drive_files")
    op.drop_index("ix_drive_files_provider_file_id", table_name="drive_files")
    op.drop_index("ix_drive_files_connection_id", table_name="drive_files")
    op.drop_table("drive_files")
