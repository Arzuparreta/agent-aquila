"""Telegram bot token in user settings + run cancellation flag.

Revision ID: 0031_telegram_ui_integration_cancel_run
Revises: 0030_harness_user_context_turn_profile
Create Date: 2026-04-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_telegram_ui_integration_cancel_run"
down_revision = "0030_harness_user_context_turn_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_ai_settings",
        sa.Column("telegram_bot_token_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_ai_settings",
        sa.Column(
            "telegram_polling_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "user_ai_settings",
        sa.Column(
            "telegram_poll_timeout",
            sa.Integer(),
            nullable=False,
            server_default="45",
        ),
    )
    op.add_column(
        "user_ai_settings",
        sa.Column("telegram_webhook_secret", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "cancel_requested")
    op.drop_column("user_ai_settings", "telegram_webhook_secret")
    op.drop_column("user_ai_settings", "telegram_poll_timeout")
    op.drop_column("user_ai_settings", "telegram_polling_enabled")
    op.drop_column("user_ai_settings", "telegram_bot_token_encrypted")
