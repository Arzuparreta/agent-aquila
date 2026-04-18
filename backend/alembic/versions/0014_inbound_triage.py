"""Add triage columns to emails and events.

Tracks the verdict of ``InboundFilterService`` so the proactive layer only
fires on ``actionable`` items and the artist can later review/promote what
was silenced.

Revision ID: 0014_inbound_triage
Revises: 0013_email_attachment_id_text
Create Date: 2026-04-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0014_inbound_triage"
down_revision = "0013_email_attachment_id_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("emails", "events"):
        op.add_column(
            table,
            sa.Column("triage_category", sa.String(length=16), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("triage_reason", sa.String(length=255), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("triage_source", sa.String(length=16), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("triage_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            f"ix_{table}_triage_category",
            table,
            ["triage_category"],
        )


def downgrade() -> None:
    for table in ("emails", "events"):
        op.drop_index(f"ix_{table}_triage_category", table_name=table)
        op.drop_column(table, "triage_at")
        op.drop_column(table, "triage_source")
        op.drop_column(table, "triage_reason")
        op.drop_column(table, "triage_category")
