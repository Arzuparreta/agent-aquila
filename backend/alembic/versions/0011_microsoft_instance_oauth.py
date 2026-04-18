"""Microsoft OAuth app credentials on instance_oauth_settings.

Revision ID: 0011_microsoft_instance_oauth
Revises: 0010_instance_oauth_settings
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_microsoft_instance_oauth"
down_revision = "0010_instance_oauth_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "instance_oauth_settings",
        sa.Column("microsoft_oauth_client_id", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "instance_oauth_settings",
        sa.Column("microsoft_oauth_client_secret_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "instance_oauth_settings",
        sa.Column("microsoft_oauth_tenant", sa.String(length=64), nullable=False, server_default=""),
    )
    op.alter_column("instance_oauth_settings", "microsoft_oauth_client_id", server_default=None)
    op.alter_column("instance_oauth_settings", "microsoft_oauth_tenant", server_default=None)


def downgrade() -> None:
    op.drop_column("instance_oauth_settings", "microsoft_oauth_tenant")
    op.drop_column("instance_oauth_settings", "microsoft_oauth_client_secret_encrypted")
    op.drop_column("instance_oauth_settings", "microsoft_oauth_client_id")
