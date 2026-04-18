"""Widen email_attachments.provider_attachment_id from VARCHAR(255) to TEXT.

Gmail and Microsoft Graph return opaque base64 attachment ids that routinely
exceed 255 characters (700+ chars observed in the wild). With the original
column width the Gmail delta sync would crash mid-batch with
``StringDataRightTruncationError`` and the entire transaction would roll
back, so the worker silently stopped persisting *any* messages from that
account. Using TEXT removes the upper bound so future provider id changes
can never reintroduce this failure mode.

Revision ID: 0013_email_attachment_id_text
Revises: 0012_chat_artist_rework
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_email_attachment_id_text"
down_revision = "0012_chat_artist_rework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "email_attachments",
        "provider_attachment_id",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "email_attachments",
        "provider_attachment_id",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
