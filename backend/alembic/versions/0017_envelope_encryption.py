"""Re-wrap legacy single-key Fernet API keys into envelope form.

Reads each ``user_ai_provider_configs`` row whose ``api_key_ciphertext`` was
copied verbatim from the legacy ``user_ai_settings.api_key_encrypted`` (i.e.
encrypted with the legacy single-key Fernet derived from
``FERNET_ENCRYPTION_KEY`` or the ``JWT_SECRET`` fallback). For each one:

1. Decrypt with the legacy helper.
2. Generate a fresh per-row DEK.
3. Wrap the DEK with the current envelope KEK.
4. Encrypt the plaintext API key with the DEK.
5. Write ``wrapped_dek`` + ``api_key_ciphertext`` (overwriting the legacy
   blob with envelope ciphertext).

Rows whose legacy decryption fails (KEK rotated without setting
``FERNET_ENCRYPTION_KEY``) are NULLed and logged so the user gets a clear
"please re-enter your key" prompt instead of silently broken behaviour.

Downgrade is intentionally a no-op (decrypting back to legacy form would
require holding the plaintext to re-encrypt with the legacy key, which is
the exact state we just left). To revert, restore from a backup.

Revision ID: 0017_envelope_encryption
Revises: 0016_ai_provider_configs
Create Date: 2026-04-19
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op


revision = "0017_envelope_encryption"
down_revision = "0016_ai_provider_configs"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.envelope_encryption")


def upgrade() -> None:
    # Late import: alembic loads migration modules at startup; importing app
    # code at module load time would force the whole app to import before
    # the DB schema is ready. Importing inside upgrade() is fine.
    from app.core.crypto import decrypt_secret_strict
    from app.core.envelope_crypto import encrypt_value, kek_source
    from cryptography.fernet import InvalidToken

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, user_id, provider_kind, api_key_ciphertext "
            "FROM user_ai_provider_configs "
            "WHERE api_key_ciphertext IS NOT NULL AND wrapped_dek IS NULL"
        )
    ).mappings().all()

    if not rows:
        logger.info("No legacy AI keys to re-wrap (KEK source: %s).", kek_source())
        return

    logger.info(
        "Re-wrapping %d legacy AI key(s) into envelope form (KEK source: %s).",
        len(rows),
        kek_source(),
    )

    rewrapped = 0
    cleared = 0
    for row in rows:
        row_id = int(row["id"])
        scope = f"user={row['user_id']} provider={row['provider_kind']}"
        try:
            plaintext = decrypt_secret_strict(row["api_key_ciphertext"])
        except InvalidToken:
            logger.warning(
                "Legacy ciphertext for %s could not be decrypted with the current KEK; "
                "clearing it. The user will be prompted to re-enter the API key.",
                scope,
            )
            bind.execute(
                sa.text(
                    "UPDATE user_ai_provider_configs "
                    "SET api_key_ciphertext = NULL, wrapped_dek = NULL, "
                    "    updated_at = now() "
                    "WHERE id = :id"
                ),
                {"id": row_id},
            )
            cleared += 1
            continue

        wrapped_dek, ciphertext = encrypt_value(plaintext)
        bind.execute(
            sa.text(
                "UPDATE user_ai_provider_configs "
                "SET wrapped_dek = :wrapped_dek, "
                "    api_key_ciphertext = :ciphertext, "
                "    updated_at = now() "
                "WHERE id = :id"
            ),
            {"wrapped_dek": wrapped_dek, "ciphertext": ciphertext, "id": row_id},
        )
        rewrapped += 1

    logger.info(
        "Envelope rewrap complete: %d rewrapped, %d cleared (need user re-entry).",
        rewrapped,
        cleared,
    )


def downgrade() -> None:
    # Reverting envelope -> legacy direct Fernet would require holding every
    # plaintext key in memory to re-encrypt with the legacy single key, which
    # defeats the security point. Restore from a backup if you really need to
    # roll back. The schema columns themselves stay (they're useful even with
    # only legacy ciphertexts present).
    pass
