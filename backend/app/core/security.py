from __future__ import annotations

from calendar import timegm
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return pwd_context.verify(password, hashed_password)
    except Exception:
        # Malformed legacy hashes or unexpected passlib errors must not become 500s.
        return False


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    expire_delta = timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    expires_at = datetime.now(UTC) + expire_delta
    # Integer `exp` avoids python-jose / library edge cases with datetime payloads.
    payload: dict[str, Any] = {"sub": subject, "exp": timegm(expires_at.utctimetuple())}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token if isinstance(token, str) else token.decode("utf-8")


def create_refresh_token(subject: str) -> str:
    """Create a refresh token with longer expiry (30 days)."""
    expires_delta = timedelta(days=settings.refresh_token_expire_days)
    expires_at = datetime.now(UTC) + expires_delta
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": timegm(expires_at.utctimetuple()),
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token if isinstance(token, str) else token.decode("utf-8")


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
