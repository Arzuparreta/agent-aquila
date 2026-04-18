"""Instance-level Google OAuth app credentials (UI-configurable).

Revision ID: 0010_instance_oauth_settings
Revises: 0009_automations
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_instance_oauth_settings"
down_revision = "0009_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instance_oauth_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("google_oauth_client_id", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("google_oauth_client_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("google_oauth_redirect_base", sa.String(length=1024), nullable=False, server_default=""),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(sa.text("INSERT INTO instance_oauth_settings (id) VALUES (1)"))
    op.alter_column("instance_oauth_settings", "google_oauth_client_id", server_default=None)
    op.alter_column("instance_oauth_settings", "google_oauth_redirect_base", server_default=None)


def downgrade() -> None:
    op.drop_table("instance_oauth_settings")
