"""Multi-provider AI configs.

Splits the previous single-row-per-user ``user_ai_settings`` into:

- ``user_ai_provider_configs``: one row per ``(user_id, provider_kind)``
  holding the provider-specific config (base_url, models, extras) and the
  envelope-encrypted API key (``wrapped_dek`` + ``api_key_ciphertext``).
- ``user_ai_settings`` keeps user-level prefs and gains
  ``active_provider_kind`` (the pointer the agent loop reads). The legacy
  per-provider columns (``provider_kind``, ``base_url``, models, ``extras``,
  ``api_key_encrypted``) are kept and continuously mirrored from the
  active config so existing call sites keep working until they're migrated.

The legacy ``api_key_encrypted`` blob is left untouched here; migration
``0017_envelope_encryption`` re-wraps it into envelope form.

Revision ID: 0016_ai_provider_configs
Revises: 0015_chat_thread_default
Create Date: 2026-04-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0016_ai_provider_configs"
down_revision = "0015_chat_thread_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_ai_provider_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_kind", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column(
            "chat_model",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "embedding_model",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column("classify_model", sa.String(length=128), nullable=True),
        sa.Column("extras", sa.JSON(), nullable=True),
        sa.Column("wrapped_dek", sa.Text(), nullable=True),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_message", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_user_ai_provider_configs_user_kind",
        "user_ai_provider_configs",
        ["user_id", "provider_kind"],
        unique=True,
    )

    op.add_column(
        "user_ai_settings",
        sa.Column("active_provider_kind", sa.String(length=32), nullable=True),
    )

    # Backfill: seed user_ai_provider_configs from each existing user_ai_settings row.
    # The legacy api_key_encrypted is copied over verbatim into api_key_ciphertext;
    # 0017 will re-wrap it into envelope form (wrapped_dek + ciphertext) so the
    # current ciphertext is decryptable while in this transitional state.
    op.execute(
        """
        INSERT INTO user_ai_provider_configs (
            user_id, provider_kind, base_url, chat_model, embedding_model,
            classify_model, extras, api_key_ciphertext,
            created_at, updated_at
        )
        SELECT user_id,
               COALESCE(NULLIF(provider_kind, ''), 'openai'),
               base_url,
               COALESCE(NULLIF(chat_model, ''), ''),
               COALESCE(NULLIF(embedding_model, ''), ''),
               classify_model,
               extras,
               api_key_encrypted,
               COALESCE(created_at, now()),
               COALESCE(updated_at, now())
        FROM user_ai_settings
        ON CONFLICT (user_id, provider_kind) DO NOTHING
        """
    )

    op.execute(
        """
        UPDATE user_ai_settings
           SET active_provider_kind = COALESCE(NULLIF(provider_kind, ''), 'openai')
         WHERE active_provider_kind IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("user_ai_settings", "active_provider_kind")
    op.drop_index(
        "uq_user_ai_provider_configs_user_kind",
        table_name="user_ai_provider_configs",
    )
    op.drop_table("user_ai_provider_configs")
