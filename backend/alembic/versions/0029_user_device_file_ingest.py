"""Device file ingests (Shortcuts / bridge Track A)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_user_device_file_ingest"
down_revision = "0028_agent_user_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_device_file_ingests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("path_hint", sa.String(length=1024), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("sha256_hex", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_device_file_ingests_user_id", "user_device_file_ingests", ["user_id"], unique=False)
    op.create_index("ix_user_device_file_ingests_sha256_hex", "user_device_file_ingests", ["sha256_hex"], unique=False)
    op.create_index(
        "ix_user_device_file_ingests_created_at", "user_device_file_ingests", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_user_device_file_ingests_created_at", table_name="user_device_file_ingests")
    op.drop_index("ix_user_device_file_ingests_sha256_hex", table_name="user_device_file_ingests")
    op.drop_index("ix_user_device_file_ingests_user_id", table_name="user_device_file_ingests")
    op.drop_table("user_device_file_ingests")
