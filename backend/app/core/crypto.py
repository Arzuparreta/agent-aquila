"""Legacy single-key Fernet helpers + thin shim around envelope encryption.

The original :func:`encrypt_secret` / :func:`decrypt_secret` API is kept for
non-AI secrets that haven't been migrated yet (Microsoft tokens, Google
OAuth client secret, etc.). New AI-provider secrets go through
:mod:`app.core.envelope_crypto` which provides per-row DEKs + a typed
``KeyDecryptError`` so failures surface loudly instead of silently
returning ``None``.

The legacy ``decrypt_secret_strict`` variant raises on failure and is used
by the data-migration that re-wraps existing AI keys into envelope form.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _legacy_fernet() -> Fernet:
    """Direct Fernet using ``FERNET_ENCRYPTION_KEY`` or the JWT-derived fallback.

    The fallback is deterministic for a given ``JWT_SECRET`` so existing
    legacy ciphertexts keep decrypting until they're re-wrapped into
    envelope form by the 0017 migration.
    """
    if settings.fernet_encryption_key:
        key = settings.fernet_encryption_key.encode("utf-8")
    else:
        digest = hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plain: str | None) -> str | None:
    """Legacy single-key encrypt. Prefer :func:`app.core.envelope_crypto.encrypt_value`."""
    if plain is None or plain == "":
        return None
    return _legacy_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(blob: str | None) -> str | None:
    """Legacy single-key decrypt. Returns ``None`` on failure (silent).

    Kept for callers that already tolerate the silent-None semantics. New
    code should use :func:`app.core.envelope_crypto.decrypt_value` which
    raises a typed error.
    """
    if not blob:
        return None
    try:
        return _legacy_fernet().decrypt(blob.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def decrypt_secret_strict(blob: str) -> str:
    """Legacy decrypt that raises ``InvalidToken`` on failure.

    Used by :mod:`alembic.versions.0017_envelope_encryption` so the data
    migration can tell apart "row had no key" from "row had a key but the
    KEK has changed" and react appropriately.
    """
    return _legacy_fernet().decrypt(blob.encode("utf-8")).decode("utf-8")
