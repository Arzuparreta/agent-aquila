"""Envelope encryption for at-rest secrets (API keys, OAuth tokens).

Why envelope, not direct Fernet?
--------------------------------
The previous design (``app.core.crypto``) encrypted every secret directly
with a single key derived from ``JWT_SECRET``. That had two failure modes:

1. Rotating ``JWT_SECRET`` without setting ``FERNET_ENCRYPTION_KEY`` would
   silently invalidate every stored ciphertext (``decrypt_secret`` returns
   ``None`` on ``InvalidToken``). Users see "my key disappeared".
2. There is no way to re-key the database without holding plaintext for
   every row in memory simultaneously.

Envelope encryption splits the problem:

- The **KEK** (key-encryption key) is the long-lived root key. It lives in
  ``FERNET_ENCRYPTION_KEY`` (env), or a sibling file
  (``backend/.secrets/fernet.key``, gitignored), or is auto-generated to
  that file on first boot. Only the KEK itself is sensitive in the env
  layer — losing it is the only way ciphertexts become unreadable.
- Each secret gets its own per-row **DEK** (data-encryption key). The DEK
  encrypts the secret. The KEK encrypts the DEK and the wrapped DEK is
  stored beside the ciphertext.
- Rotating the KEK becomes a small, atomic operation: re-wrap each DEK
  with the new KEK in a single transaction. The actual ciphertexts are
  never touched.

Decryption errors are now LOUD: callers receive a typed
``KeyDecryptError`` with the affected scope so the UI can prompt the user
to re-enter the key (instead of silently behaving as keyless and looking
like the data has vanished).
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)


class KeyDecryptError(RuntimeError):
    """Raised when a stored ciphertext cannot be decrypted with the current KEK.

    ``scope`` is a human-readable label (e.g. ``"user=1 provider=ollama"``)
    used by routes to translate this into a clear UI message. ``reason``
    is the underlying cryptography error class name for logs.
    """

    def __init__(self, *, scope: str, reason: str) -> None:
        super().__init__(f"Could not decrypt secret for {scope}: {reason}")
        self.scope = scope
        self.reason = reason


# ---------------------------------------------------------------------------
# KEK loading + caching
# ---------------------------------------------------------------------------

# Default location for the auto-generated KEK file. Resolved relative to the
# repo's backend root so it survives container restarts when mounted as a
# named volume (see docker-compose.yml).
_DEFAULT_KEK_FILE = Path(__file__).resolve().parents[2] / ".secrets" / "fernet.key"

_KEK_LOCK = threading.Lock()
_KEK_CACHE: Fernet | None = None
_KEK_SOURCE: str | None = None


def _kek_file_path() -> Path:
    """Resolve the on-disk KEK path. Override with ``FERNET_KEY_FILE`` for tests."""
    override = os.environ.get("FERNET_KEY_FILE")
    if override:
        return Path(override).expanduser()
    return _DEFAULT_KEK_FILE


def _read_kek_from_file(path: Path) -> str | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    return raw or None


def _persist_kek_to_file(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.warning("Could not chmod 600 the KEK file at %s; check filesystem permissions.", path)


def load_kek() -> Fernet:
    """Resolve the KEK, in priority order:

    1. ``settings.fernet_encryption_key`` (env var ``FERNET_ENCRYPTION_KEY``).
    2. The on-disk file ``backend/.secrets/fernet.key`` (or
       ``$FERNET_KEY_FILE`` if set).
    3. Generate a new key, persist it to the file, log a loud WARNING.

    Cached for the lifetime of the process.
    """
    global _KEK_CACHE, _KEK_SOURCE
    if _KEK_CACHE is not None:
        return _KEK_CACHE
    with _KEK_LOCK:
        if _KEK_CACHE is not None:
            return _KEK_CACHE
        env_key = (settings.fernet_encryption_key or "").strip()
        if env_key:
            _KEK_CACHE = Fernet(env_key.encode("utf-8"))
            _KEK_SOURCE = "env"
            return _KEK_CACHE
        path = _kek_file_path()
        file_key = _read_kek_from_file(path)
        if file_key:
            _KEK_CACHE = Fernet(file_key.encode("utf-8"))
            _KEK_SOURCE = f"file:{path}"
            return _KEK_CACHE
        # Auto-generate. This is the path a brand-new install hits.
        new_key = Fernet.generate_key().decode("utf-8")
        try:
            _persist_kek_to_file(path, new_key)
            _KEK_SOURCE = f"file:{path}(generated)"
            logger.warning(
                "FERNET_ENCRYPTION_KEY not set; generated a new KEK and persisted it to %s. "
                "Back this file up — losing it makes every stored API key unrecoverable. "
                "Mount it as a docker volume so it survives container rebuilds.",
                path,
            )
        except OSError as exc:
            _KEK_SOURCE = "memory(transient)"
            logger.error(
                "FERNET_ENCRYPTION_KEY not set AND could not write the KEK file (%s: %s). "
                "Falling back to a process-local key — every restart will invalidate stored secrets! "
                "Set FERNET_ENCRYPTION_KEY in .env to a stable Fernet key.",
                path,
                exc,
            )
        _KEK_CACHE = Fernet(new_key.encode("utf-8"))
        return _KEK_CACHE


def kek_source() -> str:
    """Where the current KEK came from (``env``, ``file:...``, ``memory(...)``)."""
    if _KEK_SOURCE is None:
        load_kek()
    return _KEK_SOURCE or "unknown"


def reset_cache_for_tests() -> None:
    """Drop the cached KEK. Tests only — never call from app code."""
    global _KEK_CACHE, _KEK_SOURCE
    with _KEK_LOCK:
        _KEK_CACHE = None
        _KEK_SOURCE = None


# ---------------------------------------------------------------------------
# Per-row DEK + envelope helpers
# ---------------------------------------------------------------------------


def generate_dek() -> bytes:
    """Fresh per-row data-encryption key (32 random bytes, urlsafe base64)."""
    # ``Fernet.generate_key`` already returns urlsafe-base64 of 32 random bytes.
    return Fernet.generate_key()


def wrap_dek(dek: bytes, *, kek: Fernet | None = None) -> str:
    kek = kek or load_kek()
    return kek.encrypt(dek).decode("utf-8")


def unwrap_dek(wrapped: str, *, scope: str = "dek", kek: Fernet | None = None) -> bytes:
    kek = kek or load_kek()
    try:
        return kek.decrypt(wrapped.encode("utf-8"))
    except InvalidToken as exc:
        raise KeyDecryptError(scope=scope, reason="InvalidToken on KEK unwrap") from exc


def encrypt_with_dek(dek: bytes, plaintext: str) -> str:
    return Fernet(dek).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_with_dek(dek: bytes, ciphertext: str, *, scope: str = "value") -> str:
    try:
        return Fernet(dek).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise KeyDecryptError(scope=scope, reason="InvalidToken on DEK decrypt") from exc


def encrypt_value(plaintext: str) -> tuple[str, str]:
    """Convenience: build an envelope for a single value.

    Returns ``(wrapped_dek, ciphertext)``. Caller stores both columns side
    by side.
    """
    dek = generate_dek()
    return wrap_dek(dek), encrypt_with_dek(dek, plaintext)


def decrypt_value(wrapped_dek: str, ciphertext: str, *, scope: str = "value") -> str:
    """Inverse of :func:`encrypt_value`. Raises :class:`KeyDecryptError` on failure."""
    dek = unwrap_dek(wrapped_dek, scope=scope)
    return decrypt_with_dek(dek, ciphertext, scope=scope)


def rewrap_dek(wrapped: str, new_kek: Fernet, *, scope: str = "dek") -> str:
    """Take a DEK wrapped by the *current* KEK and rewrap it with ``new_kek``.

    Used by :mod:`app.scripts.rotate_kek`. The DEK plaintext lives in memory
    only inside this function and is dropped on return.
    """
    dek = unwrap_dek(wrapped, scope=scope)
    return new_kek.encrypt(dek).decode("utf-8")


def random_token_urlsafe(nbytes: int = 32) -> str:
    """Convenience for callers that need a random token (e.g. setup tokens)."""
    return secrets.token_urlsafe(nbytes)
