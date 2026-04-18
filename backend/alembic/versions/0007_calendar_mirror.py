"""Calendar mirror: provider metadata on events table

Revision ID: 0007_calendar_mirror
Revises: 0006_gmail_mirror
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_calendar_mirror"
down_revision = "0006_gmail_mirror"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("connection_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_events_connection_id",
        "events",
        "connector_connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_events_connection_id", "events", ["connection_id"], unique=False)
    op.add_column(
        "events",
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="manual"),
    )
    op.create_index("ix_events_provider", "events", ["provider"], unique=False)
    op.add_column("events", sa.Column("provider_event_id", sa.String(length=255), nullable=True))
    op.create_index("ix_events_provider_event_id", "events", ["provider_event_id"], unique=False)
    op.add_column("events", sa.Column("provider_calendar_id", sa.String(length=255), nullable=True))
    op.add_column("events", sa.Column("ical_uid", sa.String(length=255), nullable=True))
    op.create_index("ix_events_ical_uid", "events", ["ical_uid"], unique=False)
    op.create_unique_constraint(
        "uq_events_connection_provider_event",
        "events",
        ["connection_id", "provider_event_id"],
    )
    op.add_column("events", sa.Column("summary", sa.String(length=500), nullable=True))
    op.add_column("events", sa.Column("location", sa.String(length=500), nullable=True))
    op.add_column("events", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("html_link", sa.String(length=1024), nullable=True))
    op.add_column("events", sa.Column("attendees", sa.JSON(), nullable=True))
    op.add_column("events", sa.Column("recurrence", sa.JSON(), nullable=True))
    op.add_column("events", sa.Column("start_utc", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_events_start_utc", "events", ["start_utc"], unique=False)
    op.add_column("events", sa.Column("end_utc", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("all_day", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "all_day")
    op.drop_column("events", "end_utc")
    op.drop_index("ix_events_start_utc", table_name="events")
    op.drop_column("events", "start_utc")
    op.drop_column("events", "recurrence")
    op.drop_column("events", "attendees")
    op.drop_column("events", "html_link")
    op.drop_column("events", "description")
    op.drop_column("events", "location")
    op.drop_column("events", "summary")
    op.drop_constraint("uq_events_connection_provider_event", "events", type_="unique")
    op.drop_index("ix_events_ical_uid", table_name="events")
    op.drop_column("events", "ical_uid")
    op.drop_column("events", "provider_calendar_id")
    op.drop_index("ix_events_provider_event_id", table_name="events")
    op.drop_column("events", "provider_event_id")
    op.drop_index("ix_events_provider", table_name="events")
    op.drop_column("events", "provider")
    op.drop_index("ix_events_connection_id", table_name="events")
    op.drop_constraint("fk_events_connection_id", "events", type_="foreignkey")
    op.drop_column("events", "connection_id")
