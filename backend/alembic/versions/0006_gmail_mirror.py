"""Gmail mirror: emails provider columns, email_attachments, connection_sync_state

Revision ID: 0006_gmail_mirror
Revises: 0005_pending_oauth
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_gmail_mirror"
down_revision = "0005_pending_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "emails",
        sa.Column("connection_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_emails_connection_id",
        "emails",
        "connector_connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_emails_connection_id", "emails", ["connection_id"], unique=False)

    op.add_column(
        "emails",
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="manual"),
    )
    op.create_index("ix_emails_provider", "emails", ["provider"], unique=False)

    op.add_column("emails", sa.Column("provider_message_id", sa.String(length=255), nullable=True))
    op.create_index("ix_emails_provider_message_id", "emails", ["provider_message_id"], unique=False)

    op.add_column("emails", sa.Column("provider_thread_id", sa.String(length=255), nullable=True))
    op.create_index("ix_emails_provider_thread_id", "emails", ["provider_thread_id"], unique=False)

    op.create_unique_constraint(
        "uq_emails_connection_provider_msg",
        "emails",
        ["connection_id", "provider_message_id"],
    )

    op.add_column(
        "emails",
        sa.Column("direction", sa.String(length=16), nullable=False, server_default="inbound"),
    )
    op.add_column("emails", sa.Column("labels", sa.JSON(), nullable=True))
    op.add_column("emails", sa.Column("in_reply_to", sa.String(length=500), nullable=True))
    op.add_column("emails", sa.Column("snippet", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("body_html", sa.Text(), nullable=True))
    op.add_column("emails", sa.Column("internal_date", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_emails_internal_date", "emails", ["internal_date"], unique=False)
    op.add_column(
        "emails",
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "email_attachments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email_id", sa.Integer(), nullable=False),
        sa.Column("provider_attachment_id", sa.String(length=255), nullable=True),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_attachments_email_id", "email_attachments", ["email_id"], unique=False)

    op.create_table(
        "connection_sync_state",
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("resource", sa.String(length=32), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column("last_full_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delta_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.PrimaryKeyConstraint("connection_id", "resource", name="pk_connection_sync_state"),
    )


def downgrade() -> None:
    op.drop_table("connection_sync_state")
    op.drop_index("ix_email_attachments_email_id", table_name="email_attachments")
    op.drop_table("email_attachments")
    op.drop_column("emails", "is_read")
    op.drop_index("ix_emails_internal_date", table_name="emails")
    op.drop_column("emails", "internal_date")
    op.drop_column("emails", "body_html")
    op.drop_column("emails", "snippet")
    op.drop_column("emails", "in_reply_to")
    op.drop_column("emails", "labels")
    op.drop_column("emails", "direction")
    op.drop_constraint("uq_emails_connection_provider_msg", "emails", type_="unique")
    op.drop_index("ix_emails_provider_thread_id", table_name="emails")
    op.drop_column("emails", "provider_thread_id")
    op.drop_index("ix_emails_provider_message_id", table_name="emails")
    op.drop_column("emails", "provider_message_id")
    op.drop_index("ix_emails_provider", table_name="emails")
    op.drop_column("emails", "provider")
    op.drop_index("ix_emails_connection_id", table_name="emails")
    op.drop_constraint("fk_emails_connection_id", "emails", type_="foreignkey")
    op.drop_column("emails", "connection_id")
